from __future__ import annotations

from typing import Any, Protocol, TypeAlias

import disnake as discord
from disnake.ext import commands
from pymongo.asynchronous.database import AsyncDatabase

CommandContext: TypeAlias = commands.Context[Any]


class BotUser(Protocol):
    id: int
    name: str
    display_avatar: object


class EmbedContext(Protocol):
    author: discord.Member
    bot: MongoBackedBot
    message: discord.Message


class MongoBackedBot(Protocol):
    environment: str
    mdb: AsyncDatabase
    owner_id: int | None
    prefix: str
    prefixes: dict[str, str]
    user: BotUser | None

    @property
    def dev_id(self) -> int: ...

    def get_channel(self, channel_id: int) -> discord.abc.GuildChannel | None: ...

    def get_guild(self, guild_id: int) -> discord.Guild | None: ...
