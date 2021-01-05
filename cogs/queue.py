import logging
import re

import discord
from discord.ext import commands

import utils.constants as constants
from cogs.models.queue_models import Player, Group, Queue
from utils.checks import has_role
from utils.functions import create_default_embed

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
    queue.groups.sort(key=lambda x: x.tier)
    return queue


def length_check(group_length, requested_length):
    if not 1 <= requested_length <= group_length:
        out = 'Invalid Group Number. '
        if group_length == 0:
            out += 'No groups available to select!'
        elif group_length == 1:
            out += 'Only one group to select.'
        else:
            out += f'Must be between 1 and {group_length}.'
        return out
    return None


class QueueChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_message = None

        self.member_converter = commands.MemberConverter()
        self.channel_converter = commands.TextChannelConverter()
        self.db = bot.mdb['player_queue']
        self.gate_db = bot.mdb['gate_list']

        self.server_id = constants.GATES_SERVER if self.bot.environment != 'testing' else constants.DEBUG_SERVER
        self.channel_id = constants.GATES_CHANNEL if self.bot.environment != 'testing' else constants.DEBUG_CHANNEL

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == constants.GATES_SERVER:
            return True
        if ctx.guild.id == constants.DEBUG_SERVER and self.bot.environment == 'testing':
            return True

    @commands.Cog.listener(name='on_message')
    async def queue_listener(self, message):
        if message.guild is None:
            return None

        if not (self.server_id == message.guild.id and self.channel_id == message.channel.id):
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
        queue = await queue_from_guild(self.db, self.bot.get_guild(self.server_id))

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
        channel = self.bot.get_channel(self.channel_id)
        new_msg = await queue.update(self.bot, self.db, channel)

    @commands.group(name='gates', invoke_without_command=True)
    @commands.check_any(has_role('Admin'), commands.is_owner())
    async def gates(self, ctx):
        """Lists all of the current registered Gates."""
        gates = await self.gate_db.find().to_list(None)
        embed = create_default_embed(ctx)
        out = [f':white_small_square: {gate["name"].title()} Gate - {gate["emoji"]}' for gate in gates]

        embed.title = 'List of Registered Gates'
        embed.description = '\n'.join(out)
        embed.set_footer(text=f'To add a gate, see {ctx.prefix}help gates add')
        return await ctx.send(embed=embed)

    @gates.command(name='add', aliases=['create', 'new'])
    @commands.check_any(has_role('Admin'), commands.is_owner())
    async def add_gate(self, ctx, gate_name: str, gate_emoji: str):
        """
        Creates a new gate name-to-emoji pair. Must have the Admin role to perform this action.
        **Will override if there is a gate with the same name!!**
        """
        await self.gate_db.update_one({'name': gate_name},
                                      {'$set': {'name': gate_name.lower(), 'emoji': gate_emoji}}, upsert=True)
        embed = create_default_embed(ctx)
        embed.title = 'New Gate Created!'
        embed.description = f'Gate {gate_name} has been set to {gate_emoji}'
        return await ctx.send(embed=embed)

    @gates.command(name='remove', aliases=['delete', 'del'])
    @commands.check_any(has_role('Admin'), commands.is_owner())
    async def remove_gate(self, ctx, gate_name: str):
        """
        Removes a registered gate from the database. **Requires Admin**
        """
        exists = await self.gate_db.find_one({'name': gate_name.lower()})
        if not exists:
            return await ctx.send(f'Could not find a gate with the name `{gate_name}`. Check `{ctx.prefix}gates` for '
                                  f'a list of registered gates.')
        await self.gate_db.delete_one({'name': gate_name.lower()})
        embed = create_default_embed(ctx)
        embed.title = 'Removed Gate!'
        embed.description = f'Gate {gate_name} has been removed from the database.'

        return await ctx.send(embed=embed)

    @commands.command(name='claim')
    @commands.check_any(has_role('DM'), commands.is_owner())
    async def claim_group(self, ctx, group: int, gate_name: str):
        """Claims a group from the queue."""
        queue = await queue_from_guild(self.db, ctx.guild)
        gate = await self.gate_db.find_one({'name': gate_name.lower()})
        if gate is None:
            return await ctx.send('Invalid Gate Name!')

        length = len(queue.groups)
        check = length_check(length, group)
        if check is not None:
            return await ctx.send(check)

        serv = self.bot.get_guild(self.server_id)
        # Take the gate off the list, save to DB & Update Embed
        popped = queue.groups.pop(group - 1)
        await queue.update(self.bot, self.db, serv.get_channel(self.channel_id))

        # Spit out a summons to #gate-summons
        summons_channel_id = constants.SUMMONS_CHANNEL if self.bot.environment != 'testing' \
            else constants.DEBUG_SUMMONS_CHANNEL

        summons_ch = serv.get_channel(summons_channel_id)
        assignments_ch = self.channel_converter.convert(ctx, 'assignments')
        if summons_ch is not None:
            msg = ', '.join([p.mention for p in popped.players]) + '\n'
            msg += f'Welcome to the {gate["name"].lower().title()} Gate! Head to {f"<#{assignments_ch.id}>" if assignments_ch is not None else "#assignments"}' \
                   f' and grab the {gate["emoji"]} from the list and head over to the gate!\n' \
                   f'Claimed by {ctx.author.mention}'
            await summons_ch.send(msg, allowed_mentions=discord.AllowedMentions(users=True))

    @commands.command(name='leave')
    @commands.check_any(has_role('Player'), commands.is_owner())
    async def leave_queue(self, ctx):
        """Takes you out of the current queue, if you are in it."""
        queue = await queue_from_guild(self.db, ctx.guild)

        group_index = queue.in_queue(ctx.author.id)
        if group_index is None:
            return await ctx.send('You are not currently in the queue, so I cannot remove you from it.',
                                  delete_after=10)

        # Pop the Player from the Group and Update!
        serv = self.bot.get_guild(self.server_id)
        queue.groups[group_index[0]].players.pop(group_index[1])
        await queue.update(self.bot, self.db, serv.get_channel(self.channel_id))

        return await ctx.send(f'You have been removed from group #{group_index[0] + 1}', delete_after=10)

    @commands.command(name='move')
    @commands.check_any(has_role('Assistant'), commands.is_owner())
    async def move_player(self, ctx, original_group: int, player: discord.Member, new_group: int):
        """Moves a player to a different group. Requires the Assistant role."""
        queue = await queue_from_guild(self.db, ctx.guild)

        group_index = queue.in_queue(player.id)
        if group_index is None:
            return await ctx.send(f'{player.mention} is not currently in the queue, so I cannot remove them from it.',
                                  delete_after=10)

        queue.groups.sort(key=lambda x: x.tier)

        length = len(queue.groups)
        check = length_check(length, original_group)
        check_2 = length_check(length, new_group)
        if check is not None:
            return await ctx.send(check)
        elif check_2 is not None:
            return await ctx.send(check_2)

        # Pop the Player from the old group and place them in the new group
        serv = self.bot.get_guild(self.server_id)
        old_group = queue.groups[original_group - 1]
        old_index = None
        for i, user in enumerate(old_group.players):
            if user.member.id == player.id:
                old_index = i
                break
        if old_index is None:
            return await ctx.send(f'Could not find {player.mention} in Group #{original_group}')
        old_player = queue.groups[original_group - 1].players.pop(old_index)
        queue.groups[new_group - 1].players.append(old_player)
        await queue.update(self.bot, self.db, serv.get_channel(self.channel_id))

        return await ctx.send(f'{player.mention} has been moved from Group #{original_group} to Group #{new_group}',
                              delete_after=10)

    @commands.command(name='queue')
    async def send_current_queue(self, ctx):
        """Sends the current queue."""
        queue = await queue_from_guild(self.db, ctx.guild)
        embed = queue.generate_embed(self.bot)
        embed.title = 'Gate Sign-Up Queue'
        return await ctx.send(embed=embed)

    @commands.command(name='remove')
    @commands.check_any(has_role('Assistant'), commands.is_owner())
    async def remove_queue_member(self, ctx, player: discord.Member):
        """Removes a player from Queue. Requires the Assistant role."""
        queue = await queue_from_guild(self.db, ctx.guild)

        group_index = queue.in_queue(player.id)
        if group_index is None:
            return await ctx.send(f'{player.mention} was not in the queue, so they have not been removed.',
                                  delete_after=10)

        # Pop the Player from the Group and Update!
        serv = self.bot.get_guild(self.server_id)
        queue.groups[group_index[0]].players.pop(group_index[1])
        await queue.update(self.bot, self.db, serv.get_channel(self.channel_id))

        return await ctx.send(f'{player.mention} has been removed from Group #{group_index[0] + 1}', delete_after=10)

    @commands.command(name='gateinfo')
    async def group_info(self, ctx, group_number: int):
        """Returns Information about a group."""
        queue = await queue_from_guild(self.db, ctx.guild)

        length = len(queue.groups)
        check = length_check(length, group_number)
        if check is not None:
            return await ctx.send(check)

        group = queue.groups[group_number - 1]
        group.players.sort(key=lambda x: x.member.display_name)

        embed = create_default_embed(ctx)
        embed.title = f'Information for Group #{group_number}'
        embed.description = '`'*3+'diff\n' + '\n'.join([f'- {player.member.display_name}: {player.level_str}' for player in group.players]) + '\n```'
        return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(QueueChannel(bot))
