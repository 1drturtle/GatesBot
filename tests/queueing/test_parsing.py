from __future__ import annotations

import asyncio

import pytest

from queueing.parsing import check_level_role, length_check, parse_player_class
from tests.helpers.builders import make_player, make_role


def test_parse_player_class_handles_multiclass_strings() -> None:
    parsed = parse_player_class("Battle Master Fighter 5 / Wizard 3")

    assert parsed["total_level"] == 8
    assert parsed["classes"][0] == {"class": "Fighter", "subclass": "Battle Master", "level": 5}
    assert parsed["classes"][1] == {"class": "Wizard", "subclass": "None", "level": 3}


@pytest.mark.parametrize(
    ("group_length", "requested_length", "expected"),
    [
        (0, 1, "No groups available"),
        (1, 2, "Only one group"),
        (3, 0, "between 1 and 3"),
        (3, 4, "between 1 and 3"),
        (3, 2, None),
    ],
)
def test_length_check_reports_actionable_bounds(
    group_length: int,
    requested_length: int,
    expected: str | None,
) -> None:
    result = length_check(group_length, requested_length)

    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert expected in result


def test_check_level_role_allows_matching_level_role() -> None:
    player = make_player(1, roles=[make_role(1, "Level 5")], level=5)

    assert asyncio.run(check_level_role(player)) is None
    assert player.member.sent_dms == []


def test_check_level_role_messages_member_with_missing_level_role() -> None:
    player = make_player(1, roles=[make_role(1, "Player")], level=5)

    asyncio.run(check_level_role(player))

    assert "do not have a level role" in player.member.sent_dms[0]


def test_check_level_role_messages_member_with_wrong_level_role() -> None:
    player = make_player(1, roles=[make_role(1, "Level 4")], level=5)

    asyncio.run(check_level_role(player))

    assert "Level 4" in player.member.sent_dms[0]
    assert "Level 5" in player.member.sent_dms[0]
