from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import discord

from common.constants import GROUP_SIZE, ROLE_MARKERS, TIERS
from common.embeds import create_queue_embed
from queueing.documents import (
    ClassLevelDocument,
    GroupDocument,
    ParsedPlayerClassDocument,
    PlayerDocument,
    QueueDocument,
)


def parse_tier_from_total(total_level: int) -> int:
    return ([1] + [TIERS[tier] for tier in TIERS if total_level >= tier])[-1]


class QueueException(Exception):
    pass


@dataclass(slots=True)
class Player:
    member: discord.Member
    _total_level: int
    _levels: list[ClassLevelDocument]
    tier: int = field(init=False)

    def __post_init__(self) -> None:
        self.tier = parse_tier_from_total(self._total_level)

    @classmethod
    def new(
        cls,
        member: discord.Member,
        classes: ParsedPlayerClassDocument,
    ) -> Player:
        if "total_level" not in classes:
            raise QueueException("No total level found.")
        return cls(
            member=member,
            _total_level=classes["total_level"],
            _levels=classes.get("classes", []),
        )

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: PlayerDocument) -> Player | None:
        member = guild.get_member(data["member_id"])
        if member is None:
            return None
        return cls(
            member=member,
            _total_level=data["total_level"],
            _levels=data.get("classes", []),
        )

    def to_dict(self) -> PlayerDocument:
        return {
            "total_level": self.total_level,
            "classes": self.levels,
            "member_id": self.member.id,
        }

    @property
    def total_level(self) -> int:
        return self._total_level

    @property
    def levels(self) -> list[ClassLevelDocument]:
        return self._levels

    @property
    def mention(self) -> str:
        return f"<@{self.member.id}>"

    @property
    def level_str(self) -> str:
        out: list[str] = []
        for level in self.levels:
            subclass = level.get("subclass")
            class_name = level.get("class")
            out_str = ""
            out_str += f"{subclass} " if subclass is not None else ""
            out_str += f"{class_name} " if class_name is not None else "*None*"
            out_str += str(level["level"])
            out.append(out_str)
        return " / ".join(out)

    def __repr__(self) -> str:
        return f"<Player member={self.member!r}, levels={self.levels!r}, tier={self.tier!r}>"


@dataclass(slots=True)
class Group:
    players: list[Player]
    tier: int
    position: int | None = None
    locked: bool = False
    assigned: int | None = None

    def to_dict(self) -> GroupDocument:
        return {
            "players": [
                player.to_dict() for player in self.players if player is not None
            ],
            "tier": self.tier,
            "position": self.position,
            "locked": self.locked,
            "assigned": self.assigned,
        }

    @classmethod
    def new(
        cls,
        tier: int,
        players: list[Player] | None = None,
        position: int | None = None,
    ) -> Group:
        return cls(players=players or [], tier=tier, position=position)

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: GroupDocument) -> Group:
        players: list[Player] = []
        for item in data["players"]:
            player = Player.from_dict(guild, item)
            if player is not None:
                players.append(player)
        return cls(
            players=players,
            tier=data["tier"],
            position=data.get("position"),
            locked=data.get("locked", False),
            assigned=data.get("assigned"),
        )

    @property
    def player_levels_str(self) -> str:
        out = ["```diff"]
        for player in self.players:
            markers = ", ".join(
                mark
                for role_id, mark in ROLE_MARKERS.items()
                if any(role.id == role_id for role in player.member.roles)
            )
            suffix = f" [{markers}]" if markers else ""
            out.append(f"- {player.member.display_name}: {player.level_str}{suffix}")
        out.append("```")
        return "\n".join(out)

    @property
    def tier_str(self) -> str:
        tiers = sorted({player.tier for player in self.players})
        return "__" + "/".join(map(str, tiers)) + "__"

    async def generate_field(self, bot: Any) -> str:
        mark_db = bot.mdb["player_marked"]
        names: list[str] = []
        for player in self.players:
            mark_info = await mark_db.find_one({"_id": player.member.id}) or {}
            postfix = (
                f'{"*" if mark_info.get("marked", False) else ""}{mark_info.get("custom", "")}'
            )
            names.append(f"{player.mention}{postfix}")
        return discord.utils.escape_markdown(", ".join(names))

    def __repr__(self) -> str:
        return (
            f"<Group players={self.players!r}, tier={self.tier!r}, "
            f"position={self.position!r}>"
        )


@dataclass(slots=True)
class Queue:
    groups: list[Group]
    server_id: int
    channel_id: int | None
    locked: bool = False

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: QueueDocument) -> Queue:
        groups = [Group.from_dict(guild, item) for item in data["groups"]]
        return cls(
            groups=groups,
            server_id=data["server_id"],
            channel_id=data["channel_id"],
            locked=data.get("locked", False),
        )

    def to_dict(self) -> QueueDocument:
        return {
            "groups": [group.to_dict() for group in self.groups],
            "server_id": self.server_id,
            "channel_id": self.channel_id,
            "locked": self.locked,
        }

    async def generate_embed(self, bot: Any) -> discord.Embed:
        embed = create_queue_embed(bot)
        self.groups.sort(key=lambda group: group.tier)
        embed.title = "Gate Sign-Up List" + (" 🔒" if self.locked else "")

        for index, group in enumerate(self.groups):
            locked = " 🔒" if group.locked else ""
            embed.add_field(
                name=f"{index + 1}. Rank {group.tier}{locked}",
                value=await group.generate_field(bot),
                inline=False,
            )

        return embed

    async def update(
        self,
        bot: Any,
        db: Any,
        channel: discord.TextChannel,
    ) -> discord.Message:
        from queueing.services import replace_persistent_message
        from queueing.views import PlayerQueueUI

        self.groups = [group for group in self.groups if group.players]
        view = PlayerQueueUI(bot, self.__class__)
        embed = await self.generate_embed(bot)
        message = await replace_persistent_message(
            channel=channel,
            meta_db=bot.mdb["queue_meta"],
            meta_key=f"player_queue:{self.channel_id}",
            embed_title_prefix="Gate Sign-Up List",
            bot_user_id=bot.user.id,
            embed=embed,
            view=view,
        )
        await self.db_save(db)
        return message

    async def db_save(self, db: Any) -> None:
        await db.update_one(
            {"guild_id": self.server_id, "channel_id": self.channel_id},
            {"$set": self.to_dict()},
            upsert=True,
        )

    def in_queue(self, member_id: int) -> tuple[int, int] | None:
        for group_index, group in enumerate(self.groups):
            for player_index, player in enumerate(group.players):
                if player.member.id == member_id:
                    return (group_index, player_index)
        return None

    def can_fit_in_group(
        self,
        player: Player,
        group_size: int = GROUP_SIZE,
    ) -> int | None:
        for index, group in enumerate(self.groups):
            if group.tier != player.tier:
                continue
            if len(group.players) >= group_size or group.locked:
                continue
            return index
        return None

    @property
    def player_count(self) -> int:
        return sum(len(group.players) for group in self.groups)

    def __repr__(self) -> str:
        return (
            f"<Queue groups={self.groups!r}, server_id={self.server_id!r}, "
            f"channel_id={self.channel_id!r}>"
        )
