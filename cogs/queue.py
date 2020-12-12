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
        self.allowed_gid = [774388983710220328]
        self.allowed_cid = [787174754506768404]

    async def cog_check(self, ctx):
        if not ctx.guild:
            return False
        if ctx.guild.id in self.allowed_gid:
            return True

    @commands.Cog.listener(name='on_message')
    async def queue_listener(self, message):
        if message.guild is None:
            return

        if message.guild.id not in self.allowed_gid or message.channel.id not in self.allowed_cid:
            return

        if not message.content.startswith('**In Line:**'):
            return

        try:
            await message.add_reaction('<:eyes:>')
        except:
            pass

        player_class = message.content.lstrip('**In Line:**')
        player_name = message.author.display_name

        if self._last_message is not None:
            await try_delete(self._last_message)

        # Find Previous In-Line Embed and delete it
        prev_embed = None
        if self._last_embed is None:
            async for x in message.channel.history(limit=50):
                if not x.author.id == self.bot.user.id:
                    continue
                if not x.embeds:
                    continue

                prev_embed: discord.Embed = x.embeds[0]
                self._last_embed = prev_embed
                self._last_message = x

                await try_delete(x)
                break

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

        did_add = False
        current_fields = embed.fields
        for i, field in enumerate(current_fields):
            tier = int(field.name.split()[1])
            if not tier == player_tier:
                continue
            players = field.value.split(', ')
            if len(players) >= 5:
                continue
            players.append(player_name)
            embed.set_field_at(i, name=f'Tier {player_tier}', value=', '.join(players))
            did_add = True

        if not did_add:
            embed.add_field(name=f'Tier {player_tier}', value=player_name)

        # Sort Fields
        x = sorted([(f.name, f.value) for f in embed.fields], key=operator.itemgetter(0))
        embed.clear_fields()
        _ = [embed.add_field(name=a[0], value=a[1], inline=False) for a in x]

        # Send & Save
        self._last_embed = embed
        msg = await message.channel.send(embed=embed)
        self._last_message = msg

    @commands.command(name='claim')
    async def claim_group(self, ctx, group: int):
        """Claims a group from the queue."""
        await ctx.send(group)


def setup(bot):
    bot.add_cog(QueueChannel(bot))
