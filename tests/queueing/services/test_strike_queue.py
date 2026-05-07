from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from queueing.services.strike_queue import StrikeQueueService
from tests.helpers.builders import (
    make_analytics,
    make_bot,
    make_member,
    make_presentation,
    make_ready_entry,
    make_strike_service,
)
from tests.helpers.fakes import FakeChannel, FakeGuild, InMemoryGateRepository, InMemoryReadyQueueRepository


def test_signup_update_and_leave_mutate_repository_and_refresh() -> None:
    member = make_member(10, "Striker")
    service, repo, _, _, _ = make_strike_service(entries=[make_ready_entry(10, "old")])
    message = SimpleNamespace(author=member, guild=FakeGuild(1, members=[member]), id=99)

    signup = asyncio.run(service.signup_from_message(message=message, text="ready"))
    update = asyncio.run(service.update_member(guild=FakeGuild(1), member_id=10, text="new"))
    leave = asyncio.run(service.leave_member(guild=FakeGuild(1), member_id=10))

    assert signup.success is True
    assert update.success is True
    assert leave.success is True
    assert repo.entries == []
    assert service.refresh_queue_message.await_count == 3


def test_leave_member_reports_missing_entry_without_refresh() -> None:
    service, _, _, _, _ = make_strike_service()

    result = asyncio.run(service.leave_member(guild=FakeGuild(1), member_id=10))

    assert result.success is False
    service.refresh_queue_message.assert_not_awaited()


@pytest.mark.parametrize(
    ("entries", "queue_numbers", "gate", "expected"),
    [
        ([], [1], {"name": "alpha", "emoji": ":a:"}, "No Strike Team members"),
        ([make_ready_entry(10)], [2], {"name": "alpha", "emoji": ":a:"}, "Invalid Strike Team Queue number"),
        ([make_ready_entry(10)], [1], None, "does not exist"),
    ],
)
def test_assign_strike_team_validates_entries_numbers_and_gate(entries, queue_numbers, gate, expected: str) -> None:
    service, _, _, analytics, _ = make_strike_service(entries=entries, gates=gate)

    result = asyncio.run(
        service.assign_strike_team(
            guild=FakeGuild(1, members=[make_member(10, "Striker")]),
            queue_numbers=queue_numbers,
            gate_name="alpha",
        )
    )

    assert result.success is False
    assert expected in result.message
    analytics.set_last_strike_gate.assert_not_awaited()


def test_assign_strike_team_rejects_unavailable_people_and_missing_channel() -> None:
    gate = {"name": "alpha", "emoji": ":a:"}
    missing_people_service, _, _, _, _ = make_strike_service(entries=[make_ready_entry(10)], gates=gate)
    missing_channel_service, _, _, _, _ = make_strike_service(entries=[make_ready_entry(10)], gates=gate)

    missing_people = asyncio.run(
        missing_people_service.assign_strike_team(
            guild=FakeGuild(1),
            queue_numbers=[1],
            gate_name="alpha",
        )
    )
    missing_channel = asyncio.run(
        missing_channel_service.assign_strike_team(
            guild=FakeGuild(1, members=[make_member(10, "Striker")]),
            queue_numbers=[1],
            gate_name="alpha",
        )
    )

    assert missing_people.success is False
    assert "No selected Strike Team members" in missing_people.message
    assert missing_channel.success is False
    assert "channel not found" in missing_channel.message


def test_assign_strike_team_sends_message_removes_entries_and_records_analytics() -> None:
    member = make_member(10, "Striker")
    gate = {"name": "alpha", "emoji": ":a:", "owner": 99}
    analytics = make_analytics(
        get_dm_info=AsyncMock(return_value={"dm_gates": [{"gate_name": "alpha"}]}),
    )
    service, repo, _, _, _ = make_strike_service(entries=[make_ready_entry(member.id)], gates=gate, analytics=analytics)
    assignment_channel = FakeChannel(service.config.strike_queue_assignment_channel_id)
    guild = FakeGuild(1, members=[member], channels=[assignment_channel])

    result = asyncio.run(service.assign_strike_team(guild=guild, queue_numbers=[1], gate_name="alpha"))

    assert result.success is True
    assert result.assigned_member_id == member.id
    assert repo.entries == []
    assert member.mention in assignment_channel.sent[0]["content"]
    analytics.set_last_strike_gate.assert_awaited_once_with(member.id, "alpha")
    analytics.record_strike_team_reinforcement.assert_awaited_once()
    service.refresh_queue_message.assert_awaited_once()


def test_queue_view_state_delegates_to_presentation() -> None:
    entries = [make_ready_entry(10)]
    service, _, _, _, presentation = make_strike_service(entries=entries)
    guild = FakeGuild(1, members=[make_member(10, "Striker")])

    result = asyncio.run(service.queue_view_state(guild))

    assert result.title == "Strike Team Queue"
    presentation.strike_view_state.assert_awaited_once_with(guild=guild, entries=entries)


def test_refresh_queue_message_raises_when_channel_missing() -> None:
    service = StrikeQueueService(
        bot=make_bot(),
        config=make_strike_service()[0].config,
        strike_queue_repository=InMemoryReadyQueueRepository(),
        gate_repository=InMemoryGateRepository(),
        analytics_repository=make_analytics(),
        presentation_service=make_presentation(),
        view_factory=object,
    )

    with pytest.raises(ValueError, match="Strike queue channel not found"):
        asyncio.run(service.refresh_queue_message(guild=FakeGuild(1)))
