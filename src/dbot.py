import asyncio
import datetime

from bot.bootstrap import COGS, build_bot, register_persistent_views
from bot.logging_setup import configure_logging
from common.settings import settings
from common.discord_utils import try_delete

bot = build_bot()
log = configure_logging()


@bot.event
async def on_ready():
    bot.ready_time = datetime.datetime.now(datetime.timezone.utc)
    bot.loop = asyncio.get_running_loop()
    register_persistent_views(bot)

    ready_message = (
        f"\n---------------------------------------------------\n"
        f"Bot Ready!\n"
        f"Logged in as {bot.user.name} (ID: {bot.user.id})\n"
        f"Current Prefix: {settings.prefix}\n"
        f"---------------------------------------------------"
    )
    log.info(ready_message)


@bot.event
async def on_message(message):
    if message.author.bot:
        return None

    if not bot.is_ready():
        return None

    context = await bot.get_context(message)
    if context.command is not None:
        return await bot.invoke(context)


@bot.event
async def on_command(ctx):
    if ctx.command.name in ["py", "pyi", "sh"]:
        return

    await try_delete(ctx.message)


for cog in COGS:
    bot.load_extension(cog)

if __name__ == "__main__":
    bot.run(settings.token)
