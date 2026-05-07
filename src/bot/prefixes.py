from __future__ import annotations

import disnake as discord
from disnake.ext import commands

from common.settings import settings
from common.types import MongoBackedBot


async def get_prefix(client: MongoBackedBot, message: discord.Message) -> list[str]:
    if not message.guild:
        return commands.when_mentioned_or(settings.prefix)(client, message)

    guild_id = str(message.guild.id)
    if guild_id in client.prefixes:
        prefix = client.prefixes.get(guild_id, settings.prefix)
    else:
        dbsearch = await client.mdb["prefixes"].find_one({"guild_id": guild_id})
        if dbsearch is not None:
            prefix = dbsearch.get("prefix", settings.prefix)
        else:
            prefix = settings.prefix
        client.prefixes[guild_id] = prefix

    return commands.when_mentioned_or(prefix)(client, message)
