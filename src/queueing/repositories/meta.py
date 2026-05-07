from __future__ import annotations

import disnake as discord
from pymongo.asynchronous.collection import AsyncCollection

from common.discord_utils import find_or_migrate_queue_message_id


class QueueMetaRepository:
    def __init__(self, collection: AsyncCollection):
        self.collection = collection

    async def get_message_id(self, key: str) -> int | None:
        meta = await self.collection.find_one({"_id": key}) or {}
        message_id = meta.get("message_id")
        if message_id is None:
            return None
        return int(message_id)

    async def set_message_id(self, key: str, message_id: int) -> None:
        await self.collection.update_one(
            {"_id": key},
            {"$set": {"message_id": message_id}},
            upsert=True,
        )

    async def resolve_message_id(
        self,
        *,
        channel: discord.TextChannel,
        meta_key: str,
        embed_title_prefix: str,
        bot_user_id: int,
    ) -> int | None:
        return await find_or_migrate_queue_message_id(
            channel=channel,
            meta_db=self.collection,
            meta_key=meta_key,
            embed_title_prefix=embed_title_prefix,
            bot_user_id=bot_user_id,
        )
