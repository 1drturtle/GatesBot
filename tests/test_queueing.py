from __future__ import annotations

from common.constants import GROUP_SIZE, ROLE_MARKERS
from queueing.documents import ClassLevelDocument
from queueing.models import Group, Player, Queue, parse_tier_from_total
from queueing.parsing import parse_player_class


class FakeRole:
    def __init__(self, role_id: int, name: str):
        self.id = role_id
        self.name = name


class FakeMember:
    def __init__(self, member_id: int, display_name: str, roles: list[FakeRole]):
        self.id = member_id
        self.display_name = display_name
        self.roles = roles

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"


class FakeGuild:
    def __init__(self, members: list[FakeMember]):
        self._members = {member.id: member for member in members}

    def get_member(self, member_id: int) -> FakeMember | None:
        return self._members.get(member_id)


def build_levels(class_name: str, level: int, subclass: str = "None") -> list[ClassLevelDocument]:
    return [{"class": class_name, "subclass": subclass, "level": level}]


def build_fixture_objects():
    marker_role_id = next(iter(ROLE_MARKERS))
    marker_role = FakeRole(marker_role_id, "Assistant")
    player_role = FakeRole(999, "Player")
    alice = FakeMember(1, "Alice", [player_role, marker_role])
    bob = FakeMember(2, "Bob", [player_role])
    guild = FakeGuild([alice, bob])
    return alice, bob, guild


def test_parse_player_class_handles_multiclass_strings() -> None:
    parsed = parse_player_class("Battle Master Fighter 5 / Wizard 3")

    assert parsed["total_level"] == 8
    assert parsed["classes"][0]["class"] == "Fighter"
    assert parsed["classes"][0]["subclass"] == "Battle Master"
    assert parsed["classes"][1]["class"] == "Wizard"


def test_parse_tier_from_total_uses_expected_breakpoints() -> None:
    assert parse_tier_from_total(1) == 1
    assert parse_tier_from_total(5) == 2
    assert parse_tier_from_total(20) == 7


def test_queue_serialization_round_trip_preserves_groups() -> None:
    alice, _, guild = build_fixture_objects()
    player = Player(alice, 5, build_levels("Fighter", 5))
    group = Group.new(player.tier, [player], position=3)
    queue = Queue(groups=[group], server_id=123, channel_id=456, locked=True)

    rebuilt = Queue.from_dict(guild, queue.to_dict())

    assert rebuilt.server_id == 123
    assert rebuilt.locked is True
    assert len(rebuilt.groups) == 1
    assert rebuilt.groups[0].players[0].member.display_name == "Alice"
    assert "Alice" in rebuilt.groups[0].player_levels_str


def test_queue_group_fit_and_membership() -> None:
    alice, bob, _ = build_fixture_objects()
    alice_player = Player(alice, 5, build_levels("Fighter", 5))
    bob_player = Player(bob, 5, build_levels("Wizard", 5))
    queue = Queue(
        groups=[Group.new(alice_player.tier, [alice_player])],
        server_id=1,
        channel_id=2,
    )

    assert queue.in_queue(alice.id) == (0, 0)
    assert queue.can_fit_in_group(bob_player) == 0

    queue.groups[0].players = [alice_player] * GROUP_SIZE
    assert queue.can_fit_in_group(bob_player) is None
