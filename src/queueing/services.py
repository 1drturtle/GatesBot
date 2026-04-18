from __future__ import annotations

from typing import Any

import discord

from common.discord_utils import find_or_migrate_queue_message_id, try_delete
from common.embeds import create_queue_embed
from queueing.messages import build_gate_assignment_message
from queueing.models import Group


async def replace_persistent_message(
    *,
    channel: discord.TextChannel,
    meta_db: Any,
    meta_key: str,
    embed_title_prefix: str,
    bot_user_id: int,
    embed: discord.Embed,
    view: Any,
) -> discord.Message:
    old_message_id = await find_or_migrate_queue_message_id(
        channel=channel,
        meta_db=meta_db,
        meta_key=meta_key,
        embed_title_prefix=embed_title_prefix,
        bot_user_id=bot_user_id,
    )
    if old_message_id:
        try:
            old_message = await channel.fetch_message(old_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            old_message = None
        if old_message is not None:
            await try_delete(old_message)

    message = await channel.send(embed=embed, view=view)
    await meta_db.update_one(
        {"_id": meta_key},
        {"$set": {"message_id": message.id}},
        upsert=True,
    )
    return message


async def send_gate_assignment(
    *,
    bot: Any,
    group: Group,
    group_number: int,
    dm_member: discord.Member,
    assignment_channel: discord.TextChannel,
) -> None:
    group.players.sort(key=lambda player: player.member.display_name)
    for player in group.players:
        player.member = await assignment_channel.guild.fetch_member(player.member.id)

    assignment_embed = create_queue_embed(bot)
    assignment_embed.title = "Gate Assignment"
    assignment_embed.description = build_gate_assignment_message(
        group_number=group_number,
        player_count=len(group.players),
        tier_text=group.tier_str,
    )

    group_embed = create_queue_embed(bot)
    group_embed.title = f"Information for Group #{group_number}"
    group_embed.description = group.player_levels_str

    await assignment_channel.send(embed=group_embed)
    await assignment_channel.send(
        dm_member.mention,
        embed=assignment_embed,
        allowed_mentions=discord.AllowedMentions(users=True),
    )
