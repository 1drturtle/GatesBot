from __future__ import annotations

from typing import Any

import disnake as discord


async def try_delete(message: discord.Message) -> None:
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass


async def find_or_migrate_queue_message_id(
    *,
    channel: discord.TextChannel,
    meta_db: Any,
    meta_key: str,
    embed_title_prefix: str,
    bot_user_id: int | None = None,
) -> int | None:
    meta = await meta_db.find_one({"_id": meta_key}) or {}
    message_id = meta.get("message_id")
    if message_id:
        return int(message_id)

    async for msg in channel.history(limit=50):
        if bot_user_id is not None and msg.author.id != bot_user_id:
            continue
        if len(msg.embeds) != 1:
            continue
        embed = msg.embeds[0]
        if embed.title and embed.title.startswith(embed_title_prefix):
            await meta_db.update_one(
                {"_id": meta_key},
                {"$set": {"message_id": msg.id}},
                upsert=True,
            )
            return msg.id
    return None
