import discord
from discord.ext import commands
import operator
import re
import datetime

from utils.functions import try_delete, create_default_embed
from utils.checks import has_role

tiers = {
    1: 1,
    5: 2,
    8: 3,
    11: 4,
    14: 5,
    17: 6,
    20: 7
}

line_re_1 = re.compile(re.escape('**in line**'), re.IGNORECASE)
line_re_2 = re.compile(re.escape('**in line:**'), re.IGNORECASE)


class ContextProxy:
    def __init__(self, bot, message):
        self.message = message
        self.bot = bot
        self.author = message.author


class QueueChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_embed = None
        self._last_message = None
        self.allowed_gid = 762026283177213982
        self.allowed_cid = 773895672415649832

        self.member_converter = commands.MemberConverter()

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == self.allowed_gid or ctx.guild.id == 774388983710220328:
            return True

    async def get_last_embed(self, delete=True):
        guild = self.bot.get_guild(self.allowed_gid)
        if guild is None:
            guild = self.bot.get_guild(774388983710220328)
        channel = guild.get_channel(self.allowed_cid)
        if channel is None:
            channel = guild.get_channel(787391243135090759)
        async for x in channel.history(limit=50):
            if not x.author.id == self.bot.user.id:
                continue
            if not x.embeds:
                continue

            prev_embed: discord.Embed = x.embeds[0]

            if prev_embed.title != 'Gate Sign-Up List':
                continue

            self._last_embed = prev_embed
            self._last_message = x

            if delete:
                await try_delete(x)
            break
        if self._last_embed is not None:
            self._last_embed.timestamp = datetime.datetime.utcnow()

    def sort_fields(self, embed):
        for i, field in enumerate(embed.fields):
            split = field.name.split()
            if len(split) == 3:
                embed.set_field_at(i, name=' '.join(split[1:]), value=field.value)

        x = sorted(((f.name, f.value) for f in embed.fields), key=operator.itemgetter(0))
        embed.clear_fields()
        _ = [embed.add_field(name=f'{i + 1}. {a[0]}',
                             value=a[1], inline=False) for i, a in enumerate(x)]
        return embed

    async def update_last_embed(self):
        if self._last_embed is None:
            await self.get_last_embed(delete=False)
            if self._last_embed is None:
                return None
        return True

    @commands.Cog.listener(name='on_message')
    async def queue_listener(self, message):
        if message.guild is None:
            return

        if message.guild.id != self.allowed_gid or message.channel.id != self.allowed_cid:
            if message.guild.id != 774388983710220328 or message.channel.id != 787391243135090759:
                return

        test_content = message.content.lower()
        if not (test_content.startswith('**in line:**') or test_content.startswith('**in line**')):
            return

        try:
            await message.add_reaction('<:d20:773638073052561428>')
        except:
            pass

        if self._last_message is not None:
            await try_delete(self._last_message)

        # Find Previous Embed
        prev_embed = None
        if self._last_embed is None:
            prev_embed = await self.get_last_embed()

        # Create an Embed if we can't find one
        if prev_embed is None:
            if self._last_embed:
                embed = self._last_embed
            else:
                embed = create_default_embed(ContextProxy(self.bot, message), title='Gate Sign-Up List')
                embed.remove_author()
        else:
            embed = prev_embed

        # Get Tier
        player_class = line_re_2.sub('', line_re_1.sub('', message.content)).strip()
        player_level = int(player_class.split()[2]) if player_class.split()[2].isdigit() else 4
        player_tier = ([1]+[tiers[tier] for tier in tiers if player_level >= tier])[-1]

        # print(f'{player_level=}, {player_tier=}, {player_class=}')

        # Go through and add fields
        did_add = False
        current_fields = embed.fields
        for i, field in enumerate(current_fields):
            tier = int(field.name.split()[2])
            if not tier == player_tier:
                continue
            players = field.value.split(', ')
            if len(players) >= 5:
                continue
            players.append(f'<@{message.author.id}>')
            embed.set_field_at(i, name=f'Rank {player_tier}', value=', '.join(players))
            did_add = True

        if not did_add:
            embed.add_field(name=f'Rank {player_tier}', value=f'<@{message.author.id}>')

        # Sort Fields
        embed = self.sort_fields(embed)

        # Send & Save
        self._last_embed = embed
        msg = await message.channel.send(embed=embed)
        self._last_message = msg

    @commands.command(name='claim')
    @commands.check_any(has_role('DM'), commands.is_owner())
    async def claim_group(self, ctx, group: int):
        """Claims a group from the queue."""

        update = await self.update_last_embed()
        if not update:
            return await ctx.send('Could not find a queue to claim. Please contact the developer if this is a mistake.')

        available_count = len(self._last_embed.fields)

        if group < 1 or group > available_count:
            if available_count == 1:
                return await ctx.send('You can only select group 1.')
            return await ctx.send(f'Group number must be between 1 and {available_count}')

        # Update Embed
        selected = self._last_embed.fields[group - 1]
        self._last_embed.remove_field(group - 1)

        self._last_embed = self.sort_fields(self._last_embed)

        new_msg = await self._last_message.channel.send(embed=self._last_embed)
        await try_delete(self._last_message)
        self._last_message = new_msg

        await ctx.send(f'{ctx.author.mention} has claimed group #{group}.')
        return await ctx.send(f'```{selected.value}```')

    @commands.command(name='leave')
    @commands.check_any(has_role('Player'), commands.is_owner())
    async def leave_queue(self, ctx):
        """Takes you out of the current queue, if you are in it."""
        update = await self.update_last_embed()
        if not update:
            return await ctx.send('Could not find a queue to leave. Please contact the developer if this is a mistake.')

        our_fields = [(i, x) for i, x in enumerate(self._last_embed.fields) if f'<@{ctx.author.id}>' in x.value]
        if not our_fields:
            return await ctx.send('You are currently not in any queue.'
                                  ' Please contact the developer if this is a mistake.')

        embed = self._last_embed

        # get field that we're in
        index = our_fields[0]
        field = index[1]

        # take the list of people and remove us, rebuild field
        people = field.value.split(', ')
        people.remove(f'<@{ctx.author.id}>')
        field.value = ', '.join(people)

        if len(field.value) == 0:
            embed.remove_field(index[0])
        else:
            embed.set_field_at(index[0], name=field.name, value=field.value)

        # Sort Fields
        embed = self.sort_fields(embed)
        self._last_embed = embed

        # Send new embed
        new_msg = await self._last_message.channel.send(embed=self._last_embed)
        await try_delete(self._last_message)
        self._last_message = new_msg

    @commands.command(name='move')
    @commands.check_any(has_role('Assistant'), commands.is_owner())
    async def move_player(self, ctx, original_group: int, player: discord.Member, new_group: int):
        """Moves a player to a different group. Requires the Assistant role."""

        if original_group == new_group:
            return await ctx.send('Original group equals the new group, exiting.')

        update = await self.update_last_embed()
        if not update:
            return await ctx.send('Could not find a queue to edit. Please contact the developer if this is a mistake.')

        available_count = len(self._last_embed.fields)

        if (original_group < 1 or original_group > available_count) or (new_group < 1 or new_group > available_count):
            if available_count == 1:
                return await ctx.send('You can only select group 1.')
            return await ctx.send(f'Group number must be between 1 and {available_count}')

        our_fields = [(i, x) for i, x in enumerate(self._last_embed.fields) if f'<@{player.id}>' in x.value]
        if not our_fields:
            return await ctx.send(f'{player.display_name} is currently not in any queue.'
                                  f' Please contact the developer if this is a mistake.')

        # Does the Original Group intersect a field we are in?
        intersect = next((f for f in our_fields if f[0]+1 == original_group), None)
        if not intersect:
            return await ctx.send('Could not find player in original group. Please contact the developer if this is '
                                  'a mistake.')

        embed = self._last_embed

        # Remove Person from Old Field
        intersected = embed.fields[intersect[0]]
        people = intersected.value.split(', ')
        people.remove(f'<@{player.id}>')
        intersected.value = ', '.join(people)
        if intersected.value:
            embed.fields[intersect[0]] = intersected
            embed.set_field_at(intersect[0], name=intersected.name, value=intersected.value)
        else:
            embed.remove_field(intersect[0])
            if new_group > len(embed.fields):
                new_group -= 1

        # Add person to New Field
        new_field = embed.fields[new_group - 1]
        new_people = new_field.value.split(', ')
        new_people.append(f'<@{player.id}>')
        new_field.value = ', '.join(new_people)
        embed.set_field_at(new_group-1, name=new_field.name, value=new_field.value)

        # Sort & Set
        embed = self.sort_fields(embed)
        self._last_embed = embed

        # Send new embed
        new_msg = await self._last_message.channel.send(embed=self._last_embed)
        await try_delete(self._last_message)
        self._last_message = new_msg

    @commands.command(name='create')
    @commands.check_any(commands.is_owner(), has_role('Assistant'))
    async def create_queue_member(self, ctx, member: discord.Member, tier: int):
        """Manually creates a queue entry. Must have a role called Assistant"""
        update = await self.update_last_embed()
        if not update:
            return await ctx.send('Could not find a queue to edit. Please contact the developer if this is a mistake.')

        # Get Tier
        player_tier = tier
        embed = self._last_embed

        # Go through and add fields
        did_add = False
        current_fields = embed.fields
        for i, field in enumerate(current_fields):
            tier = int(field.name.split()[2])
            if not tier == player_tier:
                continue
            players = field.value.split(', ')
            if len(players) >= 5:
                continue
            players.append(f'<@{member.id}>')
            embed.set_field_at(i, name=f'Rank {player_tier}', value=', '.join(players))
            did_add = True

        if not did_add:
            embed.add_field(name=f'Rank {player_tier}', value=f'<@{member.id}>')

        # Sort Fields
        embed = self.sort_fields(embed)

        # Send & Save
        self._last_embed = embed
        msg = await self._last_message.channel.send(embed=embed)
        self._last_message = msg

    @commands.command(name='queue')
    async def send_current_queue(self, ctx):
        """Sends the current queue."""
        update = await self.update_last_embed()
        if not update:
            return await ctx.send('Could not find a queue to edit. Please contact the developer if this is a mistake.')

        return await ctx.send(embed=self._last_embed)

    @commands.command(name='remove')
    @commands.check_any(has_role('Assistant'), commands.is_owner())
    async def remove_queue_member(self, ctx, player: discord.Member):
        """Moves a player to a different group. Requires the Assistant role."""

        update = await self.update_last_embed()
        if not update:
            return await ctx.send('Could not find a queue to edit. Please contact the developer if this is a mistake.')

        our_fields = next(((i, x) for i, x in enumerate(self._last_embed.fields) if f'<@{player.id}>' in x.value), None)
        if not our_fields:
            return await ctx.send(f'{player.display_name} is currently not in any queue.'
                                  f' Please contact the developer if this is a mistake.')

        embed = self._last_embed

        intersected = our_fields[1]
        people = intersected.value.split(', ')
        people.remove(f'<@{player.id}>')
        intersected.value = ', '.join(people)
        if intersected.value:
            embed.set_field_at(our_fields[0], name=intersected.name, value=intersected.value)
        else:
            embed.remove_field(our_fields[0])

        # Sort & Set
        embed = self.sort_fields(embed)
        self._last_embed = embed

        # Send new embed
        new_msg = await self._last_message.channel.send(embed=self._last_embed)
        await try_delete(self._last_message)
        self._last_message = new_msg


def setup(bot):
    bot.add_cog(QueueChannel(bot))
