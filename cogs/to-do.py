from discord.ext import commands
from cogs.models.todo_views import TodoItem, PriorityConverter, MainMenuView
from datetime import datetime
from utils.functions import create_default_embed
from utils.constants import PRIORITIES
from utils.checks import has_role

import typing


class ToDo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mdb["todo_list"]

    async def fetch_items(self) -> typing.List[TodoItem]:
        out = []
        data = await self.db.find({"archived": False}).to_list(length=None)
        for item in data:
            task = TodoItem.from_dict(item)
            out.append(task)
        return out

    @commands.group(name="todo", invoke_without_command=True)
    @has_role("Assistant")
    async def _todo(self, ctx: commands.Context):
        """
        Show the current to-do list.
        """
        embed = create_default_embed(ctx)
        embed.title = "Current To-Do items"
        m_view = MainMenuView(ctx)

        tasks = await self.fetch_items()

        for priority in PRIORITIES:
            to_add = []
            for task in tasks:
                if task.priority == priority.lower() and not task.archived:
                    to_add.append(task)
            if to_add:
                embed.add_field(
                    name=priority,
                    value="```\n" + "\n".join((f"{i + 1}. {x.title}" for i, x in enumerate(to_add))) + "\n```",
                    inline=False,
                )

        await ctx.send(embed=embed, view=m_view)

    @_todo.command(name="create")
    @has_role("Assistant")
    async def _todo_create(self, ctx: commands.Context, priority: PriorityConverter, title: str, *, content: str):
        """
        Create a new to-do list item.
        """

        embed = create_default_embed(ctx)

        # type checker purposes
        priority = str(priority)

        now = datetime.utcnow()

        todo_item = TodoItem(owner_id=ctx.author.id, created_on=now, priority=priority, title=title, content=content)

        await self.db.insert_one(todo_item.to_dict())

        embed.title = "To-Do Item Created"
        embed.description = str(todo_item)

        view = MainMenuView(ctx)
        await view.tasks_edited()

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(ToDo(bot))
