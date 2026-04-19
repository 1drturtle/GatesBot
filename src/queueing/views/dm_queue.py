from __future__ import annotations

import disnake as discord

from queueing.services import get_queue_services


class DMQueueUI(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.services = get_queue_services(bot)
        self.dm_service = self.services.dm_queue_service

    @discord.ui.button(
        label="Leave",
        style=discord.ButtonStyle.red,
        custom_id="gatesbot_dmqueue_leave",
    )
    async def leave_button(self, button: discord.ui.Button, inter: discord.MessageInteraction):
        del button
        result = await self.dm_service.leave_member(
            guild=inter.guild,  # pyright: ignore[reportArgumentType]
            member_id=inter.author.id,
            view_factory=lambda: DMQueueUI(self.bot),
            adjust_signup_count=True,
        )

        return await inter.send(result.message, ephemeral=True)


__all__ = ["DMQueueUI"]
