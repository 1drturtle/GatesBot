from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Callable, cast

import disnake as discord

from common.embeds import create_queue_embed
from queueing.config import QueueRuntimeConfig
from queueing.contracts import ClaimResult, LeaveResult, LockResult, QueueRefreshResult, SignupResult
from queueing.documents import GateDocument
from queueing.models import Group, Player, Queue
from queueing.parsing import check_level_role, length_check, parse_player_class
from queueing.repositories import AnalyticsRepository, GateRepository, QueueRepository
from queueing.services.presentation import QueuePresentationService

PLAYER_QUEUE_JOIN_CUSTOM_ID = "gatesbot_playerqueue_join"


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
        signup_text: str | None = None,
    ) -> SignupResult:
        return await self.signup_player(
            guild=message.guild,  # pyright: ignore[reportArgumentType]
            member=message.author,  # pyright: ignore[reportArgumentType]
            player=player,
            view_factory=view_factory,
            signup_text=signup_text,
            should_delete_duplicate_source=True,
        )

    async def signup_from_text(
        self,
        *,
        guild: discord.Guild,
        member: discord.Member,
        text: str,
        view_factory: Callable[[], Any],
        should_delete_duplicate_source: bool = False,
    ) -> SignupResult:
        player_details = parse_player_class(text.strip())
        player = Player.new(member, player_details)
        await check_level_role(player)

        return await self.signup_player(
            guild=guild,
            member=member,
            player=player,
            view_factory=view_factory,
            signup_text=text.strip(),
            should_delete_duplicate_source=should_delete_duplicate_source,
        )

    async def signup_player(
        self,
        *,
        guild: discord.Guild,
        member: discord.Member,
        player: Player,
        view_factory: Callable[[], Any],
        signup_text: str | None = None,
        should_delete_duplicate_source: bool = False,
    ) -> SignupResult:
        queue = await self.queue_repository.load_for_guild(
            guild,
            channel_id=self.config.player_queue_channel_id,
        )

        if queue.in_queue(player.member.id) and not self.config.is_testing:
            return SignupResult(
                success=False,
                message="You are already in a queue!",
                should_delete_source_message=should_delete_duplicate_source,
            )

        if (index := queue.can_fit_in_group(player)) is not None:
            queue.groups[index].players.append(player)
            group_number = index + 1
        else:
            queue.groups.append(Group.new(player.tier, [player]))
            group_number = len(queue.groups)

        await self.analytics_repository.record_player_signup(
            member=member,
            total_level=player.total_level,
            levels=player.levels,  # pyright: ignore[reportArgumentType]
            signup_text=signup_text,
        )

        await self.queue_repository.save(queue)
        await self.refresh_queue_message(guild=guild, queue=queue, view_factory=view_factory)

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
        view = view_factory()
        for child in getattr(view, "children", []):
            if getattr(child, "custom_id", None) == PLAYER_QUEUE_JOIN_CUSTOM_ID:
                child.disabled = queue.locked
                break

        return await self.presentation_service.refresh_queue_message(
            channel=channel,
            meta_key=f"player_queue:{self.config.player_queue_channel_id}",
            embed_title_prefix="Gate Sign-Up List",
            embed=embed,
            view=view,
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
                    except discord.Forbidden, discord.NotFound, discord.HTTPException:
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
