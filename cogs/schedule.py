import asyncio.exceptions
import logging

import discord
import pendulum
from discord.ext import commands
import textwrap

from utils.config import ENVIRONMENT
from utils.constants import SCHEDULE_CHANNEL, SCHEDULE_CHANNEL_DEBUG

log = logging.getLogger(__name__)


class Schedule(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None
        self.running = False
        self.channel_id = (
            SCHEDULE_CHANNEL_DEBUG if ENVIRONMENT == "testing" else SCHEDULE_CHANNEL
        )

    @commands.Cog.listener(name="on_ready")
    async def ready_listener(self):
        if self.running:
            return None
        self.running = True
        self.task = self.bot.loop.create_task(self.sunday_reminder())
        # self.task.add_done_callback(self.task_error)

    async def sunday_reminder(self):
        while self.running:
            now = pendulum.now("America/New_York")
            next_msg = now.next(pendulum.SUNDAY).at(10)
            if now.day_of_week == pendulum.SUNDAY and now.hour == 10:
                await self.send_scroll_reminder(next_msg, now)
            await discord.utils.sleep_until(next_msg)

    async def send_scroll_reminder(self, next_msg, now):
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            log.info(
                f"[Reminder] Sending Sunday Message to #{channel.name} at {now.to_day_datetime_string()}. "
                f"Next at {next_msg.to_day_datetime_string()}"
            )
            x = "`" * 3
            msg = textwrap.dedent(
                f"""{x}
!scroll -one 4 -two 3 -three 2 -four 1 -five 1 -cantrip 2
!tattoo -one 4 -two 3 -three 2 -four 1 -five 1 -cantrip 2
{x}
            """
            )
            await channel.send(
                "<@&773895151008874518> - don't forget to restock tattoos "
                "and scrolls via `!scroll` and `!tattoo` in <#813448793965068328>!\n"
                + msg,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

        else:
            log.error(
                f"could not find channel with id {self.channel_id}. skipping message."
            )


def setup(bot):
    bot.add_cog(Schedule(bot))
