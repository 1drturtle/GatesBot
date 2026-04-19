from __future__ import annotations

from common.constants import GATES_CHANNEL, QUEUE_ENCOUNTER_CHANNEL
from queueing.messages import build_gate_assignment_message


def test_build_gate_assignment_message_includes_claim_context() -> None:
    message = build_gate_assignment_message(group_number=3, player_count=4, tier_text="2/3")

    assert "Group 3 is yours" in message
    assert f"<#{QUEUE_ENCOUNTER_CHANNEL}>" in message
    assert f"<#{GATES_CHANNEL}>" in message
    assert "4 person Rank 2/3" in message
