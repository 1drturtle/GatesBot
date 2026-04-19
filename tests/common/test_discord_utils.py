from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from common.discord_utils import find_or_migrate_queue_message_id
from tests.helpers.fakes import FakeChannel, FakeEmbed, FakeMember, FakeMessage


def test_uses_stored_message_id_when_present() -> None:
    meta_db = AsyncMock()
    meta_db.find_one.return_value = {"message_id": 42}

    message_id = asyncio.run(
        find_or_migrate_queue_message_id(
            channel=FakeChannel(1),
            meta_db=meta_db,
            meta_key="player_queue:1",
            embed_title_prefix="Gate Sign-Up List",
            bot_user_id=100,
        )
    )

    assert message_id == 42
    meta_db.update_one.assert_not_awaited()


def test_migrates_matching_message_id_from_history() -> None:
    meta_db = AsyncMock()
    meta_db.find_one.return_value = {}
    channel = FakeChannel(
        1,
        history_messages=[
            FakeMessage(10, author=FakeMember(999), embeds=[FakeEmbed("Gate Sign-Up List")]),
            FakeMessage(11, author=FakeMember(100), embeds=[FakeEmbed("Gate Sign-Up List")]),
        ],
    )

    message_id = asyncio.run(
        find_or_migrate_queue_message_id(
            channel=channel,
            meta_db=meta_db,
            meta_key="player_queue:1",
            embed_title_prefix="Gate Sign-Up List",
            bot_user_id=100,
        )
    )

    assert message_id == 11
    meta_db.update_one.assert_awaited_once_with(
        {"_id": "player_queue:1"},
        {"$set": {"message_id": 11}},
        upsert=True,
    )


def test_returns_none_when_no_history_message_matches() -> None:
    meta_db = AsyncMock()
    meta_db.find_one.return_value = {}
    channel = FakeChannel(
        1,
        history_messages=[
            FakeMessage(10, author=FakeMember(100), embeds=[]),
            FakeMessage(11, author=FakeMember(100), embeds=[FakeEmbed("Other")]),
        ],
    )

    message_id = asyncio.run(
        find_or_migrate_queue_message_id(
            channel=channel,
            meta_db=meta_db,
            meta_key="player_queue:1",
            embed_title_prefix="Gate Sign-Up List",
            bot_user_id=100,
        )
    )

    assert message_id is None
    meta_db.update_one.assert_not_awaited()
