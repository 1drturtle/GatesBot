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
        return f"<Gate ic={self.ic_channel.id}, ooc={self.ooc_channel.id}, dice={self.dice_channel.id}, owner={self.dm}"


class GateTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gates_db = self.bot.mdb["gate_list"]
        self.tracker_db = self.bot.mdb["gate_tracker"]
        self.server_id = constants.GATES_SERVER if self.bot.environment != "testing" else constants.DEBUG_SERVER
        self.gates = []

    async def cog_load(self):
        """Loads all claimed Gate channels on"""
        await self.bot.wait_until_ready()
        all_gates = await self.gates_db.find().to_list(length=None)
        guild = self.bot.get_guild(self.server_id)
        for gate in all_gates:
            if not gate.get("owner"):
                log.warning("No owner for " + gate.get("name"))
                continue
            name = gate["name"]
            ic_c = discord.utils.find(lambda c: c.name == f"{name}-ic", guild.channels)
            ooc_c = discord.utils.find(lambda c: c.name == f"{name}-ooc", guild.channels)
            dice_c = discord.utils.find(lambda c: c.name == f"{name}-dice", guild.channels)
            if [True for c in (ic_c, ooc_c, dice_c) if c is None]:
                log.error("Could not find a channel for " + name)

            owner = guild.get_member(gate.get("owner"))
            if not owner:
                log.error("Could not find DM for " + name)

            gate = Gate(name, ic_c, ooc_c, dice_c, owner)
            self.gates.append(gate)

    async def cog_unload(self):
        self.gates = []

    @commands.command(name="claim-gate")
    @has_role("DM")
    async def claim_gate(self, ctx, gate_name: str):
        """Claim a gate as yours in the bot's database."""
        if not (data := await self.gates_db.find_one({"name": gate_name.lower()})):
            await ctx.send(f"Gate `{gate_name}` not found, please run command with a valid gate name.")
            return None

        await self.gates_db.update_one({"_id": data["_id"]}, {"$set": {"owner": ctx.author.id}})

        embed = create_default_embed(
            ctx,
            title="Gate Ownership Claimed",
            description=f"You have claimed {gate_name.title()} Gate as your own, and it has been saved to the database."
            f" Thank you!",
        )
        await ctx.send(embed=embed)
        return None


def setup(bot):
    bot.add_cog(GateTracker(bot))
