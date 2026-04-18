from __future__ import annotations

import datetime
import logging

import discord
import disnake

import common.constants as constants
from queueing.repository import load_queue_for_guild
from queueing.views.admin import PlayerQueueManageUI

log = logging.getLogger(__name__)


class PlayerQueueUI(disnake.ui.View):
    def __init__(self, bot, queue_type, *args, **kwargs):
        super().__init__(timeout=None)
        self.bot = bot
        self.queue_type = queue_type

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

        self.server_id = (
            constants.GATES_SERVER
            if self.bot.environment != "testing"
            else constants.DEBUG_SERVER
        )
        self.channel_id = (
            constants.GATES_CHANNEL
            if self.bot.environment != "testing"
            else constants.DEBUG_CHANNEL
        )
        self.announcement_channel_id = (
            constants.GATE_ANNOUNCEMENT_CHANNEL
            if self.bot.environment != "testing"
            else constants.GATE_ANNOUNCEMENT_CHANNEL_DEBUG
        )

    async def queue_from_guild(self, db, guild: discord.Guild):
        return await load_queue_for_guild(db, guild, queue_type=self.queue_type)

    @disnake.ui.button(
        label="Leave",
        style=disnake.ButtonStyle.red,
        custom_id="gatesbot_playerqueue_leave",
    )
    async def leave_button(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        queue = await self.queue_from_guild(self.queue_db, inter.guild)

        group_index = queue.in_queue(inter.author.id)
        if group_index is None:
            return await inter.send(
                "You are not currently in the queue, so I cannot remove you from it.",
                ephemeral=True,
            )

        queue.groups[group_index[0]].players.pop(group_index[1])
        await queue.update(
            self.bot, self.queue_db, inter.guild.get_channel(self.channel_id)
        )

        data = {"$set": {"user_id": inter.author.id}, "$inc": {"gate_signup_count": -1}}
        await self.old_player_data_db.update_one(
            {"user_id": inter.author.id},
            data,
            upsert=True,
        )
        await self.mark_db.update_one(
            {"_id": inter.author.id},
            {"$set": {"marked": False}},
        )

        return await inter.send(
            f"You have been removed from group #{group_index[0] + 1}",
            ephemeral=True,
        )

    @disnake.ui.button(
        emoji="⚙",
        style=disnake.ButtonStyle.grey,
        custom_id="gatesbot_playerqueue_manage",
        disabled=False,
    )
    async def manage_button(self, button, inter: disnake.MessageInteraction):
        queue = await self.queue_from_guild(self.queue_db, inter.guild)

        if not (
            inter.author.id == self.bot.owner_id
            or any(True for role in inter.author.roles if role.name == "Assistant")
        ):
            return await inter.send(
                "You are not allowed to use this function.",
                ephemeral=True,
            )

        view = PlayerQueueManageUI(self.bot, queue)
        embed = await view.generate_menu(inter)
        return await inter.send(embed=embed, view=view, ephemeral=True)

    @disnake.ui.button(
        label="Claim",
        style=disnake.ButtonStyle.green,
        custom_id="gatesbot_playerqueue_claim",
    )
    async def claim_button(self, button, inter: disnake.MessageInteraction):
        if not (
            inter.author.id == self.bot.owner_id
            or any(True for role in inter.author.roles if role.name == "DM")
        ):
            return await inter.send(
                "You are not allowed to use this function.",
                ephemeral=True,
            )

        await inter.response.defer()

        queue = await self.queue_from_guild(self.queue_db, inter.guild)
        gate = await self.gate_list_db.find_one({"owner": inter.author.id})
        if gate is None:
            return await inter.send(
                "You have not claimed a gate. Refer to Assistant/Admin instructions for further details.",
                ephemeral=True,
            )

        group_index = None
        for index, group in enumerate(queue.groups):
            if group.assigned == inter.author.id:
                group_index = index

        if group_index is None:
            return await inter.send(
                "You do not currently have a Gate assigned.",
                ephemeral=True,
            )

        serv = self.bot.get_guild(self.server_id)
        popped = queue.groups.pop(group_index)

        player_ids = [player.member.id for player in popped.players]
        await self.mark_db.update_many(
            {"_id": {"$in": player_ids}},
            {"$set": {"marked": False}},
        )

        summons_channel_id = (
            constants.SUMMONS_CHANNEL
            if self.bot.environment != "testing"
            else constants.DEBUG_SUMMONS_CHANNEL
        )

        raw_gate = popped.to_dict()
        raw_gate["gate_name"] = gate["name"]
        raw_gate["claimed_date"] = datetime.datetime.utcnow()
        raw_gate.pop("position")

        assign_analytics = await self.dm_assign_analytics.find(
            sort=[("summonDate", -1)],
            limit=1,
            filter={"claimed": False},
        ).to_list(length=None)
        if assign_analytics:
            assign_item = assign_analytics[0]
            await self.dm_assign_analytics.update_one(
                {"_id": assign_item["_id"]},
                {"$set": {"claimed": True}, "$currentDate": {"claimDate": True}},
            )

        await self.dm_db.update_one(
            {"_id": inter.author.id},
            {
                "$inc": {"dm_claims.claims": 1},
                "$push": {"dm_gates": raw_gate},
                "$currentDate": {"dm_claims.last_claim": True},
            },
        )

        gate_analytics_data = {
            "gate_name": gate["name"],
            "date_summoned": datetime.datetime.utcnow(),
            "dm_id": inter.author.id,
            "tier": popped.tier,
            "levels": {},
        }
        for player in popped.players:
            analytics_data = {
                "$set": {"user_id": player.member.id, "last_gate_name": gate["name"]},
                "$currentDate": {"last_gate_summoned": True},
                "$inc": {
                    f"gates_summoned_per_level.{player.total_level}": 1,
                    "gate_summon_count": 1,
                },
            }
            gate_analytics_data["levels"][str(player.total_level)] = (
                int(gate_analytics_data["levels"].get(str(player.total_level), "0")) + 1
            )
            await self.old_player_data_db.update_one(
                {"user_id": player.member.id},
                analytics_data,
                upsert=True,
            )

        await self.old_gates_db.insert_one(gate_analytics_data)

        summons_ch = serv.get_channel(summons_channel_id)
        assignments_ch = serv.get_channel(constants.GATE_ASSIGNMENTS_CHANNEL)
        assignments_str = (
            f"<#{assignments_ch.id}>"
            if assignments_ch is not None
            else "#gate-assignments-v2"
        )

        out_players = sorted(popped.players, key=lambda player: player.member.display_name)

        if summons_ch is not None:
            msg = ", ".join([player.mention for player in out_players]) + "\n"
            msg += (
                f'Welcome to the {gate["name"].lower().title()} Gate! Head to {assignments_str}'
                f' and grab the {gate["emoji"]} from the list and head over to the gate!\n'
                f"Claimed by {inter.author.mention}"
            )
            await summons_ch.send(
                msg,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        await queue.update(self.bot, self.queue_db, inter.guild.get_channel(self.channel_id))

        log.info(
            f'[Queue] {inter.author} claimed {gate["name"].title()} Gate for '
            f'{", ".join(player.member.display_name for player in out_players)}.'
        )
        return await inter.send(
            f"You have claimed Group #{group_index + 1}.",
            ephemeral=True,
        )


__all__ = ["PlayerQueueUI"]
