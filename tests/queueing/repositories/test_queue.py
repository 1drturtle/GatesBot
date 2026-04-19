from __future__ import annotations

import asyncio

from queueing.models import Queue
from queueing.repositories.queue import QueueRepository, build_empty_queue_document, load_queue_for_guild
from tests.helpers.builders import make_player
from tests.helpers.fakes import FakeCollection, FakeGuild


def test_build_empty_queue_document_uses_guild_and_channel() -> None:
    assert build_empty_queue_document(123, 456) == {
        "groups": [],
        "server_id": 123,
        "channel_id": 456,
        "locked": False,
    }


def test_load_for_guild_prefers_exact_channel_document() -> None:
    collection = FakeCollection(
        [
            {"server_id": 123, "channel_id": None, "groups": [], "locked": False},
            {"guild_id": 123, "server_id": 123, "channel_id": 999, "groups": [], "locked": True},
        ]
    )
    repository = QueueRepository(collection, default_channel_id=999)

    queue = asyncio.run(repository.load_for_guild(FakeGuild(123)))

    assert queue.channel_id == 999
    assert queue.locked is True


def test_load_for_guild_prefers_legacy_none_channel_when_no_exact_match() -> None:
    collection = FakeCollection(
        [
            {"guild_id": 123, "groups": [], "locked": True},
            {"guild_id": 123, "channel_id": 555, "groups": [], "locked": False},
        ]
    )
    repository = QueueRepository(collection, default_channel_id=999)

    queue = asyncio.run(repository.load_for_guild(FakeGuild(123)))

    assert queue.server_id == 123
    assert queue.channel_id == 999
    assert queue.locked is True


def test_load_for_guild_falls_back_to_largest_queue_without_channel() -> None:
    player = make_player(1, "Alice")
    guild = FakeGuild(123, members=[player.member])
    collection = FakeCollection(
        [
            {"server_id": 123, "channel_id": 1, "groups": [], "locked": False},
            {"server_id": 123, "channel_id": 2, "groups": [{"players": [player.to_dict()], "tier": 2}], "locked": True},
        ]
    )

    queue = asyncio.run(QueueRepository(collection).load_for_guild(guild))

    assert queue.channel_id == 2
    assert queue.locked is True
    assert queue.player_count == 1


def test_load_for_guild_builds_empty_queue_when_no_document_exists() -> None:
    queue = asyncio.run(QueueRepository(FakeCollection(), default_channel_id=999).load_for_guild(FakeGuild(123)))

    assert queue == Queue(groups=[], server_id=123, channel_id=999, locked=False)


def test_load_for_guild_sorts_groups_by_tier() -> None:
    collection = FakeCollection(
        [
            {
                "server_id": 123,
                "channel_id": 999,
                "groups": [{"players": [], "tier": 5}, {"players": [], "tier": 1}],
                "locked": False,
            }
        ]
    )

    queue = asyncio.run(QueueRepository(collection, default_channel_id=999).load_for_guild(FakeGuild(123)))

    assert [group.tier for group in queue.groups] == [1, 5]


def test_save_updates_legacy_none_channel_document() -> None:
    collection = FakeCollection([{"server_id": 123, "channel_id": None, "groups": [], "locked": False}])
    repository = QueueRepository(collection, default_channel_id=999)

    asyncio.run(repository.save(Queue(groups=[], server_id=123, channel_id=999, locked=True)))

    assert len(collection.docs) == 1
    assert collection.docs[0]["channel_id"] == 999
    assert collection.docs[0]["locked"] is True
    assert collection.docs[0]["guild_id"] == 123
    selector, _, upsert = collection.update_one_calls[0]
    assert {"server_id": 123, "channel_id": None} in selector["$or"]
    assert upsert is True


def test_load_queue_for_guild_uses_repository_default_behavior() -> None:
    queue = asyncio.run(load_queue_for_guild(FakeCollection(), FakeGuild(123)))

    assert queue.server_id == 123
    assert queue.channel_id is None
