import argparse
import json
import re
import shlex
import tempfile
from typing import Callable, Iterable, List, Optional

import discord
from discord.ext import commands

from pie import check, i18n, logger, utils

from .database import Program, Subject, SubjectProgram, Teacher

_ = i18n.Translator("modules/school").translate
guild_log = logger.Guild.logger()
bot_log = logger.Bot.logger()

DEGREE_MAPPING = {
    "B": "Bachelor",
    "D": "Doctoral",
    "M": "Masters",
    "N": "Masters",
}

SEMESTERS = {"Winter", "Summer", "Both"}

# This is used to sort subjects in various situations and check
OBLIGATIONS = ["P", "PV", "D", "V", "VO", "O"]

# TODO: CommandParser SHOULD BE MOVED TO CORE (PIE)


class CommandParser(argparse.ArgumentParser):
    """Patch ArgumentParser.

    ArgumentParser calls sys.exit(2) on incorrect command,
    which would take down the bot. This subclass catches the errors
    and saves them in 'error_message' attribute.
    """

    error_message: Optional[str] = None

    def error(self, message: str):
        """Save the error message."""
        self.error_message = message

    def exit(self):
        """Make sure the program _does not_ exit."""
        pass

    def parse_args(self, args: Iterable):
        """Catch exceptions that do not occur when CLI program exits."""
        returned = self.parse_known_args(args)
        try:
            args, argv = returned
        except TypeError:
            # There was an error and it is saved in 'error_message'
            return None
        return args


class SchoolExtend:
    _teacher_extension = []
    _subject_extension = []
    _program_extension = []

    @staticmethod
    def add_teacher_extension(func: Callable):
        """Add callable to list of functions which are called
        when creating teacher info embed. Function must be static
        and must take this arguments:

            ctx: `command.Context` command context
            embed: `discord.Embed` embed to add more data
            teacher: `.database.Teacher` teacher data

        """
        if func is None:
            return

        if func not in SchoolExtend._teacher_extension:
            SchoolExtend._teacher_extension.append(func)

    @staticmethod
    def remove_teacher_extension(func: Callable):
        """Remove callable from list of functions called when
        creating teacher info embed.
        """
        if func in SchoolExtend._teacher_extension:
            SchoolExtend._teacher_extension.remove(func)

    @staticmethod
    def add_subject_extension(func: Callable):
        """Add callable to list of functions which are called
        when creating subject info embed. Function must be static
        and must take this arguments:

            ctx: `command.Context` command context
            embed: `discord.Embed` embed to add more data
            subject: `.database.Subject` subject data

        """
        if func is None:
            return

        if func not in SchoolExtend._subject_extension:
            SchoolExtend._subject_extension.append(func)

    @staticmethod
    def remove_subject_extension(func: Callable):
        """Remove callable from list of functions called when
        creating subject info embed.
        """
        if func in SchoolExtend._subject_extension:
            SchoolExtend._subject_extension.remove(func)

    @staticmethod
    def add_program_extension(func: Callable):
        """Add callable to list of functions which are called
        when creating program info embed. Function must be static
        and must take this arguments:

            ctx: `command.Context` command context
            embed: `discord.Embed` embed to add more data
            program: `.database.Program` program data
        """
        if func is None:
            return

        if func not in SchoolExtend._program_extension:
            SchoolExtend._program_extension.append(func)

    @staticmethod
    def remove_program_extension(func: Callable):
        """Remove callable from list of functions called when
        creating program info embed.
        """
        if func in SchoolExtend._program_extension:
            SchoolExtend._program_extension.remove(func)


class School(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # SUBJECT COMMANDS

    @commands.guild_only()
    @check.acl2(check.ACLevel.MEMBER)
    @commands.group(name="subject")
    async def subject_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @subject_.command(name="info")
    async def subject_info(self, ctx, abbreviation):
        """Show subject informations
        Args:
            abbreviation: Short name of subject
        """
        subject = Subject.get_by_abbreviation(ctx, abbreviation)

        if not subject:
            await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )
            return

        embed = await self._get_subject_embed(ctx, subject, True)

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @subject_.command(name="search", aliases=["list"])
    async def subject_search(self, ctx, *, name: str):
        """Search subject by name.

        Args:
            name: Subject's name (atleast 3 chars)
        """
        if len(name) < 3:
            await ctx.reply(_(ctx, "Name must be atleast 3 characters long."))
            return

        subjects = Subject.search(ctx, name)

        if len(subjects) == 0:
            await ctx.reply(
                _(ctx, "No subject with name '{name}' found.").format(name=name)
            )
            return

        subject_strings = []

        for subject in subjects:
            subject_strings.append(f"{subject.name} (**{subject.abbreviation}**)")

        subject_strings = sorted(subject_strings)
        subject_strings = School._split_list(subject_strings, 10)

        pages = []

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Results for name '{name}':").format(name=name),
        )

        for subjects in subject_strings:
            page = embed.copy()

            page.add_field(
                name="\u200b",
                value="\n".join(subjects),
                inline=False,
            )

            pages.append(page)

        scrollable = utils.ScrollableEmbed(ctx, pages)
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MOD)
    @subject_.command(name="edit")
    async def subject_edit(self, ctx, abbreviation: str, *, parameters: str):
        """Edit existing subject.

        Only include the arguments you want to change.

        Args:
            abbreviation: Original subject abbreviation
        Parameters:
            --abbreviation: New abbreviation (string)
            --name: New subject name
            --institute: Subject's institute
            --semester: `Winter`, `Summer` or `Both`
            --guarantor: ID of the guaranteeing teacher
            --teachers-add: List of teacher's ID's to add
            --teachers-remove: List of teacher's ID's to remove
        """
        subject = Subject.get_by_abbreviation(ctx, abbreviation)
        if not subject:
            await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )
            return
        args = await self._parse_subject_parameters(ctx, parameters)
        if args is None:
            return

        guarantor = None
        if args.guarantor:
            guarantor = Teacher.get_by_sid(ctx, args.guarantor)
            if not guarantor:
                await ctx.reply(
                    _(ctx, "Teacher with ID {id} not found.").format(id=args.guarantor)
                )
                return

        if args.abbreviation:
            if subject.abbreviation == args.abbreviation:
                args.abbreviation = None
            elif Subject.get_by_abbreviation(ctx, args.abbreviation):
                await ctx.reply(
                    _(
                        ctx, "Subject with abbreviation {abbreviation} already exists!"
                    ).format(abbreviation=args.abbreviation)
                )
                return

        if args.teachers_add and args.teachers_remove:
            for teacher in args.teachers_add:
                if teacher in args.teachers_remove:
                    await ctx.reply(
                        _(
                            ctx, "You can't add and remove same teacher (ID: {id})."
                        ).format(id=teacher.school_id)
                    )
                    return

        teachers_add = (
            await self._parse_teachers_args(ctx, args.teachers_add)
            if args.teachers_add
            else None
        )

        teachers_remove = (
            await self._parse_teachers_args(ctx, args.teachers_remove)
            if args.teachers_remove
            else None
        )

        if teachers_add:
            add_ignore = subject.add_teachers(teachers_add)

        if teachers_remove:
            remove_ignore = subject.remove_teachers(teachers_remove)

        subject.edit(
            args.abbreviation, args.name, args.institute, args.semester, guarantor
        )

        message = _(ctx, "Subject successfuly edited.")

        if teachers_add and add_ignore:
            message += "\n" + _(ctx, "Already teaching teachers: {teachers}").format(
                teachers=", ".join(add_ignore)
            )

        if teachers_remove and remove_ignore:
            message += "\n" + _(
                ctx, "Can't remove teachers that don't teach this subject: {teachers}"
            ).format(teachers=", ".join(remove_ignore))

        await ctx.reply(message)

        log_message = f"Subject '{abbreviation}' edited."
        if args.abbreviation:
            log_message += f" New abbreviation: '{args.abbreviation}'."

        await guild_log.info(ctx.author, ctx.channel, log_message)

    @check.acl2(check.ACLevel.MOD)
    @subject_.command(name="delete")
    async def subject_delete(self, ctx, abbreviation: str):
        """Delete subject.

        Args:
            abbreviation: Subject abbreviation
        """
        subject = Subject.get_by_abbreviation(ctx, abbreviation)
        if not subject:
            await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=abbreviation
                )
            )
            return

        embed = await self._get_subject_embed(ctx, subject, True)
        embed.title = (
            _(ctx, "Do you want to delete this subject:") + " " + embed.title + "?"
        )

        view = utils.ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            subject.delete()
            await ctx.send(
                _(ctx, "Subject {abbreviation} deleted.").format(
                    abbreviation=abbreviation
                )
            )
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Subject {subject.abbreviation} deleted.",
            )
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.MOD)
    @subject_.group(name="purge")
    async def subject_purge_(self, ctx):
        """Purge subjects that are not used."""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MOD)
    @subject_purge_.command(name="list")
    async def subject_purge_list(self, ctx):
        """Show list of subjects used by other modules"""
        subjects = Subject.get_not_used(ctx)

        class Item:
            def __init__(self, subject):
                self.abbreviation = subject.abbreviation
                self.name = subject.name

        items: List[Item] = []

        for subject in subjects:
            items.append(Item(subject))

        table: List[str] = utils.text.create_table(
            items,
            header={
                "abbreviation": _(ctx, "Abbreviation"),
                "name": _(ctx, "Subject name"),
            },
        )

        for page in table:
            await ctx.send("```" + page + "```")

    # TEACHER COMMANDS

    @commands.guild_only()
    @check.acl2(check.ACLevel.MEMBER)
    @commands.group(name="teacher")
    async def teacher_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @teacher_.command(name="info")
    async def teacher_info(self, ctx, teacher_id: int):
        """Show teacher informations

        Args:
            teacher_id: Schoold ID of teacher
        """
        teacher = Teacher.get_by_sid(ctx, teacher_id)

        if not teacher:
            await ctx.reply(
                _(ctx, "Teacher with ID {id} not found.").format(id=teacher_id)
            )
            return

        embed = await self._get_teacher_embed(ctx, teacher, True)

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @teacher_.command(name="search", aliases=["list"])
    async def teacher_search(self, ctx, name):
        """Search teacher by name.

        Args:
            name: Teacher's name (atleast 3 chars)
        """
        if len(name) < 3:
            await ctx.reply(_(ctx, "Name must be atleast 3 characters long."))
            return

        teachers = Teacher.search(ctx, name)

        if len(teachers) == 0:
            await ctx.reply(
                _(ctx, "No teacher with name '{name}' found.").format(name=name)
            )
            return

        teacher_strings = []

        for teacher in teachers:
            teacher_strings.append(f"{teacher.name} ({teacher.school_id})")

        teacher_strings = sorted(teacher_strings)
        teacher_strings = School._split_list(teacher_strings, 10)

        pages = []

        embed = utils.discord.create_embed(
            author=ctx.author,
            title=_(ctx, "Results for name '{name}':").format(name=name),
        )

        for teachers in teacher_strings:
            page = embed.copy()

            page.add_field(
                name="\u200b",
                value="\n".join(teachers),
                inline=False,
            )

            pages.append(page)

        scrollable = utils.ScrollableEmbed(ctx, pages)
        await scrollable.scroll()

    @check.acl2(check.ACLevel.MOD)
    @teacher_.command(name="edit")
    async def teacher_edit(self, ctx, id: int, *, name: str):
        """Edit existing teacher.

        Args:
            id: Teacher school ID
            name: Teacher's new name
        """

        teacher = Teacher.get_by_sid(ctx, id)

        if not teacher:
            await ctx.reply(_(ctx, "Teacher with ID {id} not found.").format(id=id))
            return

        teacher.edit(name)

        await ctx.reply(_(ctx, "Teacher succesfuly edited."))

        await guild_log.info(ctx.author, ctx.channel, f"Teacher {id} edited.")

    @check.acl2(check.ACLevel.MOD)
    @teacher_.command(name="delete")
    async def teacher_delete(self, ctx, id: int):
        """Delete teacher.

        Args:
            id: Teacher school ID
        """
        teacher = Teacher.get_by_sid(ctx, id)
        if not teacher:
            await ctx.reply(_(ctx, "Teacher with ID {id} not found.").format(id=id))
            return

        embed = await self._get_teacher_embed(ctx, teacher, True)
        embed.title = (
            _(ctx, "Do you want to delete this teacher:") + " " + embed.title + "?"
        )

        view = utils.ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            teacher.delete()
            await ctx.send(_(ctx, "Teacher {name} deleted.").format(name=teacher.name))
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Teacher {teacher.name} deleted.",
            )
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.MOD)
    @teacher_.group(name="purge")
    async def teacher_purge_(self, ctx):
        """Purge subjects that are not used."""
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MOD)
    @teacher_purge_.command(name="list")
    async def teacher_purge_list(self, ctx):
        """Show list of subjects used by other modules"""
        teachers = Teacher.get_not_used(ctx)

        class Item:
            def __init__(self, teacher):
                self.school_id = teacher.school_id
                self.name = teacher.name

        items: List[Item] = []

        for teacher in teachers:
            items.append(Item(teacher))

        table: List[str] = utils.text.create_table(
            items,
            header={
                "school_id": _(ctx, "School ID"),
                "name": _(ctx, "Teacher name"),
            },
        )

        for page in table:
            await ctx.send("```" + page + "```")

    # PROGRAM COMMANDS

    @commands.guild_only()
    @check.acl2(check.ACLevel.MEMBER)
    @commands.group(name="program")
    async def program_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MEMBER)
    @program_.command(name="info")
    async def program_info(self, ctx, degree: str, abbreviation: str):
        """Show program informations

        Args:
            degree: Program degree (B, M or D)
            abbreviation: Short name of program
        """
        degree = degree.upper()
        abbreviation = abbreviation.upper()

        if degree and degree not in DEGREE_MAPPING:
            await ctx.reply(
                _(
                    ctx,
                    "Degree must be B for Bachelor, M for Masters or D for Doctoral.",
                )
            )
            return

        program = Program.get_by_abbreviation(ctx, degree, abbreviation)

        if not program:
            await ctx.reply(
                _(
                    ctx,
                    "Program with abbreviation {abbreviation} and degree {degree} not found.",
                ).format(abbreviation=abbreviation, degree=degree)
            )
            return

        embed = await self._get_program_embed(ctx, program, True)

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MEMBER)
    @program_.command(name="list", aliases=["search"])
    async def program_list(self, ctx, *, degree: str = None):
        """List programs"""
        degree = degree.upper() if degree is not None else None

        if degree and degree not in DEGREE_MAPPING:
            ctx.reply(
                _(
                    ctx,
                    "Degree must be B for Bachelor, M for Masters or D for Doctoral.",
                )
            )
            return

        programs = Program.get_all(ctx, degree)
        sorted_programs = {}
        for program in programs:
            degree = program.degree if program.degree else "-"
            if degree not in sorted_programs:
                sorted_programs[degree] = []
            sorted_programs[degree].append(program.abbreviation)

        embed = utils.discord.create_embed(
            author=ctx.author, title=_(ctx, "Program list")
        )

        for degree, programs in sorted_programs.items():
            embed.add_field(
                name=School._translate_degree(ctx, degree),
                value=", ".join(sorted(programs)),
                inline=False,
            )

        await ctx.reply(embed=embed)

    @check.acl2(check.ACLevel.MOD)
    @program_.command(name="edit")
    async def program_edit(
        self, ctx, degree: str, abbreviation: str, *, parameters: str
    ):
        """Edit existing program.

        Only include the arguments you want to change.

        Args:
            degree: Original program degree
            abbreviation: Original program abbreviation
        Parameters:
            --abbreviation: New abbreviation (string)
            --name: New program name
            --degree: Program degree
        """
        degree = degree.upper()
        abbreviation = abbreviation.upper()

        if degree not in DEGREE_MAPPING:
            await ctx.reply(
                _(
                    ctx,
                    "Degree must be B for Bachelor, M for Masters or D for Doctoral.",
                )
            )
            return

        program = Program.get_by_abbreviation(ctx, degree, abbreviation)
        if not program:
            await ctx.reply(
                _(
                    ctx,
                    "Program with abbreviation {abbreviation} and degree {degree} not found.",
                ).format(
                    abbreviation=abbreviation,
                    degree=degree,
                )
            )
            return
        args = await self._parse_program_parameters(ctx, parameters)
        if args is None:
            return

        if args.degree and args.degree.upper() not in DEGREE_MAPPING:
            await ctx.reply(
                _(
                    ctx,
                    "New degree must be B for Bachelor, M for Masters or D for Doctoral.",
                )
            )
            return

        if args.degree or args.abbreviation:
            check_degree = (
                DEGREE_MAPPING[args.degree.upper()] if args.degree else program.degree
            )
            check_abbreviation = (
                args.abbreviation.upper() if args.abbreviation else program.abbreviation
            )
            check_program = Program.get_by_abbreviation(
                ctx, check_degree, check_abbreviation
            )
            if check_program and check_program is not program:
                await ctx.reply(
                    _(
                        ctx,
                        "A program with the abbreviation '{abbreviation}' and '{degree}' already exists.",
                    ).format(
                        abbreviation=check_abbreviation,
                        degree=School._translate_degree(ctx, check_degree),
                    )
                )
                return

        degree = DEGREE_MAPPING[args.degree.upper()] if args.degree else None
        program.edit(args.abbreviation, args.name, degree)

        await ctx.reply(_(ctx, "Program successfuly edited."))

        log_message = f"Program '{abbreviation}' edited."
        if args.abbreviation:
            log_message += f" New abbreviation: '{args.abbreviation}'."

        await guild_log.info(ctx.author, ctx.channel, log_message)

    @check.acl2(check.ACLevel.MOD)
    @program_.command(name="delete")
    async def program_delete(self, ctx, degree: str, abbreviation: str):
        """Delete program.

        Args:
            degree: Program degree
            abbreviation: Program abbreviation
        """
        degree = degree.upper()
        abbreviation = abbreviation.upper()

        if degree not in DEGREE_MAPPING:
            await ctx.reply(
                _(
                    ctx,
                    "Degree must be B for Bachelor, M for Masters or D for Doctoral.",
                )
            )
            return

        program = Program.get_by_abbreviation(ctx, degree, abbreviation)
        if not program:
            await ctx.reply(
                _(
                    ctx,
                    "Program with abbreviation {abbreviation} and degree {degree} not found.",
                ).format(abbreviation=abbreviation, degree=degree)
            )
            return

        embed = await self._get_program_embed(ctx, program, True)
        embed.title = (
            _(ctx, "Do you want to delete this program:") + " " + embed.title + "?"
        )

        view = utils.ConfirmView(ctx, embed)
        value = await view.send()

        if value is None:
            await ctx.send(_(ctx, "Deleting timed out."))
        elif value:
            program.delete()
            await ctx.send(
                _(ctx, "Program {abbreviation} for degree {degree} deleted.").format(
                    abbreviation=abbreviation,
                    degree=degree,
                )
            )
            await guild_log.info(
                ctx.author,
                ctx.channel,
                f"Program {program.abbreviation} for degree {School._translate_degree(ctx, degree)} deleted.",
            )
        else:
            await ctx.send(_(ctx, "Deleting aborted."))

    @check.acl2(check.ACLevel.MEMBER)
    @program_.group(name="subject")
    async def program_subject_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MOD)
    @program_subject_.command(name="add")
    async def program_subject_add(
        self,
        ctx,
        degree: str,
        program_abbreviation: str,
        subject_abbreviation: str,
        year: int,
        obligation: str,
    ):
        """Link program and subject.

        Args:
            subject_abbreviation: Subject abbreviation
            degree: Program degree
            program_abbreviation: Program abbreviation
            year: Year of study
            obligation: Subject obligation
        """
        await self._link_program_subject(
            ctx, degree, program_abbreviation, subject_abbreviation, year, obligation
        )

    @check.acl2(check.ACLevel.MOD)
    @program_subject_.command(name="remove")
    async def program_subject_remove(
        self,
        ctx,
        degree: str,
        program_abbreviation: str,
        subject_abbreviation: str,
        year: int,
        obligation: str,
    ):
        """Unlink program and subject.

        Args:
            degree: Program degree
            program_abbreviation: Program abbreviation
            subject_abbreviation: Subject abbreviation
            year: Year of study
            obligation: Subject obligation
        """
        await self._unlink_program_subject(
            ctx, degree, program_abbreviation, subject_abbreviation, year, obligation
        )

    @check.acl2(check.ACLevel.MOD)
    @subject_.group(name="program")
    async def subject_program(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.MOD)
    @subject_program.command(name="add")
    async def subject_program_add(
        self,
        ctx,
        subject_abbreviation: str,
        degree: str,
        program_abbreviation: str,
        year: int,
        obligation: str,
    ):
        """Link program and subject.

        Args:
            subject_abbreviation: Subject abbreviation
            degree: Program degree
            program_abbreviation: Program abbreviation
            year: Year of study
            obligation: Subject obligation
        """
        await self._link_program_subject(
            ctx, degree, program_abbreviation, subject_abbreviation, year, obligation
        )

    @check.acl2(check.ACLevel.MOD)
    @subject_program.command(name="remove")
    async def subject_program_remove(
        self,
        ctx,
        subject_abbreviation: str,
        degree: str,
        program_abbreviation: str,
        year: int,
        obligation: str,
    ):
        """Unlink program and subject.

        Args:
            subject_abbreviation: Subject abbreviation
            degree: Program degree
            program_abbreviation: Program abbreviation
            year: Year of study
            obligation: Subject obligation
        """
        await self._unlink_program_subject(
            ctx, degree, program_abbreviation, subject_abbreviation, year, obligation
        )

    # ALL DATA IMPORT

    @commands.guild_only()
    @check.acl2(check.ACLevel.GUILD_OWNER)
    @commands.group(name="school")
    async def school_(self, ctx):
        await utils.discord.send_help(ctx)

    @check.acl2(check.ACLevel.GUILD_OWNER)
    @school_.command(name="import")
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def school_import(self, ctx):
        """Import school data from scraper."""
        if len(ctx.message.attachments) != 1:
            await ctx.reply(_(ctx, "I'm expecting one JSON file."))
            return
        if not ctx.message.attachments[0].filename.lower().endswith("json"):
            await ctx.reply(_(ctx, "You have to upload a JSON file."))
            return
        await ctx.reply(_(ctx, "Processing. Make a coffee, it may take a while."))
        async with ctx.typing():
            data_file = tempfile.TemporaryFile()
            await ctx.message.attachments[0].save(data_file)
            data_file.seek(0)
            try:
                json_data = json.load(data_file)
            except json.decoder.JSONDecodeError as exc:
                await ctx.reply(
                    _(ctx, "Your JSON file contains errors.") + f"\n> `{str(exc)}`"
                )
                return

            count = await self._import_school_data(ctx, json_data)
            data_file.close()

        await guild_log.info(
            ctx.author, ctx.channel, "Processed and imported {count} school records."
        )

        await ctx.reply(_(ctx, "Processed records: {count}").format(count=count))

    @check.acl2(check.ACLevel.GUILD_OWNER)
    @school_.command(name="export")
    async def school_export(self, ctx):
        """Export all school data"""
        await ctx.send("Not implemented yet")
        # TODO

    # HELPER FUNCTIONS

    async def _parse_teachers_args(
        self, ctx, teachers: List[int]
    ) -> Optional[List[Teacher]]:
        """Helper function used in subject editing for getting
        list of Teacher objects from list of their school IDs"""
        teachers_list = []
        for teacher_sid in teachers:
            teacher = Teacher.get_by_sid(ctx, teacher_sid)
            if not teacher:
                await ctx.reply(
                    _(ctx, "Teacher with ID {id} not found.").format(id=teacher_sid)
                )
                return None
            if teacher in teachers_list:
                await ctx.reply(
                    _(
                        ctx,
                        "Teacher with ID {id} can't occure in add / remove argument more than once!",
                    ).format(id=teacher_sid)
                )
                return None

            teachers_list.append(teacher)

        return teachers_list

    async def _link_program_subject(
        self,
        ctx,
        degree: str,
        program_abbreviation: str,
        subject_abbreviation: str,
        year: int,
        obligation: str,
    ):
        """Main logic for linkin program and subject together.

        Args:
            degree: Program degree
            program_abbreviation: Program abbreviation
            subject_abbreviation: Subject abbreviation
            year: Year in which students of program has this subject
            obligation: Subject obligation for this program
        """
        program = Program.get_by_abbreviation(ctx, degree, program_abbreviation)
        if not program:
            await ctx.reply(
                _(
                    ctx,
                    "Program with abbreviation {abbreviation} and degree {degree} not found.",
                ).format(abbreviation=program_abbreviation, degree=degree)
            )
            return

        subject = Subject.get_by_abbreviation(ctx, subject_abbreviation)

        if not subject:
            await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=subject_abbreviation
                )
            )
            return

        obligation = obligation.upper()

        if obligation not in OBLIGATIONS:
            message = _(ctx, "Obligation must be:")
            for obligation in OBLIGATIONS:
                message += (
                    "\n**"
                    + obligation
                    + "** "
                    + _(ctx, "for")
                    + " "
                    + School._translate_obligation(obligation)
                )

            await ctx.reply(message)

        if SubjectProgram.get(subject, program, year, obligation):
            await ctx.reply(
                _(
                    ctx,
                    "This combination of program, degree, subject, year and obligation already exists.",
                )
            )
            return

        SubjectProgram.add_relation(subject, program, year, obligation)

        await ctx.reply(_(ctx, "Subject and program succesfully linked."))

        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"Program {program.abbreviation} ({program.degree}) linked with {subject.abbreviation} (year: {year}, obligation: {obligation}).",
        )

    async def _unlink_program_subject(
        self,
        ctx,
        degree: str,
        program_abbreviation: str,
        subject_abbreviation: str,
        year: int,
        obligation: str,
    ):
        """Main logic for unlinkin program and subject.

        Args:
            degree: Program degree
            program_abbreviation: Program abbreviation
            subject_abbreviation: Subject abbreviation
            year: Year in which students of program has this subject
            obligation: Subject obligation for this program
        """
        program = Program.get_by_abbreviation(ctx, degree, program_abbreviation)
        if not program:
            await ctx.reply(
                _(
                    ctx,
                    "Program with abbreviation {abbreviation} and degree {degree} not found.",
                ).format(abbreviation=program_abbreviation, degree=degree)
            )
            return

        subject = Subject.get_by_abbreviation(ctx, subject_abbreviation)

        if not subject:
            await ctx.reply(
                _(ctx, "Subject with abbreviation {abbreviation} not found.").format(
                    abbreviation=subject_abbreviation
                )
            )
            return

        obligation = obligation.upper()

        if obligation not in OBLIGATIONS:
            message = _(ctx, "Obligation must be:")
            for obligation in OBLIGATIONS:
                message += (
                    "\n**"
                    + obligation
                    + "** "
                    + _(ctx, "for")
                    + " "
                    + School._translate_obligation(obligation)
                )

            await ctx.reply(message)

        relation = SubjectProgram.get(subject, program, year, obligation)

        if not relation:
            await ctx.reply(
                _(
                    ctx,
                    "This combination of program, degree, subject, year and obligation does not exists.",
                )
            )
            return

        relation.delete()

        await ctx.reply(_(ctx, "Subject and program succesfully unlinked."))

        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"Program {program.abbreviation} ({program.degree}) unlinked with {subject.abbreviation} (year: {year}, obligation: {obligation}).",
        )

    @staticmethod
    def _translate_degree(ctx, degree: str) -> str:
        """Translate degree"""
        if degree == "Bachelor":
            return _(ctx, "Bachelor")
        elif degree == "Masters":
            return _(ctx, "Masters")
        elif degree == "Doctoral":
            return _(ctx, "Doctoral")
        else:
            return "-"

    @staticmethod
    def _translate_semester(ctx, semester: str) -> str:
        """Translate semester"""
        if semester == "Winter":
            return _(ctx, "Winter")
        elif semester == "Summer":
            return _(ctx, "Summer")
        elif semester == "Both":
            return _(ctx, "Both")
        else:
            return "-"

    def _translate_obligation(ctx, obligation: str) -> str:
        """Translate obligation from it's czech shortcut"""
        if obligation == "V":
            return _(ctx, "Optional")
        elif obligation == "PV":
            return _(ctx, "Compulsory - optional")
        elif obligation == "P":
            return _(ctx, "Compulsory")
        elif obligation == "O":
            return _(ctx, "Other")
        elif obligation == "D":
            return _(ctx, "Recommended")
        elif obligation == "VO":
            return _(ctx, "Optional - specialized")
        else:
            return "-"

    async def _parse_subject_parameters(
        self, ctx: commands.Context, parameters: str
    ) -> Optional[argparse.Namespace]:
        """Parse parameters for subject editing"""
        parser = CommandParser()
        parser.add_argument("--abbreviation", type=str, nargs="+", default=None)
        parser.add_argument("--name", type=str, nargs="+", default=None)
        parser.add_argument("--institute", type=str, nargs="+", default=None)
        parser.add_argument("--semester", type=str, choices=SEMESTERS)
        parser.add_argument("--guarantor", type=int, nargs="+", default=None)
        parser.add_argument("--teachers-add", type=int, nargs="+", default=None)
        parser.add_argument("--teachers-remove", type=int, nargs="+", default=None)
        args = parser.parse_args(shlex.split(parameters))
        if parser.error_message:
            await ctx.reply(
                _(ctx, "Error parsing arguments:")
                + f"\n> `{parser.error_message.replace('`', '')}`"
            )
            return None

        for kw in ["abbreviation", "name", "institute", "semester"]:
            if getattr(args, kw) is not None:
                setattr(args, kw, " ".join(getattr(args, kw)))

        if getattr(args, "guarantor") is not None:
            setattr(args, "guarantor", getattr(args, "guarantor")[0])

        return args

    async def _parse_program_parameters(
        self, ctx: commands.Context, parameters: str
    ) -> Optional[argparse.Namespace]:
        """Parse parameters for program editing"""
        parser = CommandParser()
        parser.add_argument("--abbreviation", type=str, nargs="+", default=None)
        parser.add_argument("--name", type=str, nargs="+", default=None)
        parser.add_argument("--degree", type=str, nargs="+", default=None)
        args = parser.parse_args(shlex.split(parameters))
        if parser.error_message:
            await ctx.reply(
                _(ctx, "Error parsing arguments:")
                + f"\n> `{parser.error_message.replace('`', '')}`"
            )
            return None

        for kw in ["abbreviation", "name", "degree"]:
            if getattr(args, kw) is not None:
                setattr(args, kw, " ".join(getattr(args, kw)))

        return args

    async def _get_program_embed(
        self, ctx, program: Program, extend=False
    ) -> discord.Embed:
        """Get program information embed. Uses SchoolExtend
        to provide extended information from registered
        functions"""

        subjects = {}

        for relation in program.subjects:
            if relation.year not in subjects:
                subjects[relation.year] = {}

            if relation.obligation not in subjects[relation.year]:
                subjects[relation.year][relation.obligation] = []

            subjects[relation.year][relation.obligation].append(
                f"`{relation.subject.abbreviation}`"
            )

        name = (
            program.name
            if program.name
            else _(ctx, "Program {abbreviation}").format(
                abbreviation=program.abbreviation
            )
        )

        embed = utils.discord.create_embed(author=ctx.author, title=name)
        embed.add_field(
            name=_(ctx, "Abbreviation"),
            value=program.abbreviation,
        )
        embed.add_field(
            name=_(ctx, "Degree"),
            value=School._translate_degree(ctx, program.degree),
        )

        for year in sorted(subjects.keys()):
            by_year = subjects[year]
            embed.add_field(
                name=_(ctx, "Year: {year}").format(year=year),
                value="\u200b",
                inline=False,
            )
            for obligation in OBLIGATIONS:
                if obligation not in by_year:
                    continue
                subject_list = by_year[obligation]
                embed.add_field(
                    name=School._translate_obligation(ctx, obligation),
                    value=", ".join(sorted(subject_list)),
                )

        if extend:
            for func in SchoolExtend._program_extension:
                try:
                    func(ctx=ctx, embed=embed, program=program)
                except Exception:
                    await bot_log.error(
                        ctx.author,
                        ctx.channel,
                        f"Function {func.__name__} could not be called to get more program info!",
                    )

        return embed

    async def _get_subject_embed(
        self, ctx, subject: Subject, extend=False
    ) -> discord.Embed:
        """Get subject information embed. Uses SchoolExtend
        to provide extended information from registered
        functions"""

        embed = utils.discord.create_embed(author=ctx.author, title=subject.name)

        embed.add_field(
            name=_(ctx, "Abbreviation"),
            value=subject.abbreviation,
        )
        embed.add_field(
            name=_(ctx, "Institute"),
            value=subject.institute,
        )
        embed.add_field(
            name=_(ctx, "Semester"),
            value=School._translate_semester(ctx, subject.semester),
        )

        if subject.url:
            urls = [url.url for url in subject.url]
            embed.add_field(name=_(ctx, "URL"), value="\n".join(urls), inline=False)

        if subject.guarantor:
            embed.add_field(
                name=_(ctx, "Guarantor"),
                value=f"{subject.guarantor.name} ({subject.guarantor.school_id})",
                inline=False,
            )

        if subject.teachers:
            teachers = []
            for teacher in subject.teachers:
                teachers.append(f"{teacher.name} ({teacher.school_id})")

            embed.add_field(
                name=_(ctx, "Teachers"), value="\n".join(sorted(teachers)), inline=False
            )

        if subject.programs:
            programs = {}
            for relation in subject.programs:
                degree = relation.program.degree if relation.program.degree else "-"
                if degree not in programs:
                    programs[degree] = []
                programs[degree].append(
                    _(ctx, "**{program}** ({obligation}, year: {year})").format(
                        program=relation.program.abbreviation,
                        year=relation.year,
                        obligation=School._translate_obligation(
                            ctx, relation.obligation
                        ),
                    )
                )

            for degree, program_list in programs.items():
                embed.add_field(
                    name=_(ctx, "Programs - {degree}").format(
                        degree=School._translate_degree(ctx, degree)
                    ),
                    value="\n".join(sorted(program_list)),
                    inline=False,
                )

        if extend:
            for func in SchoolExtend._subject_extension:
                try:
                    func(ctx=ctx, embed=embed, subject=subject)
                except Exception:
                    await bot_log.error(
                        ctx.author,
                        ctx.channel,
                        f"Function {func.__name__} could not be called to get more subject info!",
                    )

        return embed

    async def _get_teacher_embed(
        self, ctx, teacher: Teacher, extend=False
    ) -> discord.Embed:
        """Get teacher information embed. Uses SchoolExtend
        to provide extended information from registered
        functions"""
        guaranted_subjects = []

        for subject in teacher.guaranted_subjects:
            guaranted_subjects.append(f"`{subject.abbreviation}`")

        teached_subjects = []

        for subject in teacher.subjects:
            teached_subjects.append(f"`{subject.abbreviation}`")

        embed = utils.discord.create_embed(author=ctx.author, title=teacher.name)
        embed.add_field(
            name=_(ctx, "ID"),
            value=str(teacher.school_id),
        )
        if guaranted_subjects:
            embed.add_field(
                name=_(ctx, "Guaranted subjects"),
                value=", ".join(sorted(guaranted_subjects)),
            )

        if teached_subjects:
            embed.add_field(
                name=_(ctx, "Teaches"),
                value=", ".join(sorted(teached_subjects)),
                inline=False,
            )

        if extend:
            for func in SchoolExtend._teacher_extension:
                try:
                    func(ctx=ctx, embed=embed, teacher=teacher)
                except Exception:
                    await bot_log.error(
                        ctx.author,
                        ctx.channel,
                        f"Function {func.__name__} could not be called to get more teacher info!",
                    )

        return embed

    @staticmethod
    def _split_list(li, n):
        """Splits list into smaller list of size n.

        Should be mobed to Pie.utils
        """
        for i in range(0, len(li), n):
            yield li[i : i + n]

    async def _import_teachers(self, ctx, json_data):
        """Import teachers from JSON data"""
        teachers = []
        for id, name in json_data.items():
            teachers.append(Teacher.update_or_create(ctx, id, name))

        return teachers

    async def _import_programs(self, ctx, json_data, degree):
        """Import programs from JSON data"""
        programs = []
        for program_data in json_data:
            spec_degree = re.search(r"^[A-z]-", program_data)
            if spec_degree:
                spec_degree = spec_degree.group()
                if spec_degree[0] in DEGREE_MAPPING:
                    spec_degree = DEGREE_MAPPING[spec_degree[0]]
                else:
                    await guild_log.warning(
                        ctx.author,
                        ctx.channel,
                        f'Could not find mapping for spec_degree "{spec_degree}".',
                    )
                    spec_degree += "UNKNOWN"
                program_data = re.sub(r"^[A-z]-", "", program_data)
            program_info = program_data.split("-")
            program = {
                "abbreviation": (
                    program_info[0]
                    if program_info[1] != "A"
                    else program_info[0] + "-" + program_info[1]
                ),
                "year": program_info[-2],
                "obligation": program_info[-1],
                "degree": spec_degree if spec_degree else degree,
            }
            if program not in programs:
                programs.append(program)

        return programs

    async def _import_school_data(self, ctx, json_data) -> int:
        """Main logic for importing school (subject) data from JSON"""
        i = 0
        for subject_data in json_data:
            guarantors_data = subject_data.get("guarantors", {})
            teachers_data = subject_data.get("teachers", {})
            programs_data = subject_data.get("programmes", [])
            degrees = subject_data.get("degree", [])

            if "Bachelor" in degrees:
                degree = "Bachelor"
            elif "Masters" in degrees:
                degree = "Masters"
            elif "Doctoral" in degrees:
                degree = "Doctoral"
            else:
                degree = None

            guarantor = await self._import_teachers(ctx, guarantors_data)
            teachers = await self._import_teachers(ctx, teachers_data)

            subject = Subject.from_json(ctx, subject_data)

            if not subject:
                await guild_log.warning(
                    ctx.author,
                    ctx.channel,
                    f'Subject could not be created. Data: "{subject_data}"',
                )
                continue

            subject.set_guarantor(guarantor)
            subject.set_teachers(teachers)

            programs = await self._import_programs(ctx, programs_data, degree)

            subject.import_programs(ctx, programs)
            i += 1

        return i


async def setup(bot) -> None:
    await bot.add_cog(School(bot))
