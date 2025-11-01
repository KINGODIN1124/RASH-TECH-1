import os, discord, datetime, asyncio, random, threading, requests
from discord.ext import commands, tasks
from discord import app_commands, ui
from flask import Flask

# ================= FLASK KEEP-ALIVE =================
app = Flask(__name__)
@app.route('/')
def home(): return "✅ Bot is running!"

def run_flask(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): threading.Thread(target=run_flask).start()

# ================= BOT SETUP =================
TOKEN = os.getenv("TOKEN")
SELF_PING_URL = os.getenv("SELF_PING_URL")
LOG_CHANNEL_ID = 1434241829733404692  # change
MOD_ROLE_ID = 987654321098765432     # change

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
bot = commands.Bot(command_prefix="/", intents=intents)

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

# ================= SELF PING =================
@tasks.loop(minutes=5)
async def ping_self():
    if SELF_PING_URL:
        try: requests.get(SELF_PING_URL)
        except Exception: pass

# ================= QUERY DROPDOWN =================
class QuerySelect(ui.Select):
    def __init__(self, tier):
        self.tier = tier
        options = [
            discord.SelectOption(label="Related to Premium Apps", emoji="💎", value="premium"),
            discord.SelectOption(label="Other Query", emoji="❓", value="other")
        ]
        super().__init__(placeholder="Select your query type…", options=options)
    async def callback(self, interaction):
        ticket_last_activity[interaction.channel.id] = datetime.datetime.utcnow()
        if self.tier in ("tier1", "tier2"):
            msg = "💎 Premium issue — please confirm your account info." if self.values[0] == "premium" else "❓ Please describe your issue — I’ll assist you."
            await interaction.response.send_message(embed=discord.Embed(title="🤖 Bot Response", description=msg, color=discord.Color.green()))
        else:
            mod_role = interaction.guild.get_role(MOD_ROLE_ID)
            await interaction.response.send_message(embed=discord.Embed(title="🚨 Moderator Alert", description=f"{mod_role.mention} — assist {interaction.user.mention} (Tier 3).", color=discord.Color.red()))

class QueryView(ui.View):
    def __init__(self, tier): super().__init__(timeout=None); self.add_item(QuerySelect(tier))

# ================= TICKET CREATION =================
async def create_ticket_channel(interaction, tier):
    guild = interaction.guild
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAMES[tier]) or await guild.create_category(TICKET_CATEGORY_NAMES[tier])
    channel = await category.create_text_channel(f"ticket-{interaction.user.name}-{random.randint(100,999)}")
    await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
    await channel.set_permissions(guild.default_role, read_messages=False)
    ticket_last_activity[channel.id] = datetime.datetime.utcnow()
    async with channel.typing(): await asyncio.sleep(1.5)
    await channel.send(embed=discord.Embed(title=f"{TIER_EMOJIS[tier]} Ticket Created", description=f"Hello {interaction.user.mention}, how may I help you today?", color=discord.Color.blurple()), view=QueryView(tier))
    await channel.send(embed=discord.Embed(description="Use the button below to close this ticket.", color=discord.Color.greyple()), view=CloseTicketView(interaction.user))
    await interaction.followup.send(embed=discord.Embed(title="✅ Ticket Created", description=f"{TIER_EMOJIS[tier]} Your {tier.title()} ticket: {channel.mention}", color=discord.Color.green()), ephemeral=True)

# ================= TIER SELECT =================
class TierSelect(ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label="Tier 1", emoji="🟢", value="tier1"),
                   discord.SelectOption(label="Tier 2", emoji="🟡", value="tier2"),
                   discord.SelectOption(label="Tier 3", emoji="🔴", value="tier3")]
        super().__init__(placeholder="Select your support tier…", options=options)
    async def callback(self, interaction):
        user_id = interaction.user.id
        now = datetime.datetime.utcnow()
        if user_id in user_cooldowns and (remaining := user_cooldowns[user_id] - now).total_seconds() > 0:
            h, m = int(remaining.total_seconds() // 3600), int((remaining.total_seconds() % 3600) // 60)
            return await interaction.response.send_message(embed=discord.Embed(title="⏳ Cooldown Active", description=f"Wait **{h}h {m}m** to open another ticket.", color=discord.Color.orange()), ephemeral=True)
        user_cooldowns[user_id] = now + datetime.timedelta(hours=COOLDOWN_HOURS)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await asyncio.sleep(2)
        await create_ticket_channel(interaction, self.values[0])

class TierSelectView(ui.View):
    def __init__(self): super().__init__(timeout=60); self.add_item(TierSelect())

# ================= CLOSE & FEEDBACK =================
class CloseTicketView(ui.View):
    def __init__(self, user): super().__init__(timeout=None); self.user = user
    @ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger)
    async def close(self, interaction, _):
        if interaction.user != self.user:
            return await interaction.response.send_message(embed=discord.Embed(title="❌ Not Allowed", color=discord.Color.red()), ephemeral=True)
        await interaction.response.defer(); await close_ticket(interaction.channel, interaction.user)

class FeedbackView(ui.View):
    def __init__(self, user): super().__init__(timeout=60); self.user = user
    @ui.button(label="⭐", style=discord.ButtonStyle.secondary)
    @ui.button(label="⭐⭐⭐", style=discord.ButtonStyle.secondary)
    @ui.button(label="⭐⭐⭐⭐⭐", style=discord.ButtonStyle.success)
    async def rate(self, interaction, button):
        if interaction.user != self.user:
            return await interaction.response.send_message(embed=discord.Embed(title="❌ Not Your Ticket", color=discord.Color.red()), ephemeral=True)
        if (log := bot.get_channel(LOG_CHANNEL_ID)): await log.send(f"{interaction.user} rated {button.label}")
        await interaction.response.send_message(embed=discord.Embed(title="✅ Thanks!", description="Feedback saved.", color=discord.Color.green()), ephemeral=True)

async def close_ticket(channel, user):
    msgs = [f"[{m.created_at}] {m.author}: {m.content}" async for m in channel.history(limit=None)]
    transcript = "\n".join(msgs[::-1]) or "No messages."
    if (log := bot.get_channel(LOG_CHANNEL_ID)): await log.send(f"📜 Transcript for {channel.name}:\n```{transcript[:1900]}```")
    await channel.send(embed=discord.Embed(title="⭐ Rate Support", description="Rate 1–5 stars:", color=discord.Color.gold()), view=FeedbackView(user))
    await asyncio.sleep(30); await channel.delete()

# ================= USER COMMANDS =================
@bot.tree.command(name="ticket", description="Create a support ticket")
async def ticket(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=discord.Embed(title="🎟️ Create Ticket", description="Choose your support tier:", color=discord.Color.blurple()), view=TierSelectView(), ephemeral=True)

# ================= AUTO CLOSE =================
@tasks.loop(minutes=10)
async def auto_close_tickets():
    now = datetime.datetime.utcnow()
    for cid, last in list(ticket_last_activity.items()):
        if (now - last).total_seconds() > INACTIVITY_LIMIT:
            if (ch := bot.get_channel(cid)):
                await ch.send(embed=discord.Embed(title="⏰ Auto-Close", description="This ticket was inactive for 2 hours and is now closed.", color=discord.Color.red()))
                await asyncio.sleep(5); await ch.delete()
            ticket_last_activity.pop(cid, None)

# ================= ADMIN COMMANDS =================
@bot.tree.command(name="admin_panel", description="⚙️ Open Admin Control Panel")
@app_commands.checks.has_permissions(administrator=True)
async def admin_panel(interaction: discord.Interaction):
    view = AdminPanelView()
    embed = discord.Embed(
        title="🛠 Admin Control Panel",
        description="Manage tickets easily using the buttons below.",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class AdminPanelView(ui.View):
    def __init__(self): super().__init__(timeout=None)
    @ui.button(label="📋 List Tickets", style=discord.ButtonStyle.primary)
    async def list(self, interaction, _):
        em = discord.Embed(title="🎟 Active Tickets", color=discord.Color.blurple())
        for cat in interaction.guild.categories:
            if any(k in cat.name for k in TICKET_CATEGORY_NAMES.values()):
                for ch in cat.channels: em.add_field(name=f"#{ch.name}", value=f"ID: {ch.id}", inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)
    @ui.button(label="🧹 Purge Tickets", style=discord.ButtonStyle.danger)
    async def purge(self, interaction, _):
        for cat in interaction.guild.categories:
            if any(k in cat.name for k in TICKET_CATEGORY_NAMES.values()):
                for ch in list(cat.channels): await ch.delete()
        await interaction.response.send_message(embed=discord.Embed(title="✅ All tickets deleted.", color=discord.Color.green()), ephemeral=True)
    @ui.button(label="🔁 Reset All Cooldowns", style=discord.ButtonStyle.secondary)
    async def resetcd(self, interaction, _):
        user_cooldowns.clear()
        await interaction.response.send_message(embed=discord.Embed(title="✅ All cooldowns reset.", color=discord.Color.green()), ephemeral=True)
    @ui.button(label="📢 Broadcast", style=discord.ButtonStyle.success)
    async def broadcast(self, interaction, _):
        await interaction.response.send_message("💬 Enter the broadcast message:", ephemeral=True)
        def check(m): return m.author == interaction.user
        msg = await bot.wait_for("message", check=check)
        sent = 0
        for cid in ticket_last_activity:
            if (ch := bot.get_channel(cid)): await ch.send(embed=discord.Embed(title="📢 Admin Broadcast", description=msg.content, color=discord.Color.gold())); sent += 1
        await interaction.followup.send(embed=discord.Embed(title="✅ Broadcast Complete", description=f"Sent to {sent} tickets.", color=discord.Color.green()), ephemeral=True)

# ================= EVENTS =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    ping_self.start(); auto_close_tickets.start()
    await bot.change_presence(activity=discord.Game("🎟 /ticket | /admin_panel"))
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(msg):
    if not msg.author.bot and msg.channel.name.startswith("ticket-"):
        ticket_last_activity[msg.channel.id] = datetime.datetime.utcnow()
    await bot.process_commands(msg)

# ================= RUN =================
keep_alive()
bot.run(TOKEN)
