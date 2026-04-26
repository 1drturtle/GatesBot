from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import queueing.views.player_queue as player_queue


class FakeModalResponse:
    def __init__(self):
        self.modal = None

    async def send_modal(self, modal):
        self.modal = modal


class FakeInteraction:
    def __init__(self):
        self.author = SimpleNamespace(id=10)
        self.guild = SimpleNamespace(id=1)
        self.response = FakeModalResponse()
        self.sent: list[dict] = []

    async def send(self, content: str, **kwargs):
        self.sent.append({"content": content, **kwargs})


def test_join_button_sends_prefilled_modal(monkeypatch) -> None:
    async def run_test() -> None:
        queue_repository = SimpleNamespace(load_for_guild=AsyncMock(return_value=SimpleNamespace(locked=False)))
        services = SimpleNamespace(
            player_queue_service=SimpleNamespace(),
            queue_repository=queue_repository,
            config=SimpleNamespace(player_queue_channel_id=2),
            analytics_repository=SimpleNamespace(get_last_player_signup_text=AsyncMock(return_value="Fighter 5")),
        )
        monkeypatch.setattr(player_queue, "get_queue_services", lambda bot: services)
        view = player_queue.PlayerQueueUI(SimpleNamespace())
        join_button = next(child for child in view.children if child.custom_id == "gatesbot_playerqueue_join")
        interaction = FakeInteraction()

        await join_button.callback(interaction)

        services.analytics_repository.get_last_player_signup_text.assert_awaited_once_with(10)
        assert isinstance(interaction.response.modal, player_queue.PlayerQueueJoinModal)
        components = interaction.response.modal.to_components()["components"]
        assert components[0]["components"][0]["value"] == "Fighter 5"

    asyncio.run(run_test())


def test_join_button_is_disabled_when_view_is_built_for_locked_queue(monkeypatch) -> None:
    async def run_test() -> None:
        services = SimpleNamespace(
            player_queue_service=SimpleNamespace(),
            queue_repository=SimpleNamespace(),
            config=SimpleNamespace(player_queue_channel_id=2),
            analytics_repository=SimpleNamespace(get_last_player_signup_text=AsyncMock(return_value=None)),
        )
        monkeypatch.setattr(player_queue, "get_queue_services", lambda bot: services)

        view = player_queue.PlayerQueueUI(SimpleNamespace(), queue_locked=True)

        join_button = next(child for child in view.children if child.custom_id == "gatesbot_playerqueue_join")
        assert join_button.disabled is True

    asyncio.run(run_test())


def test_player_queue_view_is_persistent(monkeypatch) -> None:
    async def run_test() -> None:
        services = SimpleNamespace(
            player_queue_service=SimpleNamespace(),
            queue_repository=SimpleNamespace(),
            config=SimpleNamespace(player_queue_channel_id=2),
            analytics_repository=SimpleNamespace(get_last_player_signup_text=AsyncMock(return_value=None)),
        )
        monkeypatch.setattr(player_queue, "get_queue_services", lambda bot: services)

        view = player_queue.PlayerQueueUI(SimpleNamespace())

        assert view.timeout is None
        assert view.is_persistent() is True

    asyncio.run(run_test())


def test_join_button_rejects_stale_interaction_when_queue_is_locked(monkeypatch) -> None:
    async def run_test() -> None:
        queue_repository = SimpleNamespace(load_for_guild=AsyncMock(return_value=SimpleNamespace(locked=True)))
        services = SimpleNamespace(
            player_queue_service=SimpleNamespace(),
            queue_repository=queue_repository,
            config=SimpleNamespace(player_queue_channel_id=2),
            analytics_repository=SimpleNamespace(get_last_player_signup_text=AsyncMock(return_value="Fighter 5")),
        )
        monkeypatch.setattr(player_queue, "get_queue_services", lambda bot: services)
        view = player_queue.PlayerQueueUI(SimpleNamespace())
        join_button = next(child for child in view.children if child.custom_id == "gatesbot_playerqueue_join")
        interaction = FakeInteraction()

        await join_button.callback(interaction)

        services.analytics_repository.get_last_player_signup_text.assert_not_awaited()
        assert interaction.response.modal is None
        assert interaction.sent == [{"content": "The queue is currently locked.", "ephemeral": True}]

    asyncio.run(run_test())


def test_join_modal_submits_signup_text_and_sends_ephemeral_result(monkeypatch) -> None:
    async def run_test() -> None:
        signup = AsyncMock(return_value=SimpleNamespace(message="Signed up in Group #1."))
        services = SimpleNamespace(player_queue_service=SimpleNamespace(signup_from_text=signup))
        monkeypatch.setattr(player_queue, "get_queue_services", lambda bot: services)
        modal = player_queue.PlayerQueueJoinModal(SimpleNamespace())
        interaction = FakeInteraction()
        interaction.text_values = {player_queue.JOIN_MODAL_INPUT_ID: "  Fighter 5  "}

        await modal.callback(interaction)

        signup.assert_awaited_once()
        assert signup.await_args.kwargs["guild"] is interaction.guild
        assert signup.await_args.kwargs["member"] is interaction.author
        assert signup.await_args.kwargs["text"] == "Fighter 5"
        assert interaction.sent == [{"content": "Signed up in Group #1.", "ephemeral": True}]

    asyncio.run(run_test())
