from __future__ import annotations

from dataclasses import dataclass

from common import constants


@dataclass(slots=True)
class QueueRuntimeConfig:
    environment: str
    server_id: int
    player_queue_channel_id: int
    gate_announcement_channel_id: int
    summons_channel_id: int
    gate_assignments_channel_id: int
    dm_queue_channel_id: int
    dm_queue_assignment_channel_id: int
    strike_queue_channel_id: int
    strike_queue_assignment_channel_id: int

    @classmethod
    def from_environment(cls, environment: str) -> "QueueRuntimeConfig":
        is_testing = environment == "testing"
        return cls(
            environment=environment,
            server_id=constants.DEBUG_SERVER if is_testing else constants.GATES_SERVER,
            player_queue_channel_id=(constants.DEBUG_CHANNEL if is_testing else constants.GATES_CHANNEL),
            gate_announcement_channel_id=(
                constants.GATE_ANNOUNCEMENT_CHANNEL_DEBUG if is_testing else constants.GATE_ANNOUNCEMENT_CHANNEL
            ),
            summons_channel_id=(constants.DEBUG_SUMMONS_CHANNEL if is_testing else constants.SUMMONS_CHANNEL),
            gate_assignments_channel_id=constants.GATE_ASSIGNMENTS_CHANNEL,
            dm_queue_channel_id=(constants.DM_QUEUE_CHANNEL_DEBUG if is_testing else constants.DM_QUEUE_CHANNEL),
            dm_queue_assignment_channel_id=(
                constants.DM_QUEUE_ASSIGNMENT_CHANNEL_DEBUG if is_testing else constants.DM_QUEUE_ASSIGNMENT_CHANNEL
            ),
            strike_queue_channel_id=(
                constants.STRIKE_QUEUE_CHANNEL_DEBUG if is_testing else constants.STRIKE_QUEUE_CHANNEL
            ),
            strike_queue_assignment_channel_id=(
                constants.STRIKE_QUEUE_ASSIGNMENT_CHANNEL_DEBUG
                if is_testing
                else constants.STRIKE_QUEUE_ASSIGNMENT_CHANNEL
            ),
        )

    @property
    def is_testing(self) -> bool:
        return self.environment == "testing"
