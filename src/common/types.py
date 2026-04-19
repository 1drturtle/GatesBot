from __future__ import annotations

from typing import Any, Protocol, TypeAlias

import disnake as discord
from disnake.ext import commands

CommandContext: TypeAlias = commands.Context[Any]


class MongoBackedBot(Protocol):
    environment: str
    mdb: Any
    owner_id: int | None
    prefix: str
    prefixes: dict[str, str]
    user: discord.ClientUser | None

    @property
    def dev_id(self) -> int: ...

    def get_channel(self, channel_id: int) -> Any: ...

    def get_guild(self, guild_id: int) -> discord.Guild | None: ...
