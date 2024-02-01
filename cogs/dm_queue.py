import asyncio
import datetime
import logging
from collections import namedtuple

import discord
import disnake
import pendulum
import pymongo
from discord.ext import commands

import utils.constants as constants
from cogs.models.queue_models import Queue, Group
from cogs.queue import queue_from_guild, length_check
from utils.checks import has_role, has_any_role
from utils.functions import create_queue_embed, try_delete, create_default_embed

GateGroup = namedtuple("GateGroup", "gate claimed name")

log = logging.getLogger(__name__)


class DMQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

        self.db = self.bot.mdb["dm_queue"]
        self.dm_db = self.bot.mdb["dm_analytics"]
        self.assign_data_db = self.bot.mdb["dm_assign_analytics"]

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == constants.GATES_SERVER:
            return True
        if ctx.guild.id == constants.DEBUG_SERVER and self.bot.environment == "testing":
            return True

    @commands.Cog.listener(name="on_message")
    async def dm_queue_listener(self, msg):

        if msg.channel.id != self.queue_channel_id:
            return

        if not msg.content.lower().startswith("**ready"):
            return

        content = discord.utils.remove_markdown(msg.content.lower())
        rank_content = content.replace("ready: ", "").strip()

        content = {
            "$set": {"ranks": rank_content, "msg": msg.id},
            "$currentDate": {"readyOn": True},
        }

        await self.db.update_one({"_id": msg.author.id}, content, upsert=True)
        await self.dm_db.update_one(
            {"_id": msg.author.id},
            {
                "$inc": {"dm_queue.signups": 1},
                "$currentDate": {"dm_queue.last_signup": True},
            },
            upsert=True,
        )

        try:
            await msg.add_reaction("\U0001f44d")
        except (disnake.Forbidden, disnake.NotFound):
            pass

        await self.update_queue()

    async def generate_embed(self):

        guild = self.bot.get_guild(self.server_id)

        data = await self.db.find().sort("readyOn", pymongo.ASCENDING).to_list(None)
        embed = create_queue_embed(self.bot)

        out = []

        embed.title = "DM Queue"

        for i, item in enumerate(data):
            member = guild.get_member(item.get("_id"))
            cur = f'**#{i + 1}.** {member.mention} - {item.get("ranks")}'
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

            if old_embed.title != "DM Queue":
                continue

            await try_delete(msg)

        # send new
        await ch.send(embed=embed)

    @commands.group(name="dm", invoke_without_command=True)
    async def dm(self, ctx):
        """Base command for DM queue"""
        await ctx.send_help(self.dm)

    @dm.command(name="assign")
    @has_role("Admin")
    async def dm_assign(self, ctx, queue_num: int, group_num: int):
        """
        Assigns a DM to a group
        `queue_num` - The DM's queue number
        `group_num` - The group's number (from the base queue)
        """

        ch = ctx.guild.get_channel(self.assign_id)

        dm_data = await self.db.find().sort("readyOn", pymongo.ASCENDING).to_list(None)
        if len(dm_data) == 0:
            return await ctx.send("No DMs currently in DM queue.")
        if queue_num > (size := len(dm_data)):
            return await ctx.send(
                f"Invalid DM Queue number. Must be less than or equal to {size}"
            )
        elif queue_num < 1:
            return await ctx.send("Invalid DM Queue number. Must be at least 1.")

        dm = dm_data[(queue_num - 1)]
        who = ctx.guild.get_member(dm.get("_id"))

        gates_data: Queue = await queue_from_guild(
            self.bot.mdb["player_queue"], ctx.guild
        )
        check = length_check(len(gates_data.groups), group_num)
        if check is not None:
            return await ctx.send(check)

        group = gates_data.groups[group_num - 1]
        msg = (
            f"Group {group_num} is yours, see above for details."
            f" Don't forget to submit your encounter in <#798247432743551067> once ready and claim once approved!"
            f" Kindly note that this is a **{len(group.players)} person Rank {group.tier_str}** "
            f"group and adjust your encounter as needed."
            f" Please react to this message if you are, indeed, claiming."
            f" **__Please double-check your group number in <#773895672415649832> when claiming because it may have changed.__**"
        )
        embed = create_queue_embed(self.bot)
        embed.title = "Gate Assignment"
        embed.description = msg

        group.players.sort(key=lambda x: x.member.display_name)

        # update members
        for player in group.players:
            player.member = await ctx.guild.fetch_member(player.member.id)

        embed2 = create_queue_embed(self.bot)
        embed2.title = f"Information for Group #{group_num}"
        embed2.description = group.player_levels_str
        await ch.send(embed=embed2)
        await ch.send(
            f"{who.mention}",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        analytics_data = {
            "summoner": ctx.author.id,
            "dm": who.id,
            "gate_data": group.to_dict(),
            "claimed": False,
            "summonDate": datetime.datetime.utcnow(),
        }
        await self.assign_data_db.insert_one(analytics_data)
        await self.dm_db.update_one(
            {"_id": who.id}, {"$inc": {"dm_queue.assignments": 1}}, upsert=True
        )

        await self.db.delete_one({"_id": who.id})
        await self.update_queue()

        log.info(
            f"[DM Queue] {ctx.author} assigned Gate #{group_num} to {who} (DM #{queue_num})"
        )

    @dm.command(name="update")
    @has_role("DM")
    async def dm_update(self, ctx, rank_content):
        """Update your DM queue entry."""
        embed = create_default_embed(ctx)
        embed.title = "DM Queue Updated."
        embed.description = "If you are in the DM queue, your message has been updated."
        embed.add_field(name="New Message", value=rank_content)

        try:
            await self.db.update_one(
                {"_id": ctx.author.id}, {"$set": {"ranks": rank_content}}
            )
        except:
            pass
        else:
            await self.update_queue()

        await ctx.send(embed=embed, delete_after=10)

    @dm.command(name="queue", aliases=["view"])
    @has_role("DM")
    async def dm_view(self, ctx):
        """Shows the DM queue."""
        embed = await self.generate_embed()

        await ctx.send(embed=embed)

    @dm.command(name="leave")
    @has_role("DM")
    async def dm_leave(self, ctx):
        """Leave the DM queue."""
        embed = create_default_embed(ctx)
        embed.title = "DM Queue Left."
        embed.description = (
            "If you were previously in the DM queue, you have been removed from it."
        )

        try:
            await self.db.delete_one({"_id": ctx.author.id})
        except:
            pass
        else:
            await self.update_queue()

        await ctx.send(embed=embed, delete_after=10)

    @dm.command(name="remove")
    @has_role("Assistant")
    async def dm_remove(self, ctx, to_remove: discord.Member):
        """Remove a member from the DM queue."""
        embed = create_default_embed(ctx)
        embed.title = "Member Removed from Queue."
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

    async def load_recent_gates(self, who: discord.Member, existing_data=None):
        if existing_data is None:
            dm_data = await self.dm_db.find_one({"_id": who.id})
        else:
            dm_data = existing_data
        if not dm_data:
            raise commands.BadArgument(f"Member {who.mention} does not have DM stats.")

        gates = []
        for raw_data in dm_data.get("dm_gates"):
            name = raw_data.pop("gate_name")
            claimed = raw_data.pop("claimed_date")
            raw_data["position"] = None
            gate = Group.from_dict(self.bot.get_guild(self.server_id), raw_data)
            gates.append(GateGroup(gate=gate, name=name, claimed=claimed))

        gates = sorted(gates, key=lambda x: x.claimed)

        gates = gates[:10]
        gates.reverse()
        return gates

    @dm.group(name="stats", invoke_without_command=True)
    @has_any_role(["DM", "Assistant"])
    async def dm_stats(self, ctx, who: discord.Member = None):
        """Get DM stats."""
        if who is None:
            who = ctx.author
        embed = create_default_embed(
            ctx,
            title=f"{who.display_name}'s DM Stats",
        )

        # Overall Stats
        dm_data = await self.dm_db.find_one({"_id": who.id})

        if "dm_queue" in dm_data:
            last_signed = pendulum.instance(dm_data["dm_queue"]["last_signup"])

            embed.add_field(
                name="DM Queue Stats",
                value=f"**Queue Signups:** {dm_data['dm_queue'].get('signups', 0)}\n"
                f"**Queue Assignments:** {dm_data['dm_queue'].get('assignments', 0)}\n"
                f"**Last Signup:** <t:{int(last_signed.timestamp())}:f>",
                inline=False,
            )
        if "dm_claims" in dm_data:
            last_claimed = pendulum.instance(dm_data["dm_claims"]["last_claim"])
            embed.add_field(
                name="Gate Claim Stats",
                value=f"**Gate Claims:** {dm_data['dm_claims']['claims']}\n"
                f"**Last Claim:** <t:{int(last_claimed.timestamp())}:f>",
                inline=False,
            )

        # Gate stats
        recent_gates = await self.load_recent_gates(who, existing_data=dm_data)

        gate_string = "\n".join(
            f"{i+1}. Rank {x.gate.tier}, {len(x.gate.players)} players"
            for i, x in enumerate(recent_gates)
        )
        descriptor = (
            f"For more info, run `{ctx.prefix}dm stats gate # [user mention]`, "
            f"where # is the gate number to get more information on."
        )

        embed.add_field(
            name="Recent Gates (Most recent first)",
            value="```\n" + gate_string + "\n```\n" + descriptor,
            inline=False,
        )

        await ctx.send(embed=embed)

    @dm_stats.command(name="gate")
    @has_any_role(["DM", "Assistant"])
    async def dm_stats_specific(self, ctx, gate_num: int, who: discord.Member = None):
        """Get the stats on a specific gate number."""

        if who is None:
            who = ctx.author

        embed = create_default_embed(
            ctx,
            title=f"{who.display_name}'s Gate #{gate_num} Stats",
        )

        # Overall Stats
        gates = await self.load_recent_gates(who)

        try:
            gate = gates[gate_num - 1]
        except IndexError:
            raise commands.BadArgument(
                f"Gate number must exist. See `{ctx.prefix}dm stats` for gate numbers."
            )

        claimed = int(pendulum.instance(gate.claimed).timestamp())
        embed.add_field(
            name="Gate Info",
            value=f"**Rank:** {gate.gate.tier}\n**Name:** {gate.name.title()} Gate\n**Claimed at:** <t:{claimed}:f>",
            inline=False,
        )
        embed.add_field(name="Players", value=gate.gate.player_levels_str, inline=False)

        await ctx.send(embed=embed)

    @dm_stats.command(name="dump")
    @has_any_role(["DM", "Assistant"])
    async def dm_stats_dump(self, ctx, who: discord.Member = None):

        if not who:
            who = ctx.author

        dm_data = await self.dm_db.find_one({"_id": who.id})

        if not dm_data:
            raise commands.BadArgument(f"Member {who.mention} does not have DM stats.")

        gates = []
        for raw_data in dm_data.get("dm_gates"):
            name = raw_data.pop("gate_name")
            claimed = raw_data.pop("claimed_date")
            raw_data["position"] = None
            gate = Group.from_dict(self.bot.get_guild(self.server_id), raw_data)
            gates.append(GateGroup(gate=gate, name=name, claimed=claimed))

        pag = commands.Paginator()
        pag.add_line(f"DM Stats Data for {who.display_name}")
        pag.add_line("claimed date (utc), gate tier")
        for gate in gates:
            pag.add_line(f"{gate.claimed},{gate.gate.tier}")

        for page in pag.pages:
            await ctx.send(page)

    @dm_stats.command(name="reinforcements")
    @has_any_role(["DM", "Assistant"])
    async def dm_reinforcements_dump(self, ctx, who: discord.Member = None):

        if who:
            data = (
                await self.bot.mdb["reinforcement_analytics"]
                .find({"dm_id": who.id})
                .sort("gate_info.claimed_date", 1)
                .to_list(length=None)
            )
        else:
            data = (
                await self.bot.mdb["reinforcement_analytics"]
                .find()
                .sort("gate_info.claimed_date", 1)
                .to_list(length=None)
            )

        if not data:
            raise commands.BadArgument("Could not find reinforcement data")

        pag = commands.Paginator()
        pag.add_line(
            f"Reinforcement Data Data for {who.display_name}"
            if who
            else "Reinforcement Data"
        )
        pag.add_line("dm id, gate claimed date (utc), gate tier")
        for r in data:
            pag.add_line(
                f"{r['dm_id']},{r['gate_info']['claimed_date']},{r['gate_info']['tier']}"
            )

        for page in pag.pages:
            await ctx.send(page)

    @dm_stats.command(name="claimed")
    @has_any_role(["Assistant", "Admin"])
    async def dm_stats_claimed(self, ctx):
        """
        Shows the last claim date of all registered DM(s). The DM must have claimed a gate before.
        """
        data = await self.dm_db.find().to_list(length=None)
        embed = create_default_embed(ctx, title="DM Analytics - Last DM Claim")
        molded_data = []
        for item in data:
            member = ctx.guild.get_member(item["_id"])
            try:
                timestamp = int(
                    (
                        item["dm_claims"].get("last_claim")
                        - datetime.datetime(1970, 1, 1)
                    ).total_seconds()
                )
            except (KeyError, IndexError):
                continue
            molded_data.append((member, timestamp))
        molded_data = sorted(molded_data, key=lambda i: i[1])
        embed.description = "\n".join(
            [f"{i[0].mention}: <t:{i[1]}:R>" for i in molded_data]
        )

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(DMQueue(bot))
