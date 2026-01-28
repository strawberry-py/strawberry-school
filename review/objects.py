from __future__ import annotations

import datetime
from typing import Optional, Union

import discord
from discord.ext import commands

import pie.acl
import pie.exceptions
from pie import i18n
from pie.utils.objects import VotableEmbed

from .database import ReviewBase, SubjectReview, TeacherReview

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
        review: Union[SubjectReview, TeacherReview],
        bot: commands.Bot,
        author: Optional[discord.Member] = None,
        footer: Optional[str] = None,
        *args,
        **kwargs,
    ):
        super(ReviewEmbed, self).__init__(*args, **kwargs)
        self.review: ReviewBase = review
        self.bot: commands.Bot = bot

        base_footer = "📩 "
        if author is not None:
            base_footer += f" {author.display_name}"
        if footer is not None:
            base_footer += " | " + footer
        self.set_footer(
            icon_url=author.display_avatar.url if author else None,
            text=base_footer,
        )
        self.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)

    async def vote_up(self, itx: discord.Interaction):
        """Implementation of vote_up function from VotableEmbed"""
        if await self._is_author(itx) or not await self._has_permission(itx):
            return

        self.review.vote(itx.user, True)
        await itx.response.send_message(
            _(itx, "Your positive vote has been counted."), ephemeral=True
        )

    async def vote_neutral(self, itx: discord.Interaction):
        """Implementation of vote_neutral function from VotableEmbed"""
        if await self._is_author(itx) or not await self._has_permission(itx):
            return

        self.review.vote(itx.user, None)
        await itx.response.send_message(
            _(itx, "Your vote has been deleted."), ephemeral=True
        )

    async def vote_down(self, itx: discord.Interaction):
        """Implementation of vote_down function from VotableEmbed"""
        if await self._is_author(itx) or not await self._has_permission(itx):
            return

        self.review.vote(itx.user, False)
        await itx.response.send_message(
            _(itx, "Your negative vote has been counted."), ephemeral=True
        )

    async def _is_author(self, itx: discord.Interaction) -> bool:
        """Checks if interacting user is review author"""
        if self.review.author_id == itx.user.id:
            await itx.response.send_message(
                _(itx, "Can't vote on own review!"), ephemeral=True
            )
            return True
        return False

    async def _has_permission(self, itx: discord.Interaction) -> bool:
        """Checks if user has ACL for review list to vote"""
        perm = (
            "review subject list"
            if isinstance(self.review, SubjectReview)
            else "review teacher list"
        )

        res = pie.acl.can_invoke_command(self.bot, itx, perm)
        if not res:
            await itx.response.send_message(
                _(itx, "You don't have permissions to vote!"), ephemeral=True
            )
        return res
