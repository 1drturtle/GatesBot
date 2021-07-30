import pymongo
from discord.ext import commands
import discord

import utils.constants as constants
import logging
from utils.functions import create_queue_embed, try_delete, create_default_embed
from utils.checks import has_role
import asyncio
from cogs.queue import queue_from_guild, length_check
from cogs.models.queue_models import Queue

log = logging.getLogger(__name__)


class DMQueue(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.queue_channel_id = constants.DM_QUEUE_CHANNEL_DEBUG if self.bot.environment == 'testing' else \
            constants.DM_QUEUE_CHANNEL
        self.assign_id = constants.DM_QUEUE_ASSIGNMENT_CHANNEL_DEBUG if self.bot.environment == 'testing' else \
            constants.DM_QUEUE_ASSIGNMENT_CHANNEL
        self.server_id = constants.GATES_SERVER if self.bot.environment != 'testing' else constants.DEBUG_SERVER

        self.db = self.bot.mdb['dm_queue']

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == constants.GATES_SERVER:
            return True
        if ctx.guild.id == constants.DEBUG_SERVER and self.bot.environment == 'testing':
            return True

    @commands.Cog.listener(name='on_message')
    async def dm_queue_listener(self, msg):

        if msg.channel.id != self.queue_channel_id:
            return

        if not msg.content.lower().startswith('**ready'):
            return

        content = discord.utils.remove_markdown(msg.content.lower())
        rank_content = content.replace('ready: ', '').strip()

        content = {
            '$set': {
                'ranks': rank_content,
                'msg': msg.id
            },
            '$currentDate': {'readyOn': True}
        }

        await self.db.update_one(
            {'_id': msg.author.id}, content, upsert=True
        )

        try:
            await msg.add_reaction('\U0001f44d')
        except:
            pass

        await self.update_queue()

    async def update_queue(self):

        await asyncio.sleep(1)

        guild = self.bot.get_guild(self.server_id)
        ch = guild.get_channel(self.queue_channel_id)

        data = await self.db.find().sort('readyOn', pymongo.ASCENDING).to_list(None)
        embed = create_queue_embed(self.bot)

        out = []

        embed.title = 'DM Queue'

        for i, item in enumerate(data):
            member = guild.get_member(item.get('_id'))
            cur = f'**#{i + 1}.** {member.mention} - {item.get("ranks").title()}'
            out.append(cur)

        embed.description = '\n'.join(out)

        # find old & delete
        history = await ch.history(limit=50).flatten()
        for msg in history:
            if len(msg.embeds) != 1 or msg.author.id != self.bot.user.id:
                continue

            old_embed = msg.embeds[0]

            if old_embed.title != 'DM Queue':
                continue

            await try_delete(msg)

        # send new
        await ch.send(embed=embed)

    @commands.group(name='dm', invoke_without_command=True)
    async def dm(self, ctx):
        """Base command for DM queue"""
        await ctx.send_help(self.dm)

    @dm.command(name='assign')
    @has_role('Admin')
    async def dm_assign(self, ctx, queue_num: int, group_num: int):
        """
        Assigns a DM to a group
        `queue_num` - The DM's queue number
        `group_num` - The group's number (from the base queue)
        """

        ch = ctx.guild.get_channel(self.assign_id)

        dm_data = await self.db.find().sort('readyOn', pymongo.ASCENDING).to_list(None)
        if len(dm_data) == 0:
            return await ctx.send('No DMs currently in DM queue.')
        if queue_num > (size := len(dm_data)):
            return await ctx.send(f'Invalid DM Queue number. Must be less than or equal to {size}')
        elif queue_num < 1:
            return await ctx.send(f'Invalid DM Queue number. Must be at least 1.')

        dm = dm_data[(queue_num - 1)]
        who = ctx.guild.get_member(dm.get('_id'))

        gates_data: Queue = await queue_from_guild(self.bot.mdb['player_queue'], ctx.guild)
        check = length_check(len(gates_data.groups), group_num)
        if check is not None:
            return await ctx.send(check)

        group = gates_data.groups[group_num - 1]
        msg = f'Group {group_num} is yours, see above for details.' \
              f' Don\'t forget to submit your encounter in <#798247432743551067> once ready and claim once approved!' \
              f' Kindly note that this is a **{len(group.players)} person Rank {group.tier}** ' \
              f'group and adjust your encounter as needed.' \
              f' Please react to this message if you are, indeed, claiming.' \
              f' **__Double check the Group # in <#773895672415649832> when claiming please!__**'
        embed = create_queue_embed(self.bot)
        embed.title = 'Gate Assignment'
        embed.description = msg

        group.players.sort(key=lambda x: x.member.display_name)

        embed2 = create_queue_embed(self.bot)
        embed2.title = f'Information for Group #{group_num}'
        embed2.description = '`' * 3 + 'diff\n' + '\n'.join([f'- {player.member.display_name}:'
                                                             f' {player.level_str}' for player in
                                                             group.players]) + '\n```'
        await ch.send(embed=embed2)
        await ch.send(f'{who.mention}', embed=embed,
                       allowed_mentions=discord.AllowedMentions(users=True))

        await self.db.delete_one({'_id': who.id})
        await self.update_queue()

    @dm.command(name='leave')
    @has_role('DM')
    async def dm_leave(self, ctx):
        """Leave the DM queue."""
        embed = create_default_embed(ctx)
        embed.title = 'DM Queue Left.'
        embed.description = 'If you were previously in the DM queue, you have been removed from it.'

        try:
            await self.db.delete_one({'_id': ctx.author.id})
        except:
            pass
        else:
            await self.update_queue()

        await ctx.send(embed=embed, delete_after=10)


def setup(bot):
    bot.add_cog(DMQueue(bot))
