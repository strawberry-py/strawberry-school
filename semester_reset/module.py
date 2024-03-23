import discord
from discord.ext import commands
from pie import check, i18n

_ = i18n.Translator("modules/semester_reset").translate


class SemesterReset(commands.Cog):
    @check.acl2(check.ACLevel.MOD)
    @commands.guild_only()
    @commands.command(name="role-reset")
    async def role_reset(
        self, ctx, highest_role: discord.Role, lowest_role: discord.Role
    ):
        """Specify roles to remove from members of the guild."""
        all_roles = list(ctx.guild.roles)
        found_lowest = False
        found_highest = False
        correct_order = False
        low_idx = None
        high_idx = None
        for idx, role in enumerate(all_roles):
            if role == lowest_role:
                found_lowest = True
                low_idx = idx
                if found_highest:
                    break
            elif role == highest_role:
                high_idx = idx
                found_highest = True
                if found_lowest:
                    correct_order = True
                    break
        if not found_lowest or not found_highest:
            await ctx.send(_(ctx, "Cannot find specified roles, aborting."))
            return
        if correct_order:
            roles = all_roles[low_idx : high_idx + 1]
        else:
            roles = all_roles[high_idx : low_idx + 1]
        success = 0
        async with ctx.typing():
            for role in roles:
                members = role.members
                for member in members:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        await ctx.send(
                            _(
                                ctx, "Cannot remove role {role} from member {member}."
                            ).format(role=role.name, member=member.display_name)
                        )
                    success += 1
                    if success % 100 == 0:
                        await ctx.send(
                            _(
                                ctx,
                                "Successfully removed roles from {member_count} members. Continuing...",
                            ).format(member_count=success)
                        )
        await ctx.send(
            _(
                ctx, "Done, removed {role_count} roles from {member_count} members"
            ).format(role_count=len(roles), member_count=success)
        )

    @check.acl2(check.ACLevel.MOD)
    @commands.guild_only()
    @commands.command(name="channels_reset")
    async def channels_reset(self, ctx, *, categories=None):
        """Remove user overrides from specified channels. Use space-separated list of category names as an argument."""
        if categories is None:
            await ctx.send(
                _(ctx, "Use space-separated list of category names as an argument.")
            )
            return
        category_strings = set(categories.split())
        categories = filter(
            lambda x: True if x.name in category_strings else False,
            ctx.guild.categories,
        )
        success = 0
        async with ctx.typing():
            for category in categories:
                for channel in category.channels:
                    overwrite_dict = channel.overwrites
                    for overwrite_target in overwrite_dict:
                        if not isinstance(overwrite_target, discord.Member):
                            continue
                        try:
                            await channel.set_permissions(
                                overwrite_target, overwrite=None
                            )
                        except Exception:
                            await ctx.send(
                                _(
                                    ctx,
                                    "Could not delete overwrites of member {member} in the channel {channel}.",
                                ).format(
                                    member=overwrite_target.display_name,
                                    channel=channel.mention,
                                )
                            )
                    success += 1
                    if success % 100 == 0:
                        await ctx.send(
                            _(
                                ctx,
                                "Already visited {channel_count} channels. Continuing...",
                            ).format(channel_count=success)
                        )
        await ctx.send(
            _(ctx, "Done, visited {channel_count} channels.").format(
                channel_count=success
            )
        )


async def setup(bot) -> None:
    await bot.add_cog(SemesterReset(bot))
