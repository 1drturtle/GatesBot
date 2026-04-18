from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class QueueViewState:
    title: str
    description: str = ""
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SignupResult:
    success: bool
    message: str
    queue_updated: bool = False
    group_number: int | None = None
    should_delete_source_message: bool = False


@dataclass(slots=True)
class LeaveResult:
    success: bool
    message: str
    queue_updated: bool = False
    group_number: int | None = None


@dataclass(slots=True)
class ClaimResult:
    success: bool
    message: str
    queue_updated: bool = False
    claimed_group_number: int | None = None
    summoned_mentions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AssignResult:
    success: bool
    message: str
    queue_updated: bool = False
    queue_state: QueueViewState | None = None
    assigned_member_id: int | None = None


@dataclass(slots=True)
class LockResult:
    success: bool
    message: str
    queue_updated: bool = False
    is_locked: bool | None = None


@dataclass(slots=True)
class QueueRefreshResult:
    message_id: int
    payload: dict[str, Any]
