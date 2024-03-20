import datetime

import discord
import re


def create_default_embed(ctx, **kwargs) -> discord.Embed:
    embed = discord.Embed(color=discord.Color(int("0x2F3136", base=16)), **kwargs)
    embed.set_author(
        name=ctx.author.display_name, icon_url=str(ctx.message.author.display_avatar)
    )
    embed.set_footer(text=ctx.bot.user.name, icon_url=str(ctx.bot.user.display_avatar))
    embed.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
    return embed


def create_queue_embed(bot, **kwargs) -> discord.Embed:
    embed = discord.Embed(color=discord.Color(int("0x2F3136", base=16)), **kwargs)
    embed.set_footer(text=bot.user.name, icon_url=str(bot.user.display_avatar))
    embed.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
    return embed


async def try_delete(message):
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass


## Queue Utilities

player_class_regex = re.compile(r"(?P<subclass>(?:\w+ )*)(?P<class>\w+) (?P<level>\d+)")

def length_check(group_length, requested_length):
    if not 1 <= requested_length <= group_length:
        out = "Invalid Group Number. "
        if group_length == 0:
            out += "No groups available to select!"
        elif group_length == 1:
            out += "Only one group to select."
        else:
            out += f"Must be between 1 and {group_length}."
        return out
    return None


async def check_level_role(player):
    level = player.total_level
    level_role = f"Level {level}"
    has_level_role = discord.utils.find(
        lambda r: r.name == level_role, player.member.roles
    )

    if has_level_role:
        return None

    wrong_role = discord.utils.find(
        lambda r: r.name.lower().startswith("level"), player.member.roles
    )
    if not wrong_role:
        return await player.member.send(
            "Hi! You currently do not have a level role. Grab one from near the top of"
            " <#874436255088275496>!"
        )
    else:
        return await player.member.send(
            f"Hi! You currently have the role for {wrong_role.name}, but you put your level"
            f" as Level {player.total_level} into the signup."
            f"\nPlease either grab the correct role "
            f"from <#874436255088275496> or leave the queue with `=leave` and sign-up with"
            f" the correct level. Thank you!"
        )


def parse_player_class(class_str) -> dict:
    out = {"total_level": 0, "classes": []}

    # [Subclass] <Class> <Level> / [Subclass] <Class> <Level>
    matches = player_class_regex.findall(class_str)
    for match in matches:
        try:
            level = int(match[-1].strip())  # Last group is always a number.
        except ValueError:
            level = 4
        player_class = match[-2].strip() or "None"
        subclass = match[0].strip() or "None"

        out["total_level"] += level
        out["classes"].append(
            {"class": player_class, "subclass": subclass, "level": level}
        )

    return out
