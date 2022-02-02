import nextcord
from nextcord.ext import tasks, commands

import pie.database.config
from pie import check, i18n, logger, utils

from .database import TeacherChannel as TeacherChannelDB

_ = i18n.Translator("modules/school").translate
guild_log = logger.Guild.logger()
config = pie.database.config.Config.get()


class TeacherChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.load_deltas.start()

    @commands.guild_only()
    @commands.check(check.acl)
    @commands.group(name="teacherchannel")
    async def teacherchannel_(self, ctx):
        """Syncing teacher channels' permissions."""
        await utils.discord.send_help(ctx)

    @commands.check(check.acl)
    @teacherchannel_.command(name="list")
    async def teacherchannel_list(self, ctx):
        """List active teacher channels."""

        class Item:
            def __init__(self, obj: TeacherChannelDB):
                channel_m = ctx.guild.get_channel(obj.master_id)
                channel_s = ctx.guild.get_channel(obj.slave_id)
                self.m_channel = "#" + getattr(channel_m, "name", str(obj.master_id))
                self.s_channel = "#" + getattr(channel_s, "name", str(obj.slave_id))
                self.teachers = ", ".join(
                    [
                        getattr(
                            ctx.guild.get_member(t.user_id),
                            "display_name",
                            str(t.user_id),
                        )
                        for t in obj.teachers
                    ]
                )

        items = [Item(t) for t in TeacherChannelDB.get_all(ctx.guild.id)]
        if len(items) < 1:
            await ctx.reply(_(ctx, "No teacher channels are set."))
            return
        table = utils.text.create_table(
            items,
            header={
                "m_channel": _(ctx, "Original channel"),
                "s_channel": _(ctx, "Teacher channel"),
                "teachers": _(ctx, "Teachers"),
            },
        )
        for page in table:
            await ctx.send("```" + page + "```")

    @commands.check(check.acl)
    @teacherchannel_.command(name="set", aliases=["add"])
    async def teacherchannel_set(
        self, ctx, master: nextcord.TextChannel, slave: nextcord.TextChannel
    ):
        """Create a teacherchannel relation to sync.
        Args:
            master: Primary channel without any teacher.
            slave: Channel that is supposed to be visible for teachers of this channel."""
        config = TeacherChannelDB.add_channel(ctx.guild.id, master.id, slave.id)
        if not config:
            await ctx.reply(_(ctx, "This channel is already assigned."))
            return
        await self._sync(slave, master, config)
        await ctx.reply(_(ctx, "Teacher channel relation created."))
        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"Teacher channel relation created. Master: #{master.name}, slave: #{slave.name}.",
        )

    @commands.check(check.acl)
    @teacherchannel_.command(name="unset", aliases=["remove", "delete"])
    async def teacherchannel_unset(self, ctx, channel: nextcord.TextChannel):
        """Remove teacherchannel relation.
        Args:
            channel: Either slave or master channel, both have the same effect."""
        teacherchannel = TeacherChannelDB.get(ctx.guild.id, channel.id)
        if not teacherchannel:
            await ctx.reply(_(ctx, "This channel was never assigned."))
            return
        teacherchannel.remove_channel()
        await ctx.reply(_(ctx, "Teacher channel unset."))
        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"Teacher channel relation of channel {channel.name} unset.",
        )

    @commands.check(check.acl)
    @teacherchannel_.group(name="teacher")
    async def teacherchannel_teacher(self, ctx):
        """Manipulation with teachers of a teacher channel. Subcommands: **add** | **remove**."""
        await utils.discord.send_help(ctx)

    @commands.check(check.acl)
    @teacherchannel_teacher.command(name="add", aliases=["set"])
    async def teacherchannel_teacher_add(
        self, ctx, channel: nextcord.TextChannel, teacher: nextcord.Member
    ):
        """Mark user as a teacher of a channel. Permission sync will not apply to this member.
        Grants permissions to the teacher channel (slave) only.
        Args:
            channel: Either slave or master channel, both have the same effect.
            teacher: Member to be marked as a teacher of this teacher channel."""
        config = TeacherChannelDB.add_teacher(ctx.guild.id, channel.id, teacher.id)
        if not config:
            await ctx.reply(
                _(
                    ctx,
                    "Could not add teacher. Either the channel is not a teacher channel "
                    "or this user has already been added.",
                )
            )
            return
        if channel.id != config.slave_id:
            channel = ctx.guild.get_channel(config.slave_id)
        await channel.set_permissions(teacher, read_messages=True, send_messages=True)
        await ctx.reply(_(ctx, "Teacher added."))
        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"Teacher {teacher.display_name} added to teacher channel {channel.name}.",
        )

    @commands.check(check.acl)
    @teacherchannel_teacher.command(name="remove", aliases=["unset", "delete"])
    async def teacherchannel_teacher_remove(
        self, ctx, channel: nextcord.TextChannel, teacher: nextcord.Member
    ):
        """Unmark user as a teacher of a channel. Permission overrides will be removed from the teacher channel (slave).
        Args:
            channel: Either slave or master channel, both have the same effect.
            teacher: Member which is no longer supposed to be marked as a teacher."""
        success = TeacherChannelDB.remove_teacher(ctx.guild.id, channel.id, teacher.id)
        if not success:
            await ctx.reply(
                _(
                    ctx,
                    "Could not remove teacher that was not there in the first place.",
                )
            )
            return
        config = TeacherChannelDB.get(ctx.guild.id, channel.id)
        if channel.id != config.slave_id:
            channel = ctx.guild.get_channel(config.slave_id)
        await channel.set_permissions(teacher, overwrite=None)
        await ctx.reply(_(ctx, "Teacher removed."))
        await guild_log.info(
            ctx.author,
            ctx.channel,
            f"Teacher {teacher.display_name} removed from teacher channel {channel.name}.",
        )

    @tasks.loop(seconds=10.0, count=1)
    async def load_deltas(self):
        guild_ids = TeacherChannelDB.get_guild_ids()
        for guild_id in guild_ids:
            guild = self.bot.get_guild(guild_id)
            channels_to_sync = TeacherChannelDB.get_all(guild_id)
            for teacherchannel in channels_to_sync:
                master = guild.get_channel(teacherchannel.master_id)
                slave = guild.get_channel(teacherchannel.slave_id)
                if not master:
                    if slave is not None:
                        name_to_log = slave.name
                        await slave.delete()
                    else:
                        name_to_log = "<#" + str(teacherchannel.slave_id) + ">"
                    await guild_log.warning(
                        None,
                        None,
                        f"Teacher channel {name_to_log} cannot be synced, channel "
                        f"#<{teacherchannel.master_id}> "
                        f"does not exist! Deleting from database.",
                    )
                    teacherchannel.remove_channel()
                    continue
                if not slave:
                    await guild_log.warning(
                        None,
                        None,
                        f"Teacher channel #<{teacherchannel.slave_id}> "
                        f"(slave of #{master.name}) cannot be synced, "
                        f"it does not exist! Deleting from database.",
                    )
                    teacherchannel.remove_channel()
                    continue
                await self._sync(slave, master, teacherchannel)

    @load_deltas.before_loop
    async def before_load(self):
        """Ensures that bot is ready before syncing channels."""
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        channel_before: nextcord.abc.GuildChannel,
        channel_after: nextcord.abc.GuildChannel,
    ):
        if not isinstance(channel_after, nextcord.TextChannel):
            return
        teacherchannel = TeacherChannelDB.get(channel_after.guild.id, channel_after.id)
        if not teacherchannel:
            return
        if channel_after.id == teacherchannel.slave_id:
            return
        await self._sync(channel_before, channel_after, teacherchannel)

    async def _sync(
        self,
        channel_before: nextcord.abc.GuildChannel,
        channel_after: nextcord.abc.GuildChannel,
        teacherchannel: TeacherChannelDB,
    ) -> None:
        slave_channel = channel_after.guild.get_channel(teacherchannel.slave_id)
        if not slave_channel:
            await guild_log.warning(
                None,
                None,
                f"Teacher channel #<{teacherchannel.slave_id}> cannot be synced, "
                f"it does not exist! Deleting from db.",
            )
            teacherchannel.remove_channel()
            return
        if channel_after.category != channel_before.category:
            await slave_channel.move(
                category=channel_after.category, after=channel_after, offset=0
            )
        if channel_after.overwrites != channel_before.overwrites:
            # negative change
            for (target, overwrite) in channel_before.overwrites.items():
                if (target, overwrite) in channel_after.overwrites.items():
                    continue
                if target.id not in [t.user_id for t in teacherchannel.teachers]:
                    await slave_channel.set_permissions(target, overwrite=None)

            # positive change
            for target, overwrite in channel_after.overwrites.items():
                if (target, overwrite) in channel_before.overwrites.items():
                    continue
                if target.id not in [t.user_id for t in teacherchannel.teachers]:
                    await slave_channel.set_permissions(target, overwrite=overwrite)


def setup(bot) -> None:
    bot.add_cog(TeacherChannel(bot))
