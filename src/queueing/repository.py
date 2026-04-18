from __future__ import annotations

from typing import Any, TypeVar

import discord

from queueing.documents import QueueDocument
from queueing.models import Queue

QueueType = TypeVar("QueueType", bound=Queue)


def build_empty_queue_document(guild_id: int) -> QueueDocument:
    return {
        "groups": [],
        "server_id": guild_id,
        "channel_id": None,
        "locked": False,
    }


async def load_queue_for_guild(
    db: Any,
    guild: discord.Guild,
    *,
    queue_type: type[QueueType] = Queue,
) -> QueueType:
    queue_data = await db.find_one({"guild_id": guild.id})
    raw_document = queue_data or build_empty_queue_document(guild.id)
    queue = queue_type.from_dict(guild, raw_document)
    queue.groups.sort(key=lambda group: group.tier)
    return queue
