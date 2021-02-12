import asyncio
import logging

import discord
import pendulum
from discord.ext import commands

log = logging.getLogger(__name__)


class Schedule(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None

    @commands.Cog.listener(name='on_ready')
    async def ready_listener(self):
        self.task = asyncio.create_task(self.every_minute())
        self.task.add_done_callback(self.task_error)

    async def every_minute(self):
        while True:
            now = pendulum.now('America/New_York')
            next = now + pendulum.duration(minutes=1)
            next_msg = now.next(pendulum.FRIDAY).at(10)
            log.info(f'next friday is {next_msg.to_day_datetime_string()}')
            log.info(f'it is {now.to_day_datetime_string()}. {self.bot.guilds}')
            await discord.utils.sleep_until(next)

    def task_error(self, task):
        if task.exception():
            task.print_stack()


def setup(bot):
    bot.add_cog(Schedule(bot))
