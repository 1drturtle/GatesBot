import discord
import datetime


def create_default_embed(ctx, **kwargs) -> discord.Embed:
    embed = discord.Embed(color=discord.Color(int('0x2F3136', base=16)), **kwargs)
    embed.set_author(name=ctx.author.display_name,
                     icon_url=str(ctx.message.author.avatar_url)
                     )
    embed.set_footer(text=ctx.bot.user.name,
                     icon_url=str(ctx.bot.user.avatar_url))
    embed.timestamp = datetime.datetime.utcnow()
    return embed


async def try_delete(message):
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass
