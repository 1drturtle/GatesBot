from __future__ import annotations

from typing import Any, TypeVar

import disnake as discord
from pymongo.asynchronous.collection import AsyncCollection

from queueing.documents import QueueDocument, StoredQueueDocument
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
    def __init__(self, collection: AsyncCollection, *, default_channel_id: int | None = None):
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
        docs = await self.collection.find({"$or": [{"guild_id": guild.id}, {"server_id": guild.id}]}).to_list(
            length=None
        )
        raw = self._choose_preferred_document(docs, resolved_channel_id)

        if raw is None:
            raw_document = build_empty_queue_document(guild.id, resolved_channel_id)
        else:
            raw_document = self._normalize_document(raw, guild.id, resolved_channel_id)

        queue = queue_type.from_dict(guild, raw_document)
        queue.groups.sort(key=lambda group: group.tier)
        return queue  # pyright: ignore[reportReturnType]

    async def save(self, queue: Queue) -> None:
        payload: StoredQueueDocument = {**queue.to_dict(), "guild_id": queue.server_id}
        selector = self._build_save_selector(queue.server_id, queue.channel_id)
        await self.collection.update_one(
            selector,
            {"$set": payload},
            upsert=True,
        )

    @staticmethod
    def _choose_preferred_document(
        docs: list[StoredQueueDocument],
        channel_id: int | None,
    ) -> StoredQueueDocument | None:
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
    def _normalize_document(
        raw: StoredQueueDocument,
        guild_id: int,
        channel_id: int | None,
    ) -> QueueDocument:
        resolved_channel_id = raw.get("channel_id")
        if resolved_channel_id is None and channel_id is not None:
            resolved_channel_id = channel_id

        return {
            "groups": raw.get("groups", []),
            "server_id": raw.get("server_id", raw.get("guild_id", guild_id)),
            "channel_id": resolved_channel_id,
            "locked": raw.get("locked", False),
        }

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


async def load_queue_for_guild(
    db: AsyncCollection,
    guild: discord.Guild,
    *,
    queue_type: type[QueueType] = Queue,
) -> QueueType:
    repository = QueueRepository(db)
    return await repository.load_for_guild(guild, queue_type=queue_type)
