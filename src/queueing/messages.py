from __future__ import annotations

from common.constants import GATES_CHANNEL, QUEUE_ENCOUNTER_CHANNEL


def build_gate_assignment_message(group_number: int, player_count: int, tier_text: str) -> str:
    return (
        f"Group {group_number} is yours, see above for details."
        f" Don't forget to submit your encounter in <#{QUEUE_ENCOUNTER_CHANNEL}> once ready and claim once approved!"
        f" Kindly note that this is a **{player_count} person Rank {tier_text}** "
        "group and adjust your encounter as needed."
        " Please react to this message if you are, indeed, claiming."
        " **__Please double-check your group number in "
        f"<#{GATES_CHANNEL}> when claiming because it may have changed.__**"
    )
