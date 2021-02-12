import asyncio
import logging

import discord
import pendulum
from discord.ext import commands

from utils.constants import SCHEDULE_CHANNEL, SCHEDULE_CHANNEL_DEBUG
from utils.config import ENVIRONMENT

log = logging.getLogger(__name__)


class Schedule(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None
        self.channel_id = SCHEDULE_CHANNEL_DEBUG if ENVIRONMENT == 'testing' else SCHEDULE_CHANNEL

    @commands.Cog.listener(name='on_ready')
    async def ready_listener(self):
        self.task = asyncio.create_task(self.every_minute())
        self.task.add_done_callback(self.task_error)

    async def every_minute(self):
        while True:
            now = pendulum.now('America/New_York')
            next = now + pendulum.duration(minutes=1)
            next_msg = now.next(pendulum.FRIDAY).at(10)
            log.info(f'it is {now.to_day_datetime_string()}. {self.bot.guilds}')
            if now.day_of_week == pendulum.FRIDAY and now.hour == 10:
                channel = self.bot.get_channel(self.channel_id)
                if channel:
                    log.info(f'sending message to #{channel.name} at {now.to_day_datetime_string()}')
                    await channel.send('-')
                else:
                    log.error(f'could not find channel with id {self.channel_id}. skipping message.')
            await discord.utils.sleep_until(next)

    def task_error(self, task):
        if task.exception():
            task.print_stack()


def setup(bot):
    bot.add_cog(Schedule(bot))
