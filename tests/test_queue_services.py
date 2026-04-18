from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from queueing.config import QueueRuntimeConfig
from queueing.models import Group, Player, Queue
from queueing.repository import ReadyQueueEntry
from queueing.services import DMQueueService, PlayerQueueService, StrikeQueueService


class FakeRole:
    def __init__(self, role_id: int, name: str):
        self.id = role_id
        self.name = name


class FakeMember:
    def __init__(self, member_id: int, display_name: str):
        self.id = member_id
        self.display_name = display_name
        self.nick = None
        self.roles: list[FakeRole] = []
        self.joined_at = None

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"


class FakeChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.sent: list[str] = []

    async def send(self, content=None, **kwargs):
        if content is not None:
            self.sent.append(str(content))
        return SimpleNamespace(id=len(self.sent) + 1)

    async def edit(self, **kwargs):
        del kwargs

    async def history(self, limit: int = 25):
        del limit
        if False:
            yield None


class FakeGuild:
    def __init__(self, members: list[FakeMember], channels: list[FakeChannel]):
        self._members = {member.id: member for member in members}
        self._channels = {channel.id: channel for channel in channels}
        self.roles = [FakeRole(1, "Player")]

    def get_member(self, member_id: int):
        return self._members.get(member_id)

    async def fetch_member(self, member_id: int):
        return self.get_member(member_id)

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)


class InMemoryQueueRepository:
    def __init__(self, queue: Queue):
        self.queue = queue

    async def load_for_guild(self, guild, *, channel_id=None, queue_type=Queue):
        del guild, channel_id, queue_type
        return self.queue

    async def save(self, queue: Queue):
        self.queue = queue


class InMemoryReadyQueueRepository:
    def __init__(self, entries: list[ReadyQueueEntry]):
        self.entries = entries

    async def list_entries(self):
        return list(self.entries)

    async def upsert_ready(self, *, member_id: int, text: str, message_id: int):
        del message_id
        self.entries = [entry for entry in self.entries if entry.member_id != member_id]
        self.entries.append(
            ReadyQueueEntry(member_id=member_id, text=text, message_id=None, ready_on=None)
        )

    async def update_text(self, *, member_id: int, text: str):
        for entry in self.entries:
            if entry.member_id == member_id:
                entry.text = text

    async def remove_member(self, member_id: int) -> bool:
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.member_id != member_id]
        return len(self.entries) < before

    async def remove_members(self, member_ids: list[int]):
        self.entries = [entry for entry in self.entries if entry.member_id not in set(member_ids)]


class InMemoryGateRepository:
    def __init__(self, gate: dict[str, object] | None):
        self.gate = gate

    async def get_by_name(self, gate_name: str):
        if self.gate and self.gate["name"] == gate_name.lower():
            return dict(self.gate)
        return None

    async def get_by_owner(self, owner_id: int):
        if self.gate and self.gate.get("owner") == owner_id:
            return dict(self.gate)
        return None

    async def set_owner(self, gate_name: str, owner_id: int):
        if self.gate and self.gate["name"] == gate_name.lower():
            self.gate["owner"] = owner_id


def make_player(member_id: int, name: str, level: int = 5) -> Player:
    member = FakeMember(member_id, name)
    return Player(member=member, _total_level=level, _levels=[{"class": "Fighter", "subclass": "None", "level": level}])


def make_player_service(*, testing: bool, queue: Queue, gate: dict[str, object] | None = None):
    config = QueueRuntimeConfig.from_environment("testing" if testing else "production")
    analytics = SimpleNamespace(
        record_player_signup=AsyncMock(),
        decrement_player_signup=AsyncMock(),
        set_marked=AsyncMock(),
        clear_marks_for_members=AsyncMock(),
        mark_assignment_claimed=AsyncMock(),
        record_dm_claim=AsyncMock(),
        get_dm_info=AsyncMock(return_value={"dm_gates": [{"gate_name": "alpha"}]}),
        record_gate_reinforcement=AsyncMock(),
        record_player_gate_summon=AsyncMock(),
        record_claimed_group=AsyncMock(),
        set_unlock_timestamp=AsyncMock(),
    )
    service = PlayerQueueService(
        bot=SimpleNamespace(user=SimpleNamespace(id=999)),
        config=config,
        queue_repository=InMemoryQueueRepository(queue),
        gate_repository=InMemoryGateRepository(gate),
        analytics_repository=analytics,
        presentation_service=SimpleNamespace(),
    )
    service.refresh_queue_message = AsyncMock()
    return service, analytics


def test_player_signup_prefers_existing_group() -> None:
    player = make_player(1, "Alice")
    queue = Queue(groups=[Group.new(player.tier, [])], server_id=1, channel_id=2)
    service, analytics = make_player_service(testing=False, queue=queue)
    guild = FakeGuild([player.member], [])
    message = SimpleNamespace(guild=guild, author=player.member, id=10)

    result = asyncio.run(
        service.signup_from_message(
            message=message,
            player=player,
            view_factory=lambda: object(),
        )
    )

    assert result.success is True
    assert result.group_number == 1
    assert len(queue.groups[0].players) == 1
    analytics.record_player_signup.assert_awaited_once()


def test_player_signup_blocks_duplicates_outside_testing() -> None:
    player = make_player(1, "Alice")
    queue = Queue(groups=[Group.new(player.tier, [player])], server_id=1, channel_id=2)
    service, analytics = make_player_service(testing=False, queue=queue)
    guild = FakeGuild([player.member], [])
    message = SimpleNamespace(guild=guild, author=player.member, id=10)

    result = asyncio.run(
        service.signup_from_message(
            message=message,
            player=player,
            view_factory=lambda: object(),
        )
    )

    assert result.success is False
    assert result.should_delete_source_message is True
    analytics.record_player_signup.assert_not_called()


def test_player_signup_allows_duplicates_in_testing() -> None:
    player = make_player(1, "Alice")
    queue = Queue(groups=[Group.new(player.tier, [player])], server_id=1, channel_id=2)
    service, analytics = make_player_service(testing=True, queue=queue)
    guild = FakeGuild([player.member], [])
    message = SimpleNamespace(guild=guild, author=player.member, id=10)

    result = asyncio.run(
        service.signup_from_message(
            message=message,
            player=player,
            view_factory=lambda: object(),
        )
    )

    assert result.success is True
    assert len(queue.groups[0].players) == 2
    analytics.record_player_signup.assert_awaited_once()


def test_player_claim_command_and_assignment_paths() -> None:
    dm = FakeMember(10, "DM")
    p1 = make_player(1, "Alice")
    p2 = make_player(2, "Bob")
    summons = FakeChannel(794179073202978836)
    assignments = FakeChannel(874795661198000208)
    guild = FakeGuild([dm, p1.member, p2.member], [summons, assignments])

    queue_command = Queue(
        groups=[Group.new(p1.tier, [p1]), Group.new(p2.tier, [p2])],
        server_id=1,
        channel_id=2,
    )
    service_command, analytics_command = make_player_service(
        testing=False,
        queue=queue_command,
        gate={"name": "alpha", "emoji": ":a:", "owner": dm.id},
    )

    result_command = asyncio.run(
        service_command.claim_group(
            guild=guild,
            claimant=dm,
            gate_name="alpha",
            group_number=1,
            view_factory=lambda: object(),
        )
    )

    queue_assigned = Queue(
        groups=[Group.new(p1.tier, [p1], position=1), Group.new(p2.tier, [p2])],
        server_id=1,
        channel_id=2,
    )
    queue_assigned.groups[0].assigned = dm.id
    service_assigned, analytics_assigned = make_player_service(
        testing=False,
        queue=queue_assigned,
        gate={"name": "alpha", "emoji": ":a:", "owner": dm.id},
    )

    result_assigned = asyncio.run(
        service_assigned.claim_group(
            guild=guild,
            claimant=dm,
            use_assignment=True,
            view_factory=lambda: object(),
        )
    )

    assert result_command.success is True
    assert result_assigned.success is True
    assert result_command.claimed_group_number == result_assigned.claimed_group_number == 1
    assert len(queue_command.groups) == 1
    assert len(queue_assigned.groups) == 1
    analytics_command.record_dm_claim.assert_awaited_once()
    analytics_assigned.record_dm_claim.assert_awaited_once()


def test_dm_assign_validates_and_assigns() -> None:
    dm_member = FakeMember(20, "Delta")
    summoner = FakeMember(21, "Summoner")
    player = make_player(1, "Alice")
    group = Group.new(player.tier, [player])
    queue = Queue(groups=[group], server_id=1, channel_id=2)

    config = QueueRuntimeConfig.from_environment("production")
    guild = FakeGuild([dm_member, summoner, player.member], [FakeChannel(config.dm_queue_assignment_channel_id)])

    dm_repo = InMemoryReadyQueueRepository(
        [ReadyQueueEntry(member_id=dm_member.id, text="tier 3", message_id=1, ready_on=None)]
    )
    queue_repo = InMemoryQueueRepository(queue)
    analytics = SimpleNamespace(
        record_dm_queue_signup=AsyncMock(),
        record_dm_assignment=AsyncMock(),
        increment_dm_assignments=AsyncMock(),
    )
    presentation = SimpleNamespace(send_gate_assignment=AsyncMock())

    service = DMQueueService(
        bot=SimpleNamespace(),
        config=config,
        dm_queue_repository=dm_repo,
        queue_repository=queue_repo,
        analytics_repository=analytics,
        presentation_service=presentation,
    )
    service.refresh_queue_message = AsyncMock()

    invalid = asyncio.run(
        service.assign_dm_to_group(
            guild=guild,
            summoner=summoner,
            group_number=1,
            queue_number=2,
            view_factory=lambda: object(),
        )
    )
    valid = asyncio.run(
        service.assign_dm_to_group(
            guild=guild,
            summoner=summoner,
            group_number=1,
            queue_number=1,
            view_factory=lambda: object(),
        )
    )

    assert invalid.success is False
    assert valid.success is True
    assert queue.groups[0].assigned == dm_member.id
    assert dm_repo.entries == []
    presentation.send_gate_assignment.assert_awaited_once()


def test_strike_assign_rejects_invalid_gate() -> None:
    strike_member = FakeMember(30, "Striker")
    queue_repo = InMemoryReadyQueueRepository(
        [ReadyQueueEntry(member_id=strike_member.id, text="ready", message_id=1, ready_on=None)]
    )
    config = QueueRuntimeConfig.from_environment("production")
    guild = FakeGuild([strike_member], [FakeChannel(config.strike_queue_assignment_channel_id)])

    analytics = SimpleNamespace(
        set_last_strike_gate=AsyncMock(),
        get_dm_info=AsyncMock(return_value=None),
        record_strike_team_reinforcement=AsyncMock(),
    )

    service = StrikeQueueService(
        bot=SimpleNamespace(),
        config=config,
        strike_queue_repository=queue_repo,
        gate_repository=InMemoryGateRepository(None),
        analytics_repository=analytics,
        presentation_service=SimpleNamespace(),
    )
    service.refresh_queue_message = AsyncMock()

    result = asyncio.run(
        service.assign_strike_team(
            guild=guild,
            queue_numbers=[1],
            gate_name="missing",
            view_factory=lambda: object(),
        )
    )

    assert result.success is False
    assert "does not exist" in result.message
