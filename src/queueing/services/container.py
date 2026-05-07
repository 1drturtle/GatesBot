from __future__ import annotations

from dataclasses import dataclass

import disnake as discord

from common.types import MongoBackedBot
from queueing.config import QueueRuntimeConfig
from queueing.repositories import (
    AnalyticsRepository,
    DMQueueRepository,
    GateRepository,
    QueueMetaRepository,
    QueueRepository,
    StrikeQueueRepository,
)
from queueing.services.dm_queue import DMQueueService
from queueing.services.player_queue import PlayerQueueService
from queueing.services.presentation import QueuePresentationService
from queueing.services.strike_queue import StrikeQueueService


# functions that must exist to prevent circular imports. only called one due to caching
def _player_queue_view(bot: MongoBackedBot) -> discord.ui.View:
    from queueing.views.player_queue import PlayerQueueUI

    return PlayerQueueUI(bot)


def _dm_queue_view(bot: MongoBackedBot) -> discord.ui.View:
    from queueing.views.dm_queue import DMQueueUI

    return DMQueueUI(bot)


def _strike_queue_view(bot: MongoBackedBot) -> discord.ui.View:
    from queueing.views.strike_queue import StrikeQueueUI

    return StrikeQueueUI(bot)


@dataclass(slots=True)
class QueueServices:
    config: QueueRuntimeConfig
    queue_repository: QueueRepository
    dm_queue_repository: DMQueueRepository
    strike_queue_repository: StrikeQueueRepository
    gate_repository: GateRepository
    analytics_repository: AnalyticsRepository
    meta_repository: QueueMetaRepository
    presentation_service: QueuePresentationService
    player_queue_service: PlayerQueueService
    dm_queue_service: DMQueueService
    strike_queue_service: StrikeQueueService


_SERVICE_CACHE_ATTR = "_queue_services"


def get_queue_services(bot: MongoBackedBot) -> QueueServices:
    cached = getattr(bot, _SERVICE_CACHE_ATTR, None)
    if cached is not None:
        return cached

    config = QueueRuntimeConfig.from_environment(bot.environment)
    queue_repository = QueueRepository(
        bot.mdb["player_queue"],
        default_channel_id=config.player_queue_channel_id,
    )
    dm_queue_repository = DMQueueRepository(bot.mdb["dm_queue"])
    strike_queue_repository = StrikeQueueRepository(bot.mdb["strike_queue"])
    gate_repository = GateRepository(bot.mdb["gate_list"])
    analytics_repository = AnalyticsRepository(bot.mdb)
    meta_repository = QueueMetaRepository(bot.mdb["queue_meta"])
    presentation_service = QueuePresentationService(bot=bot, meta_repository=meta_repository)

    player_queue_service = PlayerQueueService(
        bot=bot,
        config=config,
        queue_repository=queue_repository,
        gate_repository=gate_repository,
        analytics_repository=analytics_repository,
        presentation_service=presentation_service,
        view_factory=lambda: _player_queue_view(bot),
    )
    dm_queue_service = DMQueueService(
        bot=bot,
        config=config,
        dm_queue_repository=dm_queue_repository,
        queue_repository=queue_repository,
        analytics_repository=analytics_repository,
        presentation_service=presentation_service,
        view_factory=lambda: _dm_queue_view(bot),
    )
    strike_queue_service = StrikeQueueService(
        bot=bot,
        config=config,
        strike_queue_repository=strike_queue_repository,
        gate_repository=gate_repository,
        analytics_repository=analytics_repository,
        presentation_service=presentation_service,
        view_factory=lambda: _strike_queue_view(bot),
    )

    services = QueueServices(
        config=config,
        queue_repository=queue_repository,
        dm_queue_repository=dm_queue_repository,
        strike_queue_repository=strike_queue_repository,
        gate_repository=gate_repository,
        analytics_repository=analytics_repository,
        meta_repository=meta_repository,
        presentation_service=presentation_service,
        player_queue_service=player_queue_service,
        dm_queue_service=dm_queue_service,
        strike_queue_service=strike_queue_service,
    )
    setattr(bot, _SERVICE_CACHE_ATTR, services)
    return services
