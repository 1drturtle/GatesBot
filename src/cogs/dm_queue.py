from __future__ import annotations

import datetime
import logging
from collections import namedtuple

import disnake as discord
import pendulum
from disnake.ext import commands

import common.constants as constants
from common.checks import has_any_role, has_role
from common.embeds import create_default_embed
from queueing.models import Group
from queueing.services import get_queue_services
from queueing.views import DMQueueUI

GateGroup = namedtuple("GateGroup", "gate claimed name")

log = logging.getLogger(__name__)


class DMQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.services = get_queue_services(bot)
        self.dm_service = self.services.dm_queue_service
        self.presentation = self.services.presentation_service

        self.queue_channel_id = self.services.config.dm_queue_channel_id
        self.assign_id = self.services.config.dm_queue_assignment_channel_id
        self.server_id = self.services.config.server_id

        self.db = self.bot.mdb["dm_queue"]
        self.meta_db = self.bot.mdb["queue_meta"]
        self.dm_db = self.bot.mdb["dm_analytics"]
        self.assign_data_db = self.bot.mdb["dm_assign_analytics"]

    async def cog_check(self, ctx):  # type: ignore
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
        await self.dm_service.signup_from_message(
            message=msg,
            text=rank_content,
            view_factory=lambda: DMQueueUI(self.bot),
        )

        try:
            await msg.add_reaction("\U0001f44d")
        except discord.Forbidden, discord.NotFound:
            pass

        await self.update_queue()

    async def generate_embed(self):
        guild = self.bot.get_guild(self.server_id)
        entries = await self.services.dm_queue_repository.list_entries()
        return await self.presentation.build_dm_queue_embed(guild=guild, entries=entries)

    async def update_queue(self):
        guild = self.bot.get_guild(self.server_id)
        await self.dm_service.refresh_queue_message(
            guild=guild,
            view_factory=lambda: DMQueueUI(self.bot),
        )

    @commands.group(name="dm", invoke_without_command=True)
    async def dm(self, ctx):
        """Base command for DM queue"""
        await ctx.send_help(self.dm)

    @dm.command(name="assign")
    @has_role("Assistant")
    async def dm_assign(self, ctx, queue_num: int, group_num: int):
        """
        Assigns a DM to a group
        `queue_num` - The DM's queue number
        `group_num` - The group's number (from the base queue)
        """
        result = await self.dm_service.assign_dm_to_group(
            guild=ctx.guild,
            summoner=ctx.author,
            group_number=group_num,
            queue_number=queue_num,
            view_factory=lambda: DMQueueUI(self.bot),
            allow_reassignment=True,
        )
        if not result.success:
            return await ctx.send(result.message)
        who = ctx.guild.get_member(result.assigned_member_id)
        log.info(f"[DM Queue] {ctx.author} assigned Gate #{group_num} to {who} (DM #{queue_num})")

    @dm.command(name="update")
    @has_role("DM")
    async def dm_update(self, ctx, rank_content):
        """Update your DM queue entry."""
        embed = create_default_embed(ctx)
        embed.title = "DM Queue Updated."
        embed.description = "If you are in the DM queue, your message has been updated."
        embed.add_field(name="New Message", value=rank_content)

        await self.dm_service.update_member(
            guild=ctx.guild,
            member_id=ctx.author.id,
            text=rank_content,
            view_factory=lambda: DMQueueUI(self.bot),
        )

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
        embed.description = "If you were previously in the DM queue, you have been removed from it."

        await self.dm_service.leave_member(
            guild=ctx.guild,
            member_id=ctx.author.id,
            view_factory=lambda: DMQueueUI(self.bot),
            adjust_signup_count=True,
        )

        await ctx.send(embed=embed, delete_after=10)

    @dm.command(name="remove")
    @has_role("Assistant")
    async def dm_remove(self, ctx, to_remove: discord.Member):
        """Remove a member from the DM queue."""
        embed = create_default_embed(ctx)
        embed.title = "Member Removed from Queue."
        embed.description = f"{to_remove.mention} has been removed from queue, if they were in it."

        await self.dm_service.leave_member(
            guild=ctx.guild,
            member_id=to_remove.id,
            view_factory=lambda: DMQueueUI(self.bot),
            adjust_signup_count=False,
        )

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

        gates = sorted(gates, key=lambda x: x.claimed, reverse=True)

        gates = gates[:10]
        # gates.reverse()
        return gates

    @dm.group(name="stats", invoke_without_command=True)
    @has_any_role(["DM", "Assistant"])
    async def dm_stats(self, ctx, who: discord.Member | None = None):
        """Get DM stats."""
        who = who or ctx.author

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
            f"{i + 1}. Rank {x.gate.tier}, {len(x.gate.players)} players" for i, x in enumerate(recent_gates)
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
    async def dm_stats_specific(self, ctx, gate_num: int, dm_user: discord.Member | None = None):
        """Get the stats on a specific gate number."""

        who: discord.Member = dm_user or ctx.author

        embed = create_default_embed(
            ctx,
            title=f"{who.display_name}'s Gate #{gate_num} Stats",
        )

        # Overall Stats
        gates = await self.load_recent_gates(who)

        try:
            gate = gates[gate_num - 1]
        except IndexError as err:
            raise commands.BadArgument(f"Gate number must exist. See `{ctx.prefix}dm stats` for gate numbers.") from err

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
    async def dm_stats_dump(self, ctx, who: discord.Member | None = None):
        who = who or ctx.author

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
    async def dm_reinforcements_dump(self, ctx, who: discord.Member | None = None):
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
        pag.add_line(f"Reinforcement Data Data for {who.display_name}" if who else "Reinforcement Data")
        pag.add_line("dm id, gate claimed date (utc), gate tier")
        for r in data:
            pag.add_line(f"{r['dm_id']},{r['gate_info']['claimed_date']},{r['gate_info']['tier']}")

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
                timestamp = int((item["dm_claims"].get("last_claim") - datetime.datetime(1970, 1, 1)).total_seconds())
            except KeyError, IndexError:
                continue
            molded_data.append((member, timestamp))
        molded_data = sorted(molded_data, key=lambda i: i[1])
        embed.description = "\n".join([f"{i[0].mention}: <t:{i[1]}:R>" for i in molded_data])

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(DMQueue(bot))
