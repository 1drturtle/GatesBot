from discord.ext import commands
from discord.ext import tasks
import discord
import datetime
import logging
import pendulum

from collections import namedtuple
from utils.functions import create_default_embed
from utils.checks import has_role
from utils import constants as constants
import typing
from tabulate import tabulate

PLACEHOLDER_POLL_TIME = 300

log = logging.getLogger(__name__)


class Gates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.placeholder_db = bot.mdb["placeholder_events"]
        self.settings_db = bot.mdb["placeholder-settings"]
        self.active_db = bot.mdb["active_users"]
        self.server_id = constants.GATES_SERVER if self.bot.environment != "testing" else constants.DEBUG_SERVER
        self.db_task = self.check_db_placeholders.start()

    def cog_unload(self):
        self.db_task.cancel()

    @commands.Cog.listener(name="on_message")
    async def placeholder_listener(self, message):
        """
        Listens to a message to see if it's a placeholder in an IC channel.
        """

        # stop if we're not in the right guild
        if not message.guild:
            return

        if not message.guild.id == self.server_id:
            return

        if message.author.bot:
            return

        # get the member
        member = message.guild.get_member(message.author.id)
        if member is None:
            log.info(f"could not find member info for user {message.author.name}#{message.author.discriminator}")
            return

        # stop if they don't have the role
        if not discord.utils.find(lambda r: r.name == "Placeholder Notifications", member.roles):
            return

        # stop if the channel is wrong
        if "-ic" not in message.channel.name.lower():
            return

        # stop if there's no placeholder:
        if not any([x in message.content.lower() for x in ["*ph*", "*placeholder*", "_ph_", "_placeholder_"]]):
            return

        # register the placeholder in the database
        data = {
            "author_id": message.author.id,
            "guild_id": message.guild.id,
            "channel_id": message.channel.id,
            "message_id": message.id,
            "message_date": datetime.datetime.utcnow(),
        }

        await self.placeholder_db.insert_one(data)

    @tasks.loop(seconds=300)
    async def check_db_placeholders(self):
        """
        Goes through each db document to see if it's time to schedule an event for reminder. Happens
        when the message date + 1 hour is within 10 minutes of now.
        """
        cursor = self.placeholder_db.find().sort("message_date")
        utc_now = datetime.datetime.utcnow()
        log.debug("running placeholder loop!")
        scheduled = []
        for document in await cursor.to_list(length=None):
            setting = await self.settings_db.find_one({"user_id": document["author_id"]})
            setting = setting.get("hours", 1) if setting else 1

            if ((document["message_date"] + datetime.timedelta(hours=setting)) - utc_now).total_seconds() <= (
                15 * 60
            ):  # ten minutes
                await self.placeholder_db.delete_one({"message_id": document["message_id"]})
                self.bot.loop.create_task(self.run_placeholder_reminder(document, setting))
                scheduled.append(document)

        if scheduled:
            log.debug(f"[Placeholder] {len(scheduled)} placeholder(s) have been scheduled.")

    async def run_placeholder_reminder(self, placeholder_data: dict, hours: int = 1):
        """
        Takes the data from the databases and waits until message date + 1 hour, and then sends them a DM
        :param dict placeholder_data: Data to run the reminder, fetched from the database.
        :param int hours: Number of hours to wait after message before a PM is sent.
        """
        # wait until an hour has passed from the original message
        future = placeholder_data["message_date"] + datetime.timedelta(hours=hours)
        await discord.utils.sleep_until(future)

        # get data from bot
        guild = self.bot.get_guild(placeholder_data["guild_id"])
        member = guild.get_member(placeholder_data["author_id"])
        channel = guild.get_channel(placeholder_data["channel_id"])

        try:
            log.info(f"[Placheholder] running placeholder for {member.display_name} in #{channel.name}")
        except:
            pass
        try:
            message = await channel.fetch_message(placeholder_data["message_id"])
        except discord.NotFound:
            return None

        if message is None or not any(
            [x in message.content.lower() for x in ["*ph*", "*placeholder*", "_ph_", "_placeholder_"]]
        ):
            # stop if the message is gone or the placeholder is done
            return None

        ContextProxy = namedtuple("ContextProxy", ["message", "bot", "author"])
        ctx = ContextProxy(message, self.bot, member)

        try:
            hour_str = f"{hours} hours"
            if hours == 1:
                hour_str = "1 hour"
            embed = create_default_embed(ctx, title="Placeholder Reminder!")
            embed.description = (
                f"You sent a placeholder in {channel.mention} that hasn't been updated in {hour_str}!\n"
                f"[Here's a link to the message]({message.jump_url})\n"
            )
            return await member.send(embed=embed)
        except Exception:
            log.debug(f"Could not send placeholder reminder to {member.name}")

    @check_db_placeholders.before_loop
    async def before_check_db_placeholders(self):
        await self.bot.wait_until_ready()

    @commands.command(name="updatetime")
    async def placeholder_update_setting(self, ctx, hours: int = None):
        """
        Sets the amount of hours to wait before sending a placeholder notification. If no argument is specified, shows the current setting.

        `hours` - Number of hours to wait. Must be greater than or equal to one.
        """
        embed = create_default_embed(ctx)
        if hours is None:
            embed.title = "Current Placeholder Setting"
            db_result = await self.settings_db.find_one({"user_id": ctx.author.id})
            if db_result is None:
                db_result = 1
            else:
                db_result = db_result["hours"]
            embed.description = (
                f"The current setting is to send a reminder after {db_result} hour" f'{"s" if db_result != 1 else ""}.'
            )
            return await ctx.send(embed=embed)

        if hours < 1:
            raise commands.BadArgument("`hours` must be greater or equal to one.")

        await self.settings_db.update_one({"user_id": ctx.author.id}, {"$set": {"hours": hours}}, upsert=True)
        embed.title = "Placeholder settings updated!"
        embed.description = (
            f"The current setting is now to send a reminder after {hours} hour" f'{"s" if hours != 1 else ""}.'
        )

        return await ctx.send(embed=embed)

    @commands.Cog.listener("on_message")
    async def user_active_updater(self, message):
        # stop if we're not in the right guild
        if not message.guild:
            return

        if not message.guild.id == self.server_id:
            return

        if message.author.bot:
            return

        # store the data
        return await self.active_db.update_one(
            {"_id": message.author.id},
            {"$set": {"_id": message.author.id}, "$currentDate": {"last_post": True}},
            upsert=True,
        )

    # @commands.command(name='inactiveusers', aliases=['inactive'])
    # @commands.check_any(commands.is_owner(), has_role('Admin'))
    # async def inactiveusers(self, ctx, weeks=2):
    #     """
    #     Shows users who have not posted in X amount of weeks.
    #     Requires the Admin role
    #
    #     `weeks` - Amount of weeks to check for. Defaults to 2.
    #     """
    #     the_past = datetime.datetime.fromtimestamp(pendulum.now(tz=pendulum.tz.UTC).subtract(weeks=weeks).timestamp())
    #     data = await self.active_db.find({
    #         'last_post': {'$lte': the_past}
    #     }).to_list(None)
    #
    #     paginator = commands.Paginator()
    #
    #     out_data: typing.List[list] = []
    #     for item in data:
    #         user = self.bot.get_guild(self.server_id).get_member(item['_id'])
    #         if user is None:
    #             log.info(f'member {item["_id"]} not found - removing from database.')
    #             await self.active_db.delete_one({'_id': item['_id']})
    #             continue
    #         last = pendulum.instance(item['last_post'])
    #         out_data.append([user, last])
    #
    #     out_data = sorted(out_data, key=lambda i: i[1])
    #
    #     for x in out_data:
    #         x[1] = x[1].to_day_datetime_string()
    #
    #     out_data.insert(0, ['Member', 'Last Posted (UTC)'])
    #
    #     table = tabulate(out_data, headers='firstrow', tablefmt='fancy_grid')
    #     table = table.splitlines()
    #
    #     for line in table:
    #         paginator.add_line(line)
    #
    #     await ctx.send(f'**Members who have not sent a message in {weeks} week(s):**')
    #     for page in paginator.pages:
    #         await ctx.send(page)

    @commands.command(name="inactive")
    @commands.check_any(commands.is_owner(), has_role("Admin"))
    async def inactive(self, ctx):
        q = self.bot.cogs["QueueChannel"]
        s = self.bot.get_guild(q.server_id)

        pag = commands.Paginator()

        out = []
        for mem in s.members:
            if not discord.utils.find(lambda r: r.name == "Active", mem.roles):
                if mem.bot:
                    continue
                out.append(mem)

        pag.add_line("-- Members without Active role --\n")
        for x in out:
            pag.add_line(f"- {x.display_name}")

        for page in pag.pages:
            await ctx.send(page)


def setup(bot):
    bot.add_cog(Gates(bot))
