from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord

from queueing.documents import ClassLevelDocument, ParsedPlayerClassDocument

if TYPE_CHECKING:
    from queueing.models import Player


PLAYER_CLASS_REGEX = re.compile(r"(?P<subclass>(?:\w+ )*)(?P<class>\w+) (?P<level>\d+)")


def length_check(group_length: int, requested_length: int) -> str | None:
    if 1 <= requested_length <= group_length:
        return None

    out = "Invalid Group Number. "
    if group_length == 0:
        out += "No groups available to select!"
    elif group_length == 1:
        out += "Only one group to select."
    else:
        out += f"Must be between 1 and {group_length}."
    return out


async def check_level_role(player: Player) -> discord.Message | None:
    level = player.total_level
    level_role = f"Level {level}"
    has_level_role = discord.utils.find(
        lambda role: role.name == level_role,
        player.member.roles,
    )

    if has_level_role:
        return None

    wrong_role = discord.utils.find(
        lambda role: role.name.lower().startswith("level"),
        player.member.roles,
    )
    if wrong_role is None:
        return await player.member.send(
            "Hi! You currently do not have a level role. Grab one from near the top of <#874436255088275496>!"
        )

    return await player.member.send(
        f"Hi! You currently have the role for {wrong_role.name}, but you put your level"
        f" as Level {player.total_level} into the signup."
        f"\nPlease either grab the correct role "
        f"from <#874436255088275496> or leave the queue with `=leave` and sign-up with"
        f" the correct level. Thank you!"
    )


def parse_player_class(class_str: str) -> ParsedPlayerClassDocument:
    out: ParsedPlayerClassDocument = {"total_level": 0, "classes": []}

    for subclass, class_name, raw_level in PLAYER_CLASS_REGEX.findall(class_str):
        try:
            level = int(raw_level.strip())
        except ValueError:
            level = 4

        class_doc: ClassLevelDocument = {
            "class": class_name.strip() or "None",
            "subclass": subclass.strip() or "None",
            "level": level,
        }
        out["total_level"] += level
        out["classes"].append(class_doc)

    return out
