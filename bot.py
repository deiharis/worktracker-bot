import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import io
from datetime import datetime, timezone
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ.get("TOKEN")
STATUS_CHANNEL_ID = int(os.environ.get("STATUS_CHANNEL_ID"))
LOG_FILE = "work_log.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def format_duration(total_seconds):
    total_seconds = int(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}h {minutes}m {seconds}s"


def get_session_seconds(s):
    if "duration_seconds" in s:
        return s["duration_seconds"]
    elif "duration_minutes" in s:
        return s["duration_minutes"] * 60
    return 0


def get_user_total_seconds(sessions, user_id):
    return sum(get_session_seconds(s) for s in sessions if s["user_id"] == user_id)


def load_data():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    return {"active_sessions": {}, "completed_sessions": []}


def save_data(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)


@tree.command(name="clockin", description="Clock in to start your work session")
async def clockin(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)
    username = interaction.user.display_name

    if user_id in data["active_sessions"]:
        await interaction.followup.send(
            "⚠️ You are already clocked in! Use `/clockout` to end your session first.",
            ephemeral=True
        )
        return

    now = datetime.now(timezone.utc)
    data["active_sessions"][user_id] = {
        "username": username,
        "clock_in": now.isoformat()
    }
    save_data(data)

    channel = bot.get_channel(STATUS_CHANNEL_ID)
    embed = discord.Embed(
        title="🟢 Clocked In",
        description=f"**{username}** has started their work session.",
        color=0x00C853,
        timestamp=now
    )
    embed.set_footer(text=f"User ID: {user_id}")
    await channel.send(embed=embed)

    await interaction.followup.send(
        f"✅ You have been clocked in at `{now.strftime('%Y-%m-%d %H:%M:%S')} UTC`. Good luck!",
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
        total_seconds = int((clock_out - clock_in).total_seconds())
        readable = format_duration(total_seconds)

        entry = {
            "user_id": user_id,
            "username": username,
            "clock_in": session["clock_in"],
            "clock_out": clock_out.isoformat(),
            "duration_seconds": total_seconds,
            "description": str(self.description)
        }
        data["completed_sessions"].append(entry)
        save_data(data)

        channel = bot.get_channel(STATUS_CHANNEL_ID)
        embed = discord.Embed(
            title="🔴 Clocked Out",
            description=f"**{username}** has ended their work session.",
            color=0xFF1744,
            timestamp=clock_out
        )
        embed.add_field(name="⏱️ Duration", value=readable, inline=True)
        embed.add_field(
            name="🕐 Session",
            value=f"{clock_in.strftime('%H:%M:%S')} → {clock_out.strftime('%H:%M:%S')} UTC",
            inline=True
        )
        embed.add_field(name="📝 Work Summary", value=str(self.description), inline=False)
        await channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ Clocked out! You worked for **{readable}**. Great work!",
            ephemeral=True
        )


@tree.command(name="clockout", description="Clock out and submit your work summary")
async def clockout(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data["active_sessions"]:
        await interaction.response.send_message(
            "⚠️ You are not clocked in! Use `/clockin` to start a session.",
            ephemeral=True
        )
        return

    await interaction.response.send_modal(WorkDescriptionModal())


@tree.command(name="mystats", description="See a quick summary of your work history")
async def mystats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)
    sessions = [s for s in data["completed_sessions"] if s["user_id"] == user_id]

    if not sessions:
        await interaction.followup.send("No completed sessions found.", ephemeral=True)
        return

    total_seconds = get_user_total_seconds(data["completed_sessions"], user_id)
    recent = sessions[-5:]

    embed = discord.Embed(
        title=f"📊 Stats for {interaction.user.display_name}",
        color=0x2979FF
    )
    embed.add_field(
        name="Total Time Logged",
        value=f"{format_duration(total_seconds)} across {len(sessions)} session(s)",
        inline=False
    )
    for s in reversed(recent):
        ci = datetime.fromisoformat(s["clock_in"]).strftime("%b %d, %H:%M")
        dur = format_duration(get_session_seconds(s))
        embed.add_field(
            name=f"{ci} UTC — {dur}",
            value=s["description"][:100] + ("..." if len(s["description"]) > 100 else ""),
            inline=False
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="teamstatus", description="See who is currently clocked in")
async def teamstatus(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()

    if not data["active_sessions"]:
        await interaction.followup.send("Nobody is currently clocked in.", ephemeral=True)
        return

    embed = discord.Embed(title="👥 Currently Working", color=0x00BFA5)
    now = datetime.now(timezone.utc)
    for uid, session in data["active_sessions"].items():
        ci = datetime.fromisoformat(session["clock_in"])
        elapsed = format_duration(int((now - ci).total_seconds()))
        embed.add_field(
            name=session["username"],
            value=f"Clocked in at {ci.strftime('%H:%M:%S')} UTC ({elapsed} ago)",
            inline=False
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="myreport", description="See your full personal time report with monthly breakdown")
async def myreport(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)
    sessions = [s for s in data["completed_sessions"] if s["user_id"] == user_id]

    if not sessions:
        await interaction.followup.send(
            "You have no completed sessions yet.", ephemeral=True
        )
        return

    total_seconds = get_user_total_seconds(data["completed_sessions"], user_id)

    monthly = {}
    for s in sessions:
        ci = datetime.fromisoformat(s["clock_in"])
        month_key = ci.strftime("%B %Y")
        monthly[month_key] = monthly.get(month_key, 0) + get_session_seconds(s)

    embed = discord.Embed(
        title=f"📋 Personal Report — {interaction.user.display_name}",
        color=0x2979FF
    )
    embed.add_field(
        name="🕐 Total Time Logged",
        value=f"`{format_duration(total_seconds)}` across `{len(sessions)}` session(s)",
        inline=False
    )

    sorted_months = sorted(monthly.items(), key=lambda x: datetime.strptime(x[0], "%B %Y"))
    monthly_lines = [f"**{month}:** {format_duration(secs)}" for month, secs in sorted_months]
    embed.add_field(
        name="📅 Monthly Breakdown",
        value="\n".join(monthly_lines) if monthly_lines else "No data",
        inline=False
    )

    recent = sessions[-5:]
    session_lines = []
    for s in reversed(recent):
        ci = datetime.fromisoformat(s["clock_in"])
        dur = format_duration(get_session_seconds(s))
        date_str = ci.strftime("%b %d, %Y at %H:%M UTC")
        preview = s["description"][:80] + ("..." if len(s["description"]) > 80 else "")
        session_lines.append(f"**{date_str}** — {dur}\n_{preview}_")

    embed.add_field(
        name="🔍 Last 5 Sessions",
        value="\n\n".join(session_lines) if session_lines else "None",
        inline=False
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="serverreport", description="See total hours logged by everyone, with a chart")
async def serverreport(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    sessions = data["completed_sessions"]

    if not sessions:
        await interaction.followup.send("No sessions have been logged yet.")
        return

    user_totals = {}
    for s in sessions:
        uid = s["user_id"]
        secs = get_session_seconds(s)
        if uid not in user_totals:
            user_totals[uid] = {"username": s["username"], "seconds": 0}
        user_totals[uid]["seconds"] += secs

    sorted_users = sorted(user_totals.items(), key=lambda x: x[1]["seconds"], reverse=True)

    embed = discord.Embed(
        title="📊 Server Work Report",
        description=f"{len(sorted_users)} member(s) have logged time",
        color=0x7C4DFF
    )

    medals = ["🥇", "🥈", "🥉"]
    leaderboard_lines = []
    for i, (uid, info) in enumerate(sorted_users):
        medal = medals[i] if i < 3 else f"`#{i + 1}`"
        leaderboard_lines.append(
            f"{medal} **{info['username']}** — `{format_duration(info['seconds'])}`"
        )
    embed.add_field(
        name="🏆 Leaderboard",
        value="\n".join(leaderboard_lines),
        inline=False
    )

    names = [info["username"] for _, info in sorted_users]
    hours = [info["seconds"] / 3600 for _, info in sorted_users]
    bar_palette = ["#7C4DFF", "#536DFE", "#448AFF", "#40C4FF", "#18FFFF",
                   "#00E5FF", "#00B0FF", "#0091EA", "#304FFE", "#651FFF"]
    bar_colors = [bar_palette[i % len(bar_palette)] for i in range(len(names))]
    fig_width = max(7, len(names) * 1.4)
    fig, ax = plt.subplots(figsize=(fig_width, 5))
    bars = ax.bar(names, hours, color=bar_colors, width=0.55, zorder=2)
    bg_color = "#2b2d31"
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor("#1e1f22")
    ax.set_title("Total Hours Worked — All Members", fontsize=13,
                 color="white", pad=14, fontweight="bold")
    ax.set_ylabel("Hours", fontsize=11, color="#b5bac1")
    ax.set_xlabel("Team Member", fontsize=11, color="#b5bac1")
    ax.tick_params(axis="x", colors="white", labelsize=10)
    ax.tick_params(axis="y", colors="#b5bac1", labelsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#3f4147")
    ax.spines["bottom"].set_color("#3f4147")
    ax.grid(axis="y", color="#3f4147", linestyle="--", linewidth=0.7, zorder=1)
    for bar, h in zip(bars, hours):
        label_h = int(h)
        label_m = int((h - label_h) * 60)
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(hours) * 0.015,
            f"{label_h}h {label_m}m",
            ha="center", va="bottom", fontsize=9, color="white", fontweight="bold"
        )
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    chart_file = discord.File(buf, filename="server_report.png")
    embed.set_image(url="attachment://server_report.png")
    await interaction.followup.send(embed=embed, file=chart_file)


@tree.command(name="editsessions", description="View your recent sessions so you can find which one to edit")
async def editsessions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)
    sessions = [s for s in data["completed_sessions"] if s["user_id"] == user_id]

    if not sessions:
        await interaction.followup.send(
            "You have no completed sessions to edit.", ephemeral=True
        )
        return

    recent = sessions[-10:]
    lines = []
    total = len(sessions)
    for i, s in enumerate(reversed(recent)):
        real_index = total - i
        ci = datetime.fromisoformat(s["clock_in"]).strftime("%Y-%m-%d %H:%M UTC")
        co = datetime.fromisoformat(s["clock_out"]).strftime("%H:%M UTC")
        dur = format_duration(get_session_seconds(s))
        lines.append(f"`#{real_index}` — **{ci}** → **{co}** ({dur})")

    embed = discord.Embed(
        title="🗂️ Your Recent Sessions",
        description=(
            "Below are your last 10 sessions.\n"
            "To edit one, use:\n"
            "`/edittime session_number:<number> field:<clock_in or clock_out> new_time:<YYYY-MM-DD HH:MM>`\n\n"
            + "\n".join(lines)
        ),
        color=0xFFA000
    )
    embed.set_footer(text="Times are in UTC. Use YYYY-MM-DD HH:MM format when editing.")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="edittime", description="Edit the clock-in or clock-out time of a past session")
@app_commands.describe(
    session_number="The session number shown by /editsessions",
    field="Which time to change: clock_in or clock_out",
    new_time="New time in UTC, format: YYYY-MM-DD HH:MM (e.g. 2024-06-01 09:30)"
)
@app_commands.choices(field=[
    app_commands.Choice(name="clock_in", value="clock_in"),
    app_commands.Choice(name="clock_out", value="clock_out")
])
async def edittime(
    interaction: discord.Interaction,
    session_number: int,
    field: str,
    new_time: str
):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)
    user_sessions = [s for s in data["completed_sessions"] if s["user_id"] == user_id]

    if not user_sessions:
        await interaction.followup.send(
            "You have no completed sessions to edit.", ephemeral=True
        )
        return

    total = len(user_sessions)
    if session_number < 1 or session_number > total:
        await interaction.followup.send(
            f"❌ Invalid session number. You have `{total}` session(s). Run `/editsessions` to see them.",
            ephemeral=True
        )
        return

    try:
        new_dt = datetime.strptime(new_time, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        await interaction.followup.send(
            "❌ Invalid format. Please use `YYYY-MM-DD HH:MM` — for example: `2024-06-01 09:30`",
            ephemeral=True
        )
        return

    target = user_sessions[session_number - 1]
    global_index = None
    for i, s in enumerate(data["completed_sessions"]):
        if (s["user_id"] == user_id
                and s["clock_in"] == target["clock_in"]
                and s["clock_out"] == target["clock_out"]):
            global_index = i
            break

    if global_index is None:
        await interaction.followup.send(
            "❌ Could not locate that session. Please try again.", ephemeral=True
        )
        return

    session = data["completed_sessions"][global_index]
    old_clock_in = datetime.fromisoformat(session["clock_in"])
    old_clock_out = datetime.fromisoformat(session["clock_out"])

    if field == "clock_in":
        if new_dt >= old_clock_out:
            await interaction.followup.send(
                f"❌ The new clock-in (`{new_time} UTC`) must be before clock-out "
                f"(`{old_clock_out.strftime('%Y-%m-%d %H:%M')} UTC`).",
                ephemeral=True
            )
            return
        old_value_str = old_clock_in.strftime("%Y-%m-%d %H:%M UTC")
        session["clock_in"] = new_dt.isoformat()
        new_clock_in, new_clock_out = new_dt, old_clock_out
    else:
        if new_dt <= old_clock_in:
            await interaction.followup.send(
                f"❌ The new clock-out (`{new_time} UTC`) must be after clock-in "
                f"(`{old_clock_in.strftime('%Y-%m-%d %H:%M')} UTC`).",
                ephemeral=True
            )
            return
        old_value_str = old_clock_out.strftime("%Y-%m-%d %H:%M UTC")
        session["clock_out"] = new_dt.isoformat()
        new_clock_in, new_clock_out = old_clock_in, new_dt

    new_total_seconds = int((new_clock_out - new_clock_in).total_seconds())
    session["duration_seconds"] = new_total_seconds
    session.pop("duration_minutes", None)
    data["completed_sessions"][global_index] = session
    save_data(data)

    embed = discord.Embed(title="✏️ Session Updated", color=0x00C853)
    embed.add_field(name="Session", value=f"#{session_number}", inline=True)
    embed.add_field(name="Field Changed", value=field.replace("_", " ").title(), inline=True)
    embed.add_field(name="Old Value", value=old_value_str, inline=False)
    embed.add_field(name="New Value", value=f"{new_time} UTC", inline=False)
    embed.add_field(name="Recalculated Duration", value=format_duration(new_total_seconds), inline=False)
    embed.set_footer(text="Your log has been updated.")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot is online as {bot.user}")


bot.run(TOKEN)