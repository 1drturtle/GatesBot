from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from queueing.config import QueueRuntimeConfig
from queueing.models import Group, Player, Queue
from queueing.repositories.ready_queue import ReadyQueueEntry
from queueing.services.dm_queue import DMQueueService
from queueing.services.player_queue import PlayerQueueService
from queueing.services.strike_queue import StrikeQueueService

from tests.helpers.fakes import (
    FakeMember,
    FakeRole,
    InMemoryGateRepository,
    InMemoryQueueRepository,
    InMemoryReadyQueueRepository,
)


def make_role(role_id: int = 1, name: str = "Player") -> FakeRole:
    return FakeRole(role_id, name)


def make_member(member_id: int = 1, name: str = "Member", *, roles: list[FakeRole] | None = None) -> FakeMember:
    return FakeMember(member_id, name, roles=roles)


def make_player(
    member_id: int = 1,
    name: str = "Player",
    *,
    level: int = 5,
    roles: list[FakeRole] | None = None,
) -> Player:
    return Player(
        member=make_member(member_id, name, roles=roles),
        _total_level=level,
        _levels=[{"class": "Fighter", "subclass": "None", "level": level}],
    )


def make_group(*players: Player, tier: int | None = None, position: int | None = None, locked: bool = False) -> Group:
    resolved_tier = tier if tier is not None else (players[0].tier if players else 1)
    group = Group.new(resolved_tier, list(players), position=position)
    group.locked = locked
    return group


def make_queue(*groups: Group, server_id: int = 1, channel_id: int | None = 2, locked: bool = False) -> Queue:
    return Queue(groups=list(groups), server_id=server_id, channel_id=channel_id, locked=locked)


def make_ready_entry(member_id: int = 1, text: str = "ready", message_id: int | None = 1) -> ReadyQueueEntry:
    return ReadyQueueEntry(member_id=member_id, text=text, message_id=message_id, ready_on=None)


def make_config(environment: str = "production") -> QueueRuntimeConfig:
    return QueueRuntimeConfig.from_environment(environment)


def make_analytics(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "record_player_signup": AsyncMock(),
        "get_last_player_signup_text": AsyncMock(return_value=None),
        "decrement_player_signup": AsyncMock(),
        "set_marked": AsyncMock(),
        "clear_marks_for_members": AsyncMock(),
        "mark_assignment_claimed": AsyncMock(),
        "record_dm_claim": AsyncMock(),
        "get_dm_info": AsyncMock(return_value={"dm_gates": [{"gate_name": "alpha"}]}),
        "record_gate_reinforcement": AsyncMock(),
        "record_player_gate_summon": AsyncMock(),
        "record_claimed_group": AsyncMock(),
        "set_unlock_timestamp": AsyncMock(),
        "record_dm_queue_signup": AsyncMock(),
        "record_dm_assignment": AsyncMock(),
        "increment_dm_assignments": AsyncMock(),
        "set_last_strike_gate": AsyncMock(),
        "record_strike_team_reinforcement": AsyncMock(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_bot(bot_id: int = 999) -> SimpleNamespace:
    user = SimpleNamespace(id=bot_id, name="GatesBot", display_avatar="https://example.test/bot.png")
    return SimpleNamespace(user=user, mdb={}, environment="testing", owner_id=bot_id)


def make_presentation(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "build_player_queue_embed": AsyncMock(return_value=SimpleNamespace(title="Gate Sign-Up List")),
        "build_dm_queue_embed": AsyncMock(return_value=SimpleNamespace(title="DM Queue")),
        "build_strike_queue_embed": AsyncMock(return_value=SimpleNamespace(title="Strike Team Queue")),
        "refresh_queue_message": AsyncMock(return_value=SimpleNamespace(message_id=1, payload={})),
        "send_gate_assignment": AsyncMock(),
        "dm_view_state": AsyncMock(return_value=SimpleNamespace(title="DM Queue", lines=[])),
        "strike_view_state": AsyncMock(return_value=SimpleNamespace(title="Strike Team Queue", lines=[])),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_player_service(
    queue: Queue,
    *,
    testing: bool = False,
    gate: dict[str, Any] | None = None,
    analytics: SimpleNamespace | None = None,
    presentation: SimpleNamespace | None = None,
) -> tuple[PlayerQueueService, InMemoryQueueRepository, SimpleNamespace, SimpleNamespace]:
    service = PlayerQueueService(
        bot=make_bot(),
        config=make_config("testing" if testing else "production"),
        queue_repository=InMemoryQueueRepository(queue),
        gate_repository=InMemoryGateRepository(gate),
        analytics_repository=analytics or make_analytics(),
        presentation_service=presentation or make_presentation(),
    )
    service.refresh_queue_message = AsyncMock()
    return service, service.queue_repository, service.analytics_repository, service.presentation_service


def make_dm_service(
    queue: Queue,
    *,
    entries: list[ReadyQueueEntry] | None = None,
    analytics: SimpleNamespace | None = None,
    presentation: SimpleNamespace | None = None,
) -> tuple[DMQueueService, InMemoryReadyQueueRepository, InMemoryQueueRepository, SimpleNamespace, SimpleNamespace]:
    service = DMQueueService(
        bot=make_bot(),
        config=make_config(),
        dm_queue_repository=InMemoryReadyQueueRepository(entries),
        queue_repository=InMemoryQueueRepository(queue),
        analytics_repository=analytics or make_analytics(),
        presentation_service=presentation or make_presentation(),
    )
    service.refresh_queue_message = AsyncMock()
    return (
        service,
        service.dm_queue_repository,
        service.queue_repository,
        service.analytics_repository,
        service.presentation_service,
    )


def make_strike_service(
    *,
    entries: list[ReadyQueueEntry] | None = None,
    gates: list[dict[str, Any]] | dict[str, Any] | None = None,
    analytics: SimpleNamespace | None = None,
    presentation: SimpleNamespace | None = None,
) -> tuple[StrikeQueueService, InMemoryReadyQueueRepository, InMemoryGateRepository, SimpleNamespace, SimpleNamespace]:
    service = StrikeQueueService(
        bot=make_bot(),
        config=make_config(),
        strike_queue_repository=InMemoryReadyQueueRepository(entries),
        gate_repository=InMemoryGateRepository(gates),
        analytics_repository=analytics or make_analytics(),
        presentation_service=presentation or make_presentation(),
    )
    service.refresh_queue_message = AsyncMock()
    return (
        service,
        service.strike_queue_repository,
        service.gate_repository,
        service.analytics_repository,
        service.presentation_service,
    )
