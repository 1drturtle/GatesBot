from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.prefixes import get_prefix
from common.settings import settings
from tests.helpers.fakes import FakeGuild


class FakeClient:
    def __init__(self):
        self.prefixes: dict[str, str] = {}
        self.mdb = {"prefixes": AsyncMock()}
        self.user = SimpleNamespace(id=999)


def test_prefix_falls_back_to_database_then_caches() -> None:
    client = FakeClient()
    client.mdb["prefixes"].find_one.return_value = {"prefix": "!"}
    message = SimpleNamespace(guild=FakeGuild(123))

    result = asyncio.run(get_prefix(client, message))

    assert "!" in result
    assert client.prefixes["123"] == "!"
    client.mdb["prefixes"].find_one.assert_awaited_once_with({"guild_id": "123"})


def test_prefix_uses_cache_without_database_call() -> None:
    client = FakeClient()
    client.prefixes["123"] = "?"
    message = SimpleNamespace(guild=FakeGuild(123))

    result = asyncio.run(get_prefix(client, message))

    assert "?" in result
    client.mdb["prefixes"].find_one.assert_not_awaited()


def test_prefix_uses_default_for_direct_messages() -> None:
    client = FakeClient()
    message = SimpleNamespace(guild=None)

    result = asyncio.run(get_prefix(client, message))

    assert settings.prefix in result
    client.mdb["prefixes"].find_one.assert_not_awaited()
