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


def has_any_role(role_names: list[str]):

    role_names = [r.lower() for r in role_names]

    async def predicate(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        result = discord.utils.find(lambda r: r.name.lower() in role_names, ctx.author.roles)
        if result is None and not ctx.author.id == ctx.bot.owner_id:
            raise commands.CheckFailure(f'Missing any of {", ".join(role_names)} roles to run this command.')
        return True

    return commands.check(predicate)
