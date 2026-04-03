import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime, timezone

# --- CONFIG ---
import os
TOKEN = os.environ.get("TOKEN")
STATUS_CHANNEL_ID = int(os.environ.get("STATUS_CHANNEL_ID"))
LOG_FILE = "work_log.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- DATA STORAGE ---
def load_data():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return {"active_sessions": {}, "completed_sessions": []}

def save_data(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# --- SLASH COMMANDS ---

@tree.command(name="clockin", description="Clock in to start your work session")
async def clockin(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)
    username = interaction.user.display_name

    if user_id in data["active_sessions"]:
        await interaction.response.send_message(
            "⚠️ You're already clocked in! Use `/clockout` to end your session first.",
            ephemeral=True
        )
        return

    now = datetime.now(timezone.utc)
    data["active_sessions"][user_id] = {
        "username": username,
        "clock_in": now.isoformat()
    }
    save_data(data)

    # Post to status channel
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    embed = discord.Embed(
        title="🟢 Clocked In",
        description=f"**{username}** has started their work session.",
        color=0x00C853,
        timestamp=now
    )
    embed.set_footer(text=f"User ID: {user_id}")
    await channel.send(embed=embed)

    await interaction.response.send_message(
        f"✅ You've been clocked in at `{now.strftime('%Y-%m-%d %H:%M:%S')} UTC`. Good luck!",
        ephemeral=True
    )


class WorkDescriptionModal(discord.ui.Modal, title="Work Session Summary"):
    description = discord.ui.TextInput(
        label="What did you work on?",
        style=discord.TextStyle.paragraph,
        placeholder="Describe your tasks, progress, and any blockers...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        user_id = str(interaction.user.id)
        username = interaction.user.display_name

        session = data["active_sessions"].pop(user_id)
        clock_in = datetime.fromisoformat(session["clock_in"])
        clock_out = datetime.now(timezone.utc)
        duration = clock_out - clock_in
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes = remainder // 60

        entry = {
            "user_id": user_id,
            "username": username,
            "clock_in": session["clock_in"],
            "clock_out": clock_out.isoformat(),
            "duration_minutes": int(duration.total_seconds() // 60),
            "description": str(self.description)
        }
        data["completed_sessions"].append(entry)
        save_data(data)

        # Post to status channel
        channel = bot.get_channel(STATUS_CHANNEL_ID)
        embed = discord.Embed(
            title="🔴 Clocked Out",
            description=f"**{username}** has ended their work session.",
            color=0xFF1744,
            timestamp=clock_out
        )
        embed.add_field(name="⏱️ Duration", value=f"{hours}h {minutes}m", inline=True)
        embed.add_field(
            name="🕐 Session",
            value=f"{clock_in.strftime('%H:%M')} → {clock_out.strftime('%H:%M')} UTC",
            inline=True
        )
        embed.add_field(name="📝 Work Summary", value=str(self.description), inline=False)
        await channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ Clocked out! You worked for **{hours}h {minutes}m**. Great work!",
            ephemeral=True
        )


@tree.command(name="clockout", description="Clock out and submit your work summary")
async def clockout(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data["active_sessions"]:
        await interaction.response.send_message(
            "⚠️ You're not clocked in! Use `/clockin` to start a session.",
            ephemeral=True
        )
        return

    # This opens the modal (popup form) asking for a work description
    await interaction.response.send_modal(WorkDescriptionModal())


@tree.command(name="mystats", description="See your work history and total hours")
async def mystats(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)
    sessions = [s for s in data["completed_sessions"] if s["user_id"] == user_id]

    if not sessions:
        await interaction.response.send_message("No completed sessions found.", ephemeral=True)
        return

    total_minutes = sum(s["duration_minutes"] for s in sessions)
    total_hours = total_minutes // 60
    total_mins = total_minutes % 60
    recent = sessions[-5:]  # Last 5 sessions

    embed = discord.Embed(
        title=f"📊 Stats for {interaction.user.display_name}",
        color=0x2979FF
    )
    embed.add_field(
        name="Total Time Logged",
        value=f"{total_hours}h {total_mins}m across {len(sessions)} sessions",
        inline=False
    )
    for s in reversed(recent):
        ci = datetime.fromisoformat(s["clock_in"]).strftime("%b %d, %H:%M")
        dur = f"{s['duration_minutes'] // 60}h {s['duration_minutes'] % 60}m"
        embed.add_field(
            name=f"{ci} UTC — {dur}",
            value=s["description"][:100] + ("..." if len(s["description"]) > 100 else ""),
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="teamstatus", description="See who is currently clocked in")
async def teamstatus(interaction: discord.Interaction):
    data = load_data()
    if not data["active_sessions"]:
        await interaction.response.send_message("Nobody is currently clocked in.", ephemeral=True)
        return

    embed = discord.Embed(title="👥 Currently Working", color=0x00BFA5)
    now = datetime.now(timezone.utc)
    for uid, session in data["active_sessions"].items():
        ci = datetime.fromisoformat(session["clock_in"])
        elapsed = now - ci
        hours, rem = divmod(int(elapsed.total_seconds()), 3600)
        mins = rem // 60
        embed.add_field(
            name=session["username"],
            value=f"Clocked in at {ci.strftime('%H:%M')} UTC ({hours}h {mins}m ago)",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot is online as {bot.user}")

bot.run(TOKEN)