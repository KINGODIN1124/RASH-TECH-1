import os
import json
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from datetime import datetime, timedelta
from flask import Flask
import threading
import requests

# ---------- FLASK SERVER FOR SELF-PING ----------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def self_ping():
    while True:
        try:
            requests.get(os.getenv("SELF_PING_URL"))
        except Exception:
            pass

# ---------- DISCORD BOT SETUP ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)
COOLDOWN_HOURS = 24

# Load apps from JSON
def load_apps():
    if not os.path.exists("apps.json"):
        with open("apps.json", "w") as f:
            json.dump({}, f)
    with open("apps.json", "r") as f:
        return json.load(f)

def save_apps(apps):
    with open("apps.json", "w") as f:
        json.dump(apps, f, indent=4)

apps_data = load_apps()
user_cooldowns = {}

# ---------- VIEWS ----------
class AppSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=app,
                description=f"Access the {app} premium app",
                emoji=apps_data[app]["emoji"]
            ) for app in apps_data
        ]
        super().__init__(placeholder="Choose a premium app...", options=options)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        join_duration = datetime.utcnow() - user.joined_at
        if join_duration < timedelta(hours=24):
            await interaction.response.send_message(
                f"❌ You must be at least 24 hours in this server before accessing premium apps.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📸 Please send a screenshot showing your YouTube subscription to our channel. "
            "Once verified, you’ll receive the link!",
            ephemeral=True
        )

        # Log that user selected app
        print(f"{user} selected {self.values[0]}")

class AppSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AppSelect())

# ---------- COMMANDS ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Sync error: {e}")

# /ticket command
@bot.tree.command(name="ticket", description="Create a support ticket")
async def ticket(interaction: discord.Interaction):
    user = interaction.user
    now = datetime.utcnow()
    if user.id in user_cooldowns:
        if now < user_cooldowns[user.id]:
            remaining = user_cooldowns[user.id] - now
            await interaction.response.send_message(
                f"⏳ You must wait {int(remaining.total_seconds()//3600)} hours before creating another ticket.",
                ephemeral=True
            )
            return

    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    ticket_channel = await guild.create_text_channel(
        name=f"ticket-{user.name}",
        overwrites=overwrites,
        category=None
    )

    embed = discord.Embed(
        title=f"🎟️ Hello {user.name}, welcome to Rash Tech Support!",
        description=(
            "We’re happy to have you here!\n\n"
            "**About Us:** Rash Tech offers premium app support and help with your favorite tools.\n\n"
            "Below is a list of available premium apps you can explore:\n"
            "🧩 *New premium apps are added soon!*\n\n"
            "Please select the app you’re interested in below 👇"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Rash Tech • Premium Support")

    await ticket_channel.send(embed=embed, view=AppSelectView())
    await interaction.response.send_message(
        f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True
    )

    user_cooldowns[user.id] = now + timedelta(hours=COOLDOWN_HOURS)

# Admin command to add new apps
@bot.tree.command(name="addapp", description="Add a new premium app (Admin only)")
@app_commands.describe(name="App name", emoji="App emoji", link="Premium link")
async def addapp(interaction: discord.Interaction, name: str, emoji: str, link: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an admin to use this command.", ephemeral=True)
        return

    apps_data[name] = {"emoji": emoji, "link": link}
    save_apps(apps_data)
    await interaction.response.send_message(f"✅ Added new app: {emoji} {name}", ephemeral=True)

# Admin command to reload app list
@bot.tree.command(name="reloadapps", description="Reload premium apps from JSON file (Admin only)")
async def reloadapps(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    global apps_data
    apps_data = load_apps()
    await interaction.response.send_message("🔁 Reloaded app list successfully!", ephemeral=True)

# ---------- RUN ----------
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(os.getenv("TOKEN"))
