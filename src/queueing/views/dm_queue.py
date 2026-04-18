from __future__ import annotations

import disnake

from queueing.services import get_queue_services


class DMQueueUI(disnake.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.services = get_queue_services(bot)
        self.dm_service = self.services.dm_queue_service

    @disnake.ui.button(
        label="Leave",
        style=disnake.ButtonStyle.red,
        custom_id="gatesbot_dmqueue_leave",
    )
    async def leave_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        del button
        result = await self.dm_service.leave_member(
            guild=inter.guild,  # pyright: ignore[reportArgumentType]
            member_id=inter.author.id,
            view_factory=lambda: DMQueueUI(self.bot),
            adjust_signup_count=True,
        )

        return await inter.send(result.message, ephemeral=True)


__all__ = ["DMQueueUI"]
