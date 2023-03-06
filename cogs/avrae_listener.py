from typing import List

import disnake
from disnake.ext import commands

from cogs.tracker import Gate
from utils import constants
import re

TURN_MSG_RGX = re.compile(r"\*\*.+\*\*: (\w|[^(])+(\(.+\))")


class AvraeListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )

    @commands.Cog.listener(name="on_message")
    async def turn_listener(self, message: disnake.Message):
        if (not message.guild) or (message.guild.id != self.server_id):
            return

        if message.author.id != constants.AVRAE_USER_ID:
            return

        gates_list: List[Gate] = self.bot.cogs["GateTracker"].gates

        if not any(x for x in gates_list if x.dice_channel.id == message.channel.id):
            return

        if re_match := TURN_MSG_RGX.match(message.content):
            user_id = int(re_match.group(2).strip("(<@>)"))
        else:
            return

        user = message.guild.get_member(user_id)
        turn_start_date = message.created_at

        await message.channel.send(f'{user.mention}: {turn_start_date}')


def setup(bot):
    bot.add_cog(AvraeListener(bot))
