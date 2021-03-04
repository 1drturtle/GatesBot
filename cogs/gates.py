from discord.ext import commands
from discord.ext import tasks
import discord
import datetime
import logging

from collections import namedtuple
from utils.functions import create_default_embed
from utils.checks import has_role
from utils import constants as constants

PLACEHOLDER_POLL_TIME = 300

log = logging.getLogger(__name__)

class Gates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.placeholder_db = bot.mdb['placeholder_events']
        self.server_id = constants.GATES_SERVER if self.bot.environment != 'testing' else constants.DEBUG_SERVER
        self.db_task = self.check_db_placeholders.start()

    def cog_unload(self):
        self.db_task.cancel()

    @commands.command(name='dmcalc', aliases=['xp', 'calc'])
    @commands.check_any(has_role('DM'), commands.is_owner())
    async def xp_calc(self, ctx, total_xp: int, player_count: int, modifier: float = 1):
        """
        Performs the XP calculations for a gate.
        Usage `=dmcalc <Total XP> <# of Players> [modifier]`
        **Requires DM Role**
        """
        xp_player = total_xp // player_count
        xp_player_modified = round(xp_player * modifier)
        gold_player = xp_player // 4

        embed = create_default_embed(ctx)
        embed.title = 'XP Calculations'
        embed.add_field(name='Total XP',
                        value=f'{total_xp}{" (x" + str(modifier) + ")" if modifier != 1 else ""}')
        embed.add_field(name='Number of Players', value=f'{player_count}')
        embed.add_field(name='XP per Player', value=f'{xp_player}')
        if modifier != 1:
            embed.add_field(name='XP Per Player (Modified)', value=f'{xp_player_modified}')
        embed.add_field(name='Gold per Player', value=f'{gold_player}')

        return await ctx.send(embed=embed)

    @commands.Cog.listener(name='on_message')
    async def placeholder_listener(self, message):
        """
        Listens to a message to see if it's a placeholder in an IC channel.
        """

        # stop if we're not in the right guild
        if not message.guild:
            return

        if not message.guild.id == self.server_id:
            return

        # stop if they don't have the role
        if not discord.utils.find(lambda r: r.name == 'Placeholder Notifications', message.author.roles):
            return

        # stop if the channel is wrong
        if '-ic' not in message.channel.name.lower():
            return

        # stop if there's no placeholder:
        if '*ph*' not in (content := message.content.lower()) and '*placeholder*' not in content:
            return

        # register the placeholder in the database
        data = {
            'author_id': message.author.id,
            'guild_id': message.guild.id,
            'channel_id': message.channel.id,
            'message_id': message.id,
            'message_date': datetime.datetime.utcnow()
        }

        await self.placeholder_db.insert_one(data)

    @tasks.loop(seconds=300)
    async def check_db_placeholders(self):
        """
        Goes through each db document to see if it's time to schedule an event for reminder. Happens
        when the message date + 1 hour is within 10 minutes of now.
        """
        cursor = self.placeholder_db.find().sort('message_date')
        utc_now = datetime.datetime.utcnow()
        for document in await cursor.to_list(length=None):
            if (document['message_date'] - utc_now).seconds >= (10 * 60):  # ten minutes
                self.bot.loop.create_task(self.run_placeholder_reminder(document))

    async def run_placeholder_reminder(self, placeholder_data: dict):
        """
        Takes the data from the databases and waits until message date + 1 hour, and then sends them a DM
        :param dict placeholder_data: Data to run the reminder, fetched from the database.
        """
        # wait until an hour has passed from the original message
        future = placeholder_data['message_date'] + datetime.timedelta(hours=1)
        await discord.utils.sleep_until(future)
        # get data from bot
        guild = self.bot.get_guild(placeholder_data['guild_id'])
        member = guild.get_member(placeholder_data['author_id'])
        channel = guild.get_channel(placeholder_data['channel_id'])
        message = await channel.fetch_message(placeholder_data['message_id'])

        if '*ph*' not in (content := message.content.lower()) and '*placeholder*' not in content\
                or message is None:
            # stop if the message is gone or the placeholder is done
            return await self.placeholder_db.delete_one({'message_id': placeholder_data['message_id']})

        ContextProxy = namedtuple('ContextProxy', ['message', 'bot', 'author'])
        ctx = ContextProxy(message, self.bot, member)

        try:
            embed = create_default_embed(ctx, title='Placeholder Reminder!')
            embed.description = f'You sent a placeholder in {channel.mention} that hasn\'t been updated in an hour!\n' \
                                f'[Here\'s a link to the message]({message.jump_url})\n'
            await self.placeholder_db.delete_one({'message_id': placeholder_data['message_id']})
            return await member.send(embed=embed)
        except Exception:
            log.debug(f'Could not send placeholder reminder to {member.name}')

    @check_db_placeholders.before_loop
    async def before_check_db_placeholders(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(Gates(bot))
