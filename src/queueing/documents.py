from __future__ import annotations

from datetime import datetime
from typing import TypedDict


ClassLevelDocument = TypedDict(
    "ClassLevelDocument",
    {
        "class": str,
        "subclass": str,
        "level": int,
    },
)


class ParsedPlayerClassDocument(TypedDict):
    total_level: int
    classes: list[ClassLevelDocument]


class PlayerDocument(TypedDict):
    total_level: int
    classes: list[ClassLevelDocument]
    member_id: int


class GroupDocument(TypedDict, total=False):
    players: list[PlayerDocument]
    tier: int
    position: int | None
    locked: bool
    assigned: int | None


class GateDocument(GroupDocument, total=False):
    gate_name: str
    claimed_date: datetime


class QueueDocument(TypedDict):
    groups: list[GroupDocument]
    server_id: int
    channel_id: int | None
    locked: bool
