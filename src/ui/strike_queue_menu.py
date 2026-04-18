import disnake
import discord
import utils.constants as constants


class StrikeQueueUI(disnake.ui.View):
    def __init__(self, bot, queue_type, *args, **kwargs):
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_type = queue_type
        self.queue_channel_id = (
            constants.STRIKE_QUEUE_CHANNEL_DEBUG
            if self.bot.environment == "testing"
            else constants.STRIKE_QUEUE_CHANNEL
        )
        self.assign_id = (
            constants.STRIKE_QUEUE_ASSIGNMENT_CHANNEL_DEBUG
            if self.bot.environment == "testing"
            else constants.STRIKE_QUEUE_ASSIGNMENT_CHANNEL
        )
        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )

        self.strike_cog = self.bot.cogs["StrikeQueue"]

        self.db = self.bot.mdb["strike_queue"]
        self.gate_db = bot.mdb["gate_list"]
        self.data_db = self.bot.mdb["queue_analytics"]
        self.r_db = self.bot.mdb["reinforcement_analytics"]

    @disnake.ui.button(
        label="Leave",
        style=disnake.ButtonStyle.red,
        custom_id="gatesbot_strikequeue_leave",
    )
    async def leave_button(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        """
        Attempt to leave the Strike queue.
        """

        try:
            await self.db.delete_one({"_id": inter.author.id})
        except:
            return await inter.send(
                "You were not in the Strike queue, or an error occurred.",
                ephemeral=True,
            )
        else:
            await self.strike_cog.update_queue()

        return await inter.send("You have left the Strike queue.", ephemeral=True)
