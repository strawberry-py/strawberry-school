from __future__ import annotations

import datetime
from typing import Optional

import discord
from discord.ext import commands

import pie.acl
import pie.exceptions
from pie import i18n
from pie.utils.objects import VotableEmbed

from .database import SubjectReview

_ = i18n.Translator("modules/school").translate


class ReviewEmbed(VotableEmbed):
    """Embed implementing VotableEmbed used in ScrollableVotingEmbed

    Args:
        review: Review database object, must implement `vote(discord.Member, discord.Interaction)`
                and have attribute author_id
        footer: Optional footer text
        *args: Same arguments as used in discord.Embed
        **kwargs: Same keyword arguments as used in discord.Embed
    """

    def __init__(
        self,
        review,
        bot: commands.Bot,
        author: Optional[discord.Member] = None,
        footer: Optional[str] = None,
        *args,
        **kwargs,
    ):
        super(ReviewEmbed, self).__init__(*args, **kwargs)
        self.review = review
        self.bot = bot

        base_footer = "📩 "
        if author is not None:
            base_footer += f" {author.display_name}"
        if footer is not None:
            base_footer += " | " + footer
        self.set_footer(
            icon_url=getattr(author, "avatar_url", None),
            text=base_footer,
        )
        self.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)

    async def vote_up(self, interaction: discord.Interaction):
        """Implementation of vote_up function from VotableEmbed"""
        utx = i18n.TranslationContext(interaction.guild.id, interaction.user.id)

        if await self._is_author(utx, interaction) or not await self._has_permission(
            utx, interaction
        ):
            return

        self.review.vote(interaction.user, True)
        await interaction.response.send_message(
            _(utx, "Your positive vote has been counted."), ephemeral=True
        )

    async def vote_neutral(self, interaction: discord.Interaction):
        """Implementation of vote_neutral function from VotableEmbed"""
        utx = i18n.TranslationContext(interaction.guild.id, interaction.user.id)

        if await self._is_author(utx, interaction) or not await self._has_permission(
            utx, interaction
        ):
            return

        self.review.vote(interaction.user, None)
        await interaction.response.send_message(
            _(utx, "Your vote has been deleted."), ephemeral=True
        )

    async def vote_down(self, interaction: discord.Interaction):
        """Implementation of vote_down function from VotableEmbed"""
        utx = i18n.TranslationContext(interaction.guild.id, interaction.user.id)

        if await self._is_author(utx, interaction) or not await self._has_permission(
            utx, interaction
        ):
            return

        self.review.vote(interaction.user, False)
        await interaction.response.send_message(
            _(utx, "Your negative vote has been counted."), ephemeral=True
        )

    async def _is_author(
        self, utx: i18n.TranslationContext, interaction: discord.Interaction
    ) -> bool:
        """Checks if interacting user is review author"""
        if self.review.author_id == interaction.user.id:
            await interaction.response.send_message(
                _(utx, "Can't vote on own review!"), ephemeral=True
            )
            return True
        return False

    async def _has_permission(
        self, utx: i18n.TranslationContext, interaction: discord.Interaction
    ) -> bool:
        """Checks if user has ACL for review list to vote"""
        perm = (
            "review subject list"
            if isinstance(self.review, SubjectReview)
            else "review teacher list"
        )

        res = pie.acl.can_invoke_command(interaction, perm)
        if not res:
            await interaction.response.send_message(
                _(utx, "You don't have permissions to vote!"), ephemeral=True
            )
        return res
