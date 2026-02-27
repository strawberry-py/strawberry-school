from __future__ import annotations

import textwrap
from typing import Iterator, List, Optional, Type, Union

import discord
from discord.ext import commands

from pie import check, i18n, logger, utils
from pie.utils.objects import ConfirmView, ScrollableVotingEmbed

from ..school.database import Subject, Teacher
from ..school.module import SchoolExtend
from .database import ReviewBase, SubjectReview, TeacherReview
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
        grade = f"{grade:.1f}" if grade else "-"
        embed.add_field(
            name=_(ctx, "Average grade:"),
            value=grade,
            inline=False,
        )

    @staticmethod
    def _extend_teacher(ctx: commands.Context, embed: discord.Embed, teacher: Teacher):
        """Extends teacher information from School module"""
        grade = TeacherReview.avg_grade(teacher)
        grade = f"{grade:.1f}" if grade else "-"
        embed.add_field(
            name=_(ctx, "Average grade:"),
            value=grade,
            inline=False,
        )

    # Helper functions - Validation

    async def _validate_grade(self, ctx: commands.Context, grade: int) -> bool:
        """Validate grade is within acceptable range.

        Returns:
            True if valid, False otherwise (error message sent to user)
        """
        if grade < 1 or grade > 5:
            await ctx.send(_(ctx, "Grade must be between 1 and 5 inclusive."))
            return False
        return True

    async def _validate_review_text(self, ctx: commands.Context, text: str) -> bool:
        """Validate review text is not empty.

        Returns:
            True if valid, False otherwise (error message sent to user)
        """
        if text is None or not len(text):
            await ctx.send(_(ctx, "Review must contain text."))
            return False
        return True

    # Helper functions - Entity Retrieval

    async def _get_subject_or_reply(
        self, ctx: commands.Context, abbreviation: str
    ) -> Optional[Subject]:
        """Get subject by abbreviation or send error message.

        Returns:
            Subject if found, None otherwise (error message sent to user)
        """
        subject = Subject.get_by_abbreviation(ctx, abbreviation)
        if not subject:
            await ctx.send(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )
        return subject

    async def _get_teacher_or_reply(
        self, ctx: commands.Context, teacher_id: int
    ) -> Optional[Teacher]:
        """Get teacher by school ID or send error message.

        Returns:
            Teacher if found, None otherwise (error message sent to user)
        """
        teacher = Teacher.get_by_sid(ctx, teacher_id)
        if not teacher:
            await ctx.send(
                _(ctx, "Teacher with ID {id} not found.").format(id=teacher_id)
            )
        return teacher

    # Helper functions - Embed Creation

    def _get_subject_review_embed(
        self,
        ctx: commands.Context,
        subject: Subject,
        review: SubjectReview,
        sudo: bool = False,
        delete: bool = False,
    ) -> ReviewEmbed:
        """Create a formatted Discord embed for displaying a subject review.

        Args:
            ctx: Command context for translation and author info
            subject: The Subject being reviewed
            review: SubjectReview database object with review data
            sudo: If True, reveals author name for anonymous reviews (default: False)
            delete: If True, formats as deletion confirmation prompt (default: False)

        Returns:
            ReviewEmbed with voting functionality and formatted review details.

        Note:
            Guarantor names are italicized if different from current guarantor.
            Review text is wrapped to 1024 character chunks for Discord limits.
        """
        title = (
            _(ctx, "Review for subject '{abbreviation}':")
            if not delete
            else _(ctx, "Do you want to delete review for subject '{abbreviation}'?")
        ).format(abbreviation=subject.abbreviation)

        guarantor = review.guarantor.name if review.guarantor else "-"
        guarantor = (
            f"*{guarantor}*"
            if review.guarantor_id != subject.guarantor_id
            else guarantor
        )

        additional_info = _(ctx, "**Guarantor:** {name}").format(name=guarantor)
        additional_info += "\n" + _(ctx, "Subject grade: {grade}").format(
            grade=review.grade
        )

        return self._create_review_embed(
            ctx=ctx,
            review=review,
            title_template=title,
            title_format={},
            description=subject.name,
            additional_info=additional_info,
            sudo=sudo,
        )

    def _get_teacher_review_embed(
        self,
        ctx: commands.Context,
        teacher: Teacher,
        review: TeacherReview,
        sudo: bool = False,
        delete: bool = False,
    ) -> ReviewEmbed:
        """Create teacher review embed"""
        return self._create_review_embed(
            ctx=ctx,
            review=review,
            title_template=(
                _(ctx, "Review for teacher #{id}:")
                if not delete
                else _(ctx, "Do you want to delete review for teacher #{id}?")
            ),
            title_format={"id": teacher.school_id},
            description=teacher.name if teacher.name else None,
            additional_info=_(ctx, "Teacher grade: {grade}").format(grade=review.grade),
            sudo=sudo,
        )

    def _create_review_embed(
        self,
        ctx: commands.Context,
        review: ReviewBase,
        title_template: str,
        title_format: dict,
        description: Optional[str],
        additional_info: str,
        sudo: bool = False,
    ) -> ReviewEmbed:
        """Generic review embed creator for both subjects and teachers.

        Args:
            ctx: Command context
            review: Review object (SubjectReview or TeacherReview)
            title_template: Formatted title string
            title_format: Format dict for title
            description: Embed description
            additional_info: Additional info to display in Review ID field
            sudo: Whether to reveal anonymous author

        Returns:
            ReviewEmbed with voting functionality
        """
        if review.anonym and not sudo:
            author_name = _(ctx, "Anonymous")
        else:
            author_name = self.bot.get_user(review.author_id) or _(ctx, "Unknown user")

        embed = ReviewEmbed(
            author=ctx.author,
            title=title_template.format(**title_format),
            description=description,
            color=discord.Color.green(),
            url=None,
            review=review,
            bot=self.bot,
        )

        embed.add_field(
            name=_(ctx, "Review ID #{id}").format(id=review.idx),
            value=additional_info,
            inline=False,
        )

        embed.add_field(
            name=_(ctx, "Author:"),
            value=author_name,
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
        field_name = _(ctx, "Text:")

        for text in text_review:
            embed.add_field(name=field_name, value=text, inline=False)
            field_name = "\u200b"

        embed.add_field(name="👍\u200b", value=review.upvotes)
        embed.add_field(name="👎\u200b", value=review.downvotes)

        return embed

    @staticmethod
    def _split_list(items: List, chunk_size: int) -> Iterator[List]:
        """Split list into chunks of specified size.

        Args:
            items: List to split
            chunk_size: Number of items in each chunk
        """
        for i in range(0, len(items), chunk_size):
            yield items[i : i + chunk_size]

    async def _add_review(
        self,
        ctx: commands.Context,
        entity: Union[Subject, Teacher],
        review_class: Union[Type[SubjectReview], Type[TeacherReview]],
        grade: int,
        text: str,
        anonymous: bool,
    ) -> Optional[ReviewBase]:
        """Generic method to add and return a review.

        Args:
            ctx: Command context
            entity: Subject or Teacher being reviewed
            review_class: SubjectReview or TeacherReview class
            grade: Review grade (1-5)
            text: Review text content
            anonymous: Whether review is anonymous

        Returns:
            Review if success, None otherwise
        """
        if anonymous:
            await utils.discord.delete_message(ctx.message)

        if not await self._validate_grade(ctx, grade):
            return None

        if not await self._validate_review_text(ctx, text):
            return None

        return await self._add_or_edit_review(
            ctx, entity, review_class, grade, anonymous, text
        )

    async def _add_subject_review(
        self,
        ctx: commands.Context,
        abbreviation: str,
        grade: int,
        text: str,
        anonymous: bool,
    ) -> Optional[SubjectReview]:
        """Add and return subject review.

        Returns:
            SubjectReview if success, None otherwise
        """
        subject = await self._get_subject_or_reply(ctx, abbreviation)
        if not subject:
            return None

        return await self._add_review(
            ctx, subject, SubjectReview, grade, text, anonymous
        )

    async def _add_teacher_review(
        self,
        ctx: commands.Context,
        teacher_id: int,
        grade: int,
        text: str,
        anonymous: bool,
    ) -> Optional[TeacherReview]:
        """Add and return teacher review.

        Returns:
            TeacherReview if success, None otherwise
        """
        teacher = await self._get_teacher_or_reply(ctx, teacher_id)
        if not teacher:
            return None

        return await self._add_review(
            ctx, teacher, TeacherReview, grade, text, anonymous
        )

    async def _add_or_edit_review(
        self,
        ctx: commands.Context,
        entity: Union[Subject, Teacher],
        review_class: Union[Type[SubjectReview], Type[TeacherReview]],
        grade: int,
        anonymous: bool,
        text: str,
    ) -> ReviewBase:
        """Generic method to add or edit a review.

        Args:
            ctx: Command context
            entity: Subject or Teacher being reviewed
            review_class: SubjectReview or TeacherReview class
            grade: Review grade (1-5)
            anonymous: Whether review is anonymous
            text: Review text content

        Returns:
            Created or edited review object
        """
        review = review_class.get_member_review(ctx.author, entity)

        if review:
            review.edit(grade, anonymous, text)
        else:
            review = review_class.add(ctx, entity, grade, anonymous, text)

        return review

    async def _confirm_and_delete_review(
        self,
        ctx: commands.Context,
        review: ReviewBase,
        embed: ReviewEmbed,
        entity_name: str,
    ) -> None:
        """Generic deletion confirmation flow.

        Args:
            ctx: Command context
            review: Review to potentially delete
            embed: Confirmation embed
            entity_name: Name of entity for logging (e.g., subject abbreviation)
        """
        view = ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            review.delete()
            await guild_log.info(
                ctx.author, ctx.channel, f"Removed review for {entity_name}."
            )
            await ctx.reply(_(ctx, "Your review was removed."))
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    async def _confirm_and_sudo_delete_review(
        self,
        ctx: commands.Context,
        review: ReviewBase,
        embed: ReviewEmbed,
        review_idx: int,
        entity_name: str,
    ) -> None:
        """Generic sudo deletion confirmation flow.

        Args:
            ctx: Command context
            review: Review to potentially delete
            embed: Confirmation embed
            review_idx: Review ID for logging
            entity_name: Name of entity for logging
        """
        view = ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            member = self.bot.get_user(review.author_id) or _(ctx, "Unknown user")
            review.delete()
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Sudo removed review id {review_idx} for {entity_name} by {member}.",
            )
            await ctx.reply(_(ctx, "User's review was removed."))
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

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
            return await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )

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

        await self._confirm_and_delete_review(ctx, review, embed, subject.abbreviation)

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

        await self._confirm_and_sudo_delete_review(
            ctx, review, embed, idx, review.subject.abbreviation
        )

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
            delete=True,
        )

        await self._confirm_and_delete_review(ctx, review, embed, teacher.name)

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

        await self._confirm_and_sudo_delete_review(
            ctx, review, embed, idx, review.teacher.name
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Review(bot))
