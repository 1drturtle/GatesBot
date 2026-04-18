from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, cast

import discord

from common.embeds import create_queue_embed
from queueing.config import QueueRuntimeConfig
from queueing.contracts import (
    AssignResult,
    ClaimResult,
    LeaveResult,
    LockResult,
    QueueRefreshResult,
    QueueViewState,
    SignupResult,
)
from queueing.messages import build_gate_assignment_message
from queueing.documents import GateDocument, GroupDocument
from queueing.models import Group, Player, Queue
from queueing.parsing import length_check
from queueing.repository import (
    AnalyticsRepository,
    DMQueueRepository,
    GateRepository,
    QueueMetaRepository,
    QueueRepository,
    ReadyQueueEntry,
    StrikeQueueRepository,
)


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
    """Compatibility wrapper for existing imports."""
    old_message_id = await QueueMetaRepository(meta_db).resolve_message_id(
        channel=channel,
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
            try:
                await old_message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
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


class PlayerQueueService:
    def __init__(
        self,
        *,
        bot: Any,
        config: QueueRuntimeConfig,
        queue_repository: QueueRepository,
        gate_repository: GateRepository,
        analytics_repository: AnalyticsRepository,
        presentation_service: QueuePresentationService,
    ):
        self.bot = bot
        self.config = config
        self.queue_repository = queue_repository
        self.gate_repository = gate_repository
        self.analytics_repository = analytics_repository
        self.presentation_service = presentation_service

    async def signup_from_message(
        self,
        *,
        message: discord.Message,
        player: Player,
        view_factory: Callable[[], Any],
    ) -> SignupResult:
        queue = await self.queue_repository.load_for_guild(
            message.guild,  # pyright: ignore[reportArgumentType]
            channel_id=self.config.player_queue_channel_id,
        )

        if queue.in_queue(player.member.id) and not self.config.is_testing:
            return SignupResult(
                success=False,
                message="You are already in a queue!",
                should_delete_source_message=True,
            )

        if (index := queue.can_fit_in_group(player)) is not None:
            queue.groups[index].players.append(player)
            group_number = index + 1
        else:
            queue.groups.append(Group.new(player.tier, [player]))
            group_number = len(queue.groups)

        await self.analytics_repository.record_player_signup(
            member=message.author,  # pyright: ignore[reportArgumentType]
            total_level=player.total_level,
            levels=player.levels,  # pyright: ignore[reportArgumentType]
        )

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=message.guild, queue=queue, view_factory=view_factory)  # pyright: ignore[reportArgumentType]

        return SignupResult(
            success=True,
            message=f"Signed up in Group #{group_number}.",
            queue_updated=True,
            group_number=group_number,
        )

    async def leave_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        view_factory: Callable[[], Any],
        decrement_signup_count: bool,
        clear_marked: bool,
    ) -> LeaveResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )

        group_index = queue.in_queue(member_id)
        if group_index is None:
            return LeaveResult(
                success=False,
                message="You are not currently in the queue, so I cannot remove you from it.",
            )

        queue.groups[group_index[0]].players.pop(group_index[1])

        if decrement_signup_count:
            await self.analytics_repository.decrement_player_signup(member_id)
        if clear_marked:
            await self.analytics_repository.set_marked(member_id, marked=False)

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)

        return LeaveResult(
            success=True,
            message=f"You have been removed from group #{group_index[0] + 1}",
            queue_updated=True,
            group_number=group_index[0] + 1,
        )

    async def remove_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        return await self.leave_member(
            guild=guild,
            member_id=member_id,
            view_factory=view_factory,
            decrement_signup_count=False,
            clear_marked=False,
        )

    async def claim_group(
        self,
        *,
        guild: discord.Guild,
        claimant: discord.Member,
        view_factory: Callable[[], Any],
        gate_name: str | None = None,
        group_number: int | None = None,
        reinforcement: bool = False,
        use_assignment: bool = False,
    ) -> ClaimResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )

        gate: dict[str, Any] | None
        if gate_name is not None:
            gate = await self.gate_repository.get_by_name(gate_name)
            if gate is None:
                return ClaimResult(success=False, message="Invalid Gate Name!")
            await self.gate_repository.set_owner(gate["name"], claimant.id)
            gate["owner"] = claimant.id
        else:
            gate = await self.gate_repository.get_by_owner(claimant.id)
            if gate is None:
                return ClaimResult(
                    success=False,
                    message=("You have not claimed a gate. Refer to Assistant/Admin instructions for further details."),
                )

        if group_number is not None:
            check = length_check(len(queue.groups), group_number)
            if check is not None:
                return ClaimResult(success=False, message=check)
            group_index = group_number - 1
        elif use_assignment:
            group_index = None
            for index, group in enumerate(queue.groups):
                if group.assigned == claimant.id:
                    group_index = index
                    break
            if group_index is None:
                return ClaimResult(success=False, message="You do not currently have a Gate assigned.")
        else:
            return ClaimResult(success=False, message="A group number is required.")

        popped = queue.groups.pop(group_index)
        player_ids = [player.member.id for player in popped.players]
        await self.analytics_repository.clear_marks_for_members(player_ids)

        raw_group = popped.to_dict()
        raw_group.pop("position", None)
        raw_gate: GateDocument = {
            **raw_group,
            "gate_name": str(gate["name"]),
            "claimed_date": datetime.utcnow(),
        }

        if reinforcement:
            dm_owner = gate.get("owner")
            if dm_owner is not None:
                dm_info = await self.analytics_repository.get_dm_info(dm_owner)
                if dm_info and dm_info.get("dm_gates"):
                    await self.analytics_repository.record_gate_reinforcement(
                        dm_id=dm_owner,
                        gate_info=cast(GateDocument, dm_info["dm_gates"][-1]),
                    )
        else:
            await self.analytics_repository.mark_assignment_claimed()
            await self.analytics_repository.record_dm_claim(
                dm_id=claimant.id,
                gate_data=raw_gate,
            )

        for player in popped.players:
            await self.analytics_repository.record_player_gate_summon(
                member_id=player.member.id,
                gate_name=gate["name"],
                total_level=player.total_level,
            )

        await self.analytics_repository.record_claimed_group(
            gate_name=gate["name"],
            claimed_by=claimant.id,
            tier=popped.tier,
            player_levels=[player.total_level for player in popped.players],
        )

        summons_channel: discord.TextChannel = guild.get_channel(self.config.summons_channel_id)  # pyright: ignore[reportAssignmentType]
        assignment_channel = guild.get_channel(self.config.gate_assignments_channel_id)
        assignments_str = f"<#{assignment_channel.id}>" if assignment_channel is not None else "#gate-assignments-v2"

        sorted_players = sorted(popped.players, key=lambda player: player.member.display_name)
        mentions = [player.mention for player in sorted_players]

        if summons_channel is not None:
            message = ", ".join(mentions) + "\n"
            if reinforcement:
                message += (
                    f"{gate['name'].lower().title()} Gate is in need of reinforcements! Head to {assignments_str}"
                    f" and grab the {gate['emoji']} from the list and head over to the gate!\n"
                    f"Claimed by {claimant.mention}"
                )
            else:
                message += (
                    f"Welcome to the {gate['name'].lower().title()} Gate! Head to {assignments_str}"
                    f" and grab the {gate['emoji']} from the list and head over to the gate!\n"
                    f"Claimed by {claimant.mention}"
                )
            await summons_channel.send(
                message,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)

        return ClaimResult(
            success=True,
            message=f"You have claimed Group #{group_index + 1}.",
            queue_updated=True,
            claimed_group_number=group_index + 1,
            summoned_mentions=mentions,
        )

    async def refresh_queue_message(
        self,
        *,
        guild: discord.Guild,
        queue: Queue | None = None,
        view_factory: Callable[[], Any],
    ) -> QueueRefreshResult:
        if queue is None:
            queue = await self.queue_repository.load_for_guild(
                guild,
                channel_id=self.config.player_queue_channel_id,
            )

        queue.groups = [group for group in queue.groups if group.players]
        await self.queue_repository.save(queue)

        channel: discord.TextChannel = guild.get_channel(self.config.player_queue_channel_id)  # pyright: ignore[reportAssignmentType]
        if channel is None:
            raise ValueError("Queue channel not found")

        embed = await self.presentation_service.build_player_queue_embed(queue)
        return await self.presentation_service.refresh_queue_message(
            channel=channel,
            meta_key=f"player_queue:{self.config.player_queue_channel_id}",
            embed_title_prefix="Gate Sign-Up List",
            embed=embed,
            view=view_factory(),
        )

    async def move_member(
        self,
        *,
        guild: discord.Guild,
        original_group: int,
        member_id: int,
        new_group: int,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )

        check = length_check(len(queue.groups), original_group)
        if check is not None:
            return LeaveResult(success=False, message=check)
        check = length_check(len(queue.groups), new_group)
        if check is not None:
            return LeaveResult(success=False, message=check)

        old_group = queue.groups[original_group - 1]
        old_index = next(
            (index for index, player in enumerate(old_group.players) if player.member.id == member_id),
            None,
        )
        if old_index is None:
            return LeaveResult(
                success=False,
                message=f"Could not find <@{member_id}> in Group #{original_group}",
            )

        player = queue.groups[original_group - 1].players.pop(old_index)
        queue.groups[new_group - 1].players.append(player)

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)
        return LeaveResult(
            success=True,
            message=f"{player.mention} has been moved from Group #{original_group} to Group #{new_group}",
            queue_updated=True,
            group_number=new_group,
        )

    async def merge_groups(
        self,
        *,
        guild: discord.Guild,
        group_1: int,
        group_2: int,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )
        if len(queue.groups) <= 1:
            return LeaveResult(success=False, message="There is only one group in the queue.")

        for group_number in (group_1, group_2):
            check = length_check(len(queue.groups), group_number)
            if check is not None:
                return LeaveResult(success=False, message=check)

        queue.groups[group_1 - 1].players.extend(queue.groups[group_2 - 1].players)
        queue.groups.pop(group_2 - 1)

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)
        return LeaveResult(
            success=True,
            message=f"Group #{group_1} and #{group_2} have been merged.",
            queue_updated=True,
            group_number=group_1,
        )

    async def create_group_from_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )
        group_index = queue.in_queue(member_id)
        if group_index is None:
            return LeaveResult(
                success=False,
                message=f"<@{member_id}> was not in the queue, so they have not been moved.",
            )

        player = queue.groups[group_index[0]].players.pop(group_index[1])
        queue.groups.insert(group_index[0] + 1, Group.new(player.tier, [player]))

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)

        return LeaveResult(
            success=True,
            message=f"{player.mention} has been moved to a new tier {player.tier} group!",
            queue_updated=True,
            group_number=group_index[0] + 2,
        )

    async def shuffle_groups(
        self,
        *,
        guild: discord.Guild,
        tier: int,
        group_size: int,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )

        selected_players: list[Player] = []
        group_type = Group
        for group in queue.groups.copy():
            group_type = group.__class__
            if group.tier != tier or group.locked:
                continue
            queue.groups.remove(group)
            selected_players.extend(group.players)

        if not selected_players:
            return LeaveResult(success=False, message=f"No players in Rank {tier} was found.")

        selected_players = random.sample(selected_players, len(selected_players))
        for player in selected_players:
            if (index := queue.can_fit_in_group(player, group_size)) is not None:
                queue.groups[index].players.append(player)
            else:
                queue.groups.append(group_type.new(player.tier, [player]))

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)
        return LeaveResult(
            success=True,
            message="Queue shuffled.",
            queue_updated=True,
        )

    async def toggle_group_lock(
        self,
        *,
        guild: discord.Guild,
        group_number: int,
        view_factory: Callable[[], Any],
    ) -> LockResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )
        check = length_check(len(queue.groups), group_number)
        if check is not None:
            return LockResult(success=False, message=check)

        group = queue.groups[group_number - 1]
        group.locked = not group.locked

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)

        return LockResult(
            success=True,
            message=f"Group #{group_number} {'locked' if group.locked else 'unlocked'}.",
            queue_updated=True,
            is_locked=group.locked,
        )

    async def toggle_queue_lock(
        self,
        *,
        guild: discord.Guild,
        actor: discord.Member,
        queue_channel: discord.TextChannel,
        player_role: discord.Role,
        should_lock: bool,
        reason: str | None,
        view_factory: Callable[[], Any],
        send_announcement: bool,
    ) -> LockResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )

        perms = queue_channel.overwrites
        player_perms = perms.get(player_role, discord.PermissionOverwrite())
        player_perms.update(send_messages=not should_lock)
        perms.update({player_role: player_perms})

        action = "Lock" if should_lock else "Unlock"
        await queue_channel.edit(
            reason=f"Channel {action}. Requested by {actor}." + (f"\nReason: {reason}" if reason else ""),
            overwrites=perms,
        )

        if should_lock:
            embed = create_queue_embed(self.bot)
            embed.title = "Queue Channel Locked"
            embed.description = f"The queue channel has been temporarily locked by {actor}."
            if reason:
                embed.add_field(name="Reason", value=reason)
            await queue_channel.send(embed=embed)
        else:
            await self.analytics_repository.set_unlock_timestamp()
            for group in queue.groups:
                for player in group.players:
                    await self.analytics_repository.set_marked(player.member.id, marked=True)

            async for msg in queue_channel.history(limit=25):
                if msg.author.id != self.bot.user.id:
                    continue
                if msg.embeds and msg.embeds[0].title == "Queue Channel Locked":
                    try:
                        await msg.delete()
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        pass
                    break

            if send_announcement:
                announce: discord.TextChannel = guild.get_channel(self.config.gate_announcement_channel_id)  # pyright: ignore[reportAssignmentType]
                if announce is not None:
                    await announce.send(
                        (
                            f"<@&778973153962885161>, <#{self.config.player_queue_channel_id}> "
                            "has been unlocked! Sign up to join the queue!"
                        ),
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )

        queue.locked = should_lock
        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)

        return LockResult(
            success=True,
            message=f"Queue {'locked' if should_lock else 'unlocked'}.",
            queue_updated=True,
            is_locked=should_lock,
        )

    async def force_unlock_channel(
        self,
        *,
        actor: discord.Member,
        queue_channel: discord.TextChannel,
        player_role: discord.Role,
    ) -> LockResult:
        perms = queue_channel.overwrites
        player_perms = perms.get(player_role, discord.PermissionOverwrite())
        player_perms.update(send_messages=True)
        perms.update({player_role: player_perms})

        await queue_channel.edit(
            reason=f"Channel manual unlock. Requested by {actor}.",
            overwrites=perms,
        )

        return LockResult(success=True, message="Queue channel manually unlocked.", is_locked=False)

    async def empty_queue(
        self,
        *,
        guild: discord.Guild,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )
        queue.groups = []
        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)
        return LeaveResult(success=True, message="Queue emptied.", queue_updated=True)


class DMQueueService:
    def __init__(
        self,
        *,
        bot: Any,
        config: QueueRuntimeConfig,
        dm_queue_repository: DMQueueRepository,
        queue_repository: QueueRepository,
        analytics_repository: AnalyticsRepository,
        presentation_service: QueuePresentationService,
    ):
        self.bot = bot
        self.config = config
        self.dm_queue_repository = dm_queue_repository
        self.queue_repository = queue_repository
        self.analytics_repository = analytics_repository
        self.presentation_service = presentation_service

    async def signup_from_message(
        self,
        *,
        message: discord.Message,
        text: str,
        view_factory: Callable[[], Any],
    ) -> SignupResult:
        await self.dm_queue_repository.upsert_ready(
            member_id=message.author.id,
            text=text,
            message_id=message.id,
        )
        await self.analytics_repository.record_dm_queue_signup(message.author.id, delta=1)
        await self.refresh_queue_message(guild=message.guild, view_factory=view_factory)  # pyright: ignore[reportArgumentType]
        return SignupResult(success=True, message="Signed up for DM queue.", queue_updated=True)

    async def update_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        text: str,
        view_factory: Callable[[], Any],
    ) -> SignupResult:
        await self.dm_queue_repository.update_text(member_id=member_id, text=text)
        await self.refresh_queue_message(guild=guild, view_factory=view_factory)
        return SignupResult(success=True, message="DM queue entry updated.", queue_updated=True)

    async def leave_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        view_factory: Callable[[], Any],
        adjust_signup_count: bool,
    ) -> LeaveResult:
        removed = await self.dm_queue_repository.remove_member(member_id)
        if not removed:
            return LeaveResult(success=False, message="You were not in the DM queue, or an error occurred.")
        if adjust_signup_count:
            await self.analytics_repository.record_dm_queue_signup(member_id, delta=-1)
        await self.refresh_queue_message(guild=guild, view_factory=view_factory)
        return LeaveResult(success=True, message="You have left the DM queue.", queue_updated=True)

    async def assign_dm_to_group(
        self,
        *,
        guild: discord.Guild,
        summoner: discord.Member,
        group_number: int,
        view_factory: Callable[[], Any],
        queue_number: int | None = None,
        dm_member_id: int | None = None,
        allow_reassignment: bool = True,
    ) -> AssignResult:
        entries = await self.dm_queue_repository.list_entries()
        if not entries:
            return AssignResult(success=False, message="No DMs currently in DM queue.")

        target_entry: ReadyQueueEntry | None = None
        if queue_number is not None:
            if queue_number < 1 or queue_number > len(entries):
                return AssignResult(
                    success=False,
                    message=f"Invalid DM Queue number. Must be less than or equal to {len(entries)}",
                )
            target_entry = entries[queue_number - 1]
        elif dm_member_id is not None:
            target_entry = next((entry for entry in entries if entry.member_id == dm_member_id), None)
            if target_entry is None:
                return AssignResult(success=False, message="Selected DM is not currently in queue.")
        else:
            return AssignResult(success=False, message="No DM selection provided.")

        dm_member = guild.get_member(target_entry.member_id)
        if dm_member is None:
            return AssignResult(success=False, message="Selected DM is no longer in this server.")

        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )
        check = length_check(len(queue.groups), group_number)
        if check is not None:
            return AssignResult(success=False, message=check)

        group = queue.groups[group_number - 1]
        if group.assigned is not None and not allow_reassignment:
            return AssignResult(
                success=False,
                message=(
                    "A DM is already assigned to this gate. Please assign via command if you wish to assign again."
                ),
            )

        group.assigned = dm_member.id
        await self.queue_repository.save(queue)

        assignment_channel = guild.get_channel(self.config.dm_queue_assignment_channel_id)
        if assignment_channel is None:
            return AssignResult(success=False, message="DM assignment channel not found.")

        await self.presentation_service.send_gate_assignment(
            group=group,
            group_number=group_number,
            dm_member=dm_member,
            assignment_channel=assignment_channel,  # pyright: ignore[reportArgumentType]
        )

        await self.analytics_repository.record_dm_assignment(
            summoner_id=summoner.id,
            dm_id=dm_member.id,
            gate_data=cast(GroupDocument, group.to_dict()),
        )
        await self.analytics_repository.increment_dm_assignments(dm_member.id)

        await self.dm_queue_repository.remove_member(dm_member.id)
        await self.refresh_queue_message(guild=guild, view_factory=view_factory)

        return AssignResult(
            success=True,
            message=f"Gate #{group_number} assigned to {dm_member.mention}",
            queue_updated=True,
            assigned_member_id=dm_member.id,
        )

    async def queue_view_state(self, guild: discord.Guild) -> QueueViewState:
        entries = await self.dm_queue_repository.list_entries()
        return await self.presentation_service.dm_view_state(guild=guild, entries=entries)

    async def refresh_queue_message(
        self,
        *,
        guild: discord.Guild,
        view_factory: Callable[[], Any],
    ) -> QueueRefreshResult:
        entries = await self.dm_queue_repository.list_entries()
        channel = guild.get_channel(self.config.dm_queue_channel_id)
        if channel is None:
            raise ValueError("DM queue channel not found")

        embed = await self.presentation_service.build_dm_queue_embed(guild=guild, entries=entries)
        return await self.presentation_service.refresh_queue_message(
            channel=channel,  # pyright: ignore[reportArgumentType]
            meta_key=f"dm_queue:{self.config.dm_queue_channel_id}",
            embed_title_prefix="DM Queue",
            embed=embed,
            view=view_factory(),
        )


class StrikeQueueService:
    def __init__(
        self,
        *,
        bot: Any,
        config: QueueRuntimeConfig,
        strike_queue_repository: StrikeQueueRepository,
        gate_repository: GateRepository,
        analytics_repository: AnalyticsRepository,
        presentation_service: QueuePresentationService,
    ):
        self.bot = bot
        self.config = config
        self.strike_queue_repository = strike_queue_repository
        self.gate_repository = gate_repository
        self.analytics_repository = analytics_repository
        self.presentation_service = presentation_service

    async def signup_from_message(
        self,
        *,
        message: discord.Message,
        text: str,
        view_factory: Callable[[], Any],
    ) -> SignupResult:
        await self.strike_queue_repository.upsert_ready(
            member_id=message.author.id,
            text=text,
            message_id=message.id,
        )
        await self.refresh_queue_message(guild=message.guild, view_factory=view_factory)  # pyright: ignore[reportArgumentType]
        return SignupResult(success=True, message="Signed up for strike queue.", queue_updated=True)

    async def update_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        text: str,
        view_factory: Callable[[], Any],
    ) -> SignupResult:
        await self.strike_queue_repository.update_text(member_id=member_id, text=text)
        await self.refresh_queue_message(guild=guild, view_factory=view_factory)
        return SignupResult(success=True, message="Strike queue entry updated.", queue_updated=True)

    async def leave_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        view_factory: Callable[[], Any],
    ) -> LeaveResult:
        removed = await self.strike_queue_repository.remove_member(member_id)
        if not removed:
            return LeaveResult(success=False, message="You were not in the Strike queue, or an error occurred.")

        await self.refresh_queue_message(guild=guild, view_factory=view_factory)
        return LeaveResult(success=True, message="You have left the Strike queue.", queue_updated=True)

    async def assign_strike_team(
        self,
        *,
        guild: discord.Guild,
        queue_numbers: list[int],
        gate_name: str,
        view_factory: Callable[[], Any],
    ) -> AssignResult:
        entries = await self.strike_queue_repository.list_entries()
        if not entries:
            return AssignResult(success=False, message="No Strike Team members currently in Strike Team queue.")

        selected_entries: list[ReadyQueueEntry] = []
        for queue_number in queue_numbers:
            if queue_number < 1 or queue_number > len(entries):
                return AssignResult(
                    success=False,
                    message=(
                        f"Invalid Strike Team Queue number ({queue_number}). Must be between 1 and {len(entries)}"
                    ),
                )
            selected_entries.append(entries[queue_number - 1])

        gate_data = await self.gate_repository.get_by_name(gate_name)
        if gate_data is None:
            return AssignResult(
                success=False,
                message=(f"{gate_name} does not exist, please try again with a valid gate name."),
            )

        people = [guild.get_member(item.member_id) for item in selected_entries]
        people = [member for member in people if member is not None]
        if not people:
            return AssignResult(success=False, message="No selected Strike Team members are available.")

        assignment_channel = guild.get_channel(self.config.strike_queue_assignment_channel_id)
        if assignment_channel is None:
            return AssignResult(success=False, message="Strike assignment channel not found.")

        message = (
            f"{' '.join([member.mention for member in people])}\n"
            f"{gate_data['name'].title()} Gate is in need of Strike Team reinforcements!"
            f" Head to <#{self.config.gate_assignments_channel_id}> and grab the {gate_data['emoji']}"
            " from the list and head over to the gate!"
        )
        await assignment_channel.send(message, allowed_mentions=discord.AllowedMentions(users=True))  # pyright: ignore[reportAttributeAccessIssue]

        for member in people:
            await self.analytics_repository.set_last_strike_gate(member.id, gate_data["name"])

        dm_owner = gate_data.get("owner")
        if dm_owner is not None:
            dm_info = await self.analytics_repository.get_dm_info(dm_owner)
            if dm_info and dm_info.get("dm_gates"):
                await self.analytics_repository.record_strike_team_reinforcement(
                    user_ids=[member.id for member in people],
                    dm_id=dm_owner,
                    gate_name=gate_data["name"],
                    gate_info=cast(GateDocument, dm_info["dm_gates"][-1]),
                )

        await self.strike_queue_repository.remove_members([item.member_id for item in selected_entries])
        await self.refresh_queue_message(guild=guild, view_factory=view_factory)

        return AssignResult(
            success=True,
            message="Strike team assigned.",
            queue_updated=True,
            assigned_member_id=people[0].id if people else None,
        )

    async def queue_view_state(self, guild: discord.Guild) -> QueueViewState:
        entries = await self.strike_queue_repository.list_entries()
        return await self.presentation_service.strike_view_state(guild=guild, entries=entries)

    async def refresh_queue_message(
        self,
        *,
        guild: discord.Guild,
        view_factory: Callable[[], Any],
    ) -> QueueRefreshResult:
        entries = await self.strike_queue_repository.list_entries()
        channel = guild.get_channel(self.config.strike_queue_channel_id)
        if channel is None:
            raise ValueError("Strike queue channel not found")

        embed = await self.presentation_service.build_strike_queue_embed(guild=guild, entries=entries)
        return await self.presentation_service.refresh_queue_message(
            channel=channel,  # pyright: ignore[reportArgumentType]
            meta_key=f"strike_queue:{self.config.strike_queue_channel_id}",
            embed_title_prefix="Strike Team Queue",
            embed=embed,
            view=view_factory(),
        )


@dataclass(slots=True)
class QueueServices:
    config: QueueRuntimeConfig
    queue_repository: QueueRepository
    dm_queue_repository: DMQueueRepository
    strike_queue_repository: StrikeQueueRepository
    gate_repository: GateRepository
    analytics_repository: AnalyticsRepository
    meta_repository: QueueMetaRepository
    presentation_service: QueuePresentationService
    player_queue_service: PlayerQueueService
    dm_queue_service: DMQueueService
    strike_queue_service: StrikeQueueService


_SERVICE_CACHE_ATTR = "_queue_services"


def get_queue_services(bot: Any) -> QueueServices:
    cached = getattr(bot, _SERVICE_CACHE_ATTR, None)
    if cached is not None:
        return cached

    config = QueueRuntimeConfig.from_environment(bot.environment)
    queue_repository = QueueRepository(
        bot.mdb["player_queue"],
        default_channel_id=config.player_queue_channel_id,
    )
    dm_queue_repository = DMQueueRepository(bot.mdb["dm_queue"])
    strike_queue_repository = StrikeQueueRepository(bot.mdb["strike_queue"])
    gate_repository = GateRepository(bot.mdb["gate_list"])
    analytics_repository = AnalyticsRepository(bot.mdb)
    meta_repository = QueueMetaRepository(bot.mdb["queue_meta"])
    presentation_service = QueuePresentationService(bot=bot, meta_repository=meta_repository)

    player_queue_service = PlayerQueueService(
        bot=bot,
        config=config,
        queue_repository=queue_repository,
        gate_repository=gate_repository,
        analytics_repository=analytics_repository,
        presentation_service=presentation_service,
    )
    dm_queue_service = DMQueueService(
        bot=bot,
        config=config,
        dm_queue_repository=dm_queue_repository,
        queue_repository=queue_repository,
        analytics_repository=analytics_repository,
        presentation_service=presentation_service,
    )
    strike_queue_service = StrikeQueueService(
        bot=bot,
        config=config,
        strike_queue_repository=strike_queue_repository,
        gate_repository=gate_repository,
        analytics_repository=analytics_repository,
        presentation_service=presentation_service,
    )

    services = QueueServices(
        config=config,
        queue_repository=queue_repository,
        dm_queue_repository=dm_queue_repository,
        strike_queue_repository=strike_queue_repository,
        gate_repository=gate_repository,
        analytics_repository=analytics_repository,
        meta_repository=meta_repository,
        presentation_service=presentation_service,
        player_queue_service=player_queue_service,
        dm_queue_service=dm_queue_service,
        strike_queue_service=strike_queue_service,
    )
    setattr(bot, _SERVICE_CACHE_ATTR, services)
    return services
