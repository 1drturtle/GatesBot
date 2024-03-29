import logging

import discord
from discord.ext import commands

import utils.constants as constants
from utils.checks import has_role
from utils.functions import create_default_embed

log = logging.getLogger(__name__)


class Gate:
    def __init__(
        self,
        name: str,
        ic_channel: discord.TextChannel,
        ooc_channel: discord.TextChannel,
        dice_channel: discord.TextChannel,
        dm: discord.Member,
    ):
        self.name = name
        self.ic_channel = ic_channel
        self.ooc_channel = ooc_channel
        self.dice_channel = dice_channel
        self.dm = dm

    def __repr__(self):
        return (
            f"<Gate name={self.name}, ic={self.ic_channel.id}, ooc={self.ooc_channel.id}, "
            f"dice={self.dice_channel.id}, owner={self.dm}>"
        )


class GateOwners(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gates_db = self.bot.mdb["gate_list"]
        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )

    async def cog_load(self):
        """Loads all claimed Gate channels on"""
        await self.bot.wait_until_ready()
        all_gates = await self.gates_db.find().to_list(length=None)
        guild = self.bot.get_guild(self.server_id)
        for gate in all_gates:
            if not gate.get("owner"):
                log.warning("[GateTracker] No owner for " + gate.get("name"))
                continue

            name = gate["name"]
            ic_c = discord.utils.find(lambda c: c.name == f"{name}-ic", guild.channels)
            ooc_c = discord.utils.find(
                lambda c: c.name == f"{name}-ooc", guild.channels
            )
            dice_c = discord.utils.find(
                lambda c: c.name == f"{name}-dice", guild.channels
            )
            if not all((ic_c, ooc_c, dice_c)):
                log.error("[GateTracker] Could not find a channel for " + name)

            owner = guild.get_member(gate.get("owner"))
            if not owner:
                log.error("[GateTracker] Could not find member for " + name)

        log.info("[GateTracker] All Gates loaded.")

    @commands.command(name="claim-gate")
    @has_role("DM")
    async def claim_gate(self, ctx, gate_name: str):
        """Claim a gate as yours in the bot's database."""
        if not (data := await self.gates_db.find_one({"name": gate_name.lower()})):
            await ctx.send(
                f"Gate `{gate_name}` not found, please run command with a valid gate name."
            )
            return None

        await self.gates_db.update_one(
            {"_id": data["_id"]}, {"$set": {"owner": ctx.author.id}}
        )

        embed = create_default_embed(
            ctx,
            title="Gate Ownership Claimed",
            description=f"You have claimed {gate_name.title()} Gate as your own, and it has been saved to the database."
            f" Thank you!",
        )
        await ctx.send(embed=embed)
        return None

    @commands.command(name="gate-owners")
    @has_role("Assistant")
    async def show_gate_owners(self, ctx):
        """
        Shows known owners of gates.
        If your gate is not on this list, please run `=claim-gate <gate name>`
        """
        data = await self.gates_db.find({"owner": {"$exists": True}}).to_list(
            length=None
        )
        embed = create_default_embed(ctx, title="Gate Owners")
        description = "\n".join(
            [
                f"<@{item.get('owner')}> - {item.get('name').title()} Gate {item.get('emoji')}"
                for item in data
            ]
        )
        embed.description = description
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(GateOwners(bot))
