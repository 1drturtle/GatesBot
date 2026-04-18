from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Optional

import discord
import disnake

from common.embeds import create_default_embed
from queueing.services import get_queue_services

log = logging.getLogger(__name__)


def _player_queue_view(bot):
    from queueing.views.player_queue import PlayerQueueUI

    return PlayerQueueUI(bot)


def _dm_queue_view(bot):
    from queueing.views.dm_queue import DMQueueUI

    return DMQueueUI(bot)


class ManageUIParent(disnake.ui.View):
    def __init__(self, bot, queue):
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_type = queue.__class__
        self.services = get_queue_services(bot)
        self.player_service = self.services.player_queue_service
        self.dm_service = self.services.dm_queue_service
        self.queue_repo = self.services.queue_repository
        self.presentation = self.services.presentation_service
        self.config = self.services.config

    async def queue_from_guild(self, guild: discord.Guild):
        return await self.queue_repo.load_for_guild(
            guild,
            queue_type=self.queue_type,
            channel_id=self.config.player_queue_channel_id,
        )

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
                check=lambda msg: msg.author == interaction.author and msg.channel.id == interaction.channel_id,
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
        queue = await self.queue_from_guild(interaction.guild)
        self.remove_item(self.group_selector)
        self.group_selector = GroupSelector(self.bot, queue, self)
        self.add_item(self.group_selector)

    async def generate_menu(self, interaction) -> disnake.Embed:
        queue = await self.queue_from_guild(interaction.guild)

        embed = create_default_embed(interaction)
        embed.title = "GatesBot - Queue Manager"
        locked_emoji = "🔒 Locked" if queue.locked else "🔓 Unlocked"
        embed.description = f"**Status:** {locked_emoji}\n**Groups:** {len(queue.groups)}\n"
        return embed

    @disnake.ui.button(label="Refresh Queue", emoji="🔃")
    async def queue_refresh(self, button, inter: disnake.MessageInteraction):
        del button
        await self.player_service.refresh_queue_message(
            guild=inter.guild,  # pyright: ignore[reportArgumentType]
            view_factory=lambda: _player_queue_view(self.bot),
        )
        await self.refresh_menu(inter)

    @disnake.ui.button(label="Toggle Lock", emoji="🔒")
    async def toggle_queue_lock(self, button, inter: disnake.MessageInteraction):
        del button
        await inter.response.defer()

        queue_channel: discord.TextChannel = inter.guild.get_channel(self.config.player_queue_channel_id)  # type: ignore
        if queue_channel is None:
            return await inter.send("Queue channel not found.", ephemeral=True)

        player_role: discord.Role = discord.utils.find(
            lambda role: role.name.lower() == "player",
            inter.guild.roles,  # type: ignore
        )
        if player_role is None:
            return await inter.send("Player role not found.", ephemeral=True)

        perms = queue_channel.overwrites
        player_perms = perms.get(player_role, discord.PermissionOverwrite())
        currently_locked = player_perms.send_messages is False
        should_lock = not currently_locked

        if should_lock and not (
            inter.author.id == self.bot.owner_id or any(True for role in inter.author.roles if role.name == "Admin")  # type: ignore
        ):
            return await inter.send("You are not allowed to use this function.", ephemeral=True)

        reason = await ManageUIParent.prompt_message(inter, "Specify a reason:") if should_lock else None
        if reason and reason.lower() == "ga":
            reason = "Gate Assignments."

        await self.player_service.toggle_queue_lock(
            guild=inter.guild,  # type: ignore
            actor=inter.author,  # type: ignore
            queue_channel=queue_channel,
            player_role=player_role,
            should_lock=should_lock,
            reason=reason,
            view_factory=lambda: _player_queue_view(self.bot),
            send_announcement=not should_lock,
        )

        log.info("Queue has been %s by %s", "locked" if should_lock else "unlocked", inter.author)
        await self.refresh_menu(inter)

    @disnake.ui.button(label="Shuffle Rank", emoji="🔀")
    async def shuffle_button(self, button, inter: disnake.MessageInteraction):
        del button
        await inter.response.defer()

        tier_choice = await self.prompt_message(
            inter,
            prompt="Enter Shuffle Rank (optional, group size) Ex: 4,6",
        )
        if tier_choice is None:
            return await inter.send("No input received.", ephemeral=True)

        try:
            parts = tier_choice.split(",")
            group_choice = int(parts[1]) if len(parts) > 1 else 5
            tier = int(parts[0])
        except ValueError:
            return await inter.send("Invalid Rank or Group Size.", ephemeral=True)

        result = await self.player_service.shuffle_groups(
            guild=inter.guild,  # type: ignore
            tier=tier,
            group_size=group_choice,
            view_factory=lambda: _player_queue_view(self.bot),
        )
        if not result.success:
            return await inter.send(result.message, ephemeral=True)

        await self.refresh_menu(inter)
        log.info("[Queue] Rank %s shuffled by %s.", tier, inter.author)


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
        entries = await self.parent_view.services.dm_queue_repository.list_entries()

        dm_data = []
        for entry in entries:
            member = inter.guild.get_member(entry.member_id)  # pyright: ignore[reportOptionalMemberAccess]
            if member is None:
                with contextlib.suppress(disnake.NotFound, disnake.Forbidden):
                    member = await inter.guild.fetch_member(entry.member_id)  # pyright: ignore[reportOptionalMemberAccess]
            if member is None:
                continue
            dm_data.append((member, entry))

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

    async def custom_refresh(self, interaction):
        del interaction

    async def generate_menu(self, interaction) -> disnake.Embed:
        queue = await self.queue_from_guild(interaction.guild)
        self.group = queue.groups[self.group_num]
        assigned = f"<@{self.group.assigned}>" if self.group.assigned else "No."

        embed = create_default_embed(interaction)
        embed.title = f"GatesBot - Group #{self.group_num + 1}"
        locked_emoji = "🔒 Locked" if self.group.locked else "🔓 Unlocked"
        embed.description = (
            f"**Rank:** {self.group.tier_str.replace('_', '')}\n**Status:** {locked_emoji}\n**Assigned:** {assigned}\n"
        )
        embed.add_field("Members", await self._group_members_field(self.group))
        embed.add_field("Characters", self.group.player_levels_str, inline=False)
        return embed

    async def _group_members_field(self, group):
        names: list[str] = []
        mark_db = self.bot.mdb["player_marked"]
        for player in group.players:
            mark_info = await mark_db.find_one({"_id": player.member.id}) or {}
            postfix = f"{'*' if mark_info.get('marked', False) else ''}{mark_info.get('custom', '')}"
            names.append(f"{player.mention}{postfix}")
        return discord.utils.escape_markdown(", ".join(names))

    @disnake.ui.button(label="↩ Back", style=disnake.ButtonStyle.red)
    async def back_button(self, button, inter):
        del button
        await self.move_to_view(inter, self.parent_view)

    @disnake.ui.button(label="🔒 Toggle Group Lock", style=disnake.ButtonStyle.red)
    async def lock_group_button(self, button, inter):
        del button
        await inter.response.defer()
        result = await self.player_service.toggle_group_lock(
            guild=inter.guild,
            group_number=self.group_num + 1,
            view_factory=lambda: _player_queue_view(self.bot),
        )
        if not result.success:
            return await inter.send(result.message, ephemeral=True)
        log.info(
            "[Queue] Group #%s %s by %s.",
            self.group_num + 1,
            "locked" if result.is_locked else "unlocked",
            inter.author,
        )
        return await self.refresh_menu(inter)

    @disnake.ui.button(label="Assign", style=disnake.ButtonStyle.green)
    async def assign_button(self, button, inter: disnake.MessageInteraction):
        del button
        if self.dm_selector.selected is None:
            return await inter.send("No DM selected, cannot assign", ephemeral=True)

        await inter.response.defer()
        who = self.dm_selector.selected

        result = await self.dm_service.assign_dm_to_group(
            guild=inter.guild, # pyright: ignore[reportArgumentType]
            summoner=inter.author, # pyright: ignore[reportArgumentType]
            group_number=self.group_num + 1,
            dm_member_id=who.id,
            view_factory=lambda: _dm_queue_view(self.bot),
            allow_reassignment=False,
        )
        if not result.success:
            return await inter.send(result.message, ephemeral=True)

        log.info("[DM Queue] %s assigned Gate #%s to %s.", inter.author, self.group_num + 1, who)
        await self.refresh_menu(inter)
        await inter.send(result.message, ephemeral=True)


class DMSelector(disnake.ui.StringSelect):
    def __init__(self, bot, queue, dm_queue_data):
        self.bot = bot
        self.queue = queue
        self.dms: list[tuple[discord.Member, Any]] = dm_queue_data
        self.selected: Optional[discord.Member] = None

        options = []
        for dm, data in self.dms:
            display_name = dm.nick or dm.display_name
            options.append(display_name + ": " + data.text[: 80 - len(display_name)])
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
