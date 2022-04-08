import discord.ui
import disnake
from disnake.ext import commands
import pendulum
from utils.constants import PRIORITIES
import typing


class TodoItem:
    def __init__(self, owner_id: int, created_on, priority: str, content: str, archived: bool = False):
        self.owner_id = owner_id
        self.created_on = created_on
        self.created_on_string = f"<t:{int(pendulum.instance(created_on).timestamp())}:f>"
        self.priority = priority
        self.content = content
        self.archived = archived

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
            "content": self.content,
            "archived": self.archived,
        }

    def __str__(self):
        return (
            f"**Priority:** {self.priority.title()}\n"
            f"**Owner:** <@{self.owner_id}>\n"
            f"**Creation Date:** {self.created_on_string}\n"
            f"**Details:** {self.content}" + ("\n**Archived:** True" if self.archived else "")
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

    async def fetch_items(self) -> typing.List[TodoItem]:
        out = []
        data = await self.bot.mdb["todo_list"].find({"archived": False}).to_list(length=None)
        for item in data:
            task = TodoItem.from_dict(item)
            out.append(task)
        return out

    async def generate_embed(self, embed, select_prio=None):
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
                if task.priority == priority.lower() and not task.archived:
                    if select_prio and select_prio.lower() != task.priority.lower():
                        continue
                    to_add.append(task)
            if to_add:
                embed.add_field(
                    name=priority,
                    value="```\n" + "\n".join((f"{i + 1}. {x.content}" for i, x in enumerate(to_add))) + "\n```",
                    inline=False,
                )

        return embed


class MainMenuView(ViewBase):
    @discord.ui.select(placeholder="Select a priority to view", options=PRIORITY_OPTIONS)
    async def priority_select(self, select: discord.ui.Select, interaction: discord.MessageInteraction):

        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed, select_prio=select.values[0])

        # make options
        data = list(filter(lambda x: x.priority.lower() == select.values[0].lower(), await self.fetch_items()))

        await interaction.response.edit_message(embed=new_embed, view=PriorityView(self.ctx, data))


class IndividualSelector(discord.ui.Select):
    def __init__(self, ctx, data):
        self.ctx = ctx
        self.data = data

        options = []
        for i, item in enumerate(data):
            options.append(discord.SelectOption(label=f"#{i+1}.", description=item.content))

        super().__init__(placeholder="Select an item for more detail", options=options)

    async def callback(self, interaction: discord.MessageInteraction):
        # edit embed to individual view
        next_view = IndividualView(self.ctx, self.data)

        value = self.values[0]
        n_value = int(value.lstrip("#").rstrip(".")) - 1
        print(self.data[n_value])
        next_embed = await next_view.edit_embed(interaction.message.embeds[0], self.data[n_value])

        await interaction.response.edit_message(embed=next_embed, view=IndividualView(self.ctx, self.data))


class PriorityView(ViewBase):
    def __init__(self, ctx, items):
        super().__init__(ctx)
        self.items = items
        self.add_item(IndividualSelector(ctx, items))

    @discord.ui.button(label="Go Back", style=discord.ButtonStyle.primary)
    async def priority_select(self, button: discord.ui.Button, interaction: discord.MessageInteraction):
        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed)

        await interaction.response.edit_message(embed=new_embed, view=MainMenuView(self.ctx))


class IndividualView(ViewBase):
    def __init__(self, ctx, items):
        super().__init__(ctx)
        self.items = items

    async def edit_embed(self, embed, item):
        embed.clear_fields()
        embed.description = ""

        return embed

    @discord.ui.button(label="Go Back", style=discord.ButtonStyle.primary)
    async def priority_select(self, button: discord.ui.Button, interaction: discord.MessageInteraction):
        old_embed = interaction.message.embeds[0]
        new_embed = await self.generate_embed(old_embed)

        await interaction.response.edit_message(embed=new_embed, view=PriorityView(self.ctx, self.items))
