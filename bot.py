import discord
from discord.ext import commands
from discord import app_commands
import os
import io
import asyncio
from datetime import datetime, timezone, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from supabase import create_client, Client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ.get("TOKEN")
STATUS_CHANNEL_ID = int(os.environ.get("STATUS_CHANNEL_ID"))
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

IST_OFFSET = timedelta(hours=5, minutes=30)


def to_ist(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + IST_OFFSET


def now_ist():
    return datetime.now(timezone.utc) + IST_OFFSET


def format_duration(total_seconds):
    total_seconds = int(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}h {minutes}m {seconds}s"


def get_month_key(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


async def health_server():
    async def handle(reader, writer):
        await reader.read(1024)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
    port = int(os.environ.get("PORT", 8080))
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


@tree.command(name="clockin", description="Clock in to start your work session")
async def clockin(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    username = interaction.user.display_name

    existing = supabase.table("active_sessions").select("user_id").eq("user_id", user_id).execute()
    if existing.data:
        await interaction.followup.send(
            "⚠️ You are already clocked in! Use `/clockout` to end your session first.",
            ephemeral=True
        )
        return

    now_utc = datetime.now(timezone.utc)
    now_display = to_ist(now_utc)

    supabase.table("active_sessions").insert({
        "user_id": user_id,
        "username": username,
        "clock_in": now_utc.isoformat()
    }).execute()

    channel = bot.get_channel(STATUS_CHANNEL_ID)
    embed = discord.Embed(
        title="🟢 Clocked In",
        description=f"**{username}** has started their work session.",
        color=0x00C853,
        timestamp=now_utc
    )
    embed.add_field(
        name="🕐 Clock-in Time",
        value=f"`{now_display.strftime('%Y-%m-%d %H:%M:%S')} IST`",
        inline=False
    )
    embed.set_footer(text=f"User ID: {user_id}")
    await channel.send(embed=embed)

    await interaction.followup.send(
        f"✅ You have been clocked in at `{now_display.strftime('%Y-%m-%d %H:%M:%S')} IST`. Good luck!",
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
        user_id = str(interaction.user.id)
        username = interaction.user.display_name

        active = supabase.table("active_sessions").select("*").eq("user_id", user_id).execute()
        if not active.data:
            await interaction.response.send_message(
                "⚠️ Could not find your active session. Please try again.",
                ephemeral=True
            )
            return

        session = active.data[0]
        clock_in_utc = datetime.fromisoformat(session["clock_in"])
        clock_out_utc = datetime.now(timezone.utc)
        total_seconds = int((clock_out_utc - clock_in_utc).total_seconds())
        readable = format_duration(total_seconds)
        month_key = get_month_key(clock_in_utc)

        clock_in_ist = to_ist(clock_in_utc)
        clock_out_ist = to_ist(clock_out_utc)

        supabase.table("completed_sessions").insert({
            "user_id": user_id,
            "username": username,
            "clock_in": clock_in_utc.isoformat(),
            "clock_out": clock_out_utc.isoformat(),
            "duration_seconds": total_seconds,
            "description": str(self.description),
            "month_key": month_key
        }).execute()

        supabase.table("active_sessions").delete().eq("user_id", user_id).execute()

        channel = bot.get_channel(STATUS_CHANNEL_ID)
        embed = discord.Embed(
            title="🔴 Clocked Out",
            description=f"**{username}** has ended their work session.",
            color=0xFF1744,
            timestamp=clock_out_utc
        )
        embed.add_field(name="⏱️ Duration", value=readable, inline=True)
        embed.add_field(
            name="🕐 Session (IST)",
            value=f"{clock_in_ist.strftime('%H:%M:%S')} → {clock_out_ist.strftime('%H:%M:%S')}",
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
    user_id = str(interaction.user.id)
    existing = supabase.table("active_sessions").select("user_id").eq("user_id", user_id).execute()
    if not existing.data:
        await interaction.response.send_message(
            "⚠️ You are not clocked in! Use `/clockin` to start a session.",
            ephemeral=True
        )
        return
    await interaction.response.send_modal(WorkDescriptionModal())


@tree.command(name="mystats", description="See a quick summary of your work history")
async def mystats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)

    result = supabase.table("completed_sessions").select("*").eq("user_id", user_id).order("clock_in", desc=False).execute()
    sessions = result.data

    if not sessions:
        await interaction.followup.send("No completed sessions found.", ephemeral=True)
        return

    total_seconds = sum(s["duration_seconds"] for s in sessions)
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
        ci_ist = to_ist(datetime.fromisoformat(s["clock_in"]))
        dur = format_duration(s["duration_seconds"])
        embed.add_field(
            name=f"{ci_ist.strftime('%b %d, %H:%M')} IST — {dur}",
            value=s["description"][:100] + ("..." if len(s["description"]) > 100 else ""),
            inline=False
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="teamstatus", description="See who is currently clocked in")
async def teamstatus(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    result = supabase.table("active_sessions").select("*").execute()
    sessions = result.data

    if not sessions:
        await interaction.followup.send("Nobody is currently clocked in.", ephemeral=True)
        return

    embed = discord.Embed(title="👥 Currently Working", color=0x00BFA5)
    now_utc = datetime.now(timezone.utc)
    for session in sessions:
        ci_utc = datetime.fromisoformat(session["clock_in"])
        ci_ist = to_ist(ci_utc)
        elapsed = format_duration(int((now_utc - ci_utc).total_seconds()))
        embed.add_field(
            name=session["username"],
            value=f"Clocked in at `{ci_ist.strftime('%H:%M:%S')} IST` ({elapsed} ago)",
            inline=False
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="myreport", description="See your full personal time report with monthly breakdown")
async def myreport(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)

    result = supabase.table("completed_sessions").select("*").eq("user_id", user_id).order("clock_in", desc=False).execute()
    sessions = result.data

    if not sessions:
        await interaction.followup.send("You have no completed sessions yet.", ephemeral=True)
        return

    total_seconds = sum(s["duration_seconds"] for s in sessions)

    monthly = {}
    for s in sessions:
        mk = s["month_key"]
        monthly[mk] = monthly.get(mk, 0) + s["duration_seconds"]

    embed = discord.Embed(
        title=f"📋 Personal Report — {interaction.user.display_name}",
        color=0x2979FF
    )
    embed.add_field(
        name="🕐 Total Time Logged (This Month)",
        value=f"`{format_duration(total_seconds)}` across `{len(sessions)}` session(s)",
        inline=False
    )

    sorted_months = sorted(monthly.items())
    monthly_lines = []
    for mk, secs in sorted_months:
        try:
            label = datetime.strptime(mk, "%Y-%m").strftime("%B %Y")
        except ValueError:
            label = mk
        monthly_lines.append(f"**{label}:** {format_duration(secs)}")

    embed.add_field(
        name="📅 Monthly Breakdown",
        value="\n".join(monthly_lines) if monthly_lines else "No data",
        inline=False
    )

    recent = sessions[-5:]
    session_lines = []
    for s in reversed(recent):
        ci_ist = to_ist(datetime.fromisoformat(s["clock_in"]))
        dur = format_duration(s["duration_seconds"])
        date_str = ci_ist.strftime("%b %d, %Y at %H:%M IST")
        preview = s["description"][:80] + ("..." if len(s["description"]) > 80 else "")
        session_lines.append(f"**{date_str}** — {dur}\n_{preview}_")

    embed.add_field(
        name="🔍 Last 5 Sessions",
        value="\n\n".join(session_lines) if session_lines else "None",
        inline=False
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="lifetimehours", description="See your total hours worked since day one across all months")
async def lifetimehours(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)

    current_result = supabase.table("completed_sessions").select("duration_seconds, clock_in, month_key").eq("user_id", user_id).execute()
    archived_result = supabase.table("archived_sessions").select("duration_seconds, clock_in, month_key").eq("user_id", user_id).execute()

    current_sessions = current_result.data or []
    archived_sessions = archived_result.data or []
    all_sessions = archived_sessions + current_sessions

    if not all_sessions:
        await interaction.followup.send(
            "You have no recorded sessions at all yet. Start clocking in to build your history!",
            ephemeral=True
        )
        return

    total_seconds = sum(s["duration_seconds"] for s in all_sessions)

    monthly = {}
    for s in all_sessions:
        mk = s["month_key"]
        monthly[mk] = monthly.get(mk, 0) + s["duration_seconds"]

    sorted_months = sorted(monthly.items())
    monthly_lines = []
    for mk, secs in sorted_months:
        try:
            label = datetime.strptime(mk, "%Y-%m").strftime("%B %Y")
        except ValueError:
            label = mk
        monthly_lines.append(f"**{label}:** {format_duration(secs)}")

    embed = discord.Embed(
        title=f"🏅 Lifetime Hours — {interaction.user.display_name}",
        description="Every hour you have ever logged since day one.",
        color=0xFF6D00
    )
    embed.add_field(
        name="⏱️ Grand Total",
        value=f"`{format_duration(total_seconds)}`",
        inline=False
    )
    embed.add_field(
        name="📆 Total Sessions",
        value=f"`{len(all_sessions)}` session(s) across `{len(sorted_months)}` month(s)",
        inline=False
    )
    embed.add_field(
        name="📅 Breakdown by Month",
        value="\n".join(monthly_lines) if monthly_lines else "No data",
        inline=False
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="serverreport", description="See total hours logged by everyone, with a chart")
async def serverreport(interaction: discord.Interaction):
    await interaction.response.defer()

    result = supabase.table("completed_sessions").select("*").execute()
    sessions = result.data

    if not sessions:
        await interaction.followup.send("No sessions have been logged yet.")
        return

    user_totals = {}
    for s in sessions:
        uid = s["user_id"]
        if uid not in user_totals:
            user_totals[uid] = {"username": s["username"], "seconds": 0}
        user_totals[uid]["seconds"] += s["duration_seconds"]

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
    user_id = str(interaction.user.id)

    result = supabase.table("completed_sessions").select("*").eq("user_id", user_id).order("clock_in", desc=False).execute()
    sessions = result.data

    if not sessions:
        await interaction.followup.send("You have no completed sessions to edit.", ephemeral=True)
        return

    recent = sessions[-10:]
    lines = []
    total = len(sessions)
    for i, s in enumerate(reversed(recent)):
        real_index = total - i
        ci_ist = to_ist(datetime.fromisoformat(s["clock_in"]))
        co_ist = to_ist(datetime.fromisoformat(s["clock_out"]))
        dur = format_duration(s["duration_seconds"])
        lines.append(f"`#{real_index}` — **{ci_ist.strftime('%Y-%m-%d %H:%M IST')}** → **{co_ist.strftime('%H:%M IST')}** ({dur})")

    embed = discord.Embed(
        title="🗂️ Your Recent Sessions",
        description=(
            "Below are your last 10 sessions.\n"
            "To edit one, use:\n"
            "`/edittime session_number:<number> field:<clock_in or clock_out> new_time:<YYYY-MM-DD HH:MM>`\n"
            "⚠️ Enter times in **IST**.\n\n"
            + "\n".join(lines)
        ),
        color=0xFFA000
    )
    embed.set_footer(text="Times shown and entered in IST.")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="edittime", description="Edit the clock-in or clock-out time of a past session")
@app_commands.describe(
    session_number="The session number shown by /editsessions",
    field="Which time to change: clock_in or clock_out",
    new_time="New time in IST, format: YYYY-MM-DD HH:MM (e.g. 2024-06-01 09:30)"
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
    user_id = str(interaction.user.id)

    result = supabase.table("completed_sessions").select("*").eq("user_id", user_id).order("clock_in", desc=False).execute()
    user_sessions = result.data

    if not user_sessions:
        await interaction.followup.send("You have no completed sessions to edit.", ephemeral=True)
        return

    total = len(user_sessions)
    if session_number < 1 or session_number > total:
        await interaction.followup.send(
            f"❌ Invalid session number. You have `{total}` session(s). Run `/editsessions` to see them.",
            ephemeral=True
        )
        return

    try:
        new_dt_ist = datetime.strptime(new_time, "%Y-%m-%d %H:%M")
        new_dt_utc = new_dt_ist.replace(tzinfo=timezone.utc) - IST_OFFSET
    except ValueError:
        await interaction.followup.send(
            "❌ Invalid format. Please use `YYYY-MM-DD HH:MM` in IST — for example: `2024-06-01 09:30`",
            ephemeral=True
        )
        return

    target = user_sessions[session_number - 1]
    record_id = target["id"]
    old_clock_in_utc = datetime.fromisoformat(target["clock_in"])
    old_clock_out_utc = datetime.fromisoformat(target["clock_out"])

    if field == "clock_in":
        if new_dt_utc >= old_clock_out_utc:
            old_co_ist = to_ist(old_clock_out_utc)
            await interaction.followup.send(
                f"❌ The new clock-in (`{new_time} IST`) must be before clock-out "
                f"(`{old_co_ist.strftime('%Y-%m-%d %H:%M')} IST`).",
                ephemeral=True
            )
            return
        old_value_str = to_ist(old_clock_in_utc).strftime("%Y-%m-%d %H:%M IST")
        new_clock_in_utc = new_dt_utc
        new_clock_out_utc = old_clock_out_utc
    else:
        if new_dt_utc <= old_clock_in_utc:
            old_ci_ist = to_ist(old_clock_in_utc)
            await interaction.followup.send(
                f"❌ The new clock-out (`{new_time} IST`) must be after clock-in "
                f"(`{old_ci_ist.strftime('%Y-%m-%d %H:%M')} IST`).",
                ephemeral=True
            )
            return
        old_value_str = to_ist(old_clock_out_utc).strftime("%Y-%m-%d %H:%M IST")
        new_clock_in_utc = old_clock_in_utc
        new_clock_out_utc = new_dt_utc

    new_total_seconds = int((new_clock_out_utc - new_clock_in_utc).total_seconds())
    new_month_key = get_month_key(new_clock_in_utc)

    supabase.table("completed_sessions").update({
        field: new_dt_utc.isoformat(),
        "duration_seconds": new_total_seconds,
        "month_key": new_month_key
    }).eq("id", record_id).execute()

    embed = discord.Embed(title="✏️ Session Updated", color=0x00C853)
    embed.add_field(name="Session", value=f"#{session_number}", inline=True)
    embed.add_field(name="Field Changed", value=field.replace("_", " ").title(), inline=True)
    embed.add_field(name="Old Value", value=old_value_str, inline=False)
    embed.add_field(name="New Value", value=f"{new_time} IST", inline=False)
    embed.add_field(name="Recalculated Duration", value=format_duration(new_total_seconds), inline=False)
    embed.set_footer(text="Your log has been updated.")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="resetmonth", description="Admin only: archive this month's logs and start fresh")
async def resetmonth(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    admin_ids = os.environ.get("ADMIN_IDS", "")
    allowed = [uid.strip() for uid in admin_ids.split(",") if uid.strip()]

    if str(interaction.user.id) not in allowed:
        await interaction.followup.send(
            "❌ You do not have permission to run this command.",
            ephemeral=True
        )
        return

    result = supabase.table("completed_sessions").select("*").execute()
    sessions = result.data

    if not sessions:
        await interaction.followup.send(
            "There are no completed sessions to archive. The log is already empty.",
            ephemeral=True
        )
        return

    archive_rows = []
    for s in sessions:
        archive_rows.append({
            "user_id": s["user_id"],
            "username": s["username"],
            "clock_in": s["clock_in"],
            "clock_out": s["clock_out"],
            "duration_seconds": s["duration_seconds"],
            "description": s["description"],
            "month_key": s["month_key"]
        })

    supabase.table("archived_sessions").insert(archive_rows).execute()
    supabase.table("completed_sessions").delete().neq("id", 0).execute()

    now_utc = datetime.now(timezone.utc)
    embed = discord.Embed(
        title="🗂️ Month Reset Complete",
        color=0x00C853,
        timestamp=now_utc
    )
    embed.add_field(
        name="Sessions Archived",
        value=f"`{len(sessions)}` session(s) moved to the archive table in Supabase",
        inline=False
    )
    embed.add_field(
        name="Active Sessions",
        value="Anyone currently clocked in has been left untouched.",
        inline=False
    )
    embed.add_field(
        name="Fresh Start",
        value="The live log is now empty and ready for the new month.",
        inline=False
    )
    embed.set_footer(text=f"Reset performed by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="viewlog", description="Admin only: display a summary of the current work log")
async def viewlog(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    admin_ids = os.environ.get("ADMIN_IDS", "")
    allowed = [uid.strip() for uid in admin_ids.split(",") if uid.strip()]

    if str(interaction.user.id) not in allowed:
        await interaction.followup.send(
            "❌ You do not have permission to run this command.",
            ephemeral=True
        )
        return

    active_result = supabase.table("active_sessions").select("*").execute()
    completed_result = supabase.table("completed_sessions").select("*").execute()
    active_sessions = active_result.data
    completed_sessions = completed_result.data

    user_totals = {}
    for s in completed_sessions:
        uid = s["user_id"]
        if uid not in user_totals:
            user_totals[uid] = {"username": s["username"], "seconds": 0}
        user_totals[uid]["seconds"] += s["duration_seconds"]

    sorted_users = sorted(user_totals.items(), key=lambda x: x[1]["seconds"], reverse=True)
    lines = [f"**{info['username']}** — `{format_duration(info['seconds'])}`" for _, info in sorted_users]

    embed = discord.Embed(
        title="📁 Current Work Log",
        color=0x7C4DFF,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Active Sessions", value=str(len(active_sessions)), inline=True)
    embed.add_field(name="Completed Sessions", value=str(len(completed_sessions)), inline=True)
    embed.add_field(
        name="Totals Per User",
        value="\n".join(lines) if lines else "No data yet.",
        inline=False
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError):
        if isinstance(error.original, discord.errors.NotFound):
            return
    try:
        await interaction.followup.send(
            "⚠️ Something went wrong. Please try the command again.",
            ephemeral=True
        )
    except Exception:
        pass


@bot.event
async def on_ready():
    await tree.sync()
    asyncio.create_task(health_server())
    print(f"✅ Bot is online as {bot.user}")


bot.run(TOKEN)