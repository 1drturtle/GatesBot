from __future__ import annotations

import asyncio

from queueing.repositories.analytics import AnalyticsRepository
from tests.helpers.builders import make_member
from tests.helpers.fakes import FakeCollection


def make_repository(queue_docs: list[dict] | None = None) -> tuple[AnalyticsRepository, FakeCollection]:
    queue_collection = FakeCollection(queue_docs)
    mdb = {
        "queue_analytics": queue_collection,
        "gate_groups_analytics": FakeCollection(),
        "dm_analytics": FakeCollection(),
        "dm_assign_analytics": FakeCollection(),
        "reinforcement_analytics": FakeCollection(),
        "player_marked": FakeCollection(),
        "active_users": FakeCollection(),
    }
    return AnalyticsRepository(mdb), queue_collection


def test_record_player_signup_stores_raw_signup_text() -> None:
    repository, collection = make_repository()
    member = make_member(10, "Alice")

    asyncio.run(
        repository.record_player_signup(
            member=member,
            total_level=5,
            levels=[{"class": "Fighter", "subclass": "Champion", "level": 5}],
            signup_text="Champion Fighter 5",
        )
    )

    assert collection.docs[0]["last.signup_text"] == "Champion Fighter 5"


def test_get_last_player_signup_text_prefers_stored_raw_text() -> None:
    repository, _ = make_repository(
        [
            {
                "user_id": 10,
                "last": {
                    "signup_text": "Battle Master Fighter 5 / Wizard 3",
                    "classes": [{"class": "Fighter", "subclass": "Champion", "level": 5}],
                },
            }
        ]
    )

    result = asyncio.run(repository.get_last_player_signup_text(10))

    assert result == "Battle Master Fighter 5 / Wizard 3"


def test_get_last_player_signup_text_reconstructs_from_existing_classes() -> None:
    repository, _ = make_repository(
        [
            {
                "user_id": 10,
                "last": {
                    "classes": [
                        {"class": "Fighter", "subclass": "Battle Master", "level": 5},
                        {"class": "Wizard", "subclass": "None", "level": 3},
                    ],
                },
            }
        ]
    )

    result = asyncio.run(repository.get_last_player_signup_text(10))

    assert result == "Battle Master Fighter 5 / Wizard 3"


def test_get_last_player_signup_text_returns_none_without_data() -> None:
    repository, _ = make_repository()

    result = asyncio.run(repository.get_last_player_signup_text(10))

    assert result is None
