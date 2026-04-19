from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from queueing.repositories.ready_queue import DMQueueRepository, ReadyQueueRepository, StrikeQueueRepository
from tests.helpers.fakes import FakeCollection


def test_upsert_ready_sets_text_message_and_ready_timestamp() -> None:
    collection = FakeCollection()
    repository = ReadyQueueRepository(collection, text_field="ranks")

    asyncio.run(repository.upsert_ready(member_id=10, text="tier 3", message_id=99))

    assert collection.docs[0]["_id"] == 10
    assert collection.docs[0]["ranks"] == "tier 3"
    assert collection.docs[0]["msg"] == 99
    assert collection.docs[0]["readyOn"] is not None


def test_update_and_remove_member_mutate_target_entry() -> None:
    collection = FakeCollection([{"_id": 10, "ranks": "old"}, {"_id": 20, "ranks": "keep"}])
    repository = ReadyQueueRepository(collection, text_field="ranks")

    asyncio.run(repository.update_text(member_id=10, text="new"))
    removed = asyncio.run(repository.remove_member(10))
    missing = asyncio.run(repository.remove_member(30))

    assert removed is True
    assert missing is False
    assert collection.docs == [{"_id": 20, "ranks": "keep"}]


def test_remove_members_deletes_all_selected_ids() -> None:
    collection = FakeCollection([{"_id": 10}, {"_id": 20}, {"_id": 30}])

    asyncio.run(ReadyQueueRepository(collection, text_field="ranks").remove_members([10, 30]))

    assert collection.docs == [{"_id": 20}]


def test_list_entries_sorts_by_ready_on_and_maps_configured_text_field() -> None:
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(minutes=5)
    collection = FakeCollection(
        [
            {"_id": 20, "ranks": "new", "msg": 2, "readyOn": newer},
            {"_id": 10, "ranks": "old", "msg": 1, "readyOn": older},
        ]
    )

    entries = asyncio.run(ReadyQueueRepository(collection, text_field="ranks").list_entries())

    assert [entry.member_id for entry in entries] == [10, 20]
    assert entries[0].text == "old"
    assert entries[0].message_id == 1
    assert entries[0].ready_on == older


def test_get_queue_member_uses_one_based_index_bounds() -> None:
    collection = FakeCollection([{"_id": 10, "ranks": "first"}, {"_id": 20, "ranks": "second"}])
    repository = ReadyQueueRepository(collection, text_field="ranks")

    assert asyncio.run(repository.get_queue_member(1)).member_id == 10
    assert asyncio.run(repository.get_queue_member(0)) is None
    assert asyncio.run(repository.get_queue_member(3)) is None


def test_queue_subclasses_use_expected_text_fields() -> None:
    dm_collection = FakeCollection()
    strike_collection = FakeCollection()

    asyncio.run(DMQueueRepository(dm_collection).upsert_ready(member_id=1, text="ranks", message_id=10))
    asyncio.run(StrikeQueueRepository(strike_collection).upsert_ready(member_id=2, text="content", message_id=20))

    assert dm_collection.docs[0]["ranks"] == "ranks"
    assert strike_collection.docs[0]["content"] == "content"
