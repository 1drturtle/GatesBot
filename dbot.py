import logging
import sys
from datetime import datetime

import discord
import motor.motor_asyncio
import sentry_sdk
from discord.ext import commands

import utils.config as config
from utils.functions import try_delete

COGS = {'cogs.util', 'jishaku', 'cogs.queue', 'cogs.errors', 'cogs.help'}


async def get_prefix(client, message):
    if not message.guild:
        return commands.when_mentioned_or(config.PREFIX)(client, message)
    guild_id = str(message.guild.id)
    if guild_id in client.prefixes:
        prefix = client.prefixes.get(guild_id, config.PREFIX)
    else:
        dbsearch = await client.mdb['prefixes'].find_one({'guild_id': guild_id})
        if dbsearch is not None:
            prefix = dbsearch.get('prefix', config.PREFIX)
        else:
            prefix = config.PREFIX
        client.prefixes[guild_id] = prefix
    return commands.when_mentioned_or(prefix)(client, message)


class GatesBot(commands.Bot):
    def __init__(self, command_prefix=get_prefix, desc: str = '', **options):
        self.launch_time = datetime.utcnow()
        self._dev_id = config.DEV_ID

        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGO_URL)
        self.mdb = self.mongo_client[config.MONGO_DB]

        self.sentry_url = config.SENTRY_URL
        self.prefixes = dict()

        super(GatesBot, self).__init__(command_prefix, description=desc, **options)

    @property
    def dev_id(self):
        return self._dev_id


intents = discord.Intents(guilds=True, members=True, messages=True, reactions=True)

description = 'Bot made for The Gates D&D Server.'

bot = GatesBot(desc=description, intents=intents, allowed_mentions=discord.AllowedMentions.none())

log_formatter = logging.Formatter('%(levelname)s | %(name)s: %(message)s')
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(log_formatter)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)
log = logging.getLogger('bot')

# Make discord logs a bit quieter
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.WARN)


@bot.event
async def on_ready():

    bot.ready_time = datetime.utcnow()

    ready_message = f'\n---------------------------------------------------\n' \
                    f'Bot Ready!\n' \
                    f'Logged in as {bot.user.name} (ID: {bot.user.id})\n' \
                    f'Current Prefix: {config.PREFIX}\n' \
                    f'---------------------------------------------------'
    log.info(ready_message)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if not bot.is_ready():
        return

    context = await bot.get_context(message)
    if context.command is not None:
        return await bot.invoke(context)


@bot.event
async def on_command(ctx):
    if ctx.command.name in ['py', 'pyi', 'sh']:
        return

    await try_delete(ctx.message)


for cog in COGS:
    bot.load_extension(cog)

if __name__ == '__main__':
    if config.SENTRY_URL is not None:
        bot.sentry = sentry_sdk.init(config.SENTRY_URL, traces_sample_rate=1)

    bot.run(config.TOKEN)