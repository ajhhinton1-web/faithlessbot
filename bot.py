import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime
from keep_alive import keep_alive

# ─────────────────────────────────────────
#  Config — reads from environment variables
#  Set DISCORD_TOKEN and LOG_CHANNEL_ID in
#  the Replit Secrets panel (🔒 icon).
# ─────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "❌  DISCORD_TOKEN environment variable is not set.\n"
        "    Add it in the Replit Secrets panel (🔒 icon)."
    )

_log_id = os.environ.get("LOG_CHANNEL_ID", "")
LOG_CHANNEL_ID = int(_log_id) if _log_id.strip().isdigit() else None

CONFIG_FILE   = "config.json"
WARN_FILE     = "warnings.json"


# ─────────────────────────────────────────
#  Config helpers  (mod/admin role IDs)
# ─────────────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_mod_role_id(guild_id: int) -> int | None:
    return load_config().get(str(guild_id), {}).get("mod_role_id")

def get_admin_role_id(guild_id: int) -> int | None:
    return load_config().get(str(guild_id), {}).get("admin_role_id")


# ─────────────────────────────────────────
#  Warning helpers
# ─────────────────────────────────────────
def load_warnings() -> dict:
    if os.path.exists(WARN_FILE):
        with open(WARN_FILE) as f:
            return json.load(f)
    return {}

def save_warnings(data: dict):
    with open(WARN_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─────────────────────────────────────────
#  Bot setup
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─────────────────────────────────────────
#  Shared helpers
# ─────────────────────────────────────────
def mod_embed(title: str, colour: discord.Colour, **fields) -> discord.Embed:
    embed = discord.Embed(title=title, colour=colour, timestamp=datetime.utcnow())
    for name, value in fields.items():
        embed.add_field(name=name.replace("_", " ").title(), value=value, inline=True)
    embed.set_footer(text="Moderation Bot")
    return embed


async def log(guild: discord.Guild, embed: discord.Embed):
    if LOG_CHANNEL_ID:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)


# ─────────────────────────────────────────
#  Permission checks
# ─────────────────────────────────────────
def is_mod():
    """
    Passes if the user:
      - has Administrator permission, OR
      - has the configured Admin role, OR
      - has the configured Moderator role
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        user = interaction.user
        if user.guild_permissions.administrator:
            return True
        gid = interaction.guild.id
        admin_id = get_admin_role_id(gid)
        mod_id   = get_mod_role_id(gid)
        role_ids = {r.id for r in user.roles}
        if (admin_id and admin_id in role_ids) or (mod_id and mod_id in role_ids):
            return True
        await interaction.response.send_message(
            "❌ You need a **Moderator** or **Admin** role to use this command.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


def is_admin():
    """
    Passes if the user:
      - has Administrator permission, OR
      - has the configured Admin role
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        user = interaction.user
        if user.guild_permissions.administrator:
            return True
        admin_id = get_admin_role_id(interaction.guild.id)
        if admin_id and admin_id in {r.id for r in user.roles}:
            return True
        await interaction.response.send_message(
            "❌ You need an **Admin** role to use this command.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


# ─────────────────────────────────────────
#  Events
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅  Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"✅  Slash commands synced.")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="the server"
    ))


@bot.event
async def on_member_join(member: discord.Member):
    embed = mod_embed(
        "👋 Member Joined", discord.Colour.green(),
        user=member.mention,
        account_created=discord.utils.format_dt(member.created_at, "R"),
        member_count=str(member.guild.member_count)
    )
    await log(member.guild, embed)


@bot.event
async def on_member_remove(member: discord.Member):
    embed = mod_embed(
        "🚪 Member Left", discord.Colour.orange(),
        user=f"{member} ({member.id})",
        joined_at=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown"
    )
    await log(member.guild, embed)


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot:
        return
    embed = mod_embed(
        "🗑️ Message Deleted", discord.Colour.red(),
        author=f"{message.author} ({message.author.id})",
        channel=message.channel.mention,
        content=message.content[:1024] or "*empty*"
    )
    await log(message.guild, embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or before.content == after.content:
        return
    embed = mod_embed(
        "✏️ Message Edited", discord.Colour.yellow(),
        author=f"{before.author} ({before.author.id})",
        channel=before.channel.mention,
        before=before.content[:512] or "*empty*",
        after=after.content[:512] or "*empty*"
    )
    await log(before.guild, embed)


# ═══════════════════════════════════════════════════════════
#  ADMIN-ONLY COMMANDS
#  /ban  /unban  /clearwarnings  /announce  /role
#  /setmodrole  /setadminrole
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="setmodrole", description="[Admin] Set the Moderator role for this server.")
@app_commands.describe(role="The role to designate as Moderator")
@is_admin()
async def setmodrole(interaction: discord.Interaction, role: discord.Role):
    data = load_config()
    data.setdefault(str(interaction.guild.id), {})["mod_role_id"] = role.id
    save_config(data)
    await interaction.response.send_message(
        f"✅ **Moderator** role set to {role.mention}.", ephemeral=True
    )


@bot.tree.command(name="setadminrole", description="[Admin] Set the Admin role for this server.")
@app_commands.describe(role="The role to designate as Admin")
@is_admin()
async def setadminrole(interaction: discord.Interaction, role: discord.Role):
    data = load_config()
    data.setdefault(str(interaction.guild.id), {})["admin_role_id"] = role.id
    save_config(data)
    await interaction.response.send_message(
        f"✅ **Admin** role set to {role.mention}.", ephemeral=True
    )


@bot.tree.command(name="ban", description="[Admin] Ban a member from the server.")
@app_commands.describe(
    member="The member to ban",
    reason="Reason for the ban",
    delete_days="Days of messages to delete (0–7)"
)
@is_admin()
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided",
    delete_days: app_commands.Range[int, 0, 7] = 0
):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "❌ You cannot ban someone with an equal or higher role.", ephemeral=True
        )
    try:
        await member.send(embed=mod_embed(
            f"🔨 You have been banned from {interaction.guild.name}",
            discord.Colour.red(), reason=reason, moderator=str(interaction.user)
        ))
    except discord.Forbidden:
        pass
    await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=delete_days)
    embed = mod_embed(
        "🔨 Member Banned", discord.Colour.red(),
        member=f"{member} ({member.id})",
        reason=reason,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="unban", description="[Admin] Unban a user by their ID.")
@app_commands.describe(user_id="The user's ID to unban", reason="Reason for the unban")
@is_admin()
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}")
        embed = mod_embed(
            "✅ Member Unbanned", discord.Colour.green(),
            user=f"{user} ({user.id})",
            reason=reason,
            moderator=interaction.user.mention
        )
        await interaction.response.send_message(embed=embed)
        await log(interaction.guild, embed)
    except discord.NotFound:
        await interaction.response.send_message("❌ User not found or not banned.", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)


@bot.tree.command(name="clearwarnings", description="[Admin] Clear all warnings for a member.")
@app_commands.describe(member="The member whose warnings to clear")
@is_admin()
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    data = load_warnings()
    guild_id = str(interaction.guild.id)
    user_id  = str(member.id)
    data.get(guild_id, {}).pop(user_id, None)
    save_warnings(data)
    embed = mod_embed(
        "🧹 Warnings Cleared", discord.Colour.green(),
        member=f"{member} ({member.id})",
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="announce", description="[Admin] Send a formatted announcement to a channel.")
@app_commands.describe(
    channel="Channel to send the announcement to",
    title="Announcement title",
    message="Announcement body",
    ping="Role to ping (optional)"
)
@is_admin()
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str,
    ping: discord.Role = None
):
    embed = discord.Embed(
        title=f"📢 {title}",
        description=message,
        colour=discord.Colour.from_rgb(232, 49, 42),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Announced by {interaction.user}")
    content = ping.mention if ping else None
    await channel.send(content=content, embed=embed)
    await interaction.response.send_message(f"✅ Announcement sent to {channel.mention}.", ephemeral=True)


@bot.tree.command(name="role", description="[Admin] Add or remove a role from a member.")
@app_commands.describe(
    member="The member to modify",
    role="The role to add or remove",
    action="Add or remove"
)
@app_commands.choices(action=[
    app_commands.Choice(name="add",    value="add"),
    app_commands.Choice(name="remove", value="remove"),
])
@is_admin()
async def role_cmd(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role,
    action: str = "add"
):
    if role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ You cannot assign a role equal to or higher than your own.", ephemeral=True
        )
    if action == "add":
        await member.add_roles(role, reason=f"Role granted by {interaction.user}")
        verb = "Added"
    else:
        await member.remove_roles(role, reason=f"Role removed by {interaction.user}")
        verb = "Removed"
    embed = mod_embed(
        f"🎭 Role {verb}", discord.Colour.blurple(),
        member=member.mention,
        role=role.mention,
        action=verb,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


# ═══════════════════════════════════════════════════════════
#  MODERATOR COMMANDS  (mod + admin can use these)
#  /kick  /timeout  /untimeout  /warn  /warnings
#  /purge  /slowmode  /lock  /unlock
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="kick", description="[Mod] Kick a member from the server.")
@app_commands.describe(member="The member to kick", reason="Reason for the kick")
@is_mod()
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "❌ You cannot kick someone with an equal or higher role.", ephemeral=True
        )
    try:
        await member.send(embed=mod_embed(
            f"👢 You have been kicked from {interaction.guild.name}",
            discord.Colour.orange(), reason=reason, moderator=str(interaction.user)
        ))
    except discord.Forbidden:
        pass
    await member.kick(reason=f"{interaction.user}: {reason}")
    embed = mod_embed(
        "👢 Member Kicked", discord.Colour.orange(),
        member=f"{member} ({member.id})",
        reason=reason,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="timeout", description="[Mod] Timeout (mute) a member.")
@app_commands.describe(
    member="The member to timeout",
    minutes="Duration in minutes (max 40320 = 28 days)",
    reason="Reason for the timeout"
)
@is_mod()
async def timeout_cmd(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320] = 10,
    reason: str = "No reason provided"
):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "❌ You cannot timeout someone with an equal or higher role.", ephemeral=True
        )
    duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
    await member.timeout(duration, reason=f"{interaction.user}: {reason}")
    embed = mod_embed(
        "🔇 Member Timed Out", discord.Colour.dark_orange(),
        member=f"{member} ({member.id})",
        duration=f"{minutes} minute(s)",
        reason=reason,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="untimeout", description="[Mod] Remove a timeout from a member.")
@app_commands.describe(member="The member to untimeout", reason="Reason")
@is_mod()
async def untimeout_cmd(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    await member.timeout(None, reason=f"{interaction.user}: {reason}")
    embed = mod_embed(
        "🔊 Timeout Removed", discord.Colour.green(),
        member=f"{member} ({member.id})",
        reason=reason,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="warn", description="[Mod] Warn a member and log it.")
@app_commands.describe(member="The member to warn", reason="Reason for the warning")
@is_mod()
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    data = load_warnings()
    guild_id = str(interaction.guild.id)
    user_id  = str(member.id)
    data.setdefault(guild_id, {}).setdefault(user_id, [])
    entry = {
        "reason": reason,
        "moderator": str(interaction.user),
        "timestamp": datetime.utcnow().isoformat()
    }
    data[guild_id][user_id].append(entry)
    save_warnings(data)
    count = len(data[guild_id][user_id])
    try:
        await member.send(embed=mod_embed(
            f"⚠️ You have been warned in {interaction.guild.name}",
            discord.Colour.yellow(),
            reason=reason,
            moderator=str(interaction.user),
            total_warnings=str(count)
        ))
    except discord.Forbidden:
        pass
    embed = mod_embed(
        "⚠️ Member Warned", discord.Colour.yellow(),
        member=f"{member} ({member.id})",
        reason=reason,
        total_warnings=str(count),
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="warnings", description="[Mod] View all warnings for a member.")
@app_commands.describe(member="The member to check")
@is_mod()
async def warnings(interaction: discord.Interaction, member: discord.Member):
    data = load_warnings()
    guild_id = str(interaction.guild.id)
    user_id  = str(member.id)
    warns = data.get(guild_id, {}).get(user_id, [])
    if not warns:
        return await interaction.response.send_message(
            f"✅ {member.mention} has no warnings.", ephemeral=True
        )
    embed = discord.Embed(
        title=f"⚠️ Warnings for {member}",
        colour=discord.Colour.yellow(),
        timestamp=datetime.utcnow()
    )
    for i, w in enumerate(warns, 1):
        embed.add_field(
            name=f"Warning {i}",
            value=f"**Reason:** {w['reason']}\n**Mod:** {w['moderator']}\n**Date:** {w['timestamp'][:10]}",
            inline=False
        )
    embed.set_footer(text=f"Total: {len(warns)} warning(s)")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="purge", description="[Mod] Bulk-delete messages in a channel.")
@app_commands.describe(
    amount="Number of messages to delete (1–100)",
    member="Only delete messages from this member (optional)"
)
@is_mod()
async def purge(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100] = 10,
    member: discord.Member = None
):
    await interaction.response.defer(ephemeral=True)
    def check(m):
        return member is None or m.author == member
    deleted = await interaction.channel.purge(limit=amount, check=check)
    embed = mod_embed(
        "🧹 Messages Purged", discord.Colour.blurple(),
        channel=interaction.channel.mention,
        deleted=str(len(deleted)),
        target=member.mention if member else "Everyone",
        moderator=interaction.user.mention
    )
    await interaction.followup.send(embed=embed, ephemeral=True)
    await log(interaction.guild, embed)


@bot.tree.command(name="slowmode", description="[Mod] Set slowmode for a channel.")
@app_commands.describe(
    seconds="Slowmode delay in seconds (0 to disable, max 21600)",
    channel="Channel to apply slowmode to (defaults to current)"
)
@is_mod()
async def slowmode(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600] = 0,
    channel: discord.TextChannel = None
):
    target = channel or interaction.channel
    await target.edit(slowmode_delay=seconds)
    embed = mod_embed(
        "⏱️ Slowmode Updated", discord.Colour.blurple(),
        channel=target.mention,
        delay=f"{seconds}s" if seconds else "Disabled",
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await log(interaction.guild, embed)


@bot.tree.command(name="lock", description="[Mod] Lock a channel so members can't send messages.")
@app_commands.describe(
    channel="Channel to lock (defaults to current)",
    reason="Reason for locking"
)
@is_mod()
async def lock(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    reason: str = "No reason provided"
):
    target = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
    embed = mod_embed(
        "🔒 Channel Locked", discord.Colour.red(),
        channel=target.mention,
        reason=reason,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await target.send(embed=discord.Embed(
        description="🔒 This channel has been locked by a moderator.",
        colour=discord.Colour.red()
    ))
    await log(interaction.guild, embed)


@bot.tree.command(name="unlock", description="[Mod] Unlock a previously locked channel.")
@app_commands.describe(
    channel="Channel to unlock (defaults to current)",
    reason="Reason for unlocking"
)
@is_mod()
async def unlock(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    reason: str = "No reason provided"
):
    target = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
    embed = mod_embed(
        "🔓 Channel Unlocked", discord.Colour.green(),
        channel=target.mention,
        reason=reason,
        moderator=interaction.user.mention
    )
    await interaction.response.send_message(embed=embed)
    await target.send(embed=discord.Embed(
        description="🔓 This channel has been unlocked.",
        colour=discord.Colour.green()
    ))
    await log(interaction.guild, embed)


# ═══════════════════════════════════════════════════════════
#  GENERAL COMMANDS  (anyone)
#  /userinfo  /serverinfo  /help
# ═══════════════════════════════════════════════════════════

@bot.tree.command(name="userinfo", description="View detailed info about a member.")
@app_commands.describe(member="The member to look up (defaults to yourself)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles = [r.mention for r in member.roles if r != interaction.guild.default_role]
    embed = discord.Embed(
        title=f"👤 {member}",
        colour=member.colour if member.colour.value else discord.Colour.blurple(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID",              value=member.id,                                                                    inline=True)
    embed.add_field(name="Nickname",        value=member.nick or "None",                                                        inline=True)
    embed.add_field(name="Bot",             value="Yes" if member.bot else "No",                                                 inline=True)
    embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"),                              inline=True)
    embed.add_field(name="Joined Server",   value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="Top Role",        value=member.top_role.mention,                                                       inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles) if roles else "None",                                   inline=False)
    data = load_warnings()
    warn_count = len(data.get(str(interaction.guild.id), {}).get(str(member.id), []))
    embed.add_field(name="Warnings", value=str(warn_count), inline=True)
    embed.set_footer(text="Moderation Bot")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="View information about this server.")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(
        title=f"🏰 {g.name}",
        colour=discord.Colour.blurple(),
        timestamp=datetime.utcnow()
    )
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Owner",        value=g.owner.mention if g.owner else "Unknown", inline=True)
    embed.add_field(name="Members",      value=str(g.member_count),                       inline=True)
    embed.add_field(name="Roles",        value=str(len(g.roles)),                         inline=True)
    embed.add_field(name="Channels",     value=str(len(g.channels)),                      inline=True)
    embed.add_field(name="Boosts",       value=str(g.premium_subscription_count),         inline=True)
    embed.add_field(name="Boost Level",  value=str(g.premium_tier),                       inline=True)
    embed.add_field(name="Created",      value=discord.utils.format_dt(g.created_at, "R"), inline=True)
    embed.add_field(name="Verification", value=str(g.verification_level).title(),         inline=True)
    embed.set_footer(text=f"ID: {g.id}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="help", description="List all available commands.")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Bot Commands",
        colour=discord.Colour.from_rgb(232, 49, 42),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="Moderation Bot")

    admin_commands = [
        ("`/setmodrole`",    "Set the Moderator role for this server"),
        ("`/setadminrole`",  "Set the Admin role for this server"),
        ("`/ban`",           "Ban a member from the server"),
        ("`/unban`",         "Unban a user by ID"),
        ("`/clearwarnings`", "Clear all warnings for a member"),
        ("`/announce`",      "Send a formatted announcement"),
        ("`/role`",          "Add or remove a role from a member"),
    ]
    mod_commands = [
        ("`/kick`",      "Kick a member from the server"),
        ("`/timeout`",   "Timeout (mute) a member"),
        ("`/untimeout`", "Remove a timeout from a member"),
        ("`/warn`",      "Issue a warning to a member"),
        ("`/warnings`",  "View a member's warnings"),
        ("`/purge`",     "Bulk-delete messages"),
        ("`/slowmode`",  "Set channel slowmode"),
        ("`/lock`",      "Lock a channel"),
        ("`/unlock`",    "Unlock a channel"),
    ]
    general_commands = [
        ("`/userinfo`",   "View info about a member"),
        ("`/serverinfo`", "View info about the server"),
        ("`/help`",       "Show this help message"),
    ]

    embed.add_field(
        name="🔴 Admin Commands",
        value="\n".join(f"{cmd} — {desc}" for cmd, desc in admin_commands),
        inline=False
    )
    embed.add_field(
        name="🟡 Moderator Commands",
        value="\n".join(f"{cmd} — {desc}" for cmd, desc in mod_commands),
        inline=False
    )
    embed.add_field(
        name="🟢 General Commands",
        value="\n".join(f"{cmd} — {desc}" for cmd, desc in general_commands),
        inline=False
    )
    embed.add_field(
        name="🔐 Setup",
        value="Use `/setadminrole` and `/setmodrole` (requires Discord Admin permission) to configure role-based access.",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─────────────────────────────────────────
#  Run
# ─────────────────────────────────────────
if __name__ == "__main__":
    keep_alive()   # Starts a tiny web server so Replit/UptimeRobot can ping the bot
    bot.run(TOKEN)
