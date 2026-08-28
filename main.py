import discord
from discord import app_commands
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import json
import asyncio
from datetime import datetime, timezone

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

VERIFY_CHANNEL_ID = int(os.getenv('VERIFY_CHANNEL_ID', '1490580308536459265'))
VERIFY_ROLE_NAME = os.getenv('VERIFY_ROLE_NAME', 'Verified')
VERIFY_EMOJI = os.getenv('VERIFY_EMOJI', '✅')

# Comma-separated list of role names allowed to use staff commands (/warn, /warnings)
STAFF_ROLE_NAMES = [r.strip() for r in os.getenv('STAFF_ROLES', 'Staff,Admin,Moderator').split(',') if r.strip()]

WARNINGS_FILE = 'warnings.json'


def load_warnings():
    if os.path.exists(WARNINGS_FILE):
        with open(WARNINGS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                return {}
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {}
    return {}


def save_warnings(data):
    with open(WARNINGS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# Structure: { "guild_id": { "user_id": [ {reason, moderator_id, moderator_name, timestamp}, ... ] } }
warnings_data = load_warnings()

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="7 Products • 40 Sales"
        )
    )
    print(f"Bot is online: {bot.user.name}")


@bot.command()
@commands.has_permissions(administrator=True)
async def postverify(ctx):
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if channel is None:
        await ctx.send("Verify channel not found. Check VERIFY_CHANNEL_ID.")
        return

    embed = discord.Embed(
        title="Verification",
        description=f"React with {VERIFY_EMOJI} below to verify and gain access to Ignite Systems. Thanks for joining!",
        color=discord.Color.green()
    )
    msg = await channel.send(embed=embed)
    await msg.add_reaction(VERIFY_EMOJI)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != VERIFY_CHANNEL_ID:
        return
    if payload.member is None or payload.member.bot:
        return
    if str(payload.emoji) != VERIFY_EMOJI:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    role = discord.utils.get(guild.roles, name=VERIFY_ROLE_NAME)
    if role is None:
        return

    try:
        await payload.member.add_roles(role, reason="Reaction role verification")
    except discord.Forbidden:
        pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.channel_id != VERIFY_CHANNEL_ID:
        return
    if str(payload.emoji) != VERIFY_EMOJI:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return

    role = discord.utils.get(guild.roles, name=VERIFY_ROLE_NAME)
    if role is None:
        return

    try:
        await member.remove_roles(role, reason="Reaction role verification removed")
    except discord.Forbidden:
        pass


@bot.tree.command(name="warn", description="Warn a member and DM them the reason.")
@app_commands.describe(member="The member to warn", reason="Why they're being warned")
@app_commands.checks.has_any_role(*STAFF_ROLE_NAMES)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    guild_id = str(interaction.guild_id)
    user_id = str(member.id)

    entry = {
        "reason": reason,
        "moderator_id": interaction.user.id,
        "moderator_name": str(interaction.user),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    warnings_data.setdefault(guild_id, {}).setdefault(user_id, []).append(entry)
    save_warnings(warnings_data)

    dm_failed = False
    try:
        dm_embed = discord.Embed(
            title=f"You have been warned in {interaction.guild.name}",
            description=reason,
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="Warned by", value=str(interaction.user))
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        dm_failed = True

    confirm = f"{member.mention} has been warned for: **{reason}**"
    if dm_failed:
        confirm += "\n(Could not DM them — they may have DMs disabled.)"

    await interaction.response.send_message(confirm, ephemeral=True)


@bot.tree.command(name="warnings", description="View a member's warning history.")
@app_commands.describe(member="The member to check")
@app_commands.checks.has_any_role(*STAFF_ROLE_NAMES)
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    guild_id = str(interaction.guild_id)
    user_id = str(member.id)

    user_warnings = warnings_data.get(guild_id, {}).get(user_id, [])

    if not user_warnings:
        await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Warnings for {member}",
        description=f"Total warnings: **{len(user_warnings)}**",
        color=discord.Color.red()
    )

    for i, w in enumerate(user_warnings, start=1):
        ts = w["timestamp"].split("T")[0]
        embed.add_field(
            name=f"#{i} — {ts}",
            value=f"**Reason:** {w['reason']}\n**By:** {w['moderator_name']}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="removewarning", description="Remove a specific warning from a member by its number.")
@app_commands.describe(member="The member to remove a warning from", number="Warning number, from /warnings (e.g. 1, 2, 3)")
@app_commands.checks.has_any_role(*STAFF_ROLE_NAMES)
async def removewarning(interaction: discord.Interaction, member: discord.Member, number: int):
    guild_id = str(interaction.guild_id)
    user_id = str(member.id)

    user_warnings = warnings_data.get(guild_id, {}).get(user_id, [])

    if not user_warnings:
        await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
        return

    if number < 1 or number > len(user_warnings):
        await interaction.response.send_message(
            f"Invalid warning number. {member.mention} has {len(user_warnings)} warning(s), use a number between 1 and {len(user_warnings)}.",
            ephemeral=True
        )
        return

    removed = user_warnings.pop(number - 1)
    save_warnings(warnings_data)

    await interaction.response.send_message(
        f"Removed warning #{number} from {member.mention} (reason was: **{removed['reason']}**).",
        ephemeral=True
    )


@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member.")
@app_commands.describe(member="The member to clear all warnings for")
@app_commands.checks.has_any_role(*STAFF_ROLE_NAMES)
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    guild_id = str(interaction.guild_id)
    user_id = str(member.id)

    user_warnings = warnings_data.get(guild_id, {}).get(user_id, [])

    if not user_warnings:
        await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)
        return

    count = len(user_warnings)
    warnings_data[guild_id][user_id] = []
    save_warnings(warnings_data)

    await interaction.response.send_message(
        f"Cleared all {count} warning(s) for {member.mention}.",
        ephemeral=True
    )


@warn.error
@warnings_cmd.error
@removewarning.error
@clearwarnings.error
async def staff_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingAnyRole):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    else:
        raise error


# --- /kick ---
@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="The member to kick", reason="Reason for the kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't kick someone with an equal or higher role.", ephemeral=True)
    await member.kick(reason=reason)
    embed = discord.Embed(
        title="Member Kicked",
        description=f"{member.mention} was kicked.\n**Reason:** {reason}",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)


# --- /ban ---
@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="The member to ban", reason="Reason for the ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't ban someone with an equal or higher role.", ephemeral=True)
    await member.ban(reason=reason)
    embed = discord.Embed(
        title="Member Banned",
        description=f"{member.mention} was banned.\n**Reason:** {reason}",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)


# --- /tban (temporary ban) ---
@bot.tree.command(name="tban", description="Temporarily ban a member")
@app_commands.describe(member="The member to ban", duration_minutes="How long to ban them for, in minutes", reason="Reason for the ban")
@app_commands.checks.has_permissions(ban_members=True)
async def tban(interaction: discord.Interaction, member: discord.Member, duration_minutes: int, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't ban someone with an equal or higher role.", ephemeral=True)
    guild = interaction.guild
    user_id = member.id
    await member.ban(reason=f"{reason} (temp ban: {duration_minutes}m)")
    embed = discord.Embed(
        title="Member Temporarily Banned",
        description=f"{member.mention} was banned for **{duration_minutes} minutes**.\n**Reason:** {reason}",
        color=discord.Color.dark_red()
    )
    await interaction.response.send_message(embed=embed)

    async def unban_later():
        await asyncio.sleep(duration_minutes * 60)
        try:
            await guild.unban(discord.Object(id=user_id), reason="Temp ban expired")
        except discord.NotFound:
            pass  # already unbanned manually

    asyncio.create_task(unban_later())

# --- /purge ---
@bot.tree.command(name="purge", description="Delete a number of recent messages from this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} message(s).", ephemeral=True)


# --- Shared error handler for missing permissions ---
@kick.error
@ban.error
@tban.error
@purge.error
async def mod_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Something went wrong: {error}", ephemeral=True)


# --- /embed ---
# Paste JSON straight from Discohook (discohook.org -> build your embed -> JSON Editor)
# Either type it into json_text, or attach a .json file — file takes priority if both given.

@bot.tree.command(name="embed", description="Post an embed from Discohook-exported JSON")
@app_commands.describe(
    json_text="Paste the JSON from Discohook here (leave empty if attaching a file)",
    file="Or attach a .json file exported from Discohook"
)
@app_commands.checks.has_any_role(*STAFF_ROLE_NAMES)
async def embed_cmd(
    interaction: discord.Interaction,
    json_text: str = None,
    file: discord.Attachment = None
):
    raw = None

    if file is not None:
        if not file.filename.endswith(".json"):
            return await interaction.response.send_message("That attachment isn't a .json file.", ephemeral=True)
        raw_bytes = await file.read()
        raw = raw_bytes.decode("utf-8")
    elif json_text:
        raw = json_text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

    if not raw:
        return await interaction.response.send_message(
            "Paste JSON in `json_text` or attach a `.json` file.", ephemeral=True
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return await interaction.response.send_message(f"That JSON didn't parse: `{e}`", ephemeral=True)

    # Discohook exports either a single embed dict, or a full message dict with "embeds": [...]
    if isinstance(data, dict) and "embeds" in data:
        content = data.get("content")
        embed_dicts = data.get("embeds", [])
    elif isinstance(data, list):
        content = None
        embed_dicts = data
    elif isinstance(data, dict):
        content = None
        embed_dicts = [data]
    else:
        return await interaction.response.send_message("No embed data found in that JSON.", ephemeral=True)

    if not embed_dicts:
        return await interaction.response.send_message("No embed data found in that JSON.", ephemeral=True)
    if len(embed_dicts) > 10:
        embed_dicts = embed_dicts[:10]  # Discord's per-message cap

    try:
        built_embeds = [discord.Embed.from_dict(e) for e in embed_dicts]
    except Exception as e:
        return await interaction.response.send_message(f"Couldn't build the embed(s): `{e}`", ephemeral=True)

    await interaction.response.send_message("Posted.", ephemeral=True)
    await interaction.channel.send(content=content or None, embeds=built_embeds)


@embed_cmd.error
async def embed_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingAnyRole):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Something went wrong: {error}", ephemeral=True)


bot.run(token, log_handler=handler, log_level=logging.DEBUG)
