import asyncio
import contextlib
import typing

import discord.ui
import disnake
import pendulum
from disnake.ext import commands

from utils.constants import PRIORITIES


class TodoItem:
    def __init__(
        self,
        owner_id: int,
        created_on,
        priority: str,
        title: str,
        content: str,
        archived: bool = False,
        archiver=None,
        claimer=None,
    ):
        self.owner_id = owner_id
        self.created_on = created_on
        self.created_on_string = f"<t:{int(pendulum.instance(created_on).timestamp())}:f>"
        self.priority = priority
        self.title = title
        self.content = content
        self.archived = archived
        self.archiver = archiver
        self.claimer = claimer

    @classmethod
    def from_dict(cls, data: dict):
        if data.get("_id"):
            data.pop("_id")
        return cls(**data)

    def to_dict(self):
        return {
            "owner_id": self.owner_id,
            "created_on": self.created_on,
            "priority": self.priority,
            "title": self.title,
            "content": self.content,
            "archived": self.archived,
            "archiver": self.archiver,
            "claimer": self.claimer,
        }

    def __str__(self):
        return (
            f"**Priority:** {self.priority.title()}"
            + f"\n**Owner:** <@{self.owner_id}>"
            + (f"\n**Claimed By:** <@{self.claimer}>" if self.claimer else "")
            + f"\n**Creation Date:** {self.created_on_string}"
            + (f"\n**Archived By:** <@{self.archiver}>" if self.archiver else "")
            + f"\n**Title:** {self.title}"
            + f"\n**Details:** {self.content}"
        )

    @property
    def short(self):
        if len(self.content) < 25:
            return self.content
        else:
            return self.content[:25] + "..."


class PriorityConverter(commands.Converter):
    async def convert(self, ctx, argument: str):
        if argument.title() in PRIORITIES:
            return argument.lower()
        raise commands.BadArgument("Priority must be one of High, Medium, or Low.")


PRIORITY_OPTIONS = [
    discord.SelectOption(label="High", description="Show high-priority tasks"),
    discord.SelectOption(label="Medium", description="Show medium-priority tasks"),
    discord.SelectOption(label="Low", description="Show low-priority tasks"),
]
GO_BACK = [discord.SelectOption(label="Go Back", description="Return to Main View")]


class ViewBase(discord.ui.View):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.owner = ctx.author
        self.bot = ctx.bot

    async def interaction_check(self, interaction: disnake.Interaction) -> bool:
        if interaction.user.id == self.owner.id:
            return True
        await interaction.response.send_message("You are not the owner of this menu.", ephemeral=True)
        return False

    async def fetch_items(self, archived=False) -> typing.List[TodoItem]:
        out = []
        data = await self.bot.mdb["todo_list"].find().to_list(length=None)
        for item in data:
            task = TodoItem.from_dict(item)
            out.append(task)
        return out

    async def prompt_message(
        self, interaction: disnake.Interaction, prompt: str, ephemeral: bool = True, timeout: int = 60
    ) -> typing.Optional[str]:
        """
        Send the user a prompt in the channel and return a value from their reply.
        Returns None if the user did not reply before the timeout.
        """
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

    async def generate_embed(self, embed, select_prio=None, show_archived=False):
        embed.clear_fields()
        embed.description = ""
        tasks = await self.fetch_items()

        if select_prio:
            embed.title = f"Current To-Do Items - {select_prio.title()} Priority"
        else:
            embed.title = "Current To-Do Items"

        for priority in PRIORITIES:
            to_add = []
            for task in tasks:
                if task.priority == priority.lower():
                    if show_archived and not task.archived:
                        continue
                    if (not show_archived) and task.archived:
                        continue
                    if select_prio and select_prio.lower() != task.priority.lower():
                        continue
                    to_add.append(task)
            if to_add:
                embed.add_field(
                    name=priority,
                    value="```\n" + "\n".join((f"{i + 1}. {x.title}" for i, x in enumerate(to_add))) + "\n```",
                    inline=False,
                )

        return embed

    async def tasks_edited(self):
        # TODO: Delete previous overall message
        # TODO: Generate new message from task DB
        pass


class MainMenuView(ViewBase):
    @discord.ui.select(placeholder="Select a priority to view", options=PRIORITY_OPTIONS)
    async def priority_select(self, select: discord.ui.Select, interaction: discord.MessageInteraction):

        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed, select_prio=select.values[0])

        # make options
        data = list(
            filter(
                lambda x: x.priority.lower() == select.values[0].lower() and not x.archived, await self.fetch_items()
            )
        )

        is_archived = False
        if len(data) == 0:
            is_archived = True
            new_embed = await self.generate_embed(old_embed, select_prio=select.values[0], show_archived=True)
            new_embed.title += " - Archived"
            new_embed.description = "No un-archived tasks found. Showing archived only."

            data = list(filter(lambda x: x.priority.lower() == select.values[0].lower(), await self.fetch_items()))

            if len(data) == 0:
                await interaction.send(content="Could not find any to-do items in that category.", ephemeral=True)
                return

        await interaction.response.edit_message(
            embed=new_embed, view=PriorityView(self.ctx, data, priority=select.values[0], archived=is_archived)
        )


class IndividualSelector(discord.ui.Select):
    def __init__(self, ctx, data, priority=None):
        self.ctx = ctx
        self.data = data
        self.priority = priority

        options = []
        for i, item in enumerate(data):
            options.append(discord.SelectOption(label=f"#{i+1}.", description=item.title))

        super().__init__(placeholder="Select an item for more detail", options=options)

    async def callback(self, interaction: discord.MessageInteraction):
        # edit embed to individual view

        value = self.values[0]
        n_value = int(value.lstrip("#").rstrip(".")) - 1

        n = self.data[n_value]

        next_view = IndividualView(self.ctx, self.data, n)

        next_embed = await next_view.edit_embed(interaction.message.embeds[0], n)

        await interaction.response.edit_message(embed=next_embed, view=next_view)


class PriorityView(ViewBase):
    def __init__(self, ctx, items, priority=None, archived=False):
        super().__init__(ctx)
        self.items = items
        self.priority = priority
        self.archived = False
        self.show_archived.disabled = archived

        if len(items) > 0:
            self.add_item(IndividualSelector(ctx, items))

    @discord.ui.button(label="Show Archived", style=discord.ButtonStyle.primary)
    async def show_archived(self, button: discord.ui.Button, interaction: discord.MessageInteraction):
        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed, show_archived=True)

        self.items = list(
            filter(
                lambda x: x.priority.lower() == (self.priority or self.items[0].priority.lower()) and x.archived,
                await self.fetch_items(),
            )
        )

        new_embed.title += " - Archived"

        await interaction.response.edit_message(embed=new_embed, view=PriorityView(self.ctx, self.items))

    @discord.ui.button(label="Go Back", style=discord.ButtonStyle.primary)
    async def go_back(self, button: discord.ui.Button, interaction: discord.MessageInteraction):
        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed)

        await interaction.response.edit_message(embed=new_embed, view=MainMenuView(self.ctx))


class IndividualView(ViewBase):
    def __init__(self, ctx, items, item):
        super().__init__(ctx)
        self.items = items
        self.current_item: TodoItem = item

        self.archive_button.disabled = item.archived
        self.unarchive_button.disabled = not item.archived
        self.claim_button.disabled = item.claimer == ctx.author.id
        self.unclaim_button.disabled = not self.claim_button.disabled

    async def edit_embed(self, embed, item):
        embed.clear_fields()
        embed.description = str(item)
        embed.title = f"Individual Item | {self.current_item.priority.title()} Priority" + (
            " | Archived" if self.current_item.archived else ""
        )

        return embed

    @discord.ui.button(label="Go Back", style=discord.ButtonStyle.primary)
    async def go_back(self, _, interaction: discord.MessageInteraction):
        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed)
        new_embed.title += f" - {self.current_item.priority.title()} Priority"

        self.items = list(
            filter(
                lambda x: x.priority.lower() == self.current_item.priority.lower() and not x.archived,
                await self.fetch_items(),
            )
        )

        await interaction.response.edit_message(
            embed=new_embed, view=PriorityView(self.ctx, self.items, priority=self.current_item.priority)
        )

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit_button(self, _, interaction: discord.MessageInteraction):
        new_content = await self.prompt_message(interaction, prompt="Send a message containing the new description.")

        if not new_content:
            return await interaction.send(content="Did not receive new to-do content", ephemeral=True)

        await self.bot.mdb["todo_list"].update_one(
            {"owner_id": self.current_item.owner_id, "content": self.current_item.content},
            {"$set": {"content": new_content.strip()}},
        )
        self.current_item.content = new_content.strip()

        await interaction.followup.send(
            content="To-do item edited!\nUnfortunately due to discord limitations, this embed was not edited.",
            ephemeral=True,
        )

    @discord.ui.button(label="Archive", style=discord.ButtonStyle.red)
    async def archive_button(self, _, interaction: discord.MessageInteraction):

        await self.bot.mdb["todo_list"].update_one(
            {"owner_id": self.current_item.owner_id, "content": self.current_item.content},
            {"$set": {"archived": True, "archiver": interaction.author.id}},
        )

        self.current_item.archived = True
        self.current_item.archiver = interaction.author.id

        old_embed = interaction.message.embeds[0]
        new_embed = await self.edit_embed(old_embed, self.current_item)

        await interaction.response.edit_message(
            embed=new_embed, view=IndividualView(self.ctx, self.items, self.current_item)
        )
        await interaction.send(content="To-do item archived!", ephemeral=True)

    @discord.ui.button(label="Un-archive", style=discord.ButtonStyle.red)
    async def unarchive_button(self, _, interaction: discord.MessageInteraction):

        await self.bot.mdb["todo_list"].update_one(
            {"owner_id": self.current_item.owner_id, "content": self.current_item.content},
            {"$set": {"archived": False}, "$unset": {"archiver": True}},
        )

        self.current_item.archived = False
        self.current_item.archiver = None

        old_embed = interaction.message.embeds[0]
        new_embed = await self.edit_embed(old_embed, self.current_item)

        await interaction.response.edit_message(
            embed=new_embed, view=IndividualView(self.ctx, self.items, self.current_item)
        )
        await interaction.send(content="To-do item un-archived!", ephemeral=True)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.green, row=2)
    async def claim_button(self, _, interaction: discord.MessageInteraction):
        await self.bot.mdb["todo_list"].update_one(
            {"owner_id": self.current_item.owner_id, "content": self.current_item.content},
            {"$set": {"claimer": interaction.author.id}},
        )
        self.current_item.claimer = interaction.author.id

        old_embed = interaction.message.embeds[0]
        new_embed = await self.edit_embed(old_embed, self.current_item)

        await interaction.response.edit_message(
            embed=new_embed, view=IndividualView(self.ctx, self.items, self.current_item)
        )
        await interaction.send(content="To-do item claimed!", ephemeral=True)

    @discord.ui.button(label="Un-claim", style=discord.ButtonStyle.red, row=2)
    async def unclaim_button(self, _, interaction: discord.MessageInteraction):
        await self.bot.mdb["todo_list"].update_one(
            {"owner_id": self.current_item.owner_id, "content": self.current_item.content},
            {"$unset": {"claimer": True}},
        )
        self.current_item.claimer = None

        old_embed = interaction.message.embeds[0]
        new_embed = await self.edit_embed(old_embed, self.current_item)

        await interaction.response.edit_message(
            embed=new_embed, view=IndividualView(self.ctx, self.items, self.current_item)
        )
        await interaction.send(content="To-do item un-claimed!", ephemeral=True)
