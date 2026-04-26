from __future__ import annotations

from datetime import datetime
from typing import Any

import disnake as discord

from queueing.documents import GateDocument, GroupDocument


def _format_class_level(class_level: Any) -> str | None:
    if not isinstance(class_level, dict):
        return None

    class_name = str(class_level.get("class") or "").strip()
    subclass = str(class_level.get("subclass") or "").strip()
    level = class_level.get("level")
    if not class_name or level is None:
        return None

    parts = []
    if subclass and subclass.lower() != "none":
        parts.append(subclass)
    if class_name.lower() != "none":
        parts.append(class_name)
    if not parts:
        return None

    parts.append(str(level))
    return " ".join(parts)


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
        signup_text: str | None = None,
    ) -> None:
        set_data: dict[str, Any] = {
            "user_id": member.id,
            "last.level": total_level,
            "last.classes": levels,
            "last.name": member.display_name,
            "joined_at": member.joined_at,
        }
        if signup_text is not None:
            set_data["last.signup_text"] = signup_text

        data = {
            "$set": set_data,
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

    async def get_last_player_signup_text(self, member_id: int) -> str | None:
        data = await self.player_queue_analytics.find_one({"user_id": member_id})
        if data is None:
            return None

        last = data.get("last")
        if isinstance(last, dict):
            signup_text = last.get("signup_text")
            if isinstance(signup_text, str) and signup_text.strip():
                return signup_text

            classes = last.get("classes")
        else:
            signup_text = data.get("last.signup_text")
            if isinstance(signup_text, str) and signup_text.strip():
                return signup_text

            classes = data.get("last.classes")

        if not isinstance(classes, list):
            return None

        class_lines = [_format_class_level(class_level) for class_level in classes]
        class_lines = [line for line in class_lines if line]
        if not class_lines:
            return None
        return " / ".join(class_lines)

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
            {"user_id": member_id},
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
