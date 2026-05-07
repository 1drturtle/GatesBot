from __future__ import annotations

from datetime import datetime
from typing import Any, NotRequired, TypedDict

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


class RegisteredGateDocument(TypedDict):
    name: str
    emoji: str
    _id: NotRequired[Any]
    owner: NotRequired[int]


class DMAnalyticsDocument(TypedDict, total=False):
    _id: int
    dm_gates: list[GateDocument]


class QueueDocument(TypedDict):
    groups: list[GroupDocument]
    server_id: int
    channel_id: int | None
    locked: bool


class StoredQueueDocument(TypedDict, total=False):
    groups: list[GroupDocument]
    server_id: int
    guild_id: int
    channel_id: int | None
    locked: bool
