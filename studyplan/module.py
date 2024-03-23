import enum
import os

import discord
import pathlib
import pandas as pd
from discord.ext import commands
from pie import check, i18n


_ = i18n.Translator("modules/school").translate


class Degree(enum.Enum):
    BACHELOR = "Bakalářské"
    MASTER = "Navazující magisterské"
    DOCTOR = "Doktorské"


DEGREE_YEARS = {
    Degree.BACHELOR.value: 3,
    Degree.MASTER.value: 2,
    Degree.DOCTOR.value: 4,
}


class StudyPlan(commands.Cog):
    """Check/Create roles/rooms based on scraped data."""

    def __init__(self, bot):
        self.bot = bot
        self.programmes: pd.DataFrame = None
        self.subjects: pd.DataFrame = None
        self.dir = pathlib.Path(__file__).parent.resolve()

        self.save_dir = self.dir / "data"
        self.save_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._load_programmes(self.save_dir / "programmes.json")
            self._load_subjects(self.save_dir / "subjects.json")
        except FileNotFoundError:
            pass

    def _load_programmes(self, path):
        dtypes = {
            "name": "str",
            "abbreviation": "str",
            "degree": "str",
            "language": "str",
            "type": "str",
            "link": "str",
        }

        df = pd.read_json(path, encoding="utf8", dtype=dtypes)

        if sorted(list(dtypes.keys())) == sorted(list(df.columns)):
            self.programmes = df
        else:
            os.remove(path)
            raise ValueError

    def _load_subjects(self, path):
        dtypes = {
            "abbreviation": str,
            "name": str,
            "institute": str,
            "winter_semester": bool,
            "summer_semester": bool,
            "bachelors_degree": bool,
            "masters_degree": bool,
            "doctoral_degree": bool,
            "guarantors": list,
            "teachers": list,
            "link": str,
            "programmes": list,
        }

        df = pd.read_json(path, encoding="utf8", dtype=dtypes)

        if sorted(list(dtypes.keys())) == sorted(list(df.columns)):
            self.subjects = df
        else:
            os.remove(path)
            raise ValueError

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def load_programmes(self, ctx, attachment: discord.Attachment):
        """Load programmes from a JSON file."""
        save_path = self.save_dir / "programmes.json"
        await attachment.save(save_path)

        try:
            self._load_programmes(save_path)
            await ctx.reply(f"Loaded {len(self.programmes)} programmes")
        except ValueError:
            await ctx.reply(_(ctx, "Input file does not match expected columns"))

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def load_subjects(self, ctx, attachment: discord.Attachment):
        """Load subjects from a JSON file."""

        save_path = self.save_dir / "subjects.json"
        await attachment.save(save_path)

        try:
            self._load_subjects(save_path)
            await ctx.reply(f"Loaded {len(self.subjects)} subjects")
        except ValueError:
            await ctx.reply(_(ctx, "Input file does not match expected columns"))

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def check_programmes(self, ctx, degree: str = None, primary: bool = None):
        """Check if all programmes from the scraped data have corresponding roles."""
        degrees = set(d.value for d in Degree)

        if degree not in degrees:
            await ctx.reply(f"Please select one of: `{degrees}`")
            return
        elif primary is None:
            await ctx.reply(
                "Is this server where all year variants of programmes should be?: `True, False`"
            )
            return

        programmes = self.programmes.loc[self.programmes["degree"] == degree]

        dic_programmes = programmes.to_dict("records")

        missing_roles = []
        for programme in dic_programmes:
            if primary is False:
                role_name = f"{programme['abbreviation']}-X"
                role = discord.utils.get(ctx.guild.roles, name=role_name)
                if role is None:
                    missing_roles.append(role_name)
            if primary is True:
                for yr in range(DEGREE_YEARS.get(degree) + 2):
                    role_name = f"{programme['abbreviation']}-{yr if yr != DEGREE_YEARS.get(degree) + 1 else str(yr) + '+'}"
                    role = discord.utils.get(ctx.guild.roles, name=role_name)
                    if role is None:
                        missing_roles.append(role_name)

        if len(missing_roles) > 0:
            await ctx.reply(f"Missing roles:\n```{' '.join(missing_roles)}```")
        else:
            await ctx.reply(_(ctx, "All roles exist already."))

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def create_programmes(self, ctx, degree: str = None, primary: bool = None):
        """Create all missing roles for the programmes in the scraped data."""
        degrees = set(d.value for d in Degree)

        if degree not in degrees:
            await ctx.reply(f"Please select one of: `{degrees}`")
            return
        elif primary is None:
            await ctx.reply(
                "Is this server where all year variants of programmes should be?: `True, False`"
            )
            return

        programmes = self.programmes.loc[self.programmes["degree"] == degree]

        dic_programmes = programmes.to_dict("records")

        missing_roles = []
        for programme in dic_programmes:
            if primary is False:
                role_name = f"{programme['abbreviation']}-X"
                role = discord.utils.get(ctx.guild.roles, name=role_name)
                if role is None:
                    missing_roles.append(role_name)
                    await ctx.guild.create_role(name=role_name)
            if primary is True:
                for yr in range(DEGREE_YEARS.get(degree) + 2):
                    role_name = f"{programme['abbreviation']}-{yr if yr != DEGREE_YEARS.get(degree) + 1 else str(yr) + '+'}"
                    role = discord.utils.get(ctx.guild.roles, name=role_name)
                    if role is None:
                        missing_roles.append(role_name)
                        await ctx.guild.create_role(name=role_name)

        if len(missing_roles) > 0:
            await ctx.reply(f"Created missing roles:\n```{' '.join(missing_roles)}```")
        else:
            await ctx.reply(_(ctx, "All roles exist already"))

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def check_subjects(self, ctx, degree: str = None):
        """Check if subjects from the scraped data have corresponding rooms."""
        degrees = set(d.value for d in Degree)
        raw_institutes = list(self.subjects["institute"].tolist())
        institutes = list(set([x[0] for x in raw_institutes]))

        if degree not in degrees:
            await ctx.reply(f"Please select one of: `{degrees}`")
            return

        dic_subjects = self.subjects.to_dict("records")

        missing_categories = set()
        missing_channels = set()
        channels_in_wrong_categories = []
        channels_wrong_topic = []
        for subject in dic_subjects:
            if degree == Degree.BACHELOR.value and not subject["bachelors_degree"]:
                continue
            elif (
                degree == Degree.MASTER.value
                and not subject["masters_degree"]
                or subject["abbreviation"].startswith("X")
            ):
                continue
            elif (
                degree == Degree.DOCTOR.value
                and not subject["doctoral_degree"]
                or subject["abbreviation"].startswith("X")
            ):
                continue

            mandatory_programmes = []
            res = []
            for prog in subject["programmes"]:
                if prog.endswith("-P"):
                    mandatory_programmes.append(prog.rstrip("-P"))
                    res.append(prog)
                elif prog.endswith("-PV"):
                    res.append(prog)

            if len(res) == 0:
                continue

            channel = discord.utils.get(
                ctx.guild.channels, name=subject["abbreviation"].lower()
            )
            category = discord.utils.get(
                ctx.guild.categories, name=subject["institute"]
            )
            if category is None:
                missing_categories.add(subject["institute"])
            if channel is None:
                missing_channels.add(subject["abbreviation"])
            elif channel.category.name.rstrip("-2") != subject["institute"]:
                channels_in_wrong_categories.append(
                    f"{subject['abbreviation']} ({channel.category.name} -> {subject['institute']})"
                )
            elif channel.topic != subject["name"]:
                channels_wrong_topic.append(
                    f"{subject['abbreviation']} ({channel.topic} -> {subject['name']})"
                )

        outdated_channels = []
        for category in ctx.guild.categories:
            if category.name not in institutes:
                continue
            for channel in category.channels:
                if not (self.subjects["abbreviation"] == channel.name.upper()):
                    outdated_channels.append(f"{channel.name} ({category.name})")

        await ctx.reply(
            f"Possibly outdated channels:\n```{' '.join(outdated_channels)}```"
        )
        await ctx.reply(f"Missing categories:\n```{' '.join(missing_categories)}```")
        await ctx.reply(f"Missing channels:\n```{' '.join(missing_channels)}```")
        await ctx.reply(
            f"Channels in wrong categories:\n```{' '.join(channels_in_wrong_categories)}```"
        )
        await ctx.reply(
            f"Channels with wrong topic:\n```{' '.join(channels_wrong_topic)}```"
        )

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def create_and_modify_subjects(self, ctx, degree: str = None):
        """Create all missing rooms for the programmes in the scraped data. Makes sure the title is correct.
        Also resets the permissions so users need to reassign themselves those rooms."""
        degrees = list(self.programmes["degree"].unique())

        if degree not in degrees:
            await ctx.reply(f"Please select one of: `{degrees}`")
            return

        dic_subjects = self.subjects.to_dict("records")

        missing_categories = set()
        missing_channels = set()
        channels_in_wrong_categories = []
        channels_wrong_topic = []
        for subject in dic_subjects:
            if degree == Degree.BACHELOR.value and not subject["bachelors_degree"]:
                continue
            elif (
                degree == Degree.MASTER.value
                and not subject["masters_degree"]
                or subject["abbreviation"].startswith("X")
            ):
                continue
            elif (
                degree == Degree.DOCTOR.value
                and not subject["doctoral_degree"]
                or subject["abbreviation"].startswith("X")
            ):
                continue

            mandatory_programmes = []
            res = []
            for prog in subject["programmes"]:
                if prog.endswith("-P"):
                    mandatory_programmes.append(prog.rstrip("-P"))
                    res.append(prog)
                elif prog.endswith("-PV"):
                    res.append(prog)

            if len(res) == 0:
                continue

            mod_role = discord.utils.get(ctx.guild.roles, name="MOD")
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                ),
                mod_role: discord.PermissionOverwrite(read_messages=True),
            }
            for prg in mandatory_programmes:
                role = discord.utils.get(ctx.guild.roles, name=prg)
                overwrites[role] = discord.PermissionOverwrite(read_messages=True)

            channel = discord.utils.get(
                ctx.guild.channels, name=subject["abbreviation"].lower()
            )
            category = discord.utils.get(
                ctx.guild.categories, name=subject["institute"]
            )
            if category is None:
                missing_categories.add(subject["institute"])

                category_overwrites = {
                    ctx.guild.default_role: discord.PermissionOverwrite(
                        read_messages=False
                    ),
                    mod_role: discord.PermissionOverwrite(read_messages=True),
                }
                category = await ctx.guild.create_category_channel(
                    name=subject["institute"], overwrites=category_overwrites
                )
            if channel is None:
                print(f"{subject['abbreviation']} doesn't exist")
                try:
                    await ctx.guild.create_text_channel(
                        name=subject["abbreviation"],
                        topic=subject["name"],
                        category=category,
                        overwrites=overwrites,
                    )
                    missing_channels.add(subject["abbreviation"])
                except Exception as e:
                    print(subject["abbreviation"], subject["institute"])
                    if "Maximum number of channels in category reached" in str(e):
                        new_category = discord.utils.get(
                            ctx.guild.categories, name=f"{subject['institute']}-2"
                        )
                        if new_category is None:
                            missing_categories.add(f"{subject['institute']}-2")

                            category_overwrites = {
                                ctx.guild.default_role: discord.PermissionOverwrite(
                                    read_messages=False
                                ),
                                mod_role: discord.PermissionOverwrite(
                                    read_messages=True
                                ),
                            }
                            new_category = await ctx.guild.create_category_channel(
                                name=f"{subject['institute']}-2",
                                overwrites=category_overwrites,
                            )
                        await ctx.guild.create_text_channel(
                            name=subject["abbreviation"],
                            topic=subject["name"],
                            category=new_category,
                            overwrites=overwrites,
                        )
                        missing_channels.add(subject["abbreviation"])
            elif channel.category.name.rstrip("-2") != subject["institute"]:
                print(f"{subject['abbreviation']} moving categories")
                channels_in_wrong_categories.append(
                    f"{subject['abbreviation']} ({channel.category.name} -> {subject['institute']})"
                )
                await channel.edit(category=category)
            elif channel.topic != subject["name"]:
                print(f"{subject['abbreviation']} topic change")
                channels_wrong_topic.append(
                    f"{subject['abbreviation']} ({channel.topic} -> {subject['name']})"
                )
                if not channel.topic == subject["name"]:
                    await channel.edit(topic=subject["name"])
            else:
                if not channel.overwrites == overwrites:
                    await channel.edit(overwrites=overwrites)
                    print(f"{subject['abbreviation']} overwrites reset")

        await ctx.reply(
            f"```{len(missing_categories)} missing categories created\n"
            f"{len(missing_channels)} missing channels created\n"
            f"{len(channels_in_wrong_categories)} channels moved\n"
            f"{len(channels_wrong_topic)} channels topic edited```"
        )

    @check.acl2(check.ACLevel.MOD)
    @commands.command()
    async def reorder_channels(self, ctx, category: str):
        """Makes sure the channels in said category are in alphabetical order."""
        category = discord.utils.get(ctx.guild.categories, name=category)

        min_pos = 999
        channel_objs = category.channels
        channels = []
        print("Reading channels")
        for channel in channel_objs:
            min_pos = min(min_pos, channel.position)
            channels.append(channel.name)

        channels.sort()

        print("Reordering channels")
        for channel_name in channels:
            channel = discord.utils.get(ctx.guild.channels, name=channel_name)
            new_pos = min_pos + channels.index(channel_name)
            print(
                f"Reordering {channel_name}. position={channel.position} ({min_pos + channels.index(channel_name)})"
            )
            if new_pos != channel.position:
                await channel.edit(position=new_pos)

        await ctx.reply(_(ctx, "Done."))


async def setup(bot) -> None:
    await bot.add_cog(StudyPlan(bot))
