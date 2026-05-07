from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from queueing.services.dm_queue import DMQueueService
from tests.helpers.builders import (
    make_analytics,
    make_bot,
    make_dm_service,
    make_group,
    make_member,
    make_player,
    make_presentation,
    make_queue,
    make_ready_entry,
)
from tests.helpers.fakes import FakeChannel, FakeGuild, InMemoryQueueRepository, InMemoryReadyQueueRepository


def test_signup_upserts_entry_records_analytics_and_refreshes() -> None:
    member = make_member(10, "DM")
    queue = make_queue()
    service, dm_repo, _, analytics, _ = make_dm_service(queue)
    message = SimpleNamespace(author=member, guild=FakeGuild(1, members=[member]), id=99)

    result = asyncio.run(service.signup_from_message(message=message, text="tier 3"))

    assert result.success is True
    assert dm_repo.upserts == [{"member_id": 10, "text": "tier 3", "message_id": 99}]
    analytics.record_dm_queue_signup.assert_awaited_once_with(10, delta=1)
    service.refresh_queue_message.assert_awaited_once()


def test_update_member_changes_text_and_refreshes() -> None:
    queue = make_queue()
    service, dm_repo, _, _, _ = make_dm_service(queue, entries=[make_ready_entry(10, "old")])

    result = asyncio.run(service.update_member(guild=FakeGuild(1), member_id=10, text="new"))

    assert result.success is True
    assert dm_repo.entries[0].text == "new"
    service.refresh_queue_message.assert_awaited_once()


def test_leave_member_removes_entry_and_optionally_adjusts_analytics() -> None:
    queue = make_queue()
    service, dm_repo, _, analytics, _ = make_dm_service(queue, entries=[make_ready_entry(10)])

    result = asyncio.run(service.leave_member(guild=FakeGuild(1), member_id=10, adjust_signup_count=True))

    assert result.success is True
    assert dm_repo.entries == []
    analytics.record_dm_queue_signup.assert_awaited_once_with(10, delta=-1)


def test_leave_member_reports_missing_entry_without_refresh() -> None:
    service, _, _, analytics, _ = make_dm_service(make_queue())

    result = asyncio.run(service.leave_member(guild=FakeGuild(1), member_id=10, adjust_signup_count=True))

    assert result.success is False
    analytics.record_dm_queue_signup.assert_not_awaited()
    service.refresh_queue_message.assert_not_awaited()


@pytest.mark.parametrize(
    ("queue_number", "dm_member_id", "expected"),
    [
        (2, None, "Invalid DM Queue number"),
        (None, 99, "Selected DM is not currently in queue"),
        (None, None, "No DM selection"),
    ],
)
def test_assign_dm_to_group_validates_selection(
    queue_number: int | None,
    dm_member_id: int | None,
    expected: str,
) -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    service, _, _, _, presentation = make_dm_service(queue, entries=[make_ready_entry(10)])

    result = asyncio.run(
        service.assign_dm_to_group(
            guild=FakeGuild(1, members=[player.member]),
            summoner=make_member(20, "Assistant"),
            group_number=1,
            queue_number=queue_number,
            dm_member_id=dm_member_id,
        )
    )

    assert result.success is False
    assert expected in result.message
    presentation.send_gate_assignment.assert_not_awaited()


def test_assign_dm_to_group_rejects_missing_member_and_invalid_group() -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    service, _, _, _, _ = make_dm_service(queue, entries=[make_ready_entry(10)])
    guild_without_dm = FakeGuild(1, members=[player.member])
    guild_with_dm = FakeGuild(1, members=[player.member, make_member(10, "DM")])

    missing_member = asyncio.run(
        service.assign_dm_to_group(
            guild=guild_without_dm,
            summoner=make_member(20, "Assistant"),
            group_number=1,
            queue_number=1,
        )
    )
    invalid_group = asyncio.run(
        service.assign_dm_to_group(
            guild=guild_with_dm,
            summoner=make_member(20, "Assistant"),
            group_number=2,
            queue_number=1,
        )
    )

    assert missing_member.success is False
    assert "no longer in this server" in missing_member.message
    assert invalid_group.success is False
    assert "Invalid Group Number" in invalid_group.message


def test_assign_dm_to_group_rejects_reassignment_when_disabled() -> None:
    dm_member = make_member(10, "DM")
    player = make_player(1, "Alice")
    group = make_group(player)
    group.assigned = 11
    service, _, _, _, presentation = make_dm_service(make_queue(group), entries=[make_ready_entry(dm_member.id)])

    result = asyncio.run(
        service.assign_dm_to_group(
            guild=FakeGuild(1, members=[dm_member, player.member]),
            summoner=make_member(20, "Assistant"),
            group_number=1,
            queue_number=1,
            allow_reassignment=False,
        )
    )

    assert result.success is False
    assert "already assigned" in result.message
    presentation.send_gate_assignment.assert_not_awaited()


def test_assign_dm_to_group_rejects_missing_assignment_channel_after_saving_assignment() -> None:
    dm_member = make_member(10, "DM")
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    service, dm_repo, queue_repo, analytics, presentation = make_dm_service(
        queue,
        entries=[make_ready_entry(dm_member.id)],
    )

    result = asyncio.run(
        service.assign_dm_to_group(
            guild=FakeGuild(1, members=[dm_member, player.member]),
            summoner=make_member(20, "Assistant"),
            group_number=1,
            queue_number=1,
        )
    )

    assert result.success is False
    assert "channel not found" in result.message
    assert queue.groups[0].assigned == dm_member.id
    assert queue_repo.saved[-1] is queue
    assert dm_repo.entries == [make_ready_entry(dm_member.id)]
    analytics.record_dm_assignment.assert_not_awaited()
    presentation.send_gate_assignment.assert_not_awaited()


def test_assign_dm_to_group_successfully_assigns_and_removes_dm() -> None:
    dm_member = make_member(10, "DM")
    summoner = make_member(20, "Assistant")
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    service, dm_repo, queue_repo, analytics, presentation = make_dm_service(
        queue,
        entries=[make_ready_entry(dm_member.id)],
    )
    assignment_channel = FakeChannel(service.config.dm_queue_assignment_channel_id)
    guild = FakeGuild(1, members=[dm_member, summoner, player.member], channels=[assignment_channel])

    result = asyncio.run(
        service.assign_dm_to_group(
            guild=guild,
            summoner=summoner,
            group_number=1,
            dm_member_id=dm_member.id,
        )
    )

    assert result.success is True
    assert result.assigned_member_id == dm_member.id
    assert queue.groups[0].assigned == dm_member.id
    assert dm_repo.entries == []
    assert queue_repo.saved[-1] is queue
    presentation.send_gate_assignment.assert_awaited_once()
    analytics.record_dm_assignment.assert_awaited_once()
    analytics.increment_dm_assignments.assert_awaited_once_with(dm_member.id)


def test_queue_view_state_delegates_to_presentation() -> None:
    entries = [make_ready_entry(10)]
    service, _, _, _, presentation = make_dm_service(make_queue(), entries=entries)
    guild = FakeGuild(1, members=[make_member(10, "DM")])

    result = asyncio.run(service.queue_view_state(guild))

    assert result.title == "DM Queue"
    presentation.dm_view_state.assert_awaited_once_with(guild=guild, entries=entries)


def test_refresh_queue_message_raises_when_channel_missing() -> None:
    service = DMQueueService(
        bot=make_bot(),
        config=make_dm_service(make_queue())[0].config,
        dm_queue_repository=InMemoryReadyQueueRepository(),
        queue_repository=InMemoryQueueRepository(make_queue()),
        analytics_repository=make_analytics(),
        presentation_service=make_presentation(),
        view_factory=object,
    )

    with pytest.raises(ValueError, match="DM queue channel not found"):
        asyncio.run(service.refresh_queue_message(guild=FakeGuild(1)))
