from discord.ext import commands

from utils.functions import create_default_embed
from utils.checks import has_role


class Gates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='dmcalc', aliases=['xp', 'calc'])
    @commands.check_any(has_role('DM'), commands.is_owner())
    async def xp_calc(self, ctx, total_xp: int, player_count: int, modifier: float = 1):
        """
        Performs the XP calculations for a gate.
        Usage `=xpcalc <Total XP> <# of Players> [modifier]`
        **Requires DM Role**
        """
        xp_player = total_xp // player_count
        xp_player_modified = round(xp_player * modifier)
        gold_player = xp_player // 4
        xp_dm = xp_player // 3
        gold_dm = gold_player // 3
        if modifier != 1:
            xp_dm = xp_player_modified // 3

        embed = create_default_embed(ctx)
        embed.title = 'XP Calcuations'
        embed.add_field(name='Total XP',
                        value=f'{total_xp}{" (x"+str(modifier)+")" if modifier != 1 else ""}')
        embed.add_field(name='Number of Players', value=f'{player_count}')
        embed.add_field(name='XP per Player', value=f'{xp_player}')
        if modifier != 1:
            embed.add_field(name='XP Per Player (Modified)', value=f'{xp_player_modified}')
        embed.add_field(name='Gold per Player', value=f'{gold_player}')
        embed.add_field(name='XP for DM', value=f'{xp_dm}')
        embed.add_field(name='Gold for DM', value=f'{gold_dm}')

        return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Gates(bot))
