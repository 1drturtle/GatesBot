import disnake


class DMQueueUI(disnake.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

        self.dm_cog = self.bot.cogs["DMQueue"]
        self.db = self.bot.mdb["dm_queue"]
        self.dm_db = self.bot.mdb["dm_analytics"]

    @disnake.ui.button(
        label="Leave",
        style=disnake.ButtonStyle.red,
        custom_id="gatesbot_dmqueue_leave",
    )
    async def leave_button(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        """
        Attempt to leave the DM queue.
        """

        await self.dm_db.update_one(
            {"_id": inter.author.id},
            {
                "$inc": {"dm_queue.signups": -1},
            },
            upsert=True,
        )

        try:
            await self.db.delete_one({"_id": inter.author.id})
        except:
            return await inter.send(
                "You were not in the DM queue, or an error occurred.", ephemeral=True
            )
        else:
            await self.dm_cog.update_queue()

        return await inter.send("You have left the DM queue.", ephemeral=True)
