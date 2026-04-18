from __future__ import annotations

import disnake


class StrikeQueueUI(disnake.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.strike_cog = self.bot.cogs["StrikeQueue"]
        self.db = self.bot.mdb["strike_queue"]

    @disnake.ui.button(
        label="Leave",
        style=disnake.ButtonStyle.red,
        custom_id="gatesbot_strikequeue_leave",
    )
    async def leave_button(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        result = await self.db.delete_one({"_id": inter.author.id})
        if result.deleted_count == 0:
            return await inter.send(
                "You were not in the Strike queue, or an error occurred.",
                ephemeral=True,
            )

        await self.strike_cog.update_queue()
        return await inter.send("You have left the Strike queue.", ephemeral=True)


__all__ = ["StrikeQueueUI"]
