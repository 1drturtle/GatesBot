from __future__ import annotations

import asyncio
from types import SimpleNamespace

from queueing.config import QueueRuntimeConfig
from queueing.services.player_queue import PlayerQueueService
from tests.helpers.builders import (
    make_analytics,
    make_bot,
    make_group,
    make_member,
    make_player,
    make_player_service,
    make_presentation,
    make_queue,
    make_role,
)
from tests.helpers.fakes import (
    FakeChannel,
    FakeEmbed,
    FakeGuild,
    FakeMessage,
    InMemoryGateRepository,
    InMemoryQueueRepository,
)


def test_signup_prefers_existing_group_and_records_analytics() -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(tier=player.tier))
    service, _, analytics, _ = make_player_service(queue, testing=False)
    message = SimpleNamespace(guild=FakeGuild(1, members=[player.member]), author=player.member, id=10)

    result = asyncio.run(service.signup_from_message(message=message, player=player, view_factory=object))

    assert result.success is True
    assert result.group_number == 1
    assert queue.groups[0].players == [player]
    analytics.record_player_signup.assert_awaited_once()
    service.refresh_queue_message.assert_awaited_once()


def test_signup_blocks_duplicates_outside_testing_but_allows_in_testing() -> None:
    player = make_player(1, "Alice")
    production_queue = make_queue(make_group(player))
    testing_queue = make_queue(make_group(player))
    production_service, _, production_analytics, _ = make_player_service(production_queue, testing=False)
    testing_service, _, testing_analytics, _ = make_player_service(testing_queue, testing=True)
    message = SimpleNamespace(guild=FakeGuild(1, members=[player.member]), author=player.member, id=10)

    blocked = asyncio.run(production_service.signup_from_message(message=message, player=player, view_factory=object))
    allowed = asyncio.run(testing_service.signup_from_message(message=message, player=player, view_factory=object))

    assert blocked.success is False
    assert blocked.should_delete_source_message is True
    production_analytics.record_player_signup.assert_not_awaited()
    assert allowed.success is True
    assert len(testing_queue.groups[0].players) == 2
    testing_analytics.record_player_signup.assert_awaited_once()


def test_leave_member_removes_player_and_optionally_updates_analytics() -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    service, queue_repo, analytics, _ = make_player_service(queue)

    result = asyncio.run(
        service.leave_member(
            guild=FakeGuild(1, members=[player.member]),
            member_id=player.member.id,
            view_factory=object,
            decrement_signup_count=True,
            clear_marked=True,
        )
    )

    assert result.success is True
    assert queue.groups[0].players == []
    assert queue_repo.saved[-1] is queue
    analytics.decrement_player_signup.assert_awaited_once_with(player.member.id)
    analytics.set_marked.assert_awaited_once_with(player.member.id, marked=False)


def test_leave_member_reports_missing_player_without_saving() -> None:
    service, queue_repo, _, _ = make_player_service(make_queue())

    result = asyncio.run(
        service.leave_member(
            guild=FakeGuild(1),
            member_id=999,
            view_factory=object,
            decrement_signup_count=True,
            clear_marked=True,
        )
    )

    assert result.success is False
    assert queue_repo.saved == []


def test_move_member_validates_groups_and_moves_player() -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player), make_group(tier=player.tier))
    service, queue_repo, _, _ = make_player_service(queue)

    result = asyncio.run(
        service.move_member(
            guild=FakeGuild(1, members=[player.member]),
            original_group=1,
            member_id=player.member.id,
            new_group=2,
            view_factory=object,
        )
    )

    assert result.success is True
    assert queue.groups[0].players == []
    assert queue.groups[1].players == [player]
    assert queue_repo.saved[-1] is queue


def test_merge_groups_combines_second_group_into_first() -> None:
    alice = make_player(1, "Alice")
    bob = make_player(2, "Bob")
    queue = make_queue(make_group(alice), make_group(bob))
    service, _, _, _ = make_player_service(queue)

    result = asyncio.run(service.merge_groups(guild=FakeGuild(1), group_1=1, group_2=2, view_factory=object))

    assert result.success is True
    assert len(queue.groups) == 1
    assert queue.groups[0].players == [alice, bob]


def test_create_group_from_member_moves_player_after_current_group() -> None:
    alice = make_player(1, "Alice")
    bob = make_player(2, "Bob")
    queue = make_queue(make_group(alice, bob))
    service, _, _, _ = make_player_service(queue)

    result = asyncio.run(
        service.create_group_from_member(
            guild=FakeGuild(1, members=[alice.member, bob.member]),
            member_id=bob.member.id,
            view_factory=object,
        )
    )

    assert result.success is True
    assert [group.players for group in queue.groups] == [[alice], [bob]]


def test_shuffle_groups_preserves_locked_groups_and_repacks_selected_tier(monkeypatch) -> None:
    alice = make_player(1, "Alice")
    bob = make_player(2, "Bob")
    cara = make_player(3, "Cara")
    locked = make_group(cara, locked=True)
    queue = make_queue(make_group(alice), make_group(bob), locked)
    service, _, _, _ = make_player_service(queue)
    monkeypatch.setattr("queueing.services.player_queue.random.sample", lambda items, count: list(reversed(items)))

    result = asyncio.run(service.shuffle_groups(guild=FakeGuild(1), tier=alice.tier, group_size=2, view_factory=object))

    assert result.success is True
    assert queue.groups[0] is locked
    assert [player.member.display_name for player in queue.groups[1].players] == ["Bob", "Alice"]


def test_claim_group_handles_invalid_gate_and_successful_command_path() -> None:
    dm = make_member(10, "DM")
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    summons = FakeChannel(QueueRuntimeConfig.from_environment("production").summons_channel_id)
    assignments = FakeChannel(QueueRuntimeConfig.from_environment("production").gate_assignments_channel_id)
    guild = FakeGuild(1, members=[dm, player.member], channels=[summons, assignments])
    service, _, analytics, _ = make_player_service(queue, gate={"name": "alpha", "emoji": ":a:", "owner": dm.id})

    invalid = asyncio.run(
        service.claim_group(guild=guild, claimant=dm, gate_name="missing", group_number=1, view_factory=object)
    )
    valid = asyncio.run(
        service.claim_group(guild=guild, claimant=dm, gate_name="alpha", group_number=1, view_factory=object)
    )

    assert invalid.success is False
    assert valid.success is True
    assert valid.claimed_group_number == 1
    assert queue.groups == []
    assert summons.sent[0]["content"].startswith(player.mention)
    analytics.record_dm_claim.assert_awaited_once()
    analytics.record_player_gate_summon.assert_awaited_once_with(
        member_id=player.member.id,
        gate_name="alpha",
        total_level=player.total_level,
    )


def test_claim_group_can_use_existing_assignment() -> None:
    dm = make_member(10, "DM")
    player = make_player(1, "Alice")
    group = make_group(player)
    group.assigned = dm.id
    queue = make_queue(group)
    config = QueueRuntimeConfig.from_environment("production")
    guild = FakeGuild(1, members=[dm, player.member], channels=[FakeChannel(config.summons_channel_id)])
    service, _, _, _ = make_player_service(queue, gate={"name": "alpha", "emoji": ":a:", "owner": dm.id})

    result = asyncio.run(service.claim_group(guild=guild, claimant=dm, use_assignment=True, view_factory=object))

    assert result.success is True
    assert result.claimed_group_number == 1


def test_refresh_queue_message_removes_empty_groups_and_refreshes_persistent_message() -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(), make_group(player))
    config = QueueRuntimeConfig.from_environment("production")
    channel = FakeChannel(config.player_queue_channel_id)
    guild = FakeGuild(1, members=[player.member], channels=[channel])
    queue_repo = InMemoryQueueRepository(queue)
    presentation = make_presentation()
    service = PlayerQueueService(
        bot=make_bot(),
        config=config,
        queue_repository=queue_repo,
        gate_repository=InMemoryGateRepository(),
        analytics_repository=make_analytics(),
        presentation_service=presentation,
    )

    result = asyncio.run(service.refresh_queue_message(guild=guild, queue=queue, view_factory=object))

    assert result.message_id == 1
    assert queue.groups == [queue.groups[0]]
    assert queue.groups[0].players == [player]
    presentation.build_player_queue_embed.assert_awaited_once_with(queue)
    presentation.refresh_queue_message.assert_awaited_once()


def test_toggle_group_lock_flips_group_state() -> None:
    queue = make_queue(make_group(make_player(1, "Alice")))
    service, _, _, _ = make_player_service(queue)

    locked = asyncio.run(service.toggle_group_lock(guild=FakeGuild(1), group_number=1, view_factory=object))
    unlocked = asyncio.run(service.toggle_group_lock(guild=FakeGuild(1), group_number=1, view_factory=object))

    assert locked.is_locked is True
    assert unlocked.is_locked is False


def test_toggle_queue_lock_updates_channel_permissions_and_queue_state() -> None:
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player))
    service, queue_repo, _, _ = make_player_service(queue)
    player_role = make_role(1, "Player")
    channel = FakeChannel(service.config.player_queue_channel_id)
    guild = FakeGuild(1, members=[player.member], channels=[channel], roles=[player_role])

    result = asyncio.run(
        service.toggle_queue_lock(
            guild=guild,
            actor=make_member(2, "Assistant"),
            queue_channel=channel,
            player_role=player_role,
            should_lock=True,
            reason="maintenance",
            view_factory=object,
            send_announcement=False,
        )
    )

    assert result.success is True
    assert result.is_locked is True
    assert queue.locked is True
    assert channel.edits
    assert channel.sent[0]["embed"].title == "Queue Channel Locked"
    assert queue_repo.saved[-1] is queue


def test_toggle_queue_unlock_marks_players_and_removes_lock_notice() -> None:
    bot_message = FakeMessage(1, author=make_member(999, "Bot"), embeds=[FakeEmbed("Queue Channel Locked")])
    player = make_player(1, "Alice")
    queue = make_queue(make_group(player), locked=True)
    service, _, analytics, _ = make_player_service(queue)
    channel = FakeChannel(service.config.player_queue_channel_id, history_messages=[bot_message])
    guild = FakeGuild(1, members=[player.member], channels=[channel])

    result = asyncio.run(
        service.toggle_queue_lock(
            guild=guild,
            actor=make_member(2, "Assistant"),
            queue_channel=channel,
            player_role=make_role(1, "Player"),
            should_lock=False,
            reason=None,
            view_factory=object,
            send_announcement=False,
        )
    )

    assert result.is_locked is False
    assert queue.locked is False
    assert bot_message.deleted is True
    analytics.set_unlock_timestamp.assert_awaited_once()
    analytics.set_marked.assert_awaited_once_with(player.member.id, marked=True)
