from __future__ import annotations

from typing import Any


class GateRepository:
    def __init__(self, collection: Any):
        self.collection = collection

    async def list_gates(self) -> list[dict[str, Any]]:
        return await self.collection.find().to_list(length=None)

    async def get_by_name(self, gate_name: str) -> dict[str, Any] | None:
        return await self.collection.find_one({"name": gate_name.lower()})

    async def get_by_owner(self, owner_id: int) -> dict[str, Any] | None:
        return await self.collection.find_one({"owner": owner_id})

    async def set_owner(self, gate_name: str, owner_id: int) -> None:
        await self.collection.update_one(
            {"name": gate_name.lower()},
            {"$set": {"owner": owner_id}},
            upsert=False,
        )

    async def upsert_gate(self, gate_name: str, gate_emoji: str) -> None:
        await self.collection.update_one(
            {"name": gate_name.lower()},
            {"$set": {"name": gate_name.lower(), "emoji": gate_emoji}},
            upsert=True,
        )

    async def remove_gate(self, gate_name: str) -> None:
        await self.collection.delete_one({"name": gate_name.lower()})
