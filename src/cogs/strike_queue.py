from __future__ import annotations

import logging

import disnake as discord
from disnake.ext import commands

import common.constants as constants
from common.checks import has_role
from common.embeds import create_default_embed
from queueing.services import get_queue_services

log = logging.getLogger(__name__)

ROLE = "Assistant"


class StrikeQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.services = get_queue_services(bot)
        self.strike_service = self.services.strike_queue_service
        self.presentation = self.services.presentation_service

        self.queue_channel_id = self.services.config.strike_queue_channel_id
        self.assign_id = self.services.config.strike_queue_assignment_channel_id
        self.server_id = self.services.config.server_id

        self.db = self.bot.mdb["strike_queue"]
        self.meta_db = self.bot.mdb["queue_meta"]
        self.gate_db = bot.mdb["gate_list"]
        self.data_db = self.bot.mdb["queue_analytics"]
        self.r_db = self.bot.mdb["reinforcement_analytics"]

    async def cog_check(self, ctx):  # pyright: ignore[reportIncompatibleMethodOverride]
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
        await self.strike_service.signup_from_message(
            message=msg,
            text=msg_content,
        )

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
        entries = await self.services.strike_queue_repository.list_entries()
        return await self.presentation.build_strike_queue_embed(guild=guild, entries=entries)

    async def update_queue(self):
        guild = self.bot.get_guild(self.server_id)
        await self.strike_service.refresh_queue_message(
            guild=guild,
        )

    @commands.group(name="strike", invoke_without_command=True)
    async def strike(self, ctx):
        """Base command for DM queue"""
        await ctx.send_help(self.strike)

    @strike.command(name="assign")
    @has_role("DM")
    async def strike_assign(self, ctx, queue_nums: commands.Greedy[int], gate_name: str):
        """
        Assigns a Strike member to a group
        `queue_num` - The Strike member(s) queue number(s). You can assign multiple members at once.
        `gate_name` - The gate's name to assist.
        """
        result = await self.strike_service.assign_strike_team(
            guild=ctx.guild,
            queue_numbers=list(queue_nums),
            gate_name=gate_name,
        )
        if not result.success:
            return await ctx.send(result.message, delete_after=5)
        log.info(f"[Strike Queue] {ctx.author} assigned strike team for {gate_name}.")

    @strike.command(name="update")
    @has_role(ROLE)
    async def strike_update(self, ctx, rank_content):
        """Update your Strike Team queue entry."""
        embed = create_default_embed(ctx)
        embed.title = "Strike Team Queue Updated."
        embed.description = "If you are in the Strike Team queue, your message has been updated."
        embed.add_field(name="New Message", value=rank_content)

        await self.strike_service.update_member(
            guild=ctx.guild,
            member_id=ctx.author.id,
            text=rank_content,
        )

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

        await self.strike_service.leave_member(
            guild=ctx.guild,
            member_id=ctx.author.id,
        )

        await ctx.send(embed=embed, delete_after=10)

    @strike.command(name="remove")
    @has_role("Admin")
    async def strike_remove(self, ctx, to_remove: discord.Member):
        """Remove a member from the Strike Queue."""
        embed = create_default_embed(ctx)
        embed.title = "User Removed from Queue."
        embed.description = f"{to_remove.mention} has been removed from queue, if they were in it."

        await self.strike_service.leave_member(
            guild=ctx.guild,
            member_id=to_remove.id,
        )

        await ctx.send(embed=embed, delete_after=10)


def setup(bot):
    bot.add_cog(StrikeQueue(bot))
