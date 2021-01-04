import logging
import re

import discord
from discord.ext import commands

import utils.constants as constants
from cogs.models.queue_models import Player, Group, Queue
from utils.checks import has_role

line_re = re.compile(r'\*\*in line:*\*\*', re.IGNORECASE)
player_class_regex = re.compile(r'((\w+ )*(\w+) (\d+))')

log = logging.getLogger(__name__)


class ContextProxy:
    def __init__(self, bot, message):
        self.message = message
        self.bot = bot
        self.author = message.author


def parse_player_class(class_str) -> dict:
    out = {
        'total_level': 0,
        'classes': []
    }

    # [Subclass] <Class> <Level> / [Subclass] <Class> <Level>
    matches = player_class_regex.findall(class_str)
    for match in matches:
        try:
            level = int(match[-1].strip())  # Last group is always a number.
        except ValueError:
            level = 4
        player_class = match[2].strip() if match[2] else 'None'
        subclass = match[1].strip() if match[1] else 'None'
        out['total_level'] += level
        out['classes'].append({'class': player_class, 'subclass': subclass, 'level': level})

    return out


async def queue_from_guild(db, guild: discord.Guild) -> Queue:
    queue_data = await db.find_one({'guild_id': guild.id})
    if queue_data is None:
        queue_data = {
            'groups': [],
            'server_id': guild.id,
            'channel_id': None
        }
    queue = Queue.from_dict(guild, queue_data)
    return queue


class QueueChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_message = None

        self.member_converter = commands.MemberConverter()
        self.db = bot.mdb['player_queue']

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == constants.GATES_SERVER:
            return True
        if ctx.guild.id == constants.DEBUG_SERVER and self.bot.environemnt == 'testing':
            return True

    @commands.Cog.listener(name='on_message')
    async def queue_listener(self, message):
        if message.guild is None:
            return None

        server_id = constants.GATES_SERVER if self.bot.environment != 'testing' else constants.DEBUG_SERVER
        channel_id = constants.GATES_CHANNEL if self.bot.environment != 'testing' else constants.DEBUG_CHANNEL

        if not (server_id == message.guild.id and channel_id == message.channel.id):
            return None

        if not line_re.match(message.content):
            return None

        try:
            await message.add_reaction('<:d20:773638073052561428>')
        except discord.HTTPException:
            pass  # We ignore Discord being weird!
        except (discord.NotFound, discord.Forbidden) as e:
            log.error(f'{e.__class__.__name__} error while adding reaction to queue post.')

        # Get Player Details (Classes/Subclasses, total level)
        player_details = parse_player_class(line_re.sub('', message.content).strip())

        # Create a Player Object.
        player: Player = Player.new(message.author, player_details)

        # Get our Queue
        queue = await queue_from_guild(self.db, self.bot.get_guild(server_id))

        # Are we already in a Queue?
        if queue.in_queue(player.member.id):
            if not self.bot.environment == 'testing':
                return None

        # Can we fit in an existing group?
        can_fit = queue.can_fit_in_group(player)
        if can_fit is not None:
            queue.groups[can_fit].players.append(player)
        # If we can't, let's make a new group for our Tier.
        else:
            new_group = Group.new(player.tier, [player])
            queue.groups.append(new_group)

        # Update Queue
        channel = self.bot.get_channel(channel_id)
        new_msg = await queue.update(self.bot, self.db, channel, self._last_message)
        self._last_message = new_msg


    @commands.command(name='claim')
    @commands.check_any(has_role('DM'), commands.is_owner())
    async def claim_group(self, ctx, group: int):
        """Claims a group from the queue."""
        # TODO: Rewrite Claim Group

    @commands.command(name='leave')
    @commands.check_any(has_role('Player'), commands.is_owner())
    async def leave_queue(self, ctx):
        """Takes you out of the current queue, if you are in it."""
        # TODO: Rewrite Leave Group

    @commands.command(name='move')
    @commands.check_any(has_role('Assistant'), commands.is_owner())
    async def move_player(self, ctx, original_group: int, player: discord.Member, new_group: int):
        """Moves a player to a different group. Requires the Assistant role."""
        # TODO: Rewrite Move Player

    @commands.command(name='create')
    @commands.check_any(commands.is_owner(), has_role('Assistant'))
    async def create_queue_member(self, ctx, member: discord.Member, tier: int):
        """Manually creates a queue entry. Must have a role called Assistant"""
        # TODO: Rewrite Create Queue Member

    @commands.command(name='queue')
    async def send_current_queue(self, ctx):
        """Sends the current queue."""
        # TODO: Rewrite Send Current Queue

    @commands.command(name='remove')
    @commands.check_any(has_role('Assistant'), commands.is_owner())
    async def remove_queue_member(self, ctx, player: discord.Member):
        """Moves a player to a different group. Requires the Assistant role."""
        # TODO: Rewrite Remove Member


def setup(bot):
    bot.add_cog(QueueChannel(bot))
