import os
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from flask import Flask
import threading, asyncio, datetime, requests, random

# ---------------- Flask Keep-Alive ----------------
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

# ---------------- Discord Setup ----------------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)
TOKEN = os.getenv("TOKEN")
SELF_PING_URL = os.getenv("SELF_PING_URL")
LOG_CHANNEL_ID = 1434241829733404692      # change this
MOD_ROLE_ID   = 987654321098765432       # change this

COOLDOWN_HOURS = 24
INACTIVITY_LIMIT = 60 * 60 * 2
user_cooldowns = {}
ticket_last_activity = {}

TICKET_CATEGORY_NAMES = {
    "tier1": "🎫│Tier 1 Support",
    "tier2": "🛠│Tier 2 Support",
    "tier3": "🚨│Tier 3 Support"
}
TIER_EMOJIS = {"tier1": "🟢", "tier2": "🟡", "tier3": "🔴"}

# ---------------- Self Ping ----------------
@tasks.loop(minutes=5)
async def ping_self():
    if SELF_PING_URL:
        try:
            requests.get(SELF_PING_URL)
        except Exception:
            pass

# ---------------- Query Dropdown ----------------
class QuerySelect(ui.Select):
    def __init__(self, tier: str):
        self.tier = tier
        options = [
            discord.SelectOption(label="Related to Premium Apps", emoji="💎", value="premium"),
            discord.SelectOption(label="Other Query", emoji="❓", value="other")
        ]
        super().__init__(placeholder="Select your query type…", options=options)

    async def callback(self, interaction: discord.Interaction):
        ticket_last_activity[interaction.channel.id] = datetime.datetime.utcnow()

        if self.tier in ("tier1", "tier2"):
            if self.values[0] == "premium":
                msg = "💎 For Premium Apps: Please make sure your account is linked and active."
            else:
                msg = "❓ Please describe your issue — I’ll try to assist you here!"
            embed = discord.Embed(title="🤖 Bot Response", description=msg, color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
        else:
            mod_role = interaction.guild.get_role(MOD_ROLE_ID)
            embed = discord.Embed(
                title="🚨 Moderator Alert",
                description=f"{mod_role.mention} — please assist {interaction.user.mention} (Tier 3 ticket).",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            await interaction.channel.send(embed=embed)

class QueryView(ui.View):
    def __init__(self, tier: str):
        super().__init__(timeout=None)
        self.add_item(QuerySelect(tier))

# ---------------- Ticket Creation ----------------
async def create_ticket_channel(interaction, tier: str):
    guild = interaction.guild
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAMES[tier])
    if not category:
        category = await guild.create_category(TICKET_CATEGORY_NAMES[tier])

    channel_name = f"ticket-{interaction.user.name}-{random.randint(100,999)}"
    channel = await category.create_text_channel(
        channel_name, topic=f"{interaction.user} [{tier}]"
    )
    await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
    await channel.set_permissions(guild.default_role, read_messages=False)
    ticket_last_activity[channel.id] = datetime.datetime.utcnow()

    # Simulate typing animation
    async with channel.typing():
        await asyncio.sleep(1.5)

    embed = discord.Embed(
        title=f"{TIER_EMOJIS[tier]} Ticket Created",
        description=f"Hello {interaction.user.mention}, how may I help you today?",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.utcnow(),
    )
    embed.set_footer(text="Support System | Select query below 👇")
    await channel.send(embed=embed, view=QueryView(tier))

    await channel.send(
        embed=discord.Embed(
            description="Use the button below to close this ticket when resolved.",
            color=discord.Color.greyple(),
        ),
        view=CloseTicketView(interaction.user)
    )

    confirm = discord.Embed(
        title="✅ Ticket Created",
        description=f"{TIER_EMOJIS[tier]} Your **{tier.title()}** ticket: {channel.mention}",
        color=discord.Color.green(),
    )
    await interaction.followup.send(embed=confirm, ephemeral=True)

# ---------------- Tier Selection with Cooldown ----------------
class TierSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Tier 1 (Basic)", emoji="🟢", value="tier1"),
            discord.SelectOption(label="Tier 2 (Advanced)", emoji="🟡", value="tier2"),
            discord.SelectOption(label="Tier 3 (Critical)", emoji="🔴", value="tier3"),
        ]
        super().__init__(placeholder="Select Support Tier …", options=options)

    async def callback(self, interaction):
        user_id = interaction.user.id
        now = datetime.datetime.utcnow()

        # Check cooldown
        if user_id in user_cooldowns:
            remaining = user_cooldowns[user_id] - now
            if remaining.total_seconds() > 0:
                hrs = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                cooldown_embed = discord.Embed(
                    title="⏳ Cooldown Active",
                    description=f"You can open another ticket in **{hrs}h {mins}m**.",
                    color=discord.Color.orange(),
                )
                await interaction.response.send_message(embed=cooldown_embed, ephemeral=True)
                return

        # Apply cooldown immediately
        user_cooldowns[user_id] = now + datetime.timedelta(hours=COOLDOWN_HOURS)

        # Typing / delay animation
        await interaction.response.defer(ephemeral=True, thinking=True)
        thinking_embed = discord.Embed(
            title="🎟️ Creating Ticket...",
            description="Please wait a moment while I set up your ticket channel.",
            color=discord.Color.blurple(),
        )
        await asyncio.sleep(1.5)
        await interaction.followup.send(embed=thinking_embed, ephemeral=True)
        await asyncio.sleep(2)

        await create_ticket_channel(interaction, self.values[0])

class TierSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TierSelect())

# ---------------- Close + Feedback ----------------
class CloseTicketView(ui.View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger)
    async def close(self, interaction, _):
        if interaction.user != self.user:
            em = discord.Embed(
                title="❌ Not Allowed",
                description="Only the ticket creator may close it.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=em, ephemeral=True)
            return
        await interaction.response.defer()
        await close_ticket(interaction.channel, interaction.user)

class FeedbackView(ui.View):
    def __init__(self, user):
        super().__init__(timeout=60)
        self.user = user

    @ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    @ui.button(label="⭐⭐", style=discord.ButtonStyle.secondary)
    @ui.button(label="⭐⭐⭐", style=discord.ButtonStyle.secondary)
    @ui.button(label="⭐⭐⭐⭐", style=discord.ButtonStyle.success)
    @ui.button(label="⭐⭐⭐⭐⭐", style=discord.ButtonStyle.success)
    async def rate(self, interaction, button):
        if interaction.user != self.user:
            return await interaction.response.send_message(
                embed=discord.Embed(title="❌ Not Your Ticket", color=discord.Color.red()), ephemeral=True
            )
        log = bot.get_channel(LOG_CHANNEL_ID)
        if log:
            await log.send(f"{interaction.user} rated {button.label}")
        await interaction.response.send_message(
            embed=discord.Embed(title="✅ Thanks!", description="Feedback saved.", color=discord.Color.green()),
            ephemeral=True,
        )

async def close_ticket(channel, user):
    messages = [f"[{m.created_at}] {m.author}: {m.content}" async for m in channel.history(limit=None)]
    transcript = "\n".join(messages[::-1]) or "No messages."
    log = bot.get_channel(LOG_CHANNEL_ID)
    if log:
        await log.send(f"📜 Transcript for {channel.name}:\n```{transcript[:1900]}```")

    fb = discord.Embed(title="⭐ Rate Support", description="Rate 1–5 stars:", color=discord.Color.gold())
    await channel.send(embed=fb, view=FeedbackView(user))
    await asyncio.sleep(30)
    await channel.delete()

# ---------------- Slash Command ----------------
@bot.tree.command(name="ticket", description="Create a support ticket")
async def ticket(interaction: discord.Interaction):
    view = TierSelectView()
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="🎟️ Create Ticket",
        description="Choose your support tier below to open a ticket.",
        color=discord.Color.blurple(),
    )
    msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    view.message = msg

# ---------------- Auto-Close Inactive ----------------
@tasks.loop(minutes=10)
async def auto_close_tickets():
    now = datetime.datetime.utcnow()
    for cid, last in list(ticket_last_activity.items()):
        if (now - last).total_seconds() > INACTIVITY_LIMIT:
            ch = bot.get_channel(cid)
            if ch:
                await ch.send(
                    embed=discord.Embed(
                        title="⏰ Auto-Close",
                        description="This ticket was inactive for 2 hours and is now closed.",
                        color=discord.Color.red(),
                    )
                )
                await asyncio.sleep(5)
                await ch.delete()
            ticket_last_activity.pop(cid, None)

# ---------------- Events ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    ping_self.start()
    auto_close_tickets.start()
    print(f"✅ Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game("🎟 /ticket for support"))

@bot.event
async def on_message(msg):
    if not msg.author.bot and msg.channel.name.startswith("ticket-"):
        ticket_last_activity[msg.channel.id] = datetime.datetime.utcnow()
    await bot.process_commands(msg)

# ---------------- Run ----------------
keep_alive()
bot.run(TOKEN)
