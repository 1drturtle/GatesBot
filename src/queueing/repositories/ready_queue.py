from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pymongo


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
        items = await self.collection.find().sort("readyOn", pymongo.ASCENDING).to_list(length=None)
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
