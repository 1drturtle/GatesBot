from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

import discord
import pymongo

from common.discord_utils import find_or_migrate_queue_message_id
from queueing.documents import GateDocument, GroupDocument, QueueDocument
from queueing.models import Queue

QueueType = TypeVar("QueueType", bound=Queue)


def build_empty_queue_document(guild_id: int, channel_id: int | None = None) -> QueueDocument:
    return {
        "groups": [],
        "server_id": guild_id,
        "channel_id": channel_id,
        "locked": False,
    }


class QueueRepository:
    def __init__(self, collection: Any, *, default_channel_id: int | None = None):
        self.collection = collection
        self.default_channel_id = default_channel_id

    async def load_for_guild(
        self,
        guild: discord.Guild,
        *,
        queue_type: type[QueueType] = Queue,
        channel_id: int | None = None,
    ) -> QueueType:
        resolved_channel_id = channel_id if channel_id is not None else self.default_channel_id
        docs = await self.collection.find({"$or": [{"guild_id": guild.id}, {"server_id": guild.id}]}).to_list(None)
        raw = self._choose_preferred_document(docs, resolved_channel_id)

        if raw is None:
            raw_document = build_empty_queue_document(guild.id, resolved_channel_id)
        else:
            raw_document = dict(raw)
            if "server_id" not in raw_document and "guild_id" in raw_document:
                raw_document["server_id"] = raw_document["guild_id"]
            if raw_document.get("channel_id") is None and resolved_channel_id is not None:
                raw_document["channel_id"] = resolved_channel_id

        queue = queue_type.from_dict(guild, raw_document)  # pyright: ignore[reportArgumentType]
        queue.groups.sort(key=lambda group: group.tier)
        return queue  # pyright: ignore[reportReturnType]

    async def save(self, queue: Queue) -> None:
        payload = queue.to_dict()
        payload["guild_id"] = queue.server_id  # pyright: ignore[reportGeneralTypeIssues]
        selector = self._build_save_selector(queue.server_id, queue.channel_id)
        await self.collection.update_one(
            selector,
            {"$set": payload},
            upsert=True,
        )

    @staticmethod
    def _choose_preferred_document(
        docs: list[dict[str, Any]],
        channel_id: int | None,
    ) -> dict[str, Any] | None:
        if not docs:
            return None

        if channel_id is not None:
            for doc in docs:
                if doc.get("channel_id") == channel_id:
                    return doc
            for doc in docs:
                if doc.get("channel_id") is None:
                    return doc

        return max(docs, key=lambda item: len(item.get("groups", [])))

    @staticmethod
    def _build_save_selector(server_id: int, channel_id: int | None) -> dict[str, Any]:
        if channel_id is None:
            return {"$or": [{"guild_id": server_id}, {"server_id": server_id}]}

        return {
            "$or": [
                {"guild_id": server_id, "channel_id": channel_id},
                {"server_id": server_id, "channel_id": channel_id},
                {"guild_id": server_id, "channel_id": None},
                {"server_id": server_id, "channel_id": None},
                {"guild_id": server_id, "channel_id": {"$exists": False}},
                {"server_id": server_id, "channel_id": {"$exists": False}},
            ]
        }


@dataclass(slots=True)
class ReadyQueueEntry:
    member_id: int
    text: str
    message_id: int | None
    ready_on: datetime | None


class ReadyQueueRepository:
    def __init__(
        self,
        collection: Any,
        *,
        text_field: str,
    ):
        self.collection = collection
        self.text_field = text_field

    async def upsert_ready(
        self,
        *,
        member_id: int,
        text: str,
        message_id: int,
    ) -> None:
        await self.collection.update_one(
            {"_id": member_id},
            {
                "$set": {self.text_field: text, "msg": message_id},
                "$currentDate": {"readyOn": True},
            },
            upsert=True,
        )

    async def update_text(self, *, member_id: int, text: str) -> None:
        await self.collection.update_one({"_id": member_id}, {"$set": {self.text_field: text}})

    async def remove_member(self, member_id: int) -> bool:
        result = await self.collection.delete_one({"_id": member_id})
        return bool(result.deleted_count)

    async def remove_members(self, member_ids: list[int]) -> None:
        await self.collection.delete_many({"_id": {"$in": member_ids}})

    async def list_entries(self) -> list[ReadyQueueEntry]:
        items = await self.collection.find().sort("readyOn", pymongo.ASCENDING).to_list(None)
        return [
            ReadyQueueEntry(
                member_id=int(item["_id"]),
                text=str(item.get(self.text_field, "")),
                message_id=item.get("msg"),
                ready_on=item.get("readyOn"),
            )
            for item in items
        ]

    async def get_queue_member(self, queue_number: int) -> ReadyQueueEntry | None:
        entries = await self.list_entries()
        if queue_number < 1 or queue_number > len(entries):
            return None
        return entries[queue_number - 1]


class DMQueueRepository(ReadyQueueRepository):
    def __init__(self, collection: Any):
        super().__init__(collection, text_field="ranks")


class StrikeQueueRepository(ReadyQueueRepository):
    def __init__(self, collection: Any):
        super().__init__(collection, text_field="content")


class GateRepository:
    def __init__(self, collection: Any):
        self.collection = collection

    async def list_gates(self) -> list[dict[str, Any]]:
        return await self.collection.find().to_list(None)

    async def get_by_name(self, gate_name: str) -> dict[str, Any] | None:
        return await self.collection.find_one({"name": gate_name.lower()})

    async def get_by_owner(self, owner_id: int) -> dict[str, Any] | None:
        return await self.collection.find_one({"owner": owner_id})

    async def set_owner(self, gate_name: str, owner_id: int) -> None:
        await self.collection.update_one(
            {"name": gate_name.lower()},
            {"$set": {"owner": owner_id}},
            upsert=False,
        )

    async def upsert_gate(self, gate_name: str, gate_emoji: str) -> None:
        await self.collection.update_one(
            {"name": gate_name.lower()},
            {"$set": {"name": gate_name.lower(), "emoji": gate_emoji}},
            upsert=True,
        )

    async def remove_gate(self, gate_name: str) -> None:
        await self.collection.delete_one({"name": gate_name.lower()})


class QueueMetaRepository:
    def __init__(self, collection: Any):
        self.collection = collection

    async def get_message_id(self, key: str) -> int | None:
        meta = await self.collection.find_one({"_id": key}) or {}
        message_id = meta.get("message_id")
        if message_id is None:
            return None
        return int(message_id)

    async def set_message_id(self, key: str, message_id: int) -> None:
        await self.collection.update_one(
            {"_id": key},
            {"$set": {"message_id": message_id}},
            upsert=True,
        )

    async def resolve_message_id(
        self,
        *,
        channel: discord.TextChannel,
        meta_key: str,
        embed_title_prefix: str,
        bot_user_id: int,
    ) -> int | None:
        return await find_or_migrate_queue_message_id(
            channel=channel,
            meta_db=self.collection,
            meta_key=meta_key,
            embed_title_prefix=embed_title_prefix,
            bot_user_id=bot_user_id,
        )


class AnalyticsRepository:
    def __init__(self, mdb: Any):
        self.player_queue_analytics = mdb["queue_analytics"]
        self.gate_group_analytics = mdb["gate_groups_analytics"]
        self.dm_analytics = mdb["dm_analytics"]
        self.dm_assign_analytics = mdb["dm_assign_analytics"]
        self.reinforcement_analytics = mdb["reinforcement_analytics"]
        self.player_marked = mdb["player_marked"]
        self.active_users = mdb["active_users"]

    async def record_player_signup(
        self,
        *,
        member: discord.Member,
        total_level: int,
        levels: list[dict[str, Any]],
    ) -> None:
        data = {
            "$set": {
                "user_id": member.id,
                "last.level": total_level,
                "last.classes": levels,
                "last.name": member.display_name,
                "joined_at": member.joined_at,
            },
            "$currentDate": {"last_gate_signup": True},
            "$inc": {"gate_signup_count": 1},
        }
        await self.player_queue_analytics.update_one(
            {"user_id": member.id},
            data,
            upsert=True,
        )
        await self.active_users.update_one(
            {"_id": member.id},
            {"$currentDate": {"last_signup": True}},
            upsert=True,
        )

    async def decrement_player_signup(self, member_id: int) -> None:
        await self.player_queue_analytics.update_one(
            {"user_id": member_id},
            {"$set": {"user_id": member_id}, "$inc": {"gate_signup_count": -1}},
            upsert=True,
        )

    async def set_marked(self, member_id: int, *, marked: bool) -> None:
        await self.player_marked.update_one(
            {"_id": member_id},
            {"$set": {"_id": member_id, "marked": marked}},
            upsert=True,
        )

    async def clear_marks_for_members(self, member_ids: list[int]) -> None:
        if not member_ids:
            return
        await self.player_marked.update_many(
            {"_id": {"$in": member_ids}},
            {"$set": {"marked": False}},
        )

    async def set_unlock_timestamp(self) -> None:
        await self.player_marked.update_one(
            {"_mark": True},
            {"$set": {"_mark": True, "timestamp": datetime.utcnow()}},
            upsert=True,
        )

    async def mark_assignment_claimed(self) -> None:
        assign_analytics = await self.dm_assign_analytics.find(
            sort=[("summonDate", -1)],
            limit=1,
            filter={"claimed": False},
        ).to_list(length=None)
        if not assign_analytics:
            return
        assign_item = assign_analytics[0]
        await self.dm_assign_analytics.update_one(
            {"_id": assign_item["_id"]},
            {"$set": {"claimed": True}, "$currentDate": {"claimDate": True}},
        )

    async def record_dm_claim(
        self,
        *,
        dm_id: int,
        gate_data: GateDocument,
    ) -> None:
        await self.dm_analytics.update_one(
            {"_id": dm_id},
            {
                "$inc": {"dm_claims.claims": 1},
                "$push": {"dm_gates": gate_data},
                "$currentDate": {"dm_claims.last_claim": True},
            },
            upsert=True,
        )

    async def record_gate_reinforcement(
        self,
        *,
        dm_id: int,
        gate_info: GateDocument,
    ) -> None:
        await self.reinforcement_analytics.insert_one(
            {
                "type": "reinforcements",
                "gate_info": gate_info,
                "dm_id": dm_id,
            }
        )

    async def get_dm_info(self, dm_id: int) -> dict[str, Any] | None:
        return await self.dm_analytics.find_one({"_id": dm_id})

    async def record_claimed_group(
        self,
        *,
        gate_name: str,
        claimed_by: int,
        tier: int,
        player_levels: list[int],
    ) -> None:
        levels: dict[str, int] = {}
        for level in player_levels:
            key = str(level)
            levels[key] = levels.get(key, 0) + 1

        await self.gate_group_analytics.insert_one(
            {
                "gate_name": gate_name,
                "date_summoned": datetime.utcnow(),
                "dm_id": claimed_by,
                "tier": tier,
                "levels": levels,
            }
        )

    async def record_player_gate_summon(
        self,
        *,
        member_id: int,
        gate_name: str,
        total_level: int,
    ) -> None:
        await self.player_queue_analytics.update_one(
            {"user_id": member_id},
            {
                "$set": {"user_id": member_id, "last_gate_name": gate_name},
                "$currentDate": {"last_gate_summoned": True},
                "$inc": {
                    f"gates_summoned_per_level.{total_level}": 1,
                    "gate_summon_count": 1,
                },
            },
            upsert=True,
        )

    async def record_dm_queue_signup(self, member_id: int, *, delta: int = 1) -> None:
        await self.dm_analytics.update_one(
            {"_id": member_id},
            {
                "$inc": {"dm_queue.signups": delta},
                "$currentDate": {"dm_queue.last_signup": True},
            },
            upsert=True,
        )

    async def increment_dm_assignments(self, dm_id: int) -> None:
        await self.dm_analytics.update_one(
            {"_id": dm_id},
            {"$inc": {"dm_queue.assignments": 1}},
            upsert=True,
        )

    async def record_dm_assignment(
        self,
        *,
        summoner_id: int,
        dm_id: int,
        gate_data: GroupDocument,
    ) -> None:
        await self.dm_assign_analytics.insert_one(
            {
                "summoner": summoner_id,
                "dm": dm_id,
                "gate_data": gate_data,
                "claimed": False,
                "summonDate": datetime.utcnow(),
            }
        )

    async def set_last_strike_gate(self, member_id: int, gate_name: str) -> None:
        await self.player_queue_analytics.update_one(
            {"_id": member_id},
            {"$set": {"last_strike": gate_name}},
            upsert=True,
        )

    async def record_strike_team_reinforcement(
        self,
        *,
        user_ids: list[int],
        dm_id: int,
        gate_name: str,
        gate_info: GateDocument,
    ) -> None:
        await self.reinforcement_analytics.insert_one(
            {
                "type": "strike_team",
                "user_ids": user_ids,
                "dm_id": dm_id,
                "gate_name": gate_name.lower(),
                "gate_info": gate_info,
            }
        )


async def load_queue_for_guild(
    db: Any,
    guild: discord.Guild,
    *,
    queue_type: type[QueueType] = Queue,
) -> QueueType:
    repository = QueueRepository(db)
    return await repository.load_for_guild(guild, queue_type=queue_type)
