from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import disnake as discord

from common.embeds import create_queue_embed
from queueing.contracts import QueueRefreshResult, QueueViewState
from queueing.messages import build_gate_assignment_message
from queueing.models import Group, Queue
from queueing.repositories import QueueMetaRepository, ReadyQueueEntry


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
    old_message_id = await QueueMetaRepository(meta_db).resolve_message_id(
        channel=channel,
        meta_key=meta_key,
        embed_title_prefix=embed_title_prefix,
        bot_user_id=bot_user_id,
    )
    if old_message_id:
        try:
            old_message = await channel.fetch_message(old_message_id)
        except discord.NotFound, discord.Forbidden, discord.HTTPException:
            old_message = None
        if old_message is not None:
            try:
                await old_message.delete()
            except discord.Forbidden, discord.NotFound, discord.HTTPException:
                pass

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
    service = QueuePresentationService(bot=bot, meta_repository=QueueMetaRepository(bot.mdb["queue_meta"]))
    await service.send_gate_assignment(
        group=group,
        group_number=group_number,
        dm_member=dm_member,
        assignment_channel=assignment_channel,
    )


class QueuePresentationService:
    def __init__(self, *, bot: Any, meta_repository: QueueMetaRepository):
        self.bot = bot
        self.meta_repository = meta_repository
        self.mark_repository = bot.mdb["player_marked"]

    async def build_player_queue_embed(self, queue: Queue) -> discord.Embed:
        queue.groups.sort(key=lambda group: group.tier)
        embed = create_queue_embed(self.bot)
        embed.title = "Gate Sign-Up List" + (" 🔒" if queue.locked else "")

        for index, group in enumerate(queue.groups):
            locked = " 🔒" if group.locked else ""
            embed.add_field(
                name=f"{index + 1}. Rank {group.tier}{locked}",
                value=await self._group_member_mentions(group),
                inline=False,
            )

        return embed

    async def build_player_waitlist_embed(
        self,
        queue: Queue,
        *,
        signup_times: dict[int, datetime],
    ) -> discord.Embed:
        players = [
            (group_index, group.tier, player)
            for group_index, group in enumerate(queue.groups)
            for player in group.players
        ]
        players.sort(
            key=lambda item: (
                signup_times.get(item[2].member.id) is None,
                signup_times.get(item[2].member.id) or datetime.max.replace(tzinfo=timezone.utc),
                item[2].member.display_name.casefold(),
            )
        )

        lines: list[str] = []
        for index, (group_index, tier, player) in enumerate(players, start=1):
            signup_time = signup_times.get(player.member.id)
            if signup_time is None:
                wait_text = "unknown signup time"
            else:
                if signup_time.tzinfo is None:
                    signup_time = signup_time.replace(tzinfo=timezone.utc)
                timestamp = int(signup_time.timestamp())
                wait_text = f"<t:{timestamp}:R> (<t:{timestamp}:f>)"

            lines.append(f"**#{index}.** {player.mention} - {wait_text} - Group #{group_index + 1}, Rank {tier}")

        embed = create_queue_embed(self.bot)
        embed.title = "Queue Waitlist"
        embed.description = "\n".join(lines) or "No players are currently in the queue."
        return embed

    async def build_dm_queue_embed(
        self,
        *,
        guild: discord.Guild,
        entries: list[ReadyQueueEntry],
    ) -> discord.Embed:
        out: list[str] = []
        for index, item in enumerate(entries):
            member = guild.get_member(item.member_id)
            if member is None:
                continue
            out.append(f"**#{index + 1}.** {member.mention} - {item.text}")

        embed = create_queue_embed(self.bot)
        embed.title = "DM Queue"
        embed.description = "\n".join(out)
        return embed

    async def build_strike_queue_embed(
        self,
        *,
        guild: discord.Guild,
        entries: list[ReadyQueueEntry],
    ) -> discord.Embed:
        out: list[str] = []
        for index, item in enumerate(entries):
            member = guild.get_member(item.member_id)
            if member is None:
                continue
            out.append(f"**#{index + 1}.** {member.mention} - {item.text.title()}")

        embed = create_queue_embed(self.bot)
        embed.title = "Strike Team Queue"
        embed.description = "\n".join(out)
        return embed

    async def refresh_queue_message(
        self,
        *,
        channel: discord.TextChannel,
        meta_key: str,
        embed_title_prefix: str,
        embed: discord.Embed,
        view: Any,
    ) -> QueueRefreshResult:
        message = await replace_persistent_message(
            channel=channel,
            meta_db=self.meta_repository.collection,
            meta_key=meta_key,
            embed_title_prefix=embed_title_prefix,
            bot_user_id=self.bot.user.id,
            embed=embed,
            view=view,
        )
        return QueueRefreshResult(
            message_id=message.id,
            payload={
                "meta_key": meta_key,
                "embed_title_prefix": embed_title_prefix,
            },
        )

    async def send_gate_assignment(
        self,
        *,
        group: Group,
        group_number: int,
        dm_member: discord.Member,
        assignment_channel: discord.TextChannel,
    ) -> None:
        group.players.sort(key=lambda player: player.member.display_name)
        for player in group.players:
            player.member = await assignment_channel.guild.fetch_member(player.member.id)

        assignment_embed = create_queue_embed(self.bot)
        assignment_embed.title = "Gate Assignment"
        assignment_embed.description = build_gate_assignment_message(
            group_number=group_number,
            player_count=len(group.players),
            tier_text=group.tier_str,
        )

        group_embed = create_queue_embed(self.bot)
        group_embed.title = f"Information for Group #{group_number}"
        group_embed.description = group.player_levels_str

        await assignment_channel.send(embed=group_embed)
        await assignment_channel.send(
            dm_member.mention,
            embed=assignment_embed,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def player_view_state(self, queue: Queue) -> QueueViewState:
        lines = [f"{index + 1}. Rank {group.tier}" for index, group in enumerate(queue.groups)]
        return QueueViewState(
            title="Gate Sign-Up List",
            description=f"{len(queue.groups)} groups",
            lines=lines,
        )

    async def dm_view_state(
        self,
        *,
        guild: discord.Guild,
        entries: list[ReadyQueueEntry],
    ) -> QueueViewState:
        lines = []
        for index, item in enumerate(entries):
            member = guild.get_member(item.member_id)
            if member is None:
                continue
            lines.append(f"#{index + 1} {member.display_name} - {item.text}")
        return QueueViewState(title="DM Queue", lines=lines)

    async def strike_view_state(
        self,
        *,
        guild: discord.Guild,
        entries: list[ReadyQueueEntry],
    ) -> QueueViewState:
        lines = []
        for index, item in enumerate(entries):
            member = guild.get_member(item.member_id)
            if member is None:
                continue
            lines.append(f"#{index + 1} {member.display_name} - {item.text}")
        return QueueViewState(title="Strike Team Queue", lines=lines)

    async def _group_member_mentions(self, group: Group) -> str:
        names: list[str] = []
        for player in group.players:
            mark_info = await self.mark_repository.find_one({"_id": player.member.id}) or {}
            postfix = f"{'*' if mark_info.get('marked', False) else ''}{mark_info.get('custom', '')}"
            names.append(f"{player.mention}{postfix}")
        return discord.utils.escape_markdown(", ".join(names))
