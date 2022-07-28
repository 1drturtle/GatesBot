import discord

from utils.constants import GROUP_SIZE, ROLE_MARKERS
from utils.constants import TIERS as TIERS
from utils.functions import create_queue_embed, try_delete


def parse_tier_from_total(total_level: int) -> int:
    return ([1] + [TIERS[tier] for tier in TIERS if total_level >= tier])[-1]


class QueueException(BaseException):
    pass


class Player:
    def __init__(self, member: discord.Member, total_level: int, levels: list):
        self.member = member
        self._levels = levels
        self._total_level = total_level
        self.tier = parse_tier_from_total(total_level)

    @classmethod
    def new(cls, member, classes):
        if "total_level" not in classes:
            raise QueueException("No total level found.")
        if "classes" not in classes:
            classes["classes"] = []
        return cls(member, classes["total_level"], classes["classes"])

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        if "total_level" not in data:
            raise QueueException("No total level found.")
        if "classes" not in data:
            data["classes"] = []
        member = guild.get_member(data["member_id"])
        if member is None:
            return None
        return cls(member, data["total_level"], data["classes"])

    def to_dict(self):
        return {"total_level": self.total_level, "classes": self.levels, "member_id": self.member.id}

    @property
    def total_level(self):
        return self._total_level

    @property
    def levels(self):
        return self._levels

    @property
    def mention(self):
        return f"<@{self.member.id}>"

    @property
    def level_str(self):
        out = []
        for level in self.levels:
            out_str = ""
            out_str += level["subclass"] + " " if level["subclass"] is not None else ""
            out_str += level["class"] + " " if level["class"] is not None else "*None*"
            out_str += str(level["level"])
            out.append(out_str)
        return " / ".join(out)

    def __repr__(self):
        return f"<Player {self.member=}, {self.levels=}, {self.tier=}>"


class Group:
    def __init__(self, players: list, tier: int, position: int = None):
        self.players = players
        self.tier = tier
        self.position = position

    def to_dict(self) -> dict:
        return {
            "players": [player.to_dict() for player in self.players if player is not None],
            "tier": self.tier,
            "position": self.position,
        }

    @classmethod
    def new(cls, tier, players=None, position=None):
        return cls(players=players, tier=tier, position=position)

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        players = []
        for item in data["players"]:
            player = Player.from_dict(guild, item)
            if player is not None:
                players.append(player)
        tier = data["tier"]
        pos = data["position"]
        return cls(players=players, tier=tier, position=pos)

    @property
    def player_levels(self):
        out = {}
        for player in self.players:
            out[player.total_level] = out.get(player.total_level, 0) + 1
        return out

    @property
    def player_levels_str(self) -> str:
        out = "```diff\n"
        for player in self.players:
            markers = ", ".join(
                [
                    mark
                    for role_id, mark in ROLE_MARKERS.items()
                    if discord.utils.find(lambda r: r.id == role_id, player.member.roles)
                ]
            )
            out += f"- {player.member.display_name}: {player.level_str}" f"{f' [{markers}]' if markers else ''}\n"
        out += "```"
        return out

    @property
    def tier_str(self) -> str:
        tiers = set()

        for player in self.players:
            tiers.add(player.tier)

        out = "/".join(map(str, sorted(tiers)))
        out = "__" + out + "__"

        return out

    async def generate_field(self, bot):
        mark_db = bot.mdb["player_marked"]
        names = []
        for player in self.players:
            mark_info = await mark_db.find_one({"_id": player.member.id})
            post_fix = f'{"*" if mark_info.get("marked", False) else ""}{mark_info.get("custom", "")}'
            names.append(f"{player.mention}{post_fix}")
        return discord.utils.escape_markdown(", ".join(names))

    def __repr__(self):
        return f"<Group {self.players=}, {self.tier=}, {self.position=}>"


class Queue:
    def __init__(self, groups: list, server_id, channel_id):
        self.groups = groups
        self.server_id = server_id
        self.channel_id = channel_id

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        groups = [Group.from_dict(guild, x) for x in data["groups"]]
        return cls(groups=groups, server_id=data["server_id"], channel_id=data["channel_id"])

    def to_dict(self):
        return {
            "groups": [group.to_dict() for group in self.groups],
            "server_id": self.server_id,
            "channel_id": self.channel_id,
        }

    async def generate_embed(self, bot) -> discord.Embed:
        embed = create_queue_embed(bot)

        # Sort Groups by Tier
        self.groups.sort(key=lambda x: x.tier)

        embed.title = "Gate Sign-Up List"

        for index, group in enumerate(self.groups):
            embed.add_field(
                name=f"{index + 1}. Rank {group.tier}",
                value=await group.generate_field(bot),
                inline=False,
            )

        return embed

    async def _get_message(self, channel):
        history = await channel.history(limit=50).flatten()
        out = None
        for msg in history:
            if len(msg.embeds) != 1:
                continue

            embed = msg.embeds[0]
            if embed.title != "Gate Sign-Up List":
                continue

            out = msg
            break
        return out

    async def update(self, bot, db, channel: discord.TextChannel) -> discord.Message:
        # Find the old queue message and delete it
        msg = await self._get_message(channel)
        if msg is not None:
            await try_delete(msg)

        # Remove empty groups
        self.groups = [group for group in self.groups if len(group.players) != 0]

        # DB Commit
        data = self.to_dict()
        await db.update_one({"guild_id": self.server_id, "channel_id": self.channel_id}, {"$set": data}, upsert=True)

        # Make a new embed
        embed = await self.generate_embed(bot)
        return await channel.send(embed=embed)

    def in_queue(self, member_id) -> tuple:
        index = None
        for i, group in enumerate(self.groups):
            for ii, player in enumerate(group.players):
                if player.member.id == member_id:
                    index = (i, ii)
        return index

    def can_fit_in_group(self, player: Player, group_size=GROUP_SIZE):
        out = None
        for index, group in enumerate(self.groups):
            if group.tier == player.tier:
                if len(group.players) >= group_size:
                    continue
                out = index
                break
        return out

    @property
    def player_count(self):
        return sum([len(g.players) for g in self.groups])

    def __repr__(self):
        return f"<Queue {self.groups=}, {self.server_id=}, {self.channel_id=}>"
