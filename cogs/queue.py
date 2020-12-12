import discord
from discord.ext import commands
import operator

from utils.functions import try_delete, create_default_embed

tiers = {
    1: 1,
    5: 2,
    8: 3,
    11: 4,
    14: 5,
    17: 6,
    20: 7
}


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
        self.allowed_gid = 774388983710220328
        self.allowed_cid = 787391243135090759

        self.member_converter = commands.MemberConverter()

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id == self.allowed_gid:
            return True

    async def get_last_embed(self, delete=True):
        channel = self.bot.get_guild(self.allowed_gid).get_channel(self.allowed_cid)
        async for x in channel.history(limit=50):
            if not x.author.id == self.bot.user.id:
                continue
            if not x.embeds:
                continue

            prev_embed: discord.Embed = x.embeds[0]
            self._last_embed = prev_embed
            self._last_message = x

            if delete:
                await try_delete(x)
            break

    def sort_fields(self, embed):
        x = sorted([(f.name, f.value) for f in embed.fields], key=operator.itemgetter(0))
        embed.clear_fields()
        _ = [embed.add_field(name=f'{i + 1}. {a[0] if len(a[0].split()) == 2 else " ".join(a[0].split()[1:])}',
                             value=a[1], inline=False) for i, a in enumerate(x)]
        return embed

    @commands.Cog.listener(name='on_message')
    async def queue_listener(self, message):
        if message.guild is None:
            return

        if message.guild.id != self.allowed_gid or message.channel.id != self.allowed_cid:
            return

        test_content = message.content.lower()
        if not (test_content.startswith('**in line:**') or test_content.startswith('**in line**')):
            return

        try:
            await message.add_reaction('<:online:787390858440736798>')
        except:
            pass

        player_class = message.content.lstrip('**In Line:**').lstrip('**In Line**')
        player_name = message.author.display_name

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
                embed = create_default_embed(ContextProxy(self.bot, message))
        else:
            embed = prev_embed

        # Get Tier
        player_level = int(player_class.split()[2]) if player_class.split()[2].isdigit() else 4
        player_tier = ([1]+[tiers[tier] for tier in tiers if player_level >= tier])[-1]

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
    async def claim_group(self, ctx, group: int):
        """Claims a group from the queue."""

        if self._last_embed is None:
            await self.get_last_embed(delete=False)
            if self._last_embed is None:
                return await ctx.send('Could not find a Queue. Please contact the developer if this is a mistake.')

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

        return await ctx.send(f'{ctx.author.display_name} has claimed group #{group}. Here are the mentions - \n'
                              f'{selected.value}')

    @commands.command(name='leave')
    async def leave_queue(self, ctx):
        """Takes you out of the current queue, if you are in it."""
        if self._last_embed is None:
            await self.get_last_embed(delete=False)
            if self._last_embed is None:
                return await ctx.send('Could not find a Queue. Please contact the developer if this is a mistake.')

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

        # Send new emebd
        new_msg = await self._last_message.channel.send(embed=self._last_embed)
        await try_delete(self._last_message)
        self._last_message = new_msg




def setup(bot):
    bot.add_cog(QueueChannel(bot))
