from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from queueing.models import Queue
from queueing.repositories.ready_queue import ReadyQueueEntry


class FakeRole:
    def __init__(self, role_id: int, name: str):
        self.id = role_id
        self.name = name


class FakeDisplayAvatar:
    def __str__(self) -> str:
        return "https://example.test/avatar.png"


class FakeMember:
    def __init__(
        self,
        member_id: int,
        display_name: str = "Member",
        *,
        roles: list[FakeRole] | None = None,
    ):
        self.id = member_id
        self.display_name = display_name
        self.name = display_name
        self.nick = None
        self.roles = roles or []
        self.joined_at = None
        self.display_avatar = FakeDisplayAvatar()
        self.sent_dms: list[str] = []

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    async def send(self, content: str, **kwargs: Any) -> SimpleNamespace:
        del kwargs
        self.sent_dms.append(content)
        return SimpleNamespace(id=len(self.sent_dms), content=content)

    def __str__(self) -> str:
        return self.display_name


class FakeEmbed:
    def __init__(self, title: str | None = None, description: str | None = None):
        self.title = title
        self.description = description


class FakeMessage:
    def __init__(
        self,
        message_id: int = 1,
        *,
        author: FakeMember | None = None,
        guild: FakeGuild | None = None,
        channel: FakeChannel | None = None,
        content: str = "",
        embeds: list[Any] | None = None,
    ):
        self.id = message_id
        self.author = author or FakeMember(999, "Bot")
        self.guild = guild
        self.channel = channel
        self.content = content
        self.embeds = embeds or []
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeSentMessage(FakeMessage):
    pass


class FakeChannel:
    def __init__(
        self,
        channel_id: int,
        *,
        guild: FakeGuild | None = None,
        history_messages: list[FakeMessage] | None = None,
        fetched_messages: dict[int, FakeMessage] | None = None,
    ):
        self.id = channel_id
        self.guild = guild
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.history_messages = history_messages or []
        self.fetched_messages = fetched_messages or {}
        self.overwrites: dict[Any, Any] = {}

    async def send(self, content: Any = None, **kwargs: Any) -> FakeSentMessage:
        payload = {"content": content, **kwargs}
        self.sent.append(payload)
        message = FakeSentMessage(message_id=len(self.sent), author=FakeMember(999, "Bot"), guild=self.guild)
        message.embeds = [kwargs["embed"]] if "embed" in kwargs else []
        return message

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    async def fetch_message(self, message_id: int) -> FakeMessage:
        return self.fetched_messages[message_id]

    async def history(self, limit: int = 50):
        del limit
        for message in self.history_messages:
            yield message


class FakeGuild:
    def __init__(
        self,
        guild_id: int = 1,
        *,
        members: list[FakeMember] | None = None,
        channels: list[FakeChannel] | None = None,
        roles: list[FakeRole] | None = None,
    ):
        self.id = guild_id
        self._members = {member.id: member for member in members or []}
        self._channels = {channel.id: channel for channel in channels or []}
        for channel in self._channels.values():
            channel.guild = self
        self.roles = roles or [FakeRole(1, "Player")]

    def get_member(self, member_id: int) -> FakeMember | None:
        return self._members.get(member_id)

    async def fetch_member(self, member_id: int) -> FakeMember | None:
        return self.get_member(member_id)

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self._channels.get(channel_id)

    def add_channel(self, channel: FakeChannel) -> None:
        channel.guild = self
        self._channels[channel.id] = channel


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def sort(self, key: str, direction: int):
        reverse = direction < 0
        self._docs = sorted(self._docs, key=lambda item: item.get(key) or datetime.min, reverse=reverse)
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


def matches_query(doc: dict[str, Any], query: dict[str, Any] | None) -> bool:
    if not query:
        return True

    for key, value in query.items():
        if key == "$or":
            return any(matches_query(doc, item) for item in value)

        if isinstance(value, dict):
            if "$exists" in value:
                if (key in doc) != bool(value["$exists"]):
                    return False
                continue
            if "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
                continue

        if doc.get(key) != value:
            return False

    return True


def _selector_fields(query: dict[str, Any] | None) -> dict[str, Any]:
    if not query:
        return {}
    out = {}
    for key, value in query.items():
        if key.startswith("$") or isinstance(value, dict):
            continue
        out[key] = value
    return out


class FakeDeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None):
        self.docs = docs or []
        self.update_one_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        self.update_many_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.delete_one_calls: list[dict[str, Any]] = []
        self.delete_many_calls: list[dict[str, Any]] = []
        self.insert_one_calls: list[dict[str, Any]] = []

    def find(self, query: dict[str, Any] | None = None, **kwargs: Any) -> FakeCursor:
        query = kwargs.get("filter", query)
        docs = [doc for doc in self.docs if matches_query(doc, query)]
        limit = kwargs.get("limit")
        if limit is not None:
            docs = docs[:limit]
        return FakeCursor(docs)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if matches_query(doc, query):
                return dict(doc)
        return None

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        self.update_one_calls.append((query, update, upsert))
        doc = next((item for item in self.docs if matches_query(item, query)), None)
        if doc is None:
            if not upsert:
                return
            doc = _selector_fields(query)
            self.docs.append(doc)

        doc.update(update.get("$set", {}))
        for field in update.get("$currentDate", {}):
            doc[field] = datetime.now(timezone.utc)
        for field, amount in update.get("$inc", {}).items():
            doc[field] = doc.get(field, 0) + amount

    async def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        self.update_many_calls.append((query, update))
        for doc in self.docs:
            if matches_query(doc, query):
                doc.update(update.get("$set", {}))

    async def delete_one(self, query: dict[str, Any]) -> FakeDeleteResult:
        self.delete_one_calls.append(query)
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not matches_query(doc, query)]
        return FakeDeleteResult(before - len(self.docs))

    async def delete_many(self, query: dict[str, Any]) -> FakeDeleteResult:
        self.delete_many_calls.append(query)
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not matches_query(doc, query)]
        return FakeDeleteResult(before - len(self.docs))

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.insert_one_calls.append(document)
        self.docs.append(dict(document))


class InMemoryQueueRepository:
    def __init__(self, queue: Queue):
        self.queue = queue
        self.saved: list[Queue] = []
        self.load_calls: list[dict[str, Any]] = []

    async def load_for_guild(self, guild: FakeGuild, *, channel_id: int | None = None, queue_type: type[Queue] = Queue):
        self.load_calls.append({"guild": guild, "channel_id": channel_id, "queue_type": queue_type})
        return self.queue

    async def save(self, queue: Queue) -> None:
        self.queue = queue
        self.saved.append(queue)


class InMemoryReadyQueueRepository:
    def __init__(self, entries: list[ReadyQueueEntry] | None = None):
        self.entries = entries or []
        self.upserts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.removed_batches: list[list[int]] = []

    async def list_entries(self) -> list[ReadyQueueEntry]:
        return list(self.entries)

    async def upsert_ready(self, *, member_id: int, text: str, message_id: int) -> None:
        self.upserts.append({"member_id": member_id, "text": text, "message_id": message_id})
        self.entries = [entry for entry in self.entries if entry.member_id != member_id]
        self.entries.append(ReadyQueueEntry(member_id=member_id, text=text, message_id=message_id, ready_on=None))

    async def update_text(self, *, member_id: int, text: str) -> None:
        self.updates.append({"member_id": member_id, "text": text})
        for entry in self.entries:
            if entry.member_id == member_id:
                entry.text = text

    async def remove_member(self, member_id: int) -> bool:
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.member_id != member_id]
        return len(self.entries) < before

    async def remove_members(self, member_ids: list[int]) -> None:
        self.removed_batches.append(member_ids)
        blocked = set(member_ids)
        self.entries = [entry for entry in self.entries if entry.member_id not in blocked]


class InMemoryGateRepository:
    def __init__(self, gates: list[dict[str, Any]] | dict[str, Any] | None = None):
        if gates is None:
            self.gates = []
        elif isinstance(gates, dict):
            self.gates = [gates]
        else:
            self.gates = gates
        self.owner_updates: list[tuple[str, int]] = []

    async def get_by_name(self, gate_name: str) -> dict[str, Any] | None:
        normalized = gate_name.lower()
        for gate in self.gates:
            if gate["name"] == normalized:
                return dict(gate)
        return None

    async def get_by_owner(self, owner_id: int) -> dict[str, Any] | None:
        for gate in self.gates:
            if gate.get("owner") == owner_id:
                return dict(gate)
        return None

    async def set_owner(self, gate_name: str, owner_id: int) -> None:
        self.owner_updates.append((gate_name, owner_id))
        for gate in self.gates:
            if gate["name"] == gate_name.lower():
                gate["owner"] = owner_id
