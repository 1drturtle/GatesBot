from __future__ import annotations

import logging
from typing import cast

import disnake as discord

from common.discord_utils import require_interaction_guild
from queueing.services import get_queue_services
from queueing.views.admin import PlayerQueueManageUI

log = logging.getLogger(__name__)

JOIN_MODAL_INPUT_ID = "gatesbot_playerqueue_join_classes"
JOIN_BUTTON_CUSTOM_ID = "gatesbot_playerqueue_join"


class PlayerQueueJoinModal(discord.ui.Modal):
    def __init__(self, bot, *, default_text: str | None = None):
        self.bot = bot
        self.services = get_queue_services(bot)
        self.player_service = self.services.player_queue_service

        components = [
            discord.ui.TextInput(
                label="Class and level",
                custom_id=JOIN_MODAL_INPUT_ID,
                style=discord.TextInputStyle.paragraph,
                placeholder="Fighter 5 or Battle Master Fighter 5 / Wizard 3",
                value=default_text,
                required=True,
                max_length=500,
            )
        ]
        super().__init__(
            title="Join Player Queue",
            custom_id="gatesbot_playerqueue_join_modal",
            components=components,
        )

    async def callback(self, inter: discord.ModalInteraction):
        text = inter.text_values[JOIN_MODAL_INPUT_ID].strip()
        member = cast(discord.Member, inter.author)
        result = await self.player_service.signup_from_text(
            guild=require_interaction_guild(inter),
            member=member,
            text=text,
        )

        return await inter.send(result.message, ephemeral=True)


class PlayerQueueUI(discord.ui.View):
    def __init__(self, bot, *, queue_locked: bool = False):
        super().__init__(timeout=None)
        self.bot = bot
        self.services = get_queue_services(bot)
        self.player_service = self.services.player_queue_service
        self.queue_repo = self.services.queue_repository
        self._set_join_button_disabled(queue_locked)

    def _set_join_button_disabled(self, disabled: bool) -> None:
        for child in self.children:
            if getattr(child, "custom_id", None) == JOIN_BUTTON_CUSTOM_ID:
                child.disabled = disabled
                return

    async def queue_from_guild(self, guild: discord.Guild):
        return await self.queue_repo.load_for_guild(
            guild,
            channel_id=self.services.config.player_queue_channel_id,
        )

    @discord.ui.button(
        label="Join",
        style=discord.ButtonStyle.green,
        custom_id=JOIN_BUTTON_CUSTOM_ID,
    )
    async def join_button(self, _: discord.ui.Button, inter: discord.MessageInteraction):
        member = cast(discord.Member, inter.author)
        queue = await self.queue_from_guild(require_interaction_guild(inter))
        if queue.locked:
            return await inter.send("The queue is currently locked.", ephemeral=True)

        default_text = await self.services.analytics_repository.get_last_player_signup_text(member.id)
        return await inter.response.send_modal(PlayerQueueJoinModal(self.bot, default_text=default_text))

    @discord.ui.button(
        label="Leave",
        style=discord.ButtonStyle.red,
        custom_id="gatesbot_playerqueue_leave",
    )
    async def leave_button(self, _: discord.ui.Button, inter: discord.MessageInteraction):
        member = cast(discord.Member, inter.author)
        result = await self.player_service.leave_member(
            guild=require_interaction_guild(inter),
            member_id=member.id,
            decrement_signup_count=True,
            clear_marked=True,
        )

        return await inter.send(result.message, ephemeral=True)

    @discord.ui.button(
        emoji="⚙",
        style=discord.ButtonStyle.grey,
        custom_id="gatesbot_playerqueue_manage",
        disabled=False,
    )
    async def manage_button(self, _, inter: discord.MessageInteraction):
        member = cast(discord.Member, inter.author)
        queue = await self.queue_from_guild(require_interaction_guild(inter))

        if not (member.id == self.bot.owner_id or any(role.name == "Assistant" for role in member.roles)):
            return await inter.send(
                "You are not allowed to use this function.",
                ephemeral=True,
            )

        view = PlayerQueueManageUI(self.bot, queue)
        embed = await view.generate_menu(inter)
        return await inter.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.primary,
        custom_id="gatesbot_playerqueue_claim",
    )
    async def claim_button(self, _, inter: discord.MessageInteraction):
        member = cast(discord.Member, inter.author)
        if not (member.id == self.bot.owner_id or any(role.name == "DM" for role in member.roles)):
            return await inter.send(
                "You are not allowed to use this function.",
                ephemeral=True,
            )

        await inter.response.defer()

        result = await self.player_service.claim_group(
            guild=require_interaction_guild(inter),
            claimant=member,
            use_assignment=True,
        )

        if not result.success:
            return await inter.send(result.message, ephemeral=True)

        log.info("[Queue] %s claimed Group #%s from the queue view.", inter.author, result.claimed_group_number)
        return await inter.send(result.message, ephemeral=True)


__all__ = ["PlayerQueueJoinModal", "PlayerQueueUI"]
