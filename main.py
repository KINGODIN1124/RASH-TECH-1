import os
import json
import discord
from discord.ext import commands
from discord import app_commands, ui
from datetime import datetime, timedelta
from flask import Flask
import threading
import requests

# ---------- FLASK SERVER ----------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# ---------- DISCORD BOT ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
COOLDOWN_HOURS = 24

# ---------- APP STORAGE ----------
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
ticket_channels = []

# ---------- SELECT MENU ----------
class AppSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=app,
                description=f"Access {app} premium app",
                emoji=apps_data[app]["emoji"]
            ) for app in apps_data
        ]
        super().__init__(placeholder="Select a premium app...", options=options)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        join_duration = datetime.utcnow() - user.joined_at
        if join_duration < timedelta(hours=24):
            await interaction.response.send_message(
                "❌ You must be in this server for at least 24 hours to access premium apps.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📸 Please upload a screenshot showing your YouTube subscription. "
            "Once verified, you’ll get your premium link.",
            ephemeral=True
        )

class AppSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AppSelect())

# ---------- ADMIN PANEL ----------
class AdminPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🗑️ Close All Tickets", style=discord.ButtonStyle.danger)
    async def close_all(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You’re not an admin.", ephemeral=True)
            return
        count = 0
        for ch in list(ticket_channels):
            try:
                await ch.delete()
                count += 1
            except:
                pass
        ticket_channels.clear()
        await interaction.response.send_message(f"✅ Closed {count} ticket channels.", ephemeral=True)

    @ui.button(label="🔒 Close Current Ticket", style=discord.ButtonStyle.secondary)
    async def close_current(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You’re not an admin.", ephemeral=True)
            return
        channel = interaction.channel
        if channel in ticket_channels:
            await channel.delete()
            ticket_channels.remove(channel)
            await interaction.response.send_message("✅ Ticket closed.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ This isn’t a ticket channel.", ephemeral=True)

    @ui.button(label="♻️ Remove All Cooldowns", style=discord.ButtonStyle.success)
    async def remove_cooldowns(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You’re not an admin.", ephemeral=True)
            return
        user_cooldowns.clear()
        await interaction.response.send_message("✅ Removed all cooldowns.", ephemeral=True)

    @ui.button(label="🎫 Open Ticket (Admin)", style=discord.ButtonStyle.primary)
    async def open_ticket_admin(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You’re not an admin.", ephemeral=True)
            return
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        ticket_channel = await guild.create_text_channel(
            name=f"admin-ticket-{interaction.user.name}",
            overwrites=overwrites
        )
        ticket_channels.append(ticket_channel)
        embed = discord.Embed(
            title=f"🎟️ Admin Ticket Created",
            description="You can use this channel to manage or test ticket features.",
            color=discord.Color.gold()
        )
        await ticket_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Admin ticket created: {ticket_channel.mention}", ephemeral=True)

# ---------- BOT EVENTS ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced.")
    except Exception as e:
        print(f"Sync error: {e}")

# ---------- USER COMMANDS ----------
@bot.tree.command(name="ticket", description="Create a support ticket")
async def ticket(interaction: discord.Interaction):
    user = interaction.user
    now = datetime.utcnow()
    if user.id in user_cooldowns and now < user_cooldowns[user.id]:
        remaining = user_cooldowns[user.id] - now
        await interaction.response.send_message(
            f"⏳ You must wait {int(remaining.total_seconds() // 3600)} hours before creating another ticket.",
            ephemeral=True
        )
        return

    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    ticket_channel = await guild.create_text_channel(
        name=f"ticket-{user.name}",
        overwrites=overwrites
    )
    ticket_channels.append(ticket_channel)
    embed = discord.Embed(
        title=f"🎟️ Hello {user.name}, welcome to Rash Tech!",
        description=(
            "We’re glad to have you here!\n\n"
            "💬 How may I help you today?\n\n"
            "**About Rash Tech:**\nWe provide premium apps and exclusive tools.\n\n"
            "🧩 Below is the list of available premium apps.\n"
            "_More are coming soon!_"
        ),
        color=discord.Color.blue()
    )
    await ticket_channel.send(embed=embed, view=AppSelectView())
    await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)
    user_cooldowns[user.id] = now + timedelta(hours=COOLDOWN_HOURS)

# ---------- ADMIN COMMANDS ----------
@bot.tree.command(name="admin_panel", description="Open the admin control panel")
async def admin_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    embed = discord.Embed(
        title="⚙️ Rash Tech Admin Panel",
        description=(
            "Welcome to the **Rash Tech Ticket Admin Panel**.\n\n"
            "You can control all ticket actions from here:\n"
            "- 🗑️ Close all tickets\n"
            "- 🔒 Close current ticket\n"
            "- ♻️ Remove all cooldowns\n"
            "- 🎫 Open admin ticket\n\n"
            "_More controls coming soon!_"
        ),
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed, view=AdminPanelView(), ephemeral=True)

@bot.tree.command(name="addapp", description="Add a new premium app (Admin only)")
@app_commands.describe(name="App name", emoji="Emoji", link="App link")
async def addapp(interaction: discord.Interaction, name: str, emoji: str, link: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    apps_data[name] = {"emoji": emoji, "link": link}
    save_apps(apps_data)
    await interaction.response.send_message(f"✅ Added new app: {emoji} {name}", ephemeral=True)

@bot.tree.command(name="reloadapps", description="Reload apps from JSON file")
async def reloadapps(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    global apps_data
    apps_data = load_apps()
    await interaction.response.send_message("🔁 Reloaded app list.", ephemeral=True)

# ---------- RUN ----------
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(os.getenv("TOKEN"))
