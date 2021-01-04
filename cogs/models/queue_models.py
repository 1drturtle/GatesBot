import operator

import discord

from utils.constants import GROUP_SIZE
from utils.constants import TIERS as TIERS
from utils.functions import create_queue_embed, try_delete


def parse_tier_from_total(total_level: int) -> int:
    return ([1] + [TIERS[tier] for tier in TIERS if total_level >= tier])[-1]


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
        if member is None:
            return None
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

    @property
    def mention(self):
        return f'<@{self.member.id}>'

    def __repr__(self):
        return f'<Player {self.member=}, {self.levels=}, {self.tier=}>'


class Group:
    def __init__(self, players: list, tier: int, position: int = None):
        self.players = players
        self.tier = tier
        self.position = position

    def to_dict(self) -> dict:
        return {
            'players': [player.to_dict() for player in self.players if player is not None],
            'tier': self.tier,
            'position': self.position
        }

    @classmethod
    def new(cls, tier, players = None, position = None):
        return cls(players=players, tier=tier, position=position)

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        players = [Player.from_dict(guild, item) for item in data['players']]
        tier = data['tier']
        pos = data['position']
        return cls(players=players, tier=tier, position=pos)

    def __repr__(self):
        return f'<Group {self.players=}, {self.tier=}, {self.position=}>'


class Queue:
    def __init__(self, groups: list, server_id, channel_id):
        self.groups = groups
        self.server_id = server_id
        self.channel_id = channel_id

    @classmethod
    def from_dict(cls, guild: discord.Guild, data: dict):
        groups = [Group.from_dict(guild, x) for x in data['groups']]
        return cls(groups=groups, server_id=data['server_id'], channel_id=data['channel_id'])

    def to_dict(self):
        return {
            'groups': [group.to_dict() for group in self.groups],
            'server_id': self.server_id,
            'channel_id': self.channel_id
        }

    def generate_embed(self, bot) -> discord.Embed:
        embed = create_queue_embed(bot)

        # Sort Groups by Tier
        self.groups.sort(key=lambda x: x.tier)

        embed.title = 'Gate Sign-Up List'

        for index, group in enumerate(self.groups):
            embed.add_field(name=f'{index + 1}. Rank {group.tier}',
                            value=', '.join([player.mention for player in group.players]), inline=False)

        return embed

    async def _get_message(self, channel):
        async for msg in channel.history(limit=50):
            if len(msg.embeds) != 1:
                continue

            embed = msg.embeds[0]

            if embed.title != 'Gate Sign-up List':
                continue

            return msg

    async def update(self, bot, db, channel: discord.TextChannel, message: discord.Message = None) -> discord.Message:
        # Find the old queue message and delete it
        msg = message
        if msg is None:
            msg = await self._get_message(channel)
        if msg is not None:
            await try_delete(msg)

        # Remove empty groups
        self.groups = [group for group in self.groups if len(group.players) != 0]

        # DB Commit
        data = self.to_dict()
        await db.update_one(
                            {'guild_id': self.server_id, 'channel_id': self.channel_id},
                            {'$set': data}, upsert=True
                            )

        # Make a new embed
        embed = self.generate_embed(bot)
        return await channel.send(embed=embed)

    def in_queue(self, member_id):
        member = None
        for group in self.groups:
            for player in group.players:
                if player.member.id == member_id:
                    member = player
        return member

    def can_fit_in_group(self, player: Player):
        out = None
        for index, group in enumerate(self.groups):
            if group.tier == player.tier:
                if len(group.players) >= GROUP_SIZE:
                    continue
                out = index
                break
        return out

    def __repr__(self):
        return f'<Queue {self.groups=}, {self.server_id=}, {self.channel_id=}>'
