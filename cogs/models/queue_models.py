import discord
from utils.constants import TIERS as tiers


def parse_tier_from_total(total_level: int) -> int:
    return ([1] + [tiers[tier] for tier in tiers if total_level >= tier])[-1]


class QueueException(BaseException):
    pass


class Player:
    def __init__(self, member: discord.Member, total_level: int, levels: list):
        self._member = member
        self._levels = levels
        self._total_level = total_level
        self.tier = parse_tier_from_total(total_level)

    @classmethod
    def new(cls, member, classes):
        if 'total_level' not in classes:
            raise QueueException('No total level found.')
        if 'classes' not in classes:
            classes['classes'] = []
        return cls(member, classes['total_level'], classes['classes'])

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        if 'total_level' not in data:
            raise QueueException('No total level found.')
        if 'classes' not in data:
            data['classes'] = []
        member = guild.get_member(data['member_id'])
        return cls(member, data['total_level'], data['classes'])

    def to_dict(self):
        return {
            'total_level': self.total_level,
            'classes': self.levels,
            'member_id': self.member.id
        }

    @property
    def total_level(self):
        return self._total_level

    @property
    def levels(self):
        return self._levels

    @property
    def member(self):
        return self._member


class Group:
    def __init__(self, players: list[Player], tier: int, position: int = None):
        self.players = players
        self.tier = tier
        self.position = position

    def to_dict(self) -> dict:
        return {
            'players': [player.to_dict() for player in self.players],
            'tier': self.tier,
            'position': self.position
        }

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        players = [Player.from_dict(guild, item) for item in data['players']]
        tier = data['tier']
        pos = data['position']
        return cls(players=players, tier=tier, position=pos)


class Queue:
    def __init__(self, groups: list[Group], server_id, channel_id):
        self.groups = groups
        self.server_id = server_id
        self.channel_id = channel_id

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        groups = [Group.from_dict(guild, x) for x in data['guilds']]
        return cls(groups=groups, server_id=data['server_id'], channel_id=data['channel_id'])

    def to_dict(self):
        return {
            'groups': [group.to_dict() for group in self.groups],
            'server_id': self.server_id,
            'channel_id': self.channel_id
        }

    def in_queue(self, member_id):
        member = None
        for group in self.groups:
            intersect = [x for x in group.players if x.member.id == member_id]
            if intersect:
                member = intersect[0]
                break
        return member
