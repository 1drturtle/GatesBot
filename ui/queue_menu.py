import disnake
import discord
import utils.constants as constants
from ui.queue_admin_menu import PlayerQueueManageUi


class PlayerQueueUI(disnake.ui.View):
    def __init__(self, bot, queue_type, *args, **kwargs):
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_type = queue_type
        self.queue_db = bot.mdb["player_queue"]
        self.channel_id = (
            constants.GATES_CHANNEL
            if self.bot.environment != "testing"
            else constants.DEBUG_CHANNEL
        )
        self.old_player_data_db = bot.mdb["queue_analytics"]

    async def queue_from_guild(self, db, guild: discord.Guild):
        queue_data = await db.find_one({"guild_id": guild.id})
        if queue_data is None:
            queue_data = {"groups": [], "server_id": guild.id, "channel_id": None}
        queue = self.queue_type.from_dict(guild, queue_data)
        queue.groups.sort(key=lambda x: x.tier)
        return queue

    @disnake.ui.button(
        label="Leave",
        style=disnake.ButtonStyle.red,
        custom_id="gatesbot_playerqueue_leave",
    )
    async def leave_button(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        """
        Attempt to leave the queue.
        """
        queue = await self.queue_from_guild(self.queue_db, inter.guild)

        group_index = queue.in_queue(inter.author.id)
        if group_index is None:
            return await inter.send(
                "You are not currently in the queue, so I cannot remove you from it.",
                ephemeral=True,
            )

        # Pop the Player from the Group and Update!
        queue.groups[group_index[0]].players.pop(group_index[1])
        await queue.update(
            self.bot, self.queue_db, inter.guild.get_channel(self.channel_id)
        )

        # update analytics
        data = {
            "$set": {
                "user_id": inter.author.id,
            },
            "$inc": {"gate_signup_count": -1},
        }

        await self.old_player_data_db.update_one(
            {"user_id": inter.author.id}, data, upsert=True
        )

        return await inter.send(
            f"You have been removed from group #{group_index[0] + 1}", ephemeral=True
        )

    @disnake.ui.button(
        emoji="⚙",
        style=disnake.ButtonStyle.grey,
        custom_id="gatesbot_playerqueue_manage",
        disabled=False,
    )
    async def manage_button(self, button, inter: disnake.MessageInteraction):
        queue = await self.queue_from_guild(self.queue_db, inter.guild)

        if not (
            inter.author.id == self.bot.owner_id
            or any(True for r in inter.author.roles if r.name == "Assistant")
        ):
            return await inter.send(
                "You are not allowed to use this function.", ephemeral=True
            )

        view = PlayerQueueManageUi(self.bot, queue)
        embed = await view.generate_menu(inter)

        return await inter.send(embed=embed, view=view, ephemeral=True)
