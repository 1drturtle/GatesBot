import disnake
import discord
import utils.constants as constants


class DMQueueUI(disnake.ui.View):
    def __init__(self, bot, queue_type, *args, **kwargs):
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_type = queue_type
        self.queue_channel_id = (
            constants.DM_QUEUE_CHANNEL_DEBUG
            if self.bot.environment == "testing"
            else constants.DM_QUEUE_CHANNEL
        )
        self.assign_id = (
            constants.DM_QUEUE_ASSIGNMENT_CHANNEL_DEBUG
            if self.bot.environment == "testing"
            else constants.DM_QUEUE_ASSIGNMENT_CHANNEL
        )
        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )

        self.dm_cog = self.bot.cogs["DMQueue"]
        self.db = self.bot.mdb["dm_queue"]
        self.dm_db = self.bot.mdb["dm_analytics"]
        self.assign_data_db = self.bot.mdb["dm_assign_analytics"]

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
