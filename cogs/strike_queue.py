import asyncio
import logging

import discord
import pymongo
from discord.ext import commands

import utils.constants as constants
from utils.checks import has_role
from utils.functions import create_queue_embed, try_delete, create_default_embed
from ui.strike_queue_menu import StrikeQueueUI

log = logging.getLogger(__name__)

ROLE = "Assistant"


class StrikeQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

        self.db = self.bot.mdb["strike_queue"]
        self.gate_db = bot.mdb["gate_list"]
        self.data_db = self.bot.mdb["queue_analytics"]
        self.r_db = self.bot.mdb["reinforcement_analytics"]

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == constants.GATES_SERVER:
            return True
        if ctx.guild.id == constants.DEBUG_SERVER and self.bot.environment == "testing":
            return True

    @commands.Cog.listener(name="on_message")
    async def strike_queue_listener(self, msg):

        if msg.channel.id != self.queue_channel_id:
            return

        if not msg.content.lower().startswith("**ready"):
            return

        content = discord.utils.remove_markdown(msg.content.lower())
        msg_content = content.replace("ready: ", "").strip()

        content = {
            "$set": {"content": msg_content, "msg": msg.id},
            "$currentDate": {"readyOn": True},
        }

        await self.db.update_one({"_id": msg.author.id}, content, upsert=True)

        # old_roles_data = await self.data_db.find_one(
        #     {'user_id': msg.author.id},
        # )
        # if old_roles_data and (old_role_name := old_roles_data.get('last_strike')):
        #     role = discord.utils.find(lambda r: r.name == old_role_name, msg.guild.roles)
        #     if role:
        #         await msg.author.remove_role(role, reason='Strike team signup, removing last role.')

        try:
            await msg.add_reaction("\U0001f44d")
        except:
            pass

        await self.update_queue()

    async def generate_embed(self):

        guild = self.bot.get_guild(self.server_id)

        data = await self.db.find().sort("readyOn", pymongo.ASCENDING).to_list(None)
        embed = create_queue_embed(self.bot)

        out = []

        embed.title = "Strike Team Queue"

        for i, item in enumerate(data):
            member = guild.get_member(item.get("_id"))
            cur = f'**#{i + 1}.** {member.mention} - {item.get("content").title()}'
            out.append(cur)

        embed.description = "\n".join(out)

        return embed

    async def update_queue(self):

        await asyncio.sleep(1)

        guild = self.bot.get_guild(self.server_id)
        ch = guild.get_channel(self.queue_channel_id)

        embed = await self.generate_embed()

        # find old & delete
        history = await ch.history(limit=50).flatten()
        for msg in history:
            if len(msg.embeds) != 1 or msg.author.id != self.bot.user.id:
                continue

            old_embed = msg.embeds[0]

            if old_embed.title != "Strike Team Queue":
                continue

            await try_delete(msg)

        # send new
        view = StrikeQueueUI(self.bot, self.__class__)

        await ch.send(embed=embed, view=view)

    @commands.group(name="strike", invoke_without_command=True)
    async def strike(self, ctx):
        """Base command for DM queue"""
        await ctx.send_help(self.strike)

    @strike.command(name="assign")
    @has_role("DM")
    async def strike_assign(
        self, ctx, queue_nums: commands.Greedy[int], gate_name: str
    ):
        """
        Assigns a Strike member to a group
        `queue_num` - The Strike member(s) queue number(s). You can assign multiple members at once.
        `gate_name` - The gate's name to assist.
        """
        ch = ctx.guild.get_channel(self.assign_id)

        queue_data = (
            await self.db.find().sort("readyOn", pymongo.ASCENDING).to_list(None)
        )

        dms = []

        for queue_num in queue_nums:
            if len(queue_data) == 0:
                return await ctx.send(
                    "No Strike Team members currently in Strike Team queue."
                )
            if queue_num > (size := len(queue_data)):
                return await ctx.send(
                    f"Invalid Strike Team Queue number ({queue_num})."
                    f" Must be less than or equal to {size}"
                )
            elif queue_num < 1:
                return await ctx.send(
                    f"Invalid Strike Team Queue number ({queue_num}). Must be at least 1."
                )

            dms.append(queue_data[(queue_num - 1)])

        people = [ctx.guild.get_member(dm.get("_id")) for dm in dms]

        gate_data = await self.gate_db.find_one({"name": gate_name.lower()})
        if gate_data is None:
            return await ctx.send(
                f"{gate_name} does not exist, please try again with a valid gate name.",
                delete_after=5,
            )
        gate_name = gate_data.get("name")

        msg = (
            f'{" ".join([p.mention for p in people])}\n'
            f"{gate_name.title()} Gate is in need of Strike Team reinforcements!"
            f' Head to <#874795661198000208> and grab the {gate_data.get("emoji")}'
            f" from the list and head over to the gate!"
        )

        await ch.send(msg, allowed_mentions=discord.AllowedMentions(users=True))

        for p in people:
            await self.data_db.update_one(
                {"_id": p.id}, {"$set": {"last_strike": gate_name}}
            )
            # role = discord.utils.find(lambda r: r.name == f'{gate_name.title()} Gate', ctx.guild.roles)
            # if role:
            #     await p.add_roles(role, reason='Strike Queue Signup, adding role.')

        # reinforcement analytics

        dm_info = await self.bot.mdb["dm_analytics"].find_one(
            {"_id": gate_data.get("owner", None)}
        )
        last_gate = dm_info["dm_gates"][-1]

        await self.r_db.insert_one(
            {
                "type": "strike_team",
                "user_ids": [p.id for p in people],
                "dm_id": gate_data["owner"],
                "gate_name": gate_name.lower(),
                "gate_info": last_gate,
            }
        )

        for person in dms:
            await self.db.delete_one({"_id": person.get("_id")})

        await self.update_queue()

        log.info(
            f'[Strike Queue] {ctx.author} summoned {", ".join(p.display_name for p in people)} to'
            f" {gate_name.title()} Gate."
        )

    @strike.command(name="update")
    @has_role(ROLE)
    async def strike_update(self, ctx, rank_content):
        """Update your Strike Team queue entry."""
        embed = create_default_embed(ctx)
        embed.title = "Strike Team Queue Updated."
        embed.description = (
            "If you are in the Strike Team queue, your message has been updated."
        )
        embed.add_field(name="New Message", value=rank_content)

        try:
            await self.db.update_one(
                {"_id": ctx.author.id}, {"$set": {"content": rank_content}}
            )
        except:
            pass
        else:
            await self.update_queue()

        await ctx.send(embed=embed, delete_after=10)

    @strike.command(name="queue", aliases=["view"])
    @has_role(ROLE)
    async def strike_view(self, ctx):
        """Shows the Strike Team queue."""
        embed = await self.generate_embed()

        await ctx.send(embed=embed)

    @strike.command(name="leave")
    @has_role(ROLE)
    async def strike_leave(self, ctx):
        """Leave the Strike Team queue."""
        embed = create_default_embed(ctx)
        embed.title = "Strike Team Queue Left."
        embed.description = "If you were previously in the Strike Team queue, you have been removed from it."

        try:
            await self.db.delete_one({"_id": ctx.author.id})
        except:
            pass
        else:
            await self.update_queue()

        await ctx.send(embed=embed, delete_after=10)

    @strike.command(name="remove")
    @has_role("Admin")
    async def strike_remove(self, ctx, to_remove: discord.Member):
        """Remove a member from the Strike Queue."""
        embed = create_default_embed(ctx)
        embed.title = "User Removed from Queue."
        embed.description = (
            f"{to_remove.mention} has been removed from queue, if they were in it."
        )

        try:
            await self.db.delete_one({"_id": to_remove.id})
        except:
            pass
        else:
            await self.update_queue()

        await ctx.send(embed=embed, delete_after=10)


def setup(bot):
    bot.add_cog(StrikeQueue(bot))
