import discord
from discord.ext import commands


def has_role(role_name: str):
    async def predicate(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        result = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.author.roles)
        if result is None and not ctx.author.id == ctx.bot.owner_id:
            raise commands.MissingRole(role_name)
        return True

    return commands.check(predicate)
