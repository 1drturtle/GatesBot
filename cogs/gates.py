import datetime
import logging
from collections import namedtuple
from typing import List

import discord
import disnake
import pendulum
from discord.ext import commands
from discord.ext import tasks

from utils import constants as constants
from utils.checks import has_role
from utils.functions import create_default_embed

PLACEHOLDER_POLL_TIME = 300

log = logging.getLogger(__name__)


class Gates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.placeholder_db = bot.mdb["placeholder_events"]
        self.settings_db = bot.mdb["placeholder-settings"]
        self.active_db = bot.mdb["active_users"]
        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )
        self.db_task = self.check_db_placeholders.start()
        self.inactive_listener = self.check_inactive.start()

    def cog_unload(self):
        self.db_task.cancel()
        self.inactive_listener.cancel()

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
            log.info(
                f"could not find member info for user {message.author.name}#{message.author.discriminator}"
            )
            return

        # stop if they don't have the role
        if not discord.utils.find(
            lambda r: r.name == "Placeholder Notifications", member.roles
        ):
            return

        # stop if the channel is wrong
        if "-ic" not in message.channel.name.lower():
            return

        # stop if there's no placeholder:
        if not any(
            [
                x in message.content.lower()
                for x in ["*ph*", "*placeholder*", "_ph_", "_placeholder_"]
            ]
        ):
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
            setting = await self.settings_db.find_one(
                {"user_id": document["author_id"]}
            )
            setting = setting.get("hours", 1) if setting else 1

            if (
                (document["message_date"] + datetime.timedelta(hours=setting)) - utc_now
            ).total_seconds() <= (
                15 * 60
            ):  # ten minutes
                await self.placeholder_db.delete_one(
                    {"message_id": document["message_id"]}
                )
                self.bot.loop.create_task(
                    self.run_placeholder_reminder(document, setting)
                )
                scheduled.append(document)

        if scheduled:
            log.debug(
                f"[Placeholder] {len(scheduled)} placeholder(s) have been scheduled."
            )

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
        member: disnake.Member = guild.get_member(placeholder_data["author_id"])
        channel = guild.get_channel(placeholder_data["channel_id"])

        try:
            log.info(
                f"[Placeholder] running placeholder for {member.display_name} in #{channel.name}"
            )
        except:
            pass
        try:
            message = await channel.fetch_message(placeholder_data["message_id"])
        except discord.NotFound:
            return None

        if message is None or not any(
            [
                x in message.content.lower()
                for x in ["*ph*", "*placeholder*", "_ph_", "_placeholder_"]
            ]
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
        Sets the amount of hours to wait before sending a placeholder notification. If no argument is specified,
        shows the current setting.

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
                f"The current setting is to send a reminder after {db_result} hour"
                f'{"s" if db_result != 1 else ""}.'
            )
            return await ctx.send(embed=embed)

        if hours < 1:
            raise commands.BadArgument("`hours` must be greater or equal to one.")

        await self.settings_db.update_one(
            {"user_id": ctx.author.id}, {"$set": {"hours": hours}}, upsert=True
        )
        embed.title = "Placeholder settings updated!"
        embed.description = (
            f"The current setting is now to send a reminder after {hours} hour"
            f'{"s" if hours != 1 else ""}.'
        )

        return await ctx.send(embed=embed)

    @commands.Cog.listener(name="on_message")
    async def activity_listener(self, message):

        # stop if we're not in the right guild
        if not getattr(message.guild, "id", None) == self.server_id:
            return

        if message.author.bot:
            return

        # role = message.guild.get_role(constants.INACTIVE_ROLE_ID)

        # if discord.utils.find(lambda r: r.id == role.id, message.author.roles):
        #     await message.author.remove_roles(
        #         role, reason="User is no longer inactive."
        #     )

        # store the data
        return await self.active_db.update_one(
            {"_id": message.author.id},
            {"$set": {"_id": message.author.id}, "$currentDate": {"last_post": True}},
            upsert=True,
        )

    @commands.group(name="inactive", invoke_without_command=True)
    @commands.check_any(commands.is_owner(), has_role("Admin"))
    async def inactive(self, ctx):
        """Shows inactive users and their last Queue sign-up."""
        q = self.bot.cogs["QueueChannel"]
        s = self.bot.get_guild(q.server_id)

        role = s.get_role(constants.INACTIVE_ROLE_ID)

        inactive_members = filter(lambda m: role in m.roles, s.members)

        desc = [f"| {'Member Name':^30} | {'Last Sign-Up':^30} |"]
        for x in inactive_members:
            data = await self.active_db.find_one({"_id": x.id})
            data = (
                f'<t:{pendulum.instance(data.get("last_signup")).int_timestamp}:R>'
                if data and data.get("last_signup")
                else "Unknown"
            )
            desc.append(f"| {x.display_name} | {data} |")

        embed = create_default_embed(ctx)
        embed.title = "Inactive Users"
        embed.description = "\n".join(desc)

        await ctx.send(embed=embed)

    @inactive.command(name="final")
    @has_role("Admin")
    async def inactive_final(self, ctx):
        """Sends the final Inactive message to all members w/ Inactive Role. Admin only."""

        # send info
        await ctx.invoke(self.inactive)

        # get members
        q = self.bot.cogs["QueueChannel"]
        s = self.bot.get_guild(q.server_id)
        role = s.get_role(constants.INACTIVE_ROLE_ID)

        inactive_members: List[disnake.Member] = list(
            filter(lambda m: role in m.roles, s.members)
        )

        final_msg = """Hi!\n\nYou've recently been pinged as "Inactive" since you have not signed up for a gate in at least 6 months.\n\nAs much as we'd love for you to stick around, we do have to enforce our server policies.\n\nIf you're ready to get back to playing, we'd appreciate it if you could re-read our rules for a refresher. Once done with that, instructions on how regain Player access are pinned in inactive-players!\n\nIf you're not ready, that's totally fine too! Unfortunately, that does mean we will have to remove you from the server. No worries though, if you haven't already, please add Aeslyn or Lentan as friends and we'd be happy to invite you back.\n\nIf we don't hear from you in 3 days, we will assume you're not interested anymore and we'll be cleaning up our inactive players."""

        # send FINAL msg to inactive users
        count = 0
        success, fail = [], []

        for member in inactive_members:
            try:
                await member.send(final_msg)
            except discord.HTTPException | discord.Forbidden:
                fail.append(member)
            else:
                success.append(member)
            count += 1

        e = create_default_embed(ctx)
        e.title = "Final Inactive Spiel Report"
        if success:
            e.add_field("Success", value="\n".join(m.mention for m in success))
        if fail:
            e.add_field(
                "Message Failed to Send", value="\n".join(m.mention for m in fail)
            )
        e.description = f"Report for {count} inactive users."

        await ctx.send(embed=e)

    # inactive role creator
    @tasks.loop(hours=24)
    async def check_inactive(self):
        # load all activity
        q = self.bot.cogs["QueueChannel"]
        s: discord.Guild = self.bot.get_guild(q.server_id)

        inactive_role = s.get_role(constants.INACTIVE_ROLE_ID)
        player_role = discord.utils.find(lambda r: r.name == "Player", s.roles)
        member_role = discord.utils.find(lambda r: r.name == "Member", s.roles)
        mod_log_channel = s.get_channel(797678485078016000)

        # six months ago
        old = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(
            days=30 * 6
        )

        data = await self.active_db.find({"last_signup": {"$lte": old}}).to_list(None)
        user_ids = [x["_id"] for x in data]

        # convert into users
        members = [s.get_member(user_id) for user_id in user_ids]
        members: List[discord.Member] = list(filter(lambda x: x is not None, members))

        # add Inactive Role & Member Role, Remove Player ROle
        count = 0
        for member in members:
            if not discord.utils.find(lambda r: r.id == inactive_role.id, member.roles):
                # change roles
                await member.add_roles(
                    inactive_role, member_role, reason="User is inactive"
                )
                await member.remove_roles(player_role, reason="User is inactive")
                # send the spiel
                try:
                    await member.send(
                        "Hello! You have been inactive for at least 6 months. "
                        "Please let us know if/when you plan to hop back into Gates "
                        "(by PMing an Admin or in <#1133560363493904435>). If you do not in the next couple weeks, "
                        "we will have to remove you form the server to keep our member list cleaner. Once that happens,"
                        " all you would need to do is shoot one of us admins a message (Lentan or Aeslyn)"
                        " and we'll get you right back in!"
                    )
                except discord.HTTPException | discord.Forbidden:
                    await mod_log_channel.send(
                        f"Could not send inactive spiel to {member.mention} via DM."
                    )
                else:
                    await mod_log_channel.send(
                        f"Inactive spiel sent to {member.mention} via DM."
                    )
                count += 1

        log.info(f"[Activity] {count} users given Inactive role... Check Complete")

    @check_inactive.before_loop
    async def before_inactive_placeholders(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(Gates(bot))
