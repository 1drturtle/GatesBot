from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import disnake as discord


EMBED_COLOUR = discord.Color(int("0x2F3136", base=16))


def _with_common_metadata(embed: discord.Embed, *, bot_user: Any) -> discord.Embed:
    embed.set_footer(text=bot_user.name, icon_url=str(bot_user.display_avatar))
    embed.timestamp = datetime.now(tz=timezone.utc)
    return embed


def create_default_embed(ctx: Any, **kwargs: Any) -> discord.Embed:
    embed = discord.Embed(color=EMBED_COLOUR, **kwargs)
    embed.set_author(
        name=ctx.author.display_name,
        icon_url=str(ctx.message.author.display_avatar),
    )
    return _with_common_metadata(embed, bot_user=ctx.bot.user)


def create_queue_embed(bot: Any, **kwargs: Any) -> discord.Embed:
    embed = discord.Embed(color=EMBED_COLOUR, **kwargs)
    return _with_common_metadata(embed, bot_user=bot.user)
