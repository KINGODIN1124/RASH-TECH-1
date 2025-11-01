import os
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from flask import Flask
import threading
import asyncio
import datetime
import requests

# ---------------- Flask Keepalive ----------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running and alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

# ---------------- Discord Bot Setup ----------------
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
TOKEN = os.getenv("TOKEN")
SELF_PING_URL = os.getenv("SELF_PING_URL")

LOG_CHANNEL_ID = 123456789012345678  # 🔧 Replace this with your log channel ID

COOLDOWN_HOURS = 24
INACTIVITY_LIMIT = 60 * 60 * 2  # 2 hours

user_cooldowns = {}
ticket_last_activity = {}

TICKET_CATEGORY_NAMES = {
    "tier1": "🎫│Tier 1 Support",
    "tier2": "🎫│Tier 2 Support",
    "tier3": "🎫│Tier 3 Support"
}

# ---------------- Flask Self Ping ----------------
@tasks.loop(minutes=5)
async def ping_self():
    try:
        if SELF_PING_URL:
            requests.get(SELF_PING_URL)
    except Exception:
        pass

# ---------------- Helper: Create Ticket ----------------
async def create_ticket_channel(interaction, tier: str):
    guild = interaction.guild
    category_name = TICKET_CATEGORY_NAMES.get(tier, "🎫│Tickets")
    category = discord.utils.get(guild.categories, name=category_name)
    if not category:
        category = await guild.create_category(category_name)

    channel = await category.create_text_channel(
        f"ticket-{interaction.user.name}",
        topic=f"Support ticket for {interaction.user} [{tier}]"
    )

    await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
    await channel.send(
        f"🎟️ Hello {interaction.user.mention}! A support team member will assist you soon.\n"
        f"To close this ticket, type `/close`."
    )

    ticket_last_activity[channel.id] = datetime.datetime.utcnow()
    await interaction.response.send_message(f"✅ Your **{tier.title()}** ticket has been created: {channel.mention}", ephemeral=True)

# ---------------- UI: Dropdown ----------------
class TierSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Tier 1", description="Basic support and FAQs", emoji="🟢", value="tier1"),
            discord.SelectOption(label="Tier 2", description="Advanced support issues", emoji="🟡", value="tier2"),
            discord.SelectOption(label="Tier 3", description="Critical issues or escalations", emoji="🔴", value="tier3")
        ]
        super().__init__(placeholder="Select your support tier...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = datetime.datetime.utcnow()

        # Cooldown check
        if user_id in user_cooldowns:
            remaining = user_cooldowns[user_id] - now
            if remaining.total_seconds() > 0:
                hours_left = int(remaining.total_seconds() // 3600)
                await interaction.response.send_message(
                    f"⏳ You can open another ticket in {hours_left} hours.",
                    ephemeral=True
                )
                return

        user_cooldowns[user_id] = now + datetime.timedelta(hours=COOLDOWN_HOURS)
        await create_ticket_channel(interaction, self.values[0])

class TierSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(TierSelect())

# ---------------- Slash Command: /ticket ----------------
@bot.tree.command(name="ticket", description="Create a support ticket")
async def ticket(interaction: discord.Interaction):
    view = TierSelectView()
    await interaction.response.send_message("🎟️ Please select your ticket tier:", view=view, ephemeral=True)

# ---------------- Slash Command: /close ----------------
@bot.tree.command(name="close", description="Close the current ticket")
async def close(interaction: discord.Interaction):
    channel = interaction.channel
    if not channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)
        return

    await interaction.response.send_message("Ticket closing... generating transcript...", ephemeral=True)

    # Generate transcript
    messages = [f"[{msg.created_at}] {msg.author}: {msg.content}" async for msg in channel.history(limit=None)]
    transcript = "\n".join(messages[::-1]) or "No messages recorded."

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"📜 Transcript for {channel.name}:\n```{transcript[:1900]}```")

    # Ask for feedback
    await interaction.followup.send("⭐ Please rate your support from 1–5:")
    def check(m): return m.author == interaction.user and m.channel == channel
    try:
        msg = await bot.wait_for("message", check=check, timeout=60.0)
        if log_channel:
            await log_channel.send(f"⭐ Feedback from {interaction.user}: {msg.content}")
    except asyncio.TimeoutError:
        if log_channel:
            await log_channel.send(f"⚙️ No feedback received from {interaction.user}.")

    await channel.delete()

# ---------------- Auto-Close Inactive Tickets ----------------
@tasks.loop(minutes=10)
async def auto_close_tickets():
    now = datetime.datetime.utcnow()
    to_close = []
    for channel_id, last_activity in list(ticket_last_activity.items()):
        if (now - last_activity).total_seconds() > INACTIVITY_LIMIT:
            channel = bot.get_channel(channel_id)
            if channel:
                to_close.append(channel)
            del ticket_last_activity[channel_id]

    for ch in to_close:
        await ch.send("⏰ This ticket has been inactive for 2 hours and will now be closed automatically.")
        await asyncio.sleep(5)
        await ch.delete()

# ---------------- Event Handlers ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    ping_self.start()
    auto_close_tickets.start()
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if not message.author.bot and message.channel.name.startswith("ticket-"):
        ticket_last_activity[message.channel.id] = datetime.datetime.utcnow()
    await bot.process_commands(message)

# ---------------- Start ----------------
keep_alive()
bot.run(TOKEN)
