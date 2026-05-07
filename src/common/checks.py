from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import disnake as discord
from disnake.ext import commands

from common.types import CommandContext


def has_role(role_name: str):
    async def predicate(ctx: CommandContext) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        author = cast(discord.Member, ctx.author)
        result = discord.utils.find(
            lambda role: role.name.lower() == role_name.lower(),
            author.roles,
        )
        if result is None and author.id != ctx.bot.owner_id:
            raise commands.MissingRole(role_name)
        return True

    return commands.check(predicate)


def has_any_role(role_names: Iterable[str]):
    lowered_role_names = [role_name.lower() for role_name in role_names]

    async def predicate(ctx: CommandContext) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        author = cast(discord.Member, ctx.author)
        result = discord.utils.find(
            lambda role: role.name.lower() in lowered_role_names,
            author.roles,
        )
        if result is None and author.id != ctx.bot.owner_id:
            joined_names = ", ".join(lowered_role_names)
            raise commands.CheckFailure(f"Missing any of {joined_names} roles to run this command.")
        return True

    return commands.check(predicate)
