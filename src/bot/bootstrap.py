from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
import motor.motor_asyncio
from discord.ext import commands

from bot.prefixes import get_prefix
from common.constants import DEBUG_SERVER
from common.settings import settings
from queueing.views import DMQueueUI, PlayerQueueUI, StrikeQueueUI

COGS = {
    "cogs.util",
    "jishaku",
    "cogs.queue",
    "cogs.placeholders",
    "cogs.schedule",
    "cogs.errors",
    "cogs.admin",
    "cogs.dm_queue",
    "cogs.strike_queue",
    "cogs.gate_owners",
}


class GatesBot(commands.Bot):
    def __init__(self, command_prefix=get_prefix, desc: str = "", **options: Any):
        self.launch_time = datetime.utcnow()
        self.ready_time: datetime | None = None
        self._dev_id = settings.dev_id
        self.environment = settings.environment
        self.loop = None  # type: ignore

        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongo_url)
        self.mdb = self.mongo_client[settings.mongo_db]
        self.prefixes: dict[str, str] = {}
        self.prefix = settings.prefix
        self.persistent_views_added = False

        super().__init__(command_prefix, description=desc, **options)

    @property
    def dev_id(self) -> int:
        return self._dev_id

    @property
    def uptime(self):
        return datetime.utcnow() - self.launch_time


def build_bot() -> GatesBot:
    intents = discord.Intents(
        guilds=True,
        members=True,
        messages=True,
        reactions=True,
        message_content=True,
    )

    return GatesBot(
        desc="Discord Bot made for The Gates D&D Server.",
        intents=intents,
        allowed_mentions=discord.AllowedMentions.none(),
        test_guilds=[DEBUG_SERVER],
    )


def register_persistent_views(bot: GatesBot) -> None:
    if bot.persistent_views_added:
        return

    bot.add_view(PlayerQueueUI(bot))
    bot.add_view(DMQueueUI(bot))
    bot.add_view(StrikeQueueUI(bot))
    bot.persistent_views_added = True
