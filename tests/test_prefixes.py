from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from bot.prefixes import get_prefix


class FakeGuild:
    def __init__(self, guild_id: int):
        self.id = guild_id


class FakeMessage:
    def __init__(self, guild: FakeGuild | None):
        self.guild = guild


class FakeClient:
    def __init__(self):
        self.prefixes: dict[str, str] = {}
        self.mdb = {"prefixes": AsyncMock()}
        self.user = type("FakeUser", (), {"id": 999})()


async def _get_cached_prefix() -> tuple[list[str], FakeClient]:
    client = FakeClient()
    client.mdb["prefixes"].find_one.return_value = {"prefix": "!"}
    message = FakeMessage(FakeGuild(123))

    result = await get_prefix(client, message)
    return result, client


def test_prefix_falls_back_to_database_then_caches() -> None:
    result, client = asyncio.run(_get_cached_prefix())

    assert "!" in result
    assert client.prefixes["123"] == "!"
