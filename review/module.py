from __future__ import annotations

import textwrap
from typing import Iterator, List, Optional

import discord
from discord.ext import commands

from pie import check, i18n, logger, utils
from pie.utils.objects import ConfirmView, ScrollableVotingEmbed

from ..school.database import Subject, Teacher
from ..school.module import SchoolExtend
from .database import SubjectReview, TeacherReview
from .objects import ReviewEmbed

_ = i18n.Translator("modules/school").translate

guild_log = logger.Guild.logger()


class Review(commands.Cog):
    """Subject reviews"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        SchoolExtend.add_subject_extension(Review._extend_subject)
        SchoolExtend.add_teacher_extension(Review._extend_teacher)

    def cog_unload(self):
        SchoolExtend.remove_subject_extension(Review._extend_subject)
        SchoolExtend.remove_teacher_extension(Review._extend_teacher)

    # School extension functions

    @staticmethod
    def _extend_subject(ctx: commands.Context, embed: discord.Embed, subject: Subject):
        """Extends subject information from School module"""
        grade = SubjectReview.avg_grade(subject)
        grade = "{:.1f}".format(grade) if grade else "-"
        embed.add_field(
            name=_(ctx, "Average grade:"),
            value=grade,
            inline=False,
        )

    @staticmethod
    def _extend_teacher(ctx: commands.Context, embed: discord.Embed, teacher: Teacher):
        """Extends subject information from School module"""
        grade = TeacherReview.avg_grade(teacher)
        grade = "{:.1f}".format(grade) if grade else "-"
        embed.add_field(
            name=_(ctx, "Average grade:"),
            value=grade,
            inline=False,
        )

    # Helper functions

    def _get_subject_review_embed(
        self,
        ctx: commands.Context,
        subject: Subject,
        review: SubjectReview,
        sudo: bool = False,
        delete: bool = False,
    ) -> ReviewEmbed:
        """Create subject review embed"""
        if review.anonym and not sudo:
            name = _(ctx, "Anonymous")
        else:
            name = self.bot.get_user(review.author_id) or _(ctx, "Unknown user")

        title = (
            _(ctx, "Review for subject '{abbreviation}':")
            if not delete
            else _(ctx, "Do you want to delete review for subject '{abbreviation}'?")
        )

        title = title.format(abbreviation=subject.abbreviation)

        embed = ReviewEmbed(
            author=ctx.author,
            title=title,
            description=subject.name if subject.name else None,
            color=discord.Color.green(),
            url=None,
            review=review,
            bot=self.bot,
        )

        guarantor = review.guarantor.name if review.guarantor else "-"
        guarantor = (
            f"*{guarantor}*"
            if review.guarantor_id != subject.guarantor_id
            else guarantor
        )

        embed.add_field(
            name=_(ctx, "Review ID #{id}").format(id=review.idx),
            value=_(ctx, "**Guarantor:** {name}").format(name=guarantor),
            inline=False,
        )

        embed.add_field(
            name=_(ctx, "Author:"),
            value=name,
        )

        if review.created != review.updated:
            embed.add_field(
                name=_(ctx, "Updated:"),
                value=review.updated,
            )
        embed.add_field(
            name=_(ctx, "Subject grade:"),
            value=str(review.grade),
        )

        embed.add_field(
            name=_(ctx, "Date of review:"),
            value=review.created,
        )

        text_review = textwrap.wrap(review.text_review, 1024)
        name = _(ctx, "Text:")

        for text in text_review:
            embed.add_field(name=name, value=text, inline=False)
            name = "\u200b"

        embed.add_field(name="👍\u200b", value=review.upvotes)
        embed.add_field(name="👎\u200b", value=review.downvotes)

        return embed

    def _get_teacher_review_embed(
        self,
        ctx: commands.Context,
        teacher: Teacher,
        review: TeacherReview,
        sudo: bool = False,
        delete: bool = False,
    ) -> ReviewEmbed:
        """Create teacher review embed"""
        if review.anonym and not sudo:
            name = _(ctx, "Anonymous")
        else:
            name = self.bot.get_user(review.author_id) or _(ctx, "Unknown user")

        title = (
            _(ctx, "Review for teacher #{id}:")
            if not delete
            else _(ctx, "Do you want to delete review for teacher #{id}?")
        )

        title = title.format(id=teacher.school_id)

        embed = ReviewEmbed(
            author=ctx.author,
            title=title,
            description=teacher.name if teacher.name else None,
            color=discord.Color.green(),
            url=None,
            review=review,
            bot=self.bot,
        )

        embed.add_field(
            name=_(ctx, "Review ID #{id}").format(id=review.idx),
            value=_(ctx, "Teacher grade: {grade}").format(grade=review.grade),
            inline=False,
        )

        embed.add_field(
            name=_(ctx, "Author:"),
            value=name,
        )

        if review.created != review.updated:
            embed.add_field(
                name=_(ctx, "Updated:"),
                value=review.updated,
            )

        embed.add_field(
            name=_(ctx, "Date of review:"),
            value=review.created,
        )

        text_review = textwrap.wrap(review.text_review, 1024)
        name = _(ctx, "Text:")

        for text in text_review:
            embed.add_field(name=name, value=text, inline=False)
            name = "\u200b"

        embed.add_field(name="👍\u200b", value=review.upvotes)
        embed.add_field(name="👎\u200b", value=review.downvotes)

        return embed

    @staticmethod
    def _split_list(li, n) -> Iterator[List[List]]:
        """Split list into lists of N items

        Args:
            li: List to split
            n: Number of items in one list
        """
        for i in range(0, len(li), n):
            yield li[i : i + n]

    async def _add_subject_review(
        self,
        ctx: commands.Context,
        abbreviation: str,
        grade: int,
        text: str,
        anonymous: bool,
    ) -> Optional[SubjectReview]:
        """Add and return review.

        Returns: review if success, None otherwise"""
        subject = Subject.get_by_abbreviation(ctx, abbreviation)

        if anonymous:
            await utils.discord.delete_message(ctx.message)

        if not subject:
            await ctx.send(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )
            return

        if grade < 1 or grade > 5:
            await ctx.send(_(ctx, "Grade must be between 1 and 5 inclusive."))
            return

        if text is None or not len(text):
            await ctx.send(_(ctx, "Review must contain text."))
            return

        review = SubjectReview.get_member_review(ctx.author, subject)

        if review:
            review.edit(grade, anonymous, text)
        else:
            review = SubjectReview.add(ctx, subject, grade, anonymous, text)

        return review

    async def _add_teacher_review(
        self,
        ctx: commands.Context,
        teacher_id: int,
        grade: int,
        text: str,
        anonymous: bool,
    ) -> Optional[TeacherReview]:
        """Add and return review.

        Returns: review if success, None otherwise"""
        teacher = Teacher.get_by_sid(ctx, teacher_id)

        if anonymous:
            await utils.discord.delete_message(ctx.message)

        if not teacher:
            await ctx.send(
                _(ctx, "Teacher with ID {id} not found.").format(id=teacher_id)
            )
            return

        if grade < 1 or grade > 5:
            await ctx.send(_(ctx, "Grade must be between 1 and 5 inclusive."))
            return

        if text is None or not len(text):
            await ctx.send(_(ctx, "Review must contain text."))
            return

        review = TeacherReview.get_member_review(ctx.author, teacher)

        if review:
            review.edit(grade, anonymous, text)
        else:
            review = TeacherReview.add(ctx, teacher, grade, anonymous, text)

        return review

    # Commands

    @commands.guild_only()
    @commands.cooldown(rate=5, per=60, type=commands.BucketType.user)
    @check.acl2(check.ACLevel.MEMBER)
    @commands.group(name="review")
    async def review_(self, ctx: commands.Context):
        """Manage school reviews"""
        await utils.discord.send_help(ctx)

    # SUBJECT REVIEW

    @check.acl2(check.ACLevel.MEMBER)
    @review_.group(name="subject")
    async def review_subject_(self, ctx: commands.Context):
        """Manage subject reviews"""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @review_subject_.command(name="list", aliases=["show", "see"])
    async def review_subject_list(self, ctx: commands.Context, abbreviation: str):
        """Show subject's reviews

        Args:
            abbreviation: Subject's abbreviation
        """
        subject = Subject.get_by_abbreviation(ctx, abbreviation)
        if subject is None:
            return await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.")
            )

        reviews = SubjectReview.get_all_by_subject(subject)

        if not reviews:
            return await ctx.reply(_(ctx, "There are no reviews for this subject."))

        pages = []
        for review in reviews:
            pages.append(self._get_subject_review_embed(ctx, subject, review))

        scrollable = ScrollableVotingEmbed(
            ctx, pages, delete_message=False, locked=True
        )
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MEMBER)
    @review_subject_.command(name="mine", aliases=["my-list", "mylist"])
    async def review_subject_mine(self, ctx: commands.Context):
        """Get list of all your reviewed subjects"""
        reviews = SubjectReview.get_all_by_author(ctx)

        if not reviews:
            return await ctx.reply(_(ctx, "You have no reviews."))

        subjects = sorted([review.subject.abbreviation for review in reviews])

        subjects = Review._split_list(subjects, 10)

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Your reviews:"),
        )

        for subject_list in subjects:
            embed.add_field(
                name="\u200b",
                value="\n".join(subject_list),
                inline=False,
            )

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @review_subject_.command(name="add", aliases=["update"])
    async def review_subject_add(
        self, ctx: commands.Context, abbreviation: str, grade: int, *, text: str
    ):
        """Add or edit subject review. Resets relevance if review is older than 1 month.

        Args:
            abbreviation: Subject's abbreviation
            grade: 1-5 (one being best)
            text: Text of your review
        """
        abbreviation = abbreviation.upper()

        result = await self._add_subject_review(
            ctx, abbreviation, grade, text, anonymous=False
        )

        if result is not None:
            await ctx.reply(
                _(ctx, "Your review of subject {abbreviation} added.").format(
                    abbreviation=abbreviation
                )
            )
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Review #{result.idx} for {abbreviation} added.",
            )

    @check.acl2(check.ACLevel.MEMBER)
    @review_subject_.command(name="add-anonymous", aliases=["anonymous", "anon"])
    async def review_subject_add_anonymous(
        self, ctx: commands.Context, abbreviation: str, grade: int, *, text: str
    ):
        """Add or edit anonymous subject review. Resets relevance if review is older than 1 month.

        Args:
            abbreviation: Subject's abbreviation
            grade: 1-5 (one being best)
            text: Text of your review
        """
        abbreviation = abbreviation.upper()

        result = await self._add_subject_review(
            ctx, abbreviation, grade, text, anonymous=True
        )

        if result is not None:
            await ctx.send(
                _(ctx, "Your review of subject {abbreviation} added.").format(
                    abbreviation=abbreviation
                )
            )
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Review #{result.idx} for {abbreviation} added.",
            )

    @check.acl2(check.ACLevel.MEMBER)
    @review_subject_.command(name="remove")
    async def review_subject_remove(self, ctx: commands.Context, abbreviation: str):
        """Remove your subject review

        Args:
            abbreviation: Subject abbreviation
        """
        abbreviation = abbreviation.upper()
        subject = Subject.get_by_abbreviation(ctx, abbreviation)

        if not subject:
            await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )
            return

        review = SubjectReview.get_member_review(ctx.author, subject)

        if review is None:
            return await ctx.send(
                _(ctx, "You have no review of subject {abbreviation}.").format(
                    abbreviation=abbreviation
                )
            )

        embed = self._get_subject_review_embed(
            ctx=ctx,
            subject=review.subject,
            review=review,
            delete=True,
        )

        view = ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            review.delete()
            await guild_log.info(
                ctx.author, ctx.channel, f"Removed review for {subject.abbreviation}."
            )
            return await ctx.reply(_(ctx, "Your review was removed."))
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.SUBMOD)
    @review_subject_.group(name="sudo")
    async def review_subject_sudo_(self, ctx: commands.Context):
        """Manage other user's subject reviews"""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.SUBMOD)
    @review_subject_sudo_.command(name="remove")
    async def review_subject_sudo_remove(self, ctx: commands.Context, idx: int):
        """Remove someone's subject review

        Args:
            idx: ID of review
        """
        review = SubjectReview.get_by_idx(ctx, idx)

        if not review:
            return await ctx.send(_(ctx, "No review with ID {id}.").format(id=idx))

        embed = self._get_subject_review_embed(
            ctx=ctx,
            subject=review.subject,
            review=review,
            sudo=True,
            delete=True,
        )

        view = ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            member = self.bot.get_user(review.author_id) or _(ctx, "Unknown user")
            abbreviation = review.subject.abbreviation
            review.delete()
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Sudo removed review id {idx} for {abbreviation} by {member}.",
            )
            return await ctx.reply(_(ctx, "User's review was removed."))
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    # TEACHER REVIEW

    @check.acl2(check.ACLevel.MEMBER)
    @review_.group(name="teacher")
    async def review_teacher_(self, ctx: commands.Context):
        """Manage teacher reviews"""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @review_teacher_.command(name="list", aliases=["show", "see"])
    async def review_teacher_list(self, ctx: commands.Context, teacher_id: int):
        """Show teacher's reviews

        Args:
            teacher_id: Teacher's school ID
        """
        teacher = Teacher.get_by_sid(ctx, teacher_id)
        if teacher is None:
            return await ctx.reply(
                _(ctx, "Teacher with ID {id} not found.").format(id=teacher_id)
            )

        reviews = TeacherReview.get_all_by_teacher(teacher)

        if not reviews:
            return await ctx.reply(_(ctx, "There are no reviews for this teacher."))

        pages = []
        for review in reviews:
            pages.append(self._get_teacher_review_embed(ctx, teacher, review))

        scrollable = ScrollableVotingEmbed(
            ctx, pages, delete_message=False, locked=True
        )
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MEMBER)
    @review_teacher_.command(name="mine", aliases=["my-list", "mylist"])
    async def review_teacher_mine(self, ctx: commands.Context):
        """Get list of all your reviewed teachers"""
        reviews = TeacherReview.get_all_by_author(ctx)

        if not reviews:
            return await ctx.reply(_(ctx, "You have no reviews."))

        teachers = sorted(
            [
                f"{review.teacher.name} ({review.teacher.school_id})"
                for review in reviews
            ]
        )

        teachers = Review._split_list(teachers, 10)

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Your reviews:"),
        )

        for teacher_list in teachers:
            embed.add_field(
                name="\u200b",
                value="\n".join(teacher_list),
                inline=False,
            )

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @review_teacher_.command(name="add", aliases=["update"])
    async def review_teacher_add(
        self, ctx: commands.Context, teacher_id: int, grade: int, *, text: str
    ):
        """Add or edit teacher review. Resets relevance if review is older than 1 month.

        Args:
            teacher_id: Teacher's school ID
            grade: 1-5 (one being best)
            text: Text of your review
        """

        result = await self._add_teacher_review(
            ctx, teacher_id, grade, text, anonymous=False
        )

        if result is not None:
            await ctx.reply(
                _(ctx, "Your review of teacher {name} added.").format(
                    name=result.teacher.name
                )
            )
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Review #{result.idx} for {result.teacher.name} added.",
            )

    @check.acl2(check.ACLevel.MEMBER)
    @review_teacher_.command(name="add-anonymous", aliases=["anonymous", "anon"])
    async def review_teacher_add_anonymous(
        self, ctx: commands.Context, teacher_id: int, grade: int, *, text: str
    ):
        """Add or edit anonymous teacher review. Resets relevance if review is older than 1 month.

        Args:
            teacher_id: Teacher's school ID
            grade: 1-5 (one being best)
            text: Text of your review
        """

        result = await self._add_teacher_review(
            ctx, teacher_id, grade, text, anonymous=True
        )

        if result is not None:
            await ctx.send(
                _(ctx, "Your review of teacher {name} added.").format(
                    name=result.teacher.name
                )
            )
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Review #{result.idx} for {result.teacher.name} added.",
            )

    @check.acl2(check.ACLevel.MEMBER)
    @review_teacher_.command(name="remove")
    async def review_teacher_remove(self, ctx: commands.Context, teacher_id: int):
        """Remove your teacher review

        Args:
            teacher_id: Teacher's school ID
        """
        teacher = Teacher.get_by_sid(ctx, teacher_id)

        if not teacher:
            await ctx.reply(
                _(ctx, "Teacher with ID {id} not found.").format(id=teacher_id)
            )
            return

        review = TeacherReview.get_member_review(ctx.author, teacher)

        if review is None:
            return await ctx.send(
                _(ctx, "You have no review of teacher {name}.").format(
                    name=teacher.name
                )
            )

        embed = self._get_teacher_review_embed(
            ctx=ctx,
            teacher=review.teacher,
            review=review,
            sudo=True,
            delete=True,
        )

        view = ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            review.delete()
            await guild_log.info(
                ctx.author, ctx.channel, f"Removed review for {teacher.name}."
            )
            return await ctx.reply(_(ctx, "Your review was removed."))
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.SUBMOD)
    @review_teacher_.group(name="sudo")
    async def review_teacher_sudo_(self, ctx: commands.Context):
        """Manage other user's reviews"""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.SUBMOD)
    @review_teacher_sudo_.command(name="remove")
    async def review_teacher_sudo_remove(self, ctx: commands.Context, idx: int):
        """Remove someone's teacher review

        Args:
            idx: ID of review
        """
        review = TeacherReview.get_by_idx(ctx, idx)

        if not review:
            return await ctx.send(_(ctx, "No review with ID {id}.").format(id=idx))

        embed = self._get_teacher_review_embed(
            ctx=ctx,
            teacher=review.teacher,
            review=review,
            sudo=True,
            delete=True,
        )

        view = ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            member = self.bot.get_user(review.author_id) or _(ctx, "Unknown user")
            name = review.teacher.name
            review.delete()
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Sudo removed review id {idx} for {name} by {member}.",
            )
            return await ctx.reply(_(ctx, "User's review was removed."))
        else:
            await ctx.send(_(ctx, "Deleting aborted."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Review(bot))
