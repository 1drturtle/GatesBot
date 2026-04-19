from __future__ import annotations

import pytest

from common.constants import GROUP_SIZE, ROLE_MARKERS
from queueing.models import Group, Player, Queue, QueueException, parse_tier_from_total
from tests.helpers.builders import make_group, make_member, make_player, make_queue, make_role
from tests.helpers.fakes import FakeGuild


@pytest.mark.parametrize(
    ("total_level", "tier"),
    [(1, 1), (4, 1), (5, 2), (8, 3), (11, 4), (14, 5), (17, 6), (20, 7)],
)
def test_parse_tier_from_total_uses_expected_breakpoints(total_level: int, tier: int) -> None:
    assert parse_tier_from_total(total_level) == tier


def test_player_new_requires_total_level() -> None:
    with pytest.raises(QueueException, match="No total level"):
        Player.new(make_member(), {"classes": []})


def test_queue_serialization_round_trip_preserves_groups_and_skips_missing_members() -> None:
    alice = make_member(1, "Alice")
    missing = make_member(2, "Missing")
    guild = FakeGuild(123, members=[alice])
    group = make_group(
        Player(alice, 5, [{"class": "Fighter", "subclass": "None", "level": 5}]),
        Player(missing, 8, [{"class": "Wizard", "subclass": "None", "level": 8}]),
        position=3,
    )
    queue = make_queue(group, server_id=123, channel_id=456, locked=True)

    rebuilt = Queue.from_dict(guild, queue.to_dict())

    assert rebuilt.server_id == 123
    assert rebuilt.channel_id == 456
    assert rebuilt.locked is True
    assert len(rebuilt.groups) == 1
    assert [player.member.display_name for player in rebuilt.groups[0].players] == ["Alice"]
    assert "Alice" in rebuilt.groups[0].player_levels_str


def test_group_player_levels_include_role_markers() -> None:
    marker_role_id = next(iter(ROLE_MARKERS))
    player = make_player(1, "Alice", roles=[make_role(marker_role_id, "Assistant")])

    assert f"[{ROLE_MARKERS[marker_role_id]}]" in make_group(player).player_levels_str


def test_queue_group_fit_respects_tier_size_and_lock() -> None:
    alice = make_player(1, "Alice", level=5)
    bob = make_player(2, "Bob", level=5)
    locked_group = make_group(tier=bob.tier, locked=True)
    queue = make_queue(make_group(alice), locked_group)

    assert queue.in_queue(alice.member.id) == (0, 0)
    assert queue.can_fit_in_group(bob) == 0

    queue.groups[0].players = [alice] * GROUP_SIZE
    assert queue.can_fit_in_group(bob) is None


def test_group_from_dict_infers_tier_from_players_when_legacy_document_omits_tier() -> None:
    player = make_player(1, "Alice", level=8)
    guild = FakeGuild(1, members=[player.member])
    raw_group = {"players": [player.to_dict()], "position": 2, "locked": True, "assigned": 99}

    group = Group.from_dict(guild, raw_group)

    assert group.tier == player.tier
    assert group.position == 2
    assert group.locked is True
    assert group.assigned == 99
