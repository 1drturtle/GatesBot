from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import random
from typing import Optional

import discord
import disnake
import pymongo

import common.constants as constants
from common.discord_utils import try_delete
from common.embeds import create_default_embed
from queueing.models import Queue
from queueing.repository import load_queue_for_guild
from queueing.services import send_gate_assignment

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
        return await load_queue_for_guild(db, guild, queue_type=self.queue_type)

    async def refresh_menu(self, interaction, kill=False):
        del kill
        await self.custom_refresh(interaction)
        embed = await self.generate_menu(interaction)

        if interaction.response.is_done():
            await interaction.edit_original_message(content=None, view=self, embed=embed)
        else:
            await interaction.response.edit_message(content=None, view=self, embed=embed)

    async def move_to_view(self, interaction, new_view):
        embed = await new_view.generate_menu(interaction)

        if interaction.response.is_done():
            await interaction.edit_original_message(view=new_view, embed=embed)
        else:
            await interaction.response.edit_message(view=new_view, embed=embed)

    async def custom_refresh(self, interaction):
        raise NotImplementedError()

    async def generate_menu(self, interaction) -> disnake.Embed:
        raise NotImplementedError()

    @staticmethod
    async def prompt_message(
        interaction: disnake.Interaction,
        prompt: str,
        ephemeral: bool = True,
        timeout: int = 60,
    ) -> str | None:
        await interaction.send(prompt, ephemeral=ephemeral)
        try:
            input_msg: disnake.Message = await interaction.bot.wait_for(
                "message",
                timeout=timeout,
                check=lambda msg: msg.author == interaction.author
                and msg.channel.id == interaction.channel_id,
            )
            with contextlib.suppress(disnake.HTTPException):
                await input_msg.delete()
            return input_msg.content
        except asyncio.TimeoutError:
            return None


class PlayerQueueManageUI(ManageUIParent):
    def __init__(self, bot, queue):
        super().__init__(bot, queue)
        self.group_selector = GroupSelector(bot, queue, self)
        self.add_item(self.group_selector)

    async def custom_refresh(self, interaction):
        queue = await self.queue_from_guild(self.queue_db, interaction.guild)
        self.remove_item(self.group_selector)
        self.group_selector = GroupSelector(self.bot, queue, self)
        self.add_item(self.group_selector)

    async def generate_menu(self, interaction) -> disnake.Embed:
        queue = await self.queue_from_guild(self.queue_db, interaction.guild)

        embed = create_default_embed(interaction)
        embed.title = "GatesBot - Queue Manager"
        locked_emoji = "🔒 Locked" if queue.locked else "🔓 Unlocked"
        embed.description = f"**Status:** {locked_emoji}\n**Groups:** {len(queue.groups)}\n"
        return embed

    @disnake.ui.button(label="Refresh Queue", emoji="🔃")
    async def queue_refresh(self, button, inter: disnake.MessageInteraction):
        del button
        queue = await self.queue_from_guild(self.queue_db, inter.guild)
        await queue.update(self.bot, self.queue_db, inter.guild.get_channel(self.channel_id))
        await self.refresh_menu(inter)

    @disnake.ui.button(label="Toggle Lock", emoji="🔒")
    async def toggle_queue_lock(self, button, inter: disnake.MessageInteraction):
        del button
        await inter.response.defer()
        queue_channel: discord.TextChannel = inter.guild.get_channel(self.channel_id)

        player_role: discord.Role = discord.utils.find(
            lambda role: role.name.lower() == "player",
            inter.guild.roles,
        )

        perms = queue_channel.overwrites
        player_perms = perms.get(player_role, discord.PermissionOverwrite())
        is_locked = player_perms.send_messages
        locked_status = "locked" if is_locked else "unlocked"

        if is_locked:
            if not (
                inter.author.id == self.bot.owner_id
                or any(True for role in inter.author.roles if role.name == "Admin")
            ):
                return await inter.send("You are not allowed to use this function.", ephemeral=True)

        reason = await ManageUIParent.prompt_message(inter, "Specify a reason:") if is_locked else None
        if reason and reason.lower() == "ga":
            reason = "Gate Assignments."

        player_perms.update(send_messages=not is_locked)
        perms.update({player_role: player_perms})

        log.info(f"Queue has been {locked_status} by {inter.author}")

        queue = await self.queue_from_guild(self.queue_db, inter.guild)
        serv = self.bot.get_guild(self.server_id)
        queue.locked = is_locked
        await queue.update(self.bot, self.queue_db, serv.get_channel(self.channel_id))

        await queue_channel.edit(
            reason=f"Channel {locked_status.title()}. Requested by {inter.author}.",
            overwrites=perms,
        )

        if queue.locked:
            embed = create_default_embed(inter)
            embed.title = f"Queue Channel {locked_status.title()}"
            embed.description = (
                f"The queue channel has been temporarily {locked_status} by {inter.author}."
            )
            embed.add_field("Reason", reason if reason else "No reason specified.")
            await queue_channel.send(embed=embed)
        else:
            for group in queue.groups:
                for player in group.players:
                    await self.mark_db.update_one(
                        {"_id": player.member.id},
                        {"$set": {"_id": player.member.id, "marked": True}},
                        upsert=True,
                    )

            async for msg in queue_channel.history(limit=25):
                if msg.author.id != self.bot.user.id:
                    continue
                if msg.embeds and msg.embeds[0].title == "Queue Channel Locked":
                    await try_delete(msg)
                    break

            announce: disnake.TextChannel = serv.get_channel(self.announcement_channel_id)
            await announce.send(
                f"<@&778973153962885161>, <#{self.channel_id}> has been unlocked! Sign up to join the queue!",
                allowed_mentions=disnake.AllowedMentions(roles=True),
            )

        await self.refresh_menu(inter)

    @disnake.ui.button(label="Shuffle Rank", emoji="🔀")
    async def shuffle_button(self, button, inter: disnake.MessageInteraction):
        del button
        await inter.response.defer()

        queue = await self.queue_from_guild(self.queue_db, inter.guild)
        tier_choice = await self.prompt_message(
            inter,
            prompt="Enter Shuffle Rank (optional, group size) Ex: 4,6",
        )

        try:
            tier_choice = tier_choice.split(",")
            group_choice = int(tier_choice[1]) if len(tier_choice) > 1 else 5
            tier_choice = int(tier_choice[0])
        except ValueError:
            return await inter.send("Invalid Rank or Group Size.", ephemeral=True)

        group_type = None
        selected_players = []
        for group in queue.groups.copy():
            group_type = group.__class__
            if group.tier != tier_choice or group.locked:
                continue
            queue.groups.remove(group)
            selected_players.extend(group.players)

        if not selected_players:
            return await inter.send(f"No players in Rank {tier_choice} was found.", ephemeral=True)

        selected_players = random.sample(selected_players, len(selected_players))
        for player in selected_players:
            if (index := queue.can_fit_in_group(player, group_choice)) is not None:
                queue.groups[index].players.append(player)
            else:
                new_group = group_type.new(player.tier, [player])
                queue.groups.append(new_group)

        await queue.update(self.bot, self.queue_db, inter.guild.get_channel(self.channel_id))
        await asyncio.sleep(2)
        await self.refresh_menu(inter)
        log.info(f"[Queue] Rank {tier_choice} shuffled by {inter.author}.")


class GroupSelector(disnake.ui.StringSelect):
    def __init__(self, bot, queue, parent_view):
        self.bot = bot
        self.queue = queue
        self.parent_view = parent_view
        super().__init__(
            placeholder="Select a group.",
            min_values=1,
            max_values=1,
            options=self.create_options(),
        )

    def create_options(self):
        options = [
            disnake.SelectOption(label=f"{index + 1}. Rank {group.tier}")
            for index, group in enumerate(self.queue.groups)
        ]
        if not options:
            return ["No queue groups."]
        return options

    async def callback(self, inter: disnake.MessageInteraction):
        if "No queue groups" in self.values[0]:
            return await self.parent_view.refresh_menu(inter)

        selection = int(self.values[0].split(".")[0]) - 1
        dm_data = (
            await self.bot.mdb["dm_queue"]
            .find()
            .sort("readyOn", pymongo.ASCENDING)
            .to_list(None)
        )
        dm_data = [(await inter.guild.fetch_member(int(item["_id"])), item) for item in dm_data]

        group_ui = GroupManagerUI(
            self.bot,
            self.queue,
            self.queue.groups[selection],
            selection,
            dm_data,
            self.parent_view,
        )
        await self.parent_view.move_to_view(inter, group_ui)


class GroupManagerUI(ManageUIParent):
    def __init__(self, bot, queue, group, group_num, dm_queue_data, parent_view):
        super().__init__(bot, queue)
        self.group = group
        self.group_num = group_num
        self.parent_view = parent_view
        self.dm_selector = DMSelector(bot, queue, dm_queue_data)
        self.add_item(self.dm_selector)

        self.dm_queue_db = self.bot.mdb["dm_queue"]
        self.dm_db = self.bot.mdb["dm_analytics"]
        self.assign_data_db = self.bot.mdb["dm_assign_analytics"]

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

    async def custom_refresh(self, interaction):
        del interaction

    async def generate_menu(self, interaction) -> disnake.Embed:
        queue = await self.queue_from_guild(self.queue_db, interaction.guild)
        self.group = queue.groups[self.group_num]
        assigned = f"<@{self.group.assigned}>" if self.group.assigned else "No."

        embed = create_default_embed(interaction)
        embed.title = f"GatesBot - Group #{self.group_num + 1}"
        locked_emoji = "🔒 Locked" if self.group.locked else "🔓 Unlocked"
        embed.description = (
            f"**Rank:** {self.group.tier_str.replace('_', '')}\n"
            f"**Status:** {locked_emoji}\n"
            f"**Assigned:** {assigned}\n"
        )
        embed.add_field("Members", await self.group.generate_field(self.bot))
        embed.add_field("Characters", self.group.player_levels_str, inline=False)
        return embed

    @disnake.ui.button(label="↩ Back", style=disnake.ButtonStyle.red)
    async def back_button(self, button, inter):
        del button
        await self.move_to_view(inter, self.parent_view)

    @disnake.ui.button(label="🔒 Toggle Group Lock", style=disnake.ButtonStyle.red)
    async def lock_group_button(self, button, inter):
        del button
        await inter.response.defer()
        queue = await self.queue_from_guild(self.queue_db, inter.guild)
        serv = self.bot.get_guild(self.server_id)
        queue.groups[self.group_num].locked = state = not queue.groups[self.group_num].locked
        await queue.update(self.bot, self.queue_db, serv.get_channel(self.channel_id))
        log.info(
            f"[Queue] Group #{self.group_num + 1} {'locked' if state else 'unlocked'} by {inter.author}."
        )
        return await self.refresh_menu(inter)

    @disnake.ui.button(label="Assign", style=disnake.ButtonStyle.green)
    async def assign_button(self, button, inter: disnake.MessageInteraction):
        del button
        if self.dm_selector.selected is None:
            return await inter.send("No DM selected, cannot assign", ephemeral=True)

        await inter.response.defer()
        who = self.dm_selector.selected
        channel = inter.guild.get_channel(self.assign_id)
        gates_data: Queue = await self.queue_from_guild(self.bot.mdb["player_queue"], inter.guild)

        group = gates_data.groups[self.group_num]
        if group.assigned is not None:
            return await inter.send(
                "A DM is already assigned to this gate. Please assign via command if you wish to assign again.",
                ephemeral=True,
            )

        group.assigned = who.id
        await gates_data.db_save(self.queue_db)
        await send_gate_assignment(
            bot=self.bot,
            group=group,
            group_number=self.group_num + 1,
            dm_member=who,
            assignment_channel=channel,
        )

        analytics_data = {
            "summoner": inter.author.id,
            "dm": who.id,
            "gate_data": group.to_dict(),
            "claimed": False,
            "summonDate": datetime.datetime.utcnow(),
        }
        await self.assign_data_db.insert_one(analytics_data)
        await self.dm_db.update_one(
            {"_id": who.id},
            {"$inc": {"dm_queue.assignments": 1}},
            upsert=True,
        )

        await self.dm_queue_db.delete_one({"_id": who.id})
        await self.bot.cogs["DMQueue"].update_queue()

        log.info(f"[DM Queue] {inter.author} assigned Gate #{self.group_num + 1} to {who}.")
        await self.refresh_menu(inter)
        await inter.send(f"Gate #{self.group_num + 1} assigned to {who}", ephemeral=True)


class DMSelector(disnake.ui.StringSelect):
    def __init__(self, bot, queue, dm_queue_data):
        self.bot = bot
        self.queue = queue
        self.dms: list[disnake.Member] = dm_queue_data
        self.selected: Optional[discord.Member] = None

        options = []
        for dm, data in self.dms:
            display_name = dm.nick or dm.display_name
            options.append(display_name + ": " + data.get("ranks")[: 80 - len(display_name)])
        if not options:
            options = ["No DMs in Queue."]

        super().__init__(
            placeholder="Select a DM.",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        selected_dm_name = self.values[0]
        if selected_dm_name == "No DMs in Queue.":
            return await inter.send("I can't do anything!", ephemeral=True)
        selected_dm_name = selected_dm_name.split(":")[0]

        selected_dm = [
            member
            for member, _ in self.dms
            if selected_dm_name == member.nick or selected_dm_name == member.display_name
        ][0]
        self.selected = selected_dm

        return await inter.send(
            f"{selected_dm.mention} selected. Click Assign to confirm.",
            ephemeral=True,
            delete_after=15,
        )


__all__ = ["PlayerQueueManageUI"]
