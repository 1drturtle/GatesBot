import disnake
import discord
import utils.constants as constants
from utils.functions import create_default_embed, try_delete
import logging

log = logging.getLogger(__name__)


class ManageUIParent(disnake.ui.View):
    def __init__(self, bot, queue):
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_type = queue.__class__
        self.queue_db = bot.mdb["player_queue"]
        self.mark_db = self.bot.mdb["player_marked"]
        self.old_player_data_db = bot.mdb["queue_analytics"]

        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )
        self.channel_id = (
            constants.GATES_CHANNEL
            if self.bot.environment != "testing"
            else constants.DEBUG_CHANNEL
        )
        self.announcement_channel_id = (
            constants.GATE_ANNOUNCEMENT_CHANNEL
            if self.bot.environment != "testing"
            else constants.GATE_ANNOUNCEMENT_CHANNEL_DEBUG
        )

    async def queue_from_guild(self, db, guild: discord.Guild):
        queue_data = await db.find_one({"guild_id": guild.id})
        if queue_data is None:
            queue_data = {"groups": [], "server_id": guild.id, "channel_id": None}
        queue = self.queue_type.from_dict(guild, queue_data)
        queue.groups.sort(key=lambda x: x.tier)
        return queue

    async def refresh_menu(self, interaction):
        await self.custom_refresh(interaction)
        embed = await self.generate_menu(interaction)

        if interaction.response.is_done():
            await interaction.edit_original_message(view=self, embed=embed)
        else:
            await interaction.response.edit_message(view=self, embed=embed)

    async def custom_refresh(self, interaction):
        raise NotImplementedError()

    async def generate_menu(self, interaction) -> disnake.Embed:
        raise NotImplementedError()


class PlayerQueueManageUi(ManageUIParent):
    def __init__(self, bot, queue):
        super().__init__(bot, queue)

        self.group_selector = GroupSelector(bot, queue)

        self.add_item(self.group_selector)

    async def custom_refresh(self, interaction):
        queue = await self.queue_from_guild(self.queue_db, interaction.guild)

        self.remove_item(self.group_selector)
        self.group_selector = GroupSelector(self.bot, queue)
        self.add_item(self.group_selector)

    async def generate_menu(self, interaction) -> disnake.Embed:
        queue = await self.queue_from_guild(self.queue_db, interaction.guild)

        embed = create_default_embed(interaction)
        embed.title = "GatesBot - Queue Manager"
        embed.description = f"**Locked:** {queue.locked}"
        return embed

    @disnake.ui.button(label="Toggle Lock", emoji="🔒")
    async def toggle_queue_lock(self, button, inter: disnake.MessageInteraction):
        queue_channel: discord.TextChannel = inter.guild.get_channel(self.channel_id)

        # new perms
        player_role: discord.Role = discord.utils.find(
            lambda r: r.name.lower() == "player", inter.guild.roles
        )

        perms = queue_channel.overwrites
        player_perms = perms.get(player_role, discord.PermissionOverwrite())

        is_locked = player_perms.send_messages
        locked_status = "locked" if is_locked else "unlocked"

        player_perms.update(send_messages=not is_locked)
        perms.update({player_role: player_perms})

        log.info(f"Queue has been {locked_status} by {inter.author}")

        # resolve queue
        queue = await self.queue_from_guild(self.queue_db, inter.guild)

        serv = self.bot.get_guild(self.server_id)
        queue.locked = is_locked
        await queue.update(self.bot, self.queue_db, serv.get_channel(self.channel_id))

        # lock the channel
        await queue_channel.edit(
            reason=f"Channel {locked_status.title()}. Requested by {inter.author}.",
            overwrites=perms,
        )

        # send a message
        if queue.locked:
            embed = create_default_embed(inter)
            embed.title = f"Queue Channel {locked_status.title()}"
            embed.description = f"The queue channel has been temporarily {locked_status} by {inter.author}."
            await queue_channel.send(embed=embed)
        else:
            # Mark all Players in Group
            for group in queue.groups:
                for player in group.players:
                    await self.mark_db.update_one(
                        {"_id": player.member.id},
                        {"$set": {"_id": player.member.id, "marked": True}},
                        upsert=True,
                    )
            # find locked message?
            async for msg in queue_channel.history(limit=25):
                if not msg.author.id == self.bot.user.id:
                    continue
                if msg.embeds:
                    em = msg.embeds[0]
                    if em.title == "Queue Channel Locked":
                        await try_delete(msg)
                        break

            announce: disnake.TextChannel = serv.get_channel(
                self.announcement_channel_id
            )
            await announce.send(
                f"<@&778973153962885161>, <#{self.channel_id}> has been unlocked! Sign up to join the queue!",
                allowed_mentions=disnake.AllowedMentions(roles=True),
            )

        await self.refresh_menu(inter)


class GroupSelector(disnake.ui.StringSelect):
    def __init__(self, bot, queue):
        self.bot = bot
        self.queue = queue

        super().__init__(
            placeholder="Select a group.",
            min_values=1,
            max_values=1,
            options=self.create_options(queue),
        )

    def create_options(self, queue):
        options = []
        for i, group in enumerate(self.queue.groups):
            options.append(
                disnake.SelectOption(
                    label=f"{i+1}. Rank {group.tier}"
                )
            )

        return options

    async def callback(self, inter: disnake.MessageInteraction):
        selection = int(self.values[0].split(".")[0]) - 1
        group_ui = GroupManagerUI(self.bot, self.queue, self.queue.groups[selection])
        embed = await group_ui.generate_menu(inter)

        await inter.send(embed=embed, view=group_ui, ephemeral=True)


class GroupManagerUI(ManageUIParent):
    def __init__(self, bot, queue, group):
        super().__init__(bot, queue)
        self.group = group

    async def custom_refresh(self, interaction):
        pass

    async def generate_menu(self, interaction) -> disnake.Embed:
        assigned = f'<@{self.group.assigned}>' if self.group.assigned else "No."

        embed = create_default_embed(interaction)
        embed.title = "GatesBot - Group Manager"
        embed.description = f"**Locked:** {self.group.locked}\n" \
                            f"**Assigned:** {assigned}\n"
        embed.add_field("Members", await self.group.generate_field(self.bot))
        embed.add_field("Characters", self.group.player_levels_str, inline=False)
        return embed
