from __future__ import annotations

import asyncio
from typing import Any

from queueing.models import Queue
from queueing.repository import QueueRepository


class FakeGuild:
    def __init__(self, guild_id: int):
        self.id = guild_id

    def get_member(self, member_id: int):
        del member_id
        return None


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    async def to_list(self, length=None):
        del length
        return list(self._docs)


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, value in query.items():
        if key == "$or":
            return any(_matches(doc, item) for item in value)

        if isinstance(value, dict) and "$exists" in value:
            exists = key in doc
            if exists != bool(value["$exists"]):
                return False
            continue

        if doc.get(key) != value:
            return False

    return True


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor([doc for doc in self.docs if _matches(doc, query)])

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        for doc in self.docs:
            if _matches(doc, query):
                doc.update(update.get("$set", {}))
                return

        if upsert:
            self.docs.append(dict(update.get("$set", {})))


def test_load_for_guild_prefers_exact_channel_document() -> None:
    collection = FakeCollection(
        [
            {
                "server_id": 123,
                "channel_id": None,
                "groups": [],
                "locked": False,
            },
            {
                "guild_id": 123,
                "server_id": 123,
                "channel_id": 999,
                "groups": [],
                "locked": True,
            },
        ]
    )
    repository = QueueRepository(collection, default_channel_id=999)

    queue = asyncio.run(repository.load_for_guild(FakeGuild(123)))

    assert queue.channel_id == 999
    assert queue.locked is True


def test_save_updates_legacy_none_channel_document() -> None:
    collection = FakeCollection(
        [
            {
                "server_id": 123,
                "channel_id": None,
                "groups": [],
                "locked": False,
            }
        ]
    )
    repository = QueueRepository(collection, default_channel_id=999)

    queue = Queue(groups=[], server_id=123, channel_id=999, locked=True)
    asyncio.run(repository.save(queue))

    assert len(collection.docs) == 1
    assert collection.docs[0]["channel_id"] == 999
    assert collection.docs[0]["locked"] is True
    assert collection.docs[0]["guild_id"] == 123
