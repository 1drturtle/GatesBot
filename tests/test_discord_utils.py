from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from common.discord_utils import find_or_migrate_queue_message_id


class FakeAuthor:
    def __init__(self, user_id: int):
        self.id = user_id


class FakeEmbed:
    def __init__(self, title: str):
        self.title = title


class FakeMessage:
    def __init__(self, message_id: int, author_id: int, title: str):
        self.id = message_id
        self.author = FakeAuthor(author_id)
        self.embeds = [FakeEmbed(title)]


class FakeChannel:
    def __init__(self, messages: list[FakeMessage]):
        self._messages = messages

    async def history(self, limit: int = 50):
        del limit
        for message in self._messages:
            yield message


async def _get_stored_message_id() -> tuple[int | None, AsyncMock]:
    meta_db = AsyncMock()
    meta_db.find_one.return_value = {"message_id": 42}

    message_id = await find_or_migrate_queue_message_id(
        channel=FakeChannel([]),
        meta_db=meta_db,
        meta_key="player_queue:1",
        embed_title_prefix="Gate Sign-Up List",
        bot_user_id=100,
    )

    return message_id, meta_db


def test_uses_stored_message_id_when_present() -> None:
    message_id, meta_db = asyncio.run(_get_stored_message_id())

    assert message_id == 42
    meta_db.update_one.assert_not_awaited()


async def _migrate_message_id_from_history() -> tuple[int | None, AsyncMock]:
    meta_db = AsyncMock()
    meta_db.find_one.return_value = {}
    channel = FakeChannel(
        [
            FakeMessage(10, 999, "Other Title"),
            FakeMessage(11, 100, "Gate Sign-Up List"),
        ]
    )

    message_id = await find_or_migrate_queue_message_id(
        channel=channel,
        meta_db=meta_db,
        meta_key="player_queue:1",
        embed_title_prefix="Gate Sign-Up List",
        bot_user_id=100,
    )

    return message_id, meta_db


def test_migrates_matching_message_id_from_history() -> None:
    message_id, meta_db = asyncio.run(_migrate_message_id_from_history())

    assert message_id == 11
    meta_db.update_one.assert_awaited_once()
