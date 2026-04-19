from __future__ import annotations

import logging

import disnake as discord

from queueing.services import get_queue_services
from queueing.views.admin import PlayerQueueManageUI

log = logging.getLogger(__name__)


class PlayerQueueUI(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.services = get_queue_services(bot)
        self.player_service = self.services.player_queue_service
        self.queue_repo = self.services.queue_repository

    async def queue_from_guild(self, guild):
        return await self.queue_repo.load_for_guild(
            guild,
            channel_id=self.services.config.player_queue_channel_id,
        )

    @discord.ui.button(
        label="Leave",
        style=discord.ButtonStyle.red,
        custom_id="gatesbot_playerqueue_leave",
    )
    async def leave_button(self, _: discord.ui.Button, inter: discord.MessageInteraction):
        result = await self.player_service.leave_member(
            guild=inter.guild,  # pyright: ignore[reportArgumentType]
            member_id=inter.author.id,
            view_factory=lambda: PlayerQueueUI(self.bot),
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
        queue = await self.queue_from_guild(inter.guild)

        if not (
            inter.author.id == self.bot.owner_id or any(True for role in inter.author.roles if role.name == "Assistant")  # pyright: ignore[reportAttributeAccessIssue]
        ):
            return await inter.send(
                "You are not allowed to use this function.",
                ephemeral=True,
            )

        view = PlayerQueueManageUI(self.bot, queue)
        embed = await view.generate_menu(inter)
        return await inter.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.green,
        custom_id="gatesbot_playerqueue_claim",
    )
    async def claim_button(self, _, inter: discord.MessageInteraction):
        if not (inter.author.id == self.bot.owner_id or any(True for role in inter.author.roles if role.name == "DM")):  # pyright: ignore[reportAttributeAccessIssue]
            return await inter.send(
                "You are not allowed to use this function.",
                ephemeral=True,
            )

        await inter.response.defer()

        result = await self.player_service.claim_group(
            guild=inter.guild,  # pyright: ignore[reportArgumentType]
            claimant=inter.author,  # pyright: ignore[reportArgumentType]
            use_assignment=True,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )

        if not result.success:
            return await inter.send(result.message, ephemeral=True)

        log.info("[Queue] %s claimed Group #%s from the queue view.", inter.author, result.claimed_group_number)
        return await inter.send(result.message, ephemeral=True)


__all__ = ["PlayerQueueUI"]
