from __future__ import annotations

from typing import Any, Callable, cast

import disnake as discord

from queueing.config import QueueRuntimeConfig
from queueing.contracts import AssignResult, LeaveResult, QueueRefreshResult, QueueViewState, SignupResult
from queueing.documents import GateDocument
from queueing.repositories import AnalyticsRepository, GateRepository, ReadyQueueEntry, StrikeQueueRepository
from queueing.services.presentation import QueuePresentationService


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
