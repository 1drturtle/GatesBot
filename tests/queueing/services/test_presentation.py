from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from queueing.repositories.meta import QueueMetaRepository
from queueing.services.presentation import QueuePresentationService, replace_persistent_message
from tests.helpers.builders import make_bot, make_group, make_member, make_player, make_queue, make_ready_entry
from tests.helpers.fakes import FakeChannel, FakeCollection, FakeGuild, FakeMessage


def make_service(*, marks: list[dict] | None = None, meta: FakeCollection | None = None) -> QueuePresentationService:
    bot = make_bot()
    bot.mdb["player_marked"] = FakeCollection(marks or [])
    bot.mdb["queue_meta"] = meta or FakeCollection()
    return QueuePresentationService(bot=bot, meta_repository=QueueMetaRepository(bot.mdb["queue_meta"]))


def test_build_player_queue_embed_sorts_groups_and_marks_players() -> None:
    alice = make_player(1, "Alice", level=5)
    bob = make_player(2, "Bob", level=1)
    queue = make_queue(make_group(alice), make_group(bob))
    service = make_service(marks=[{"_id": alice.member.id, "marked": True, "custom": "!"}])

    embed = asyncio.run(service.build_player_queue_embed(queue))

    assert embed.title == "Gate Sign-Up List"
    assert [field.name for field in embed.fields] == ["1. Rank 1", "2. Rank 2"]
    assert bob.mention in embed.fields[0].value
    assert f"{alice.mention}\\*!" in embed.fields[1].value


def test_build_player_queue_embed_shows_locked_queue_and_group() -> None:
    group = make_group(make_player(1, "Alice"), locked=True)
    queue = make_queue(group, locked=True)

    embed = asyncio.run(make_service().build_player_queue_embed(queue))

    assert embed.title == "Gate Sign-Up List 🔒"
    assert embed.fields[0].name.endswith("🔒")


def test_build_player_waitlist_embed_orders_by_wait_time_descending() -> None:
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 1, 2, tzinfo=timezone.utc)
    alice = make_player(1, "Alice")
    bob = make_player(2, "Bob")
    missing = make_player(3, "Missing")
    queue = make_queue(make_group(bob, missing, tier=2), make_group(alice, tier=1))
    service = make_service()

    embed = asyncio.run(
        service.build_player_waitlist_embed(queue, signup_times={alice.member.id: older, bob.member.id: newer})
    )

    assert embed.title == "Queue Waitlist"
    assert embed.description is not None
    assert embed.description.index(alice.mention) < embed.description.index(bob.mention)
    assert embed.description.index(bob.mention) < embed.description.index(missing.mention)
    assert "Group #2, Rank 1" in embed.description
    assert "unknown signup time" in embed.description


def test_build_dm_and_strike_embeds_skip_members_no_longer_in_guild() -> None:
    dm_member = make_member(10, "DM")
    strike_member = make_member(20, "Striker")
    guild = FakeGuild(1, members=[dm_member, strike_member])
    service = make_service()

    dm_embed = asyncio.run(
        service.build_dm_queue_embed(
            guild=guild,
            entries=[make_ready_entry(dm_member.id, "tier 3"), make_ready_entry(99, "gone")],
        )
    )
    strike_embed = asyncio.run(
        service.build_strike_queue_embed(
            guild=guild,
            entries=[make_ready_entry(strike_member.id, "ready"), make_ready_entry(98, "gone")],
        )
    )

    assert dm_embed.title == "DM Queue"
    assert dm_embed.description == f"**#1.** {dm_member.mention} - tier 3"
    assert strike_embed.title == "Strike Team Queue"
    assert strike_embed.description == f"**#1.** {strike_member.mention} - Ready"


def test_view_states_return_display_lines_for_available_members() -> None:
    alice = make_player(1, "Alice")
    dm_member = make_member(10, "DM")
    service = make_service()

    player_state = asyncio.run(service.player_view_state(make_queue(make_group(alice))))
    dm_state = asyncio.run(
        service.dm_view_state(guild=FakeGuild(1, members=[dm_member]), entries=[make_ready_entry(10, "tier 3")])
    )
    strike_state = asyncio.run(
        service.strike_view_state(guild=FakeGuild(1, members=[dm_member]), entries=[make_ready_entry(10, "ready")])
    )

    assert player_state.title == "Gate Sign-Up List"
    assert player_state.lines == ["1. Rank 2"]
    assert dm_state.lines == ["#1 DM - tier 3"]
    assert strike_state.lines == ["#1 DM - ready"]


def test_replace_persistent_message_deletes_existing_message_and_updates_meta() -> None:
    old_message = FakeMessage(42)
    channel = FakeChannel(1, fetched_messages={42: old_message})
    meta = FakeCollection([{"_id": "player_queue:1", "message_id": 42}])

    new_message = asyncio.run(
        replace_persistent_message(
            channel=channel,
            meta_db=meta,
            meta_key="player_queue:1",
            embed_title_prefix="Gate Sign-Up List",
            bot_user_id=999,
            embed=object(),
            view=object(),
        )
    )

    assert old_message.deleted is True
    assert new_message.id == 1
    assert meta.docs[0]["message_id"] == 1
    assert channel.sent[0]["embed"] is not None


def test_refresh_queue_message_builds_expected_meta_payload() -> None:
    channel = FakeChannel(1)
    service = make_service()

    result = asyncio.run(
        service.refresh_queue_message(
            channel=channel,
            meta_key="dm_queue:1",
            embed_title_prefix="DM Queue",
            embed=object(),
            view=object(),
        )
    )

    assert result.message_id == 1
    assert result.payload == {"meta_key": "dm_queue:1", "embed_title_prefix": "DM Queue"}


def test_send_gate_assignment_sends_group_info_then_dm_assignment() -> None:
    dm_member = make_member(10, "DM")
    bob = make_player(2, "Bob")
    alice = make_player(1, "Alice")
    guild = FakeGuild(1, members=[dm_member, alice.member, bob.member])
    channel = FakeChannel(1, guild=guild)
    service = make_service()

    asyncio.run(
        service.send_gate_assignment(
            group=make_group(bob, alice),
            group_number=4,
            dm_member=dm_member,
            assignment_channel=channel,
        )
    )

    assert len(channel.sent) == 2
    assert channel.sent[0]["embed"].title == "Information for Group #4"
    assert channel.sent[1]["content"] == dm_member.mention
    assert channel.sent[1]["embed"].title == "Gate Assignment"
