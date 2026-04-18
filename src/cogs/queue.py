from __future__ import annotations

import logging
import re

import discord
import disnake
import pendulum
from discord.ext import commands
from discord.ext import tasks

import common.constants as constants
from common.checks import has_role
from common.discord_utils import try_delete
from common.embeds import create_default_embed
from queueing.models import Player, Queue
from queueing.parsing import check_level_role, length_check, parse_player_class
from queueing.repository import load_queue_for_guild
from queueing.services import get_queue_services
from queueing.views import PlayerQueueUI

line_re = re.compile(r"\*\*in line:*\*\*", re.IGNORECASE)

log = logging.getLogger(__name__)


async def queue_from_guild(db, guild: discord.Guild) -> Queue:
    return await load_queue_for_guild(db, guild)


class QueueChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.services = get_queue_services(bot)
        self.player_service = self.services.player_queue_service
        self.queue_repo = self.services.queue_repository
        self.gate_repo = self.services.gate_repository
        self.queue_db = bot.mdb["player_queue"]
        self.old_player_data_db = bot.mdb["queue_analytics"]
        self.old_gates_db = bot.mdb["gate_groups_analytics"]
        self.gate_list_db = bot.mdb["gate_list"]
        self.emoji_db = bot.mdb["emoji_ranking"]

        self.dm_db = bot.mdb["dm_analytics"]
        self.player_db = bot.mdb["player_gates_analytics"]
        self.dm_assign_analytics = self.bot.mdb["dm_assign_analytics"]
        self.r_db = self.bot.mdb["reinforcement_analytics"]

        self.mark_db = self.bot.mdb["player_marked"]

        self.server_id = self.services.config.server_id
        self.channel_id = self.services.config.player_queue_channel_id
        self.announcement_channel_id = self.services.config.gate_announcement_channel_id

        self.update_bot_status.start()

    async def cog_check(self, ctx):  # pyright: ignore[reportIncompatibleMethodOverride]
        if not ctx.guild:
            return False
        if ctx.guild.id == constants.GATES_SERVER:
            return True
        if ctx.guild.id == constants.DEBUG_SERVER and self.bot.environment == "testing":
            return True

    def cog_unload(self):
        self.update_bot_status.cancel()

    @commands.Cog.listener(name="on_message")
    async def queue_listener(self, message: discord.Message):
        if message.guild is None:
            return None

        if not (self.server_id == message.guild.id and self.channel_id == message.channel.id):
            return None

        if not line_re.match(message.content):
            return None

        try:
            await message.add_reaction("<:d20:773638073052561428>")
            if message.author.id == self.bot.dev_id:
                await message.add_reaction("🐢")
        except (discord.NotFound, discord.Forbidden) as e:
            log.error(f"{e.__class__.__name__} error while adding reaction to queue post.")
        except discord.HTTPException:
            pass  # We ignore Discord being weird!

        # Get Player Details (Classes/Subclasses, total level)
        player_details = parse_player_class(line_re.sub("", message.content).strip())

        member: discord.Member = message.author  # pyright: ignore[reportAssignmentType]
        # Create a Player Object.
        player: Player = Player.new(member, player_details)
        await check_level_role(player)

        result = await self.player_service.signup_from_message(
            message=message,
            player=player,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            try:
                await message.author.send(result.message)
            except disnake.Forbidden:
                pass
            if result.should_delete_source_message:
                await try_delete(message)
            return None

    @commands.group(name="gates", invoke_without_command=True)
    @commands.check_any(has_role("Admin"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def gates(self, ctx):
        """Lists all the current registered Gates."""
        gates = await self.gate_repo.list_gates()
        embed = create_default_embed(ctx)
        out = [f":white_small_square: {gate['name'].title()} Gate - {gate['emoji']}" for gate in gates]

        embed.title = "List of Registered Gates"
        embed.description = "\n".join(out)
        embed.set_footer(text=f"To add a gate, see {ctx.prefix}help gates add")
        return await ctx.send(embed=embed)

    @gates.command(name="add", aliases=["create", "new"])
    @commands.check_any(has_role("Admin"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def add_gate(self, ctx, gate_name: str, gate_emoji: str):
        """
        Creates a new gate name-to-emoji pair. Must have the Admin role to perform this action.
        **Will override if there is a gate with the same name!!**
        """
        await self.gate_repo.upsert_gate(gate_name, gate_emoji)
        embed = create_default_embed(ctx)
        embed.title = "New Gate Created!"
        embed.description = f"Gate {gate_name} has been set to {gate_emoji}"
        return await ctx.send(embed=embed)

    @gates.command(name="remove", aliases=["delete", "del"])
    @commands.check_any(has_role("Admin"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def remove_gate(self, ctx, gate_name: str):
        """
        Removes a registered gate from the database. **Requires Admin**
        """
        exists = await self.gate_repo.get_by_name(gate_name)
        if not exists:
            return await ctx.send(
                f"Could not find a gate with the name `{gate_name}`. Check `{ctx.prefix}gates` for "
                f"a list of registered gates."
            )
        await self.gate_repo.remove_gate(gate_name)
        embed = create_default_embed(ctx)
        embed.title = "Removed Gate!"
        embed.description = f"Gate {gate_name} has been removed from the database."

        return await ctx.send(embed=embed)

    @commands.command(name="claim")
    @commands.check_any(has_role("DM"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def claim_group(self, ctx, group: int, gate_name: str, reinforcement: str = ""):
        """Claims a group from the queue."""
        result = await self.player_service.claim_group(
            guild=ctx.guild,
            claimant=ctx.author,
            gate_name=gate_name,
            group_number=group,
            reinforcement=bool(reinforcement),
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(result.message)
        log.info(f"[Queue] Gate #{group} ({gate_name} gate) claimed by {ctx.author}.")

    @commands.command(name="leave")
    @commands.check_any(has_role("Player"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def leave_queue(self, ctx):
        """Takes you out of the current queue, if you are in it."""
        result = await self.player_service.leave_member(
            guild=ctx.guild,
            member_id=ctx.author.id,
            view_factory=lambda: PlayerQueueUI(self.bot),
            decrement_signup_count=True,
            clear_marked=False,
        )
        return await ctx.send(result.message, delete_after=10)

    @commands.command(name="move")
    @commands.check_any(has_role("Assistant"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def move_player(self, ctx, original_group: int, player: discord.Member, new_group: int):
        """Moves a player to a different group. Requires the Assistant role."""
        result = await self.player_service.move_member(
            guild=ctx.guild,
            original_group=original_group,
            member_id=player.id,
            new_group=new_group,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(result.message, delete_after=10)
        log.info(f"[Queue] {ctx.author} moved {player} from group #{original_group} to group #{new_group}.")
        return await ctx.send(result.message, delete_after=10)

    @commands.command(name="merge")
    @commands.check_any(has_role("Admin"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def merge_groups(self, ctx, group_1: int, group_2: int):
        """Merges the second group into the first."""
        result = await self.player_service.merge_groups(
            guild=ctx.guild,
            group_1=group_1,
            group_2=group_2,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(result.message, delete_after=3)

        log.info(f"[Queue] {ctx.author} merged group #{group_1} and #{group_2}.")
        return await ctx.send(result.message, delete_after=5)

    @commands.command(name="queue")
    async def send_current_queue(self, ctx):
        """Sends the current queue."""
        queue = await queue_from_guild(self.queue_db, ctx.guild)
        embed = await self.services.presentation_service.build_player_queue_embed(queue)
        embed.title = "Gate Sign-Up Queue"
        return await ctx.send(embed=embed)

    @commands.command(name="remove")
    @commands.check_any(has_role("Assistant"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    async def remove_queue_member(self, ctx, player: discord.Member):
        """Removes a player from Queue. Requires the Assistant role."""
        result = await self.player_service.remove_member(
            guild=ctx.guild,
            member_id=player.id,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(
                f"{player.mention} was not in the queue, so they have not been removed.",
                delete_after=10,
            )

        log.info(f"[Queue] {ctx.author} removed {player} from Queue.")
        return await ctx.send(f"{player.mention} has been removed from queue.", delete_after=10)

    @commands.command(name="gateinfo", aliases=["groupinfo"])
    async def group_info(self, ctx, group_number: int):
        """Returns Information about a group."""
        queue = await queue_from_guild(self.queue_db, ctx.guild)

        length = len(queue.groups)
        check = length_check(length, group_number)
        if check is not None:
            return await ctx.send(check)

        group = queue.groups[group_number - 1]
        group.players.sort(key=lambda x: x.member.display_name)

        embed = create_default_embed(ctx)
        embed.title = f"Information for Group #{group_number}"
        embed.description = group.player_levels_str
        return await ctx.send(embed=embed)

    @commands.command(name="creategroup")
    @commands.check_any(has_role("Assistant"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    async def create_group(self, ctx, member: discord.Member):
        """
        Creates a new group from an existing queue member.
        `group` is which group to look in and `member` is the mention of who you are moving.
        """
        result = await self.player_service.create_group_from_member(
            guild=ctx.guild,
            member_id=member.id,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(result.message, delete_after=10)
        log.info(f"[Queue] {ctx.author} created rank gate from {member}.")
        return await ctx.send(result.message, delete_after=10)

    @commands.command(name="shuffle")
    @commands.check_any(has_role("Admin"), commands.is_owner())  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    async def shuffle_groups(self, ctx, tier: int, group_size: int = constants.GROUP_SIZE):
        """
        Shuffles the Queue. Warning! This action is __irrevocable__.
        Requires the Admin role.

        `tier` - What tier to shuffle.
        `group_size` - How big to make the shuffled groups. Default is 5
        """
        result = await self.player_service.shuffle_groups(
            guild=ctx.guild,
            tier=tier,
            group_size=group_size,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(result.message, delete_after=10)

        log.info(f"[Queue] Rank {tier} shuffled by {ctx.author} (GS {group_size})")
        return await ctx.send(
            f"{ctx.author.mention}, the queue has been shuffled!",
            allowed_mentions=discord.AllowedMentions(users=True),
            delete_after=10,
        )

    @tasks.loop(minutes=5)
    async def update_bot_status(self):
        guild = self.bot.get_guild(self.server_id)
        if guild is None:
            return None
        queue = await queue_from_guild(self.queue_db, guild)
        if queue is None:
            return None

        groups = len(queue.groups)
        status = discord.Activity(name=f"{groups} Queue Groups!", type=discord.ActivityType.watching)
        await self.bot.change_presence(activity=status)

    @update_bot_status.before_loop
    async def before_update_bot_status(self):
        await self.bot.wait_until_ready()
        log.info("Starting Bot Status Loop")

    @commands.group(name="stats", invoke_without_command=True)
    async def stats(self, ctx):
        """
        Base command for GatesBot stats.
        This command by itself will show stats about the current Queue.
        """
        queue = await queue_from_guild(self.queue_db, ctx.guild)
        if queue is None:
            return None

        group_len = len(queue.groups)

        embed = create_default_embed(ctx)
        embed.title = "Current Queue Stats"
        embed.add_field(
            name="In Queue",
            value=f"{group_len} group{'s' if group_len != 1 else ''}\n"
            f"{queue.player_count} player{'s' if queue.player_count != 1 else ''}",
        )
        groups = {}
        for group in queue.groups:
            groups[group.tier] = groups.get(group.tier, 0) + 1
        group_str = (
            "\n".join(f"**Tier {tier}**: {amt} group{'s' if amt != 1 else ''}" for tier, amt in groups.items())
            or "No groups in queue."
        )
        embed.add_field(name="Group Stats", value=group_str)

        return await ctx.send(embed=embed)

    @stats.command(name="overall", aliases=["over"])
    async def stats_overall(self, ctx):
        """
        Gathers data from __all__ previous gates (since Stat tracking started).
        """
        data = await self.old_gates_db.find().to_list(length=None)
        if not data:
            return await ctx.send("No gates data found ... Contact the developer!")

        embed = create_default_embed(ctx, title="GatesBot Analytics")

        # num of gates
        embed.add_field(
            name="Total # of Gates Summoned",
            value=f"{len(data)} Gates Summoned since 3/27/2021",
        )

        # average gate tier

        tier = sum(x.get("tier") for x in data) / len(data)

        embed.add_field(name="Average Gate Tier", value=f"Tier {tier:.1f}")

        # Most summoned-to gate
        most_summoned = dict()
        for item in data:
            most_summoned[item.get("gate_name")] = most_summoned.get(item.get("gate_name"), 0) + 1
        most_summoned = max(most_summoned.items(), key=lambda x: x[1])
        embed.add_field(
            name="Most-Summoned Gate",
            value=f"{most_summoned[0]} Gate - {most_summoned[1]} summons.",
        )

        await ctx.send(embed=embed)

    # @stats.group(name="emojis", aliases=["emoji"], invoke_without_command=True)
    # async def emoji_personal(self, ctx, who: discord.Member = None):
    #     """
    #     Gets your emoji leaderboard stats!
    #     `who` - Optional, someone to look up. Defaults to yourself!
    #     """
    #     embed = create_default_embed(ctx)
    #     who = who or ctx.author
    #     data = await self.emoji_db.find_one({"reacter_id": who.id})
    #     if not data:
    #         embed.title = "No Data Found!"
    #         embed.description = f"I could not find any emoji data for {who.mention}"
    #         return await ctx.send(embed=embed)
    #     embed.title = f"Emoji Data for {who.display_name}"
    #     embed.add_field(name="# of reactions", value=f'{data["reaction_count"]} reactions.')
    #     dt = pendulum.now() - pendulum.instance(data["last_reacted"])
    #     embed.add_field(name="Last Reaction", value=f"{dt.in_words()} ago.")
    #
    #     return await ctx.send(embed=embed)
    #
    # @emoji_personal.command(name="top", aliases=["leaderboard", "list"])
    # async def emoji_top(self, ctx):
    #     """
    #     Gets the top 10 Emoji members.
    #     """
    #     embed = create_default_embed(ctx)
    #     data = await self.emoji_db.find().to_list(length=None)
    #     users = sorted(data, key=lambda x: x["reaction_count"], reverse=True)
    #     out = "\n".join([f'- <@{u["reacter_id"]}>: `{u["reaction_count"]}`' for u in users[:10]])
    #     embed.title = "Queue Emoji Leaderboard"
    #     embed.description = out
    #     await ctx.send(embed=embed)

    @stats.group(name="player", invoke_without_command=True)
    async def queue_playerstats(self, ctx, who: discord.Member | None = None):
        """
        Shows your data for the Queue.

        `who` - (Optional) Who's data to show if not for you.
        """
        embed = create_default_embed(ctx)

        who = who or ctx.author

        data = await self.bot.mdb["queue_analytics"].find_one({"user_id": who.id})
        if data is None:
            raise commands.BadArgument(f"Could not find any data for {who.display_name}!")

        embed.title = f"Queue Data - {who.display_name}"
        now = pendulum.now(tz=pendulum.tz.UTC)
        if "last_gate_name" in data:
            last_summoned = pendulum.instance(data["last_gate_summoned"])

            embed.add_field(
                name="Last Gate Summoned",
                value=f"**Last Gate:** {data['last_gate_name'].title()}\n"
                f"**Date (UTC):** {last_summoned.to_day_datetime_string()} "
                f"({(now - last_summoned).in_words()} ago)",
            )

        embed.add_field(
            name="Other Stats",
            value=f"**Gate Signup Count:** {data.get('gate_signup_count', '*None*')}\n"
            f"**Gate Summon Count:** {data.get('gate_summon_count', '*None*')}\n",
        )

        if "gates_summoned_per_level" in data:
            out = ["```diff"]
            for k, v in data["gates_summoned_per_level"].items():
                out.append(f"+ Level {k}: {v} gate{'s' if v != 1 else ''}")
            out.append("```")
            embed.add_field(
                name="Gates Per Player Level (Summoned)",
                value="\n".join(out),
                inline=False,
            )

        return await ctx.send(embed=embed)

    @queue_playerstats.command(name="top")
    async def queue_playerstats_top(self, ctx):
        """
        Shows the top defenders in the Gates.
        """
        embed = create_default_embed(ctx)
        embed.title = "Gates Leaderboards"

        player_cache = []
        async for player in self.old_player_data_db.find():
            if not player.get("last"):
                continue
            player.pop("_id")
            player_cache.append(player)

        # top levels
        levels_sorted = sorted(player_cache, key=lambda x: x["last"].get("level"), reverse=True)[:10]
        embed.add_field(
            name="Highest (known) Level",
            value="```"
            + (
                "\n".join(
                    [
                        f"{i + 1}. {x['last'].get('name') or 'Unknown'} (L{x['last'].get('level') or '??'})"
                        for i, x in enumerate(levels_sorted)
                    ]
                )
            )
            + "\n```",
        )

        # top # of gates
        gates_sorted = sorted(player_cache, key=lambda x: x.get("gate_summon_count", 0), reverse=True)[:10]
        embed.add_field(
            name="Gates Summoned To",
            value="```"
            + (
                "\n".join(
                    [
                        f"{i + 1}. {x['last'].get('name') or 'Unknown'}: {x.get('gate_summon_count') or '0'}"
                        for i, x in enumerate(gates_sorted)
                    ]
                )
            )
            + "\n```",
        )

        return await ctx.send(embed=embed)

    # Owner/Admin Commands
    @commands.group(name="lock", invoke_without_command=True)
    @commands.check_any(commands.is_owner(), has_role("Assistant"))  # pyright: ignore[reportArgumentType]
    async def lock_queue(self, ctx, *, reason: str = "None"):
        """Locks the queue channel. Admin only."""
        queue_channel: discord.TextChannel = ctx.guild.get_channel(self.channel_id)
        if queue_channel is None:
            return await ctx.author.send("Could not find queue channel, aborting channel lock.")
        player_role: discord.Role = discord.utils.find(lambda r: r.name.lower() == "player", ctx.guild.roles)  # pyright: ignore[reportAssignmentType]
        if player_role is None:
            return await ctx.author.send("Could not find Player role, aborting channel lock.")
        await self.player_service.toggle_queue_lock(
            guild=ctx.guild,
            actor=ctx.author,
            queue_channel=queue_channel,
            player_role=player_role,
            should_lock=True,
            reason=reason,
            view_factory=lambda: PlayerQueueUI(self.bot),
            send_announcement=False,
        )
        log.info(f"Queue has been locked by {ctx.author.name}#{ctx.author.discriminator}")

    @lock_queue.command(name="group")
    @commands.check_any(commands.is_owner(), has_role("Assistant"))  # pyright: ignore[reportArgumentType]
    async def lock_group(self, ctx, group_num: int):
        """Locks or unlocks a group, depending on the current status of the group."""
        result = await self.player_service.toggle_group_lock(
            guild=ctx.guild,
            group_number=group_num,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )
        if not result.success:
            return await ctx.send(result.message)
        await ctx.send(result.message, delete_after=3)
        log.info(f"[Queue] Group #{group_num} {'locked' if result.is_locked else 'unlocked'} by {ctx.author}.")

    # Owner/Admin Commands
    @commands.command(name="unlock")
    @commands.check_any(commands.is_owner(), has_role("Assistant"))  # pyright: ignore[reportArgumentType]
    async def unlock_queue(self, ctx, *, reason: str = ""):
        """Unlocks the queue channel. Admin only."""
        queue_channel: discord.TextChannel = ctx.guild.get_channel(self.channel_id)
        if queue_channel is None:
            return await ctx.author.send("Could not find queue channel, aborting channel unlock.")
        player_role: discord.Role = discord.utils.find(lambda r: r.name.lower() == "player", ctx.guild.roles)  # pyright: ignore[reportAssignmentType]
        if player_role is None:
            return await ctx.author.send("Could not find Player role, aborting channel unlock.")

        log.info(f"Queue has been unlocked by {ctx.author.name}#{ctx.author.discriminator}")
        await self.player_service.toggle_queue_lock(
            guild=ctx.guild,
            actor=ctx.author,
            queue_channel=queue_channel,
            player_role=player_role,
            should_lock=False,
            reason=reason,
            view_factory=lambda: PlayerQueueUI(self.bot),
            send_announcement=True,
        )

    @commands.command(name="fixq")
    @commands.check_any(commands.is_owner(), has_role("Assistant"))  # pyright: ignore[reportArgumentType]
    async def manually_unlock_queue(self, ctx):
        """Unlocks the queue channel. Admin only."""
        queue_channel: discord.TextChannel = ctx.guild.get_channel(self.channel_id)

        if queue_channel is None:
            return await ctx.author.send("Could not find queue channel, aborting channel unlock.")
        player_role: discord.Role = discord.utils.find(lambda r: r.name.lower() == "player", ctx.guild.roles)  # pyright: ignore[reportAssignmentType]
        if player_role is None:
            return await ctx.author.send("Could not find Player role, aborting channel unlock.")

        log.info(f"Queue has been forcefully unlocked by {ctx.author}")
        await self.player_service.force_unlock_channel(
            actor=ctx.author,
            queue_channel=queue_channel,
            player_role=player_role,
        )

        await ctx.send("Manually unlocked...", delete_after=3)

    @commands.command(name="empty")
    @commands.check_any(commands.is_owner(), has_role("Admin"))  # pyright: ignore[reportArgumentType]
    async def empty_queue(self, ctx):
        """Empty the queue. Admin only."""
        await self.player_service.empty_queue(
            guild=ctx.guild,
            view_factory=lambda: PlayerQueueUI(self.bot),
        )

        await ctx.send(f"Queue Emptied by {ctx.author.mention}", delete_after=10)


def setup(bot):
    bot.add_cog(QueueChannel(bot))
