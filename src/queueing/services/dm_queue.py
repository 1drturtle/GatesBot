from __future__ import annotations

from typing import Callable, cast

import disnake as discord

from common.discord_utils import require_message_guild, require_text_channel
from common.types import MongoBackedBot
from queueing.config import QueueRuntimeConfig
from queueing.contracts import AssignResult, LeaveResult, QueueRefreshResult, QueueViewState, SignupResult
from queueing.documents import GroupDocument
from queueing.parsing import length_check
from queueing.repositories import AnalyticsRepository, DMQueueRepository, QueueRepository, ReadyQueueEntry
from queueing.services.presentation import QueuePresentationService


class DMQueueService:
    def __init__(
        self,
        *,
        bot: MongoBackedBot,
        config: QueueRuntimeConfig,
        dm_queue_repository: DMQueueRepository,
        queue_repository: QueueRepository,
        analytics_repository: AnalyticsRepository,
        presentation_service: QueuePresentationService,
        view_factory: Callable[[], discord.ui.View],
    ):
        self.bot = bot
        self.config = config
        self.dm_queue_repository = dm_queue_repository
        self.queue_repository = queue_repository
        self.analytics_repository = analytics_repository
        self.presentation_service = presentation_service
        self.view_factory = view_factory

    async def signup_from_message(
        self,
        *,
        message: discord.Message,
        text: str,
    ) -> SignupResult:
        await self.dm_queue_repository.upsert_ready(
            member_id=message.author.id,
            text=text,
            message_id=message.id,
        )
        await self.analytics_repository.record_dm_queue_signup(message.author.id, delta=1)
        await self.refresh_queue_message(guild=require_message_guild(message))
        return SignupResult(success=True, message="Signed up for DM queue.", queue_updated=True)

    async def update_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        text: str,
    ) -> SignupResult:
        await self.dm_queue_repository.update_text(member_id=member_id, text=text)
        await self.refresh_queue_message(guild=guild)
        return SignupResult(success=True, message="DM queue entry updated.", queue_updated=True)

    async def leave_member(
        self,
        *,
        guild: discord.Guild,
        member_id: int,
        adjust_signup_count: bool,
    ) -> LeaveResult:
        removed = await self.dm_queue_repository.remove_member(member_id)
        if not removed:
            return LeaveResult(success=False, message="You were not in the DM queue, or an error occurred.")
        if adjust_signup_count:
            await self.analytics_repository.record_dm_queue_signup(member_id, delta=-1)
        await self.refresh_queue_message(guild=guild)
        return LeaveResult(success=True, message="You have left the DM queue.", queue_updated=True)

    async def assign_dm_to_group(
        self,
        *,
        guild: discord.Guild,
        summoner: discord.Member,
        group_number: int,
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

        raw_assignment_channel = guild.get_channel(self.config.dm_queue_assignment_channel_id)
        if raw_assignment_channel is None:
            return AssignResult(success=False, message="DM assignment channel not found.")
        assignment_channel = require_text_channel(
            guild,
            self.config.dm_queue_assignment_channel_id,
            name="DM assignment",
        )

        await self.presentation_service.send_gate_assignment(
            group=group,
            group_number=group_number,
            dm_member=dm_member,
            assignment_channel=assignment_channel,
        )

        await self.analytics_repository.record_dm_assignment(
            summoner_id=summoner.id,
            dm_id=dm_member.id,
            gate_data=cast(GroupDocument, group.to_dict()),
        )
        await self.analytics_repository.increment_dm_assignments(dm_member.id)

        await self.dm_queue_repository.remove_member(dm_member.id)
        await self.refresh_queue_message(guild=guild)

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
    ) -> QueueRefreshResult:
        entries = await self.dm_queue_repository.list_entries()
        channel = require_text_channel(guild, self.config.dm_queue_channel_id, name="DM queue")

        embed = await self.presentation_service.build_dm_queue_embed(guild=guild, entries=entries)
        return await self.presentation_service.refresh_queue_message(
            channel=channel,
            meta_key=f"dm_queue:{self.config.dm_queue_channel_id}",
            embed_title_prefix="DM Queue",
            embed=embed,
            view=self.view_factory(),
        )
