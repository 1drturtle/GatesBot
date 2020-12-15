import discord
from discord.ext import commands


def has_role(role_name: str):
    async def predicate(ctx):
        result = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.author.roles)
        if result is None:
            raise commands.MissingRole(role_name)
        return True

    return commands.check(predicate)
