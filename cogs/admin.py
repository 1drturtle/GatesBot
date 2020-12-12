from discord.ext import commands
import discord
from utils.functions import create_default_embed


def channel_id_to_link(channel_id):
    if isinstance(channel_id, discord.TextChannel):
        channel_id = channel_id.id
    return f'<#{channel_id}>'


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---- Bot Owner Commands ----
    @commands.group(name='admin', invoke_without_command=True)
    @commands.is_owner()
    async def admin(self, ctx):
        """
        Owner only commands for the bot.
        """
        await ctx.send('give a subcommand nerd')

    @admin.command(name="restart")
    @commands.is_owner()
    async def restart(self, ctx):
        """
        Stops the bot, restarting it.
        """
        confirm = await ctx.prompt('Are you sure you want to shutdown the bot?')
        if confirm:
            try:
                await self.bot.logout()
            except RuntimeError:
                pass

    @admin.command(name='leave')
    @commands.is_owner()
    async def leave_guild(self, ctx, guild_id: int):
        """
        Leaves the specified guild
        """
        to_leave: discord.Guild = self.bot.get_guild(guild_id)
        if to_leave is not None:
            await ctx.send(f'Leaving Guild: `{to_leave.name}`')
            try:
                await to_leave.leave()
            except discord.HTTPException:
                pass
        else:
            return await ctx.send('Guild not found.')

    # ---- Server Owner Commands ----

    @commands.command(name='prefix', description='Changes the Bot\'s Prefix. Must have Manage Server.')
    @commands.check_any(commands.has_guild_permissions(manage_guild=True), commands.is_owner())
    @commands.guild_only()
    async def change_prefix(self, ctx, to_change: str = None):
        """
        Changes the prefix for the current guild

        Can only be ran in a guild. If no prefix is specified, will show the current prefix.
        """
        guild_id = str(ctx.guild.id)
        if to_change is None:
            if guild_id in self.bot.prefixes:
                prefix = self.bot.prefixes.get(guild_id, self.bot.prefix)
            else:
                dbsearch = await self.bot.mdb['prefixes'].find_one({'guild_id': guild_id})
                if dbsearch is not None:
                    prefix = dbsearch.get('prefix', self.bot.prefix)
                else:
                    prefix = self.bot.prefix
                self.bot.prefixes[guild_id] = prefix
            return await ctx.send(f'No prefix specified to Change. Current Prefix: `{prefix}`')
        else:
            await ctx.bot.mdb['prefixes'].update_one({'guild_id': guild_id},
                                                     {'$set': {'prefix': to_change}}, upsert=True)
            ctx.bot.prefixes[guild_id] = to_change
            return await ctx.send(f'Guild prefix updated to `{to_change}`')


def setup(bot):
    bot.add_cog(Admin(bot))
