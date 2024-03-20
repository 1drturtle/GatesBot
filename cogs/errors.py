import logging
import traceback
from datetime import timedelta

import discord
import sentry_sdk
from discord.ext import commands
import utils.constants as constants


log = logging.getLogger(__name__)


class CommandErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.error_channel_id = constants.ERROR_CHANNEL

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """The event triggered when an error is raised while invoking a command.

        Parameters
        ------------
        ctx: commands.Context
            The context used for command invocation.
        error: commands.CommandError
            The Exception raised.
        """

        # This prevents any commands with local handlers being handled here in on_command_error.
        if hasattr(ctx.command, "on_error") and getattr(
            ctx.command, "no_handle", False
        ):
            return

        # This prevents any cogs with an overwritten cog_command_error being handled here.
        cog = ctx.cog
        if cog:
            if cog._get_overridden_method(cog.cog_command_error) is not None:
                return

        ignored = (commands.CommandNotFound,)

        # Allows us to check for original exceptions raised and sent to CommandInvokeError.
        # If nothing is found. We keep the exception passed to on_command_error.
        error = getattr(error, "original", error)

        # Anything in ignored will return and prevent anything happening.
        if isinstance(error, ignored):
            return

        if ctx.command.name == "eval":
            msg = str(error) or "Error occurred in eval."
            return await ctx.send(f"Error: {msg}")

        if isinstance(error, commands.DisabledCommand):
            await ctx.send(f"{ctx.command} has been disabled.")

        elif isinstance(error, commands.EmojiNotFound):
            await ctx.send(
                "I could not find the emoji that you provided. Either I do not have access to it, "
                "or it is a default emoji."
            )

        elif isinstance(error, commands.CheckFailure):
            msg = str(error) or "You are not allowed to run this command."
            return await ctx.send(f"Error: {msg}")

        elif isinstance(error, commands.MissingRequiredArgument):
            msg = str(error) or "Missing Unknown Required Argument"
            return await ctx.send(f"Error: {msg}")

        elif isinstance(error, commands.BadArgument) or isinstance(
            error, commands.BadUnionArgument
        ):
            msg = str(error) or "Unknown Bad Argument"
            return await ctx.send(f"Error: {msg}")

        elif isinstance(error, commands.ArgumentParsingError):
            msg = str(error) or "Unknown Argument Parsing Error"
            return await ctx.send(f"Error: {msg}")

        elif isinstance(error, commands.CommandOnCooldown):
            msg = "Command on Cooldown!"
            cooldown = timedelta(seconds=int(error.retry_after))
            mins, seconds = divmod(cooldown.seconds, 60)
            time = (
                f'{mins} minute{"s" if mins != 1 else ""}'
                f'{" and " if mins > 0 else ", "}{seconds} second{"s" if seconds != 1 else ""}'
            )
            if ctx.command.parents:
                msg += (
                    f"\n`{ctx.prefix}{ctx.command.full_parent_name} {ctx.command.name}` is on cooldown for "
                    f"{time}"
                )
            else:
                msg += f"\n`{ctx.prefix}{ctx.command.name}` is on cooldown for {time}!"
            return await ctx.send(msg)

        elif isinstance(error, discord.Forbidden):
            msg = str(error) or "Forbidden - Not allowed to perform this action."
            return await ctx.send(f"Error: {msg}")
        elif isinstance(error, commands.BadArgument):
            msg = str(error) or "Unknown invalid argument."
            return await ctx.send(f"Error: {msg}")

        elif isinstance(error, commands.NoPrivateMessage):
            try:
                await ctx.author.send(
                    f"{ctx.command} can not be used in Private Messages."
                )
            except:
                pass

        else:
            raise error
            # await self.bot.get_channel(self.error_channel_id).send(error)


def setup(bot):
    bot.add_cog(CommandErrorHandler(bot))
