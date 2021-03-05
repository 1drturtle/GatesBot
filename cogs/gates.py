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
        self.settings_db = bot.mdb['placeholder-settings']
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
        log.debug('running placeholder loop!')
        for document in await cursor.to_list(length=None):
            setting = await self.settings_db.find_one({'user_id': document["author_id"]})
            if setting is None:
                setting = 1
            else:
                setting = setting['hours']

            if ((document['message_date'] + datetime.timedelta(hours=setting)) - utc_now).seconds <= (15 * 60):  # ten minutes
                log.info(f'scheduling placeholder for {document["_id"]}')
                self.bot.loop.create_task(self.run_placeholder_reminder(document, setting))
                await self.placeholder_db.delete_one({'message_id': document['message_id']})

    async def run_placeholder_reminder(self, placeholder_data: dict, hours: int = 1):
        """
        Takes the data from the databases and waits until message date + 1 hour, and then sends them a DM
        :param dict placeholder_data: Data to run the reminder, fetched from the database.
        :param int hours: Number of hours to wait after message before a PM is sent.
        """
        # wait until an hour has passed from the original message
        future = placeholder_data['message_date'] + datetime.timedelta(hours=hours)
        await discord.utils.sleep_until(future)
        log.info(f'running placeholder for {placeholder_data["_id"]}')
        # get data from bot
        guild = self.bot.get_guild(placeholder_data['guild_id'])
        member = guild.get_member(placeholder_data['author_id'])
        channel = guild.get_channel(placeholder_data['channel_id'])
        message = await channel.fetch_message(placeholder_data['message_id'])

        if '*ph*' not in (content := message.content.lower()) and '*placeholder*' not in content \
                or message is None:
            # stop if the message is gone or the placeholder is done
            return None

        ContextProxy = namedtuple('ContextProxy', ['message', 'bot', 'author'])
        ctx = ContextProxy(message, self.bot, member)

        try:
            hour_str = f'{hours} hours'
            if hours == 1:
                hour_str = '1 hour'
            embed = create_default_embed(ctx, title='Placeholder Reminder!')
            embed.description = f'You sent a placeholder in {channel.mention} that hasn\'t been updated in {hour_str}!\n' \
                                f'[Here\'s a link to the message]({message.jump_url})\n'
            return await member.send(embed=embed)
        except Exception:
            log.debug(f'Could not send placeholder reminder to {member.name}')

    @check_db_placeholders.before_loop
    async def before_check_db_placeholders(self):
        await self.bot.wait_until_ready()

    @commands.command(name='updatetime')
    async def placeholder_update_setting(self, ctx, hours: int = None):
        """
        Sets the amount of hours to wait before sending a placeholder notification. If no argument is specified, shows the current setting.

        `hours` - Number of hours to wait. Must be greater than or equal to one.
        """
        embed = create_default_embed(ctx)
        if hours is None:
            embed.title = 'Current Placeholder Setting'
            db_result = await self.settings_db.find_one({'user_id': ctx.author.id})
            if db_result is None:
                db_result = 1
            else:
                db_result = db_result['hours']
            embed.description = f'The current setting is to send a reminder after {db_result} hour' \
                                f'{"s" if db_result != 1 else ""}.'
            return await ctx.send(embed=embed)

        if hours < 1:
            raise commands.BadArgument("`hours` must be greater or equal to one.")

        await self.settings_db.update_one({'user_id': ctx.author.id}, {'$set': {'hours': hours}}, upsert=True)
        embed.title = 'Placeholder settings updated!'
        embed.description = f'The current setting is now to send a reminder after {hours} hour' \
                            f'{"s" if hours != 1 else ""}.'

        return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Gates(bot))
