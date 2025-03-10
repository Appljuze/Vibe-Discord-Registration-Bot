import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle
import sqlite3
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import nest_asyncio
from typing import Optional
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import json
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import contextmanager

class RegistrationModal(ui.Modal, title='Register Your Vibe Account'):
    account_id = ui.TextInput(
        label='Vibe Account ID',
        placeholder='Enter your Vibe Account ID...',
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            account_id = str(self.account_id)
            
            with get_db() as conn:
                c = conn.cursor()
                
                # Check if this Vibe Account ID is already registered to another user
                existing_user_check = c.execute(
                    'SELECT discord_id FROM users WHERE account_id = ?', 
                    (account_id,)
                ).fetchone()
                
                if existing_user_check and str(existing_user_check[0]) != str(interaction.user.id):
                    embed = discord.Embed(
                        title="❌ Registration Error",
                        description="This Vibe Account ID is already registered to another Discord account.",
                        color=discord.Color.blue()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Check if this user already has a registered Vibe Account ID
                existing_user = c.execute(
                    'SELECT account_id FROM users WHERE discord_id = ?', 
                    (str(interaction.user.id),)
                ).fetchone()
                
                if existing_user and existing_user[0] == account_id:
                    embed = discord.Embed(
                        title="❌ Registration Error",
                        description="This Vibe Account ID is already registered to your Discord account.",
                        color=discord.Color.blue()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                if existing_user:
                    old_account_id = existing_user[0]
                    update_message = f"Your Vibe Account ID has been updated. Previous ID: {old_account_id}"
                    
                    c.execute(
                        'UPDATE users SET account_id = ?, last_updated = CURRENT_TIMESTAMP WHERE discord_id = ?',
                        (account_id, str(interaction.user.id))
                    )
                else:
                    c.execute(
                        'INSERT INTO users (discord_id, account_id) VALUES (?, ?)',
                        (str(interaction.user.id), account_id)
                    )
                
                c.execute(
                    'INSERT INTO audit_log (action, discord_id, details) VALUES (?, ?, ?)',
                    ('register', str(interaction.user.id), f'Updated Vibe Account ID: {account_id}')
                )
                
                conn.commit()
                
                if existing_user:
                    embed = discord.Embed(
                        title="🔄 Registration Updated",
                        description=update_message,
                        color=discord.Color.blue()
                    )
                else:
                    embed = discord.Embed(
                    title="✅ Registration Successful",
                    description=f"You have successfully linked Vibe Account **{account_id}** to this Discord account!",
                    color=discord.Color.blue()
                )
                
                embed.add_field(name="Registered Vibe Account ID", value=account_id, inline=False)
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in registration modal: {str(e)}", exc_info=True)
            embed = discord.Embed(
                title="❌ Registration Error",
                description="An unexpected error occurred during registration.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

# Create the Enter ID view
class EnterIDView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)  # 5-minute timeout
    
    @discord.ui.button(label="Enter Vibe Account ID", style=ButtonStyle.success)
    async def enter_id_button(self, interaction: discord.Interaction, button: ui.Button):
        # Open the registration modal
        await interaction.response.send_modal(RegistrationModal())

# Create the Update ID view for registered users
class UpdateIDView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)  # 5-minute timeout
    
    @discord.ui.button(label="🔄 Update ID", style=ButtonStyle.primary)
    async def update_id_button(self, interaction: discord.Interaction, button: ui.Button):
        # Open the registration modal for ID update
        await interaction.response.send_modal(RegistrationModal())

class RegistrationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent buttons
    
    @discord.ui.button(label="Register", style=ButtonStyle.primary)
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            # First check if user is already registered
            with get_db() as conn:
                c = conn.cursor()
                
                user_details = c.execute(
                    'SELECT account_id, timestamp, last_updated FROM users WHERE discord_id = ?', 
                    (str(interaction.user.id),)
                ).fetchone()
            
            if user_details:
                # User is already registered, show profile with Update ID button
                account_id, timestamp, last_updated = user_details
                
                embed = discord.Embed(
                    title="Profile Details",
                    description="✅ You are already registered! \n\n🔄 Use the **Update ID** button below if you want to link to a different Vibe Account ID.",
                    color=discord.Color.blue()
                )
                
                embed.set_author(
                    name=interaction.user.name,
                    icon_url=interaction.user.avatar.url if interaction.user.avatar else None
                )
                
                embed.add_field(
                    name="Vibe Account ID",
                    value=account_id,
                    inline=False
                )
                
                embed.add_field(
                    name="Registration Date",
                    value=timestamp if timestamp else "Unknown",
                    inline=False
                )
                
                if last_updated and last_updated != timestamp:
                    embed.add_field(
                        name="Last Updated",
                        value=last_updated,
                        inline=False
                    )
                
                # Create UpdateIDView with Update ID button
                update_view = UpdateIDView()
                
                await interaction.response.send_message(embed=embed, view=update_view, ephemeral=True)
                return
            
            # If not registered, show registration info with image and "Enter ID" button
            embed = discord.Embed(
                title="Register Your Vibe Account",
                description="Start earning daily community points by connecting your Discord account to your Vibe account!\n",
                color=discord.Color.blue()
            )

            # Add prompt to enter ID
            embed.add_field( 
                name="__How to Register__",
                value="",
                inline=False
            )

            # Add prompt to enter ID
            embed.add_field( 
                name="1️⃣ Locate your Vibe Account ID (check screenshot below)",
                value="",
                inline=False
            )

            # Add prompt to enter ID
            embed.add_field( 
                name="2️⃣ Click the green button below and enter your ID 👇\n▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁",
                value="",
                inline=False
            )

            # Add account creation info
            embed.add_field(
                name="Don't Have a Vibe account yet?",
                value="You can create one at https://vibe.trading/",
                inline=False
            )    
            
            # Add image showing where to find ID
            account_id_image = os.getenv('ACCOUNT_ID_IMAGE_URL')
            if account_id_image:
                embed.set_image(url=account_id_image)
            
            # Create view with Enter ID button
            enter_id_view = EnterIDView()
            
            # Send as ephemeral message
            await interaction.response.send_message(embed=embed, view=enter_id_view, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in register button: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "An error occurred. Please try again later.",
                ephemeral=True
            )
    
    @discord.ui.button(label="Verify", style=ButtonStyle.secondary)
    async def verify_button(self, interaction: discord.Interaction, button: ui.Button):
        # Reuse check command logic
        try:
            with get_db() as conn:
                c = conn.cursor()
                
                user_details = c.execute(
                    'SELECT account_id, timestamp, last_updated FROM users WHERE discord_id = ?', 
                    (str(interaction.user.id),)
                ).fetchone()
                
                if not user_details:
                    embed = discord.Embed(
                        title="Profile Not Found",
                        description="You haven't registered your Vibe Account ID yet. Click the Register button to add your Vibe Account ID.",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                account_id, timestamp, last_updated = user_details
                
                embed = discord.Embed(
                    title="Profile Details",
                    description="✅ You are registered!",
                    color=discord.Color.blue()
                )
                
                embed.set_author(
                    name=interaction.user.name,
                    icon_url=interaction.user.avatar.url if interaction.user.avatar else None
                )
                
                embed.add_field(
                    name="Vibe Account ID",
                    value=account_id,
                    inline=False
                )
                
                embed.add_field(
                    name="Registration Date",
                    value=timestamp if timestamp else "Unknown",
                    inline=False
                )
                
                if last_updated and last_updated != timestamp:
                    embed.add_field(
                        name="Last Updated",
                        value=last_updated,
                        inline=False
                    )
                
                # Get user's roles
                roles = [role.name for role in interaction.user.roles if role.name != "@everyone"]
                
                embed.add_field(
                    name="📋 Discord Roles", 
                    value="\n".join(roles) if roles else "No roles", 
                    inline=False
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error in verify button: {str(e)}", exc_info=True)
            error_embed = discord.Embed(
                title="Error",
                description="An error occurred while retrieving your details.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            
# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
handler = RotatingFileHandler('bot.log', maxBytes=10000000, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Initialize FastAPI with rate limiting
app = FastAPI(title="Discord Role API", version="1.0.0")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=json.loads(os.getenv('ALLOWED_ORIGINS', '["*"]')),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key security
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def get_api_key(api_key_header: str = Depends(api_key_header)):
    expected_key = os.getenv('API_KEY')
    if not expected_key:
        logger.error("API_KEY not set in environment variables")
        raise HTTPException(
            status_code=500,
            detail="Server configuration error"
        )
    
    if not api_key_header or api_key_header != expected_key:
        logger.warning(f"Invalid API key attempt: {api_key_header[:10]}...")
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key"
        )
    return api_key_header

# Database context manager
@contextmanager
def get_db():
    conn = sqlite3.connect('user_registry.db')
    try:
        yield conn
    finally:
        conn.close()

# Enhanced database setup
def setup_database():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                account_id TEXT UNIQUE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add index for faster queries
        c.execute('CREATE INDEX IF NOT EXISTS idx_account_id ON users(account_id)')
        
        # Add audit log table
        c.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                discord_id TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

# Discord bot setup with enhanced intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Enable member intents
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.tree.command(name="register", description="Register your Vibe Account ID")
async def register(interaction: discord.Interaction, account_id: str):
    """Register a user's Vibe Account ID"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            
            # Check if this Vibe Account ID is already registered to another user
            existing_account = c.execute(
                'SELECT discord_id FROM users WHERE account_id = ?', 
                (account_id,)
            ).fetchone()
            
            if existing_account and str(existing_account[0]) != str(interaction.user.id):
                embed = discord.Embed(
                    title="❌ Registration Error",
                    description="This Vibe Account ID is already registered to another Discord account.",
                    color=discord.Color.blue()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user exists
            existing_user = c.execute(
                'SELECT account_id FROM users WHERE discord_id = ?', 
                (str(interaction.user.id),)
            ).fetchone()
            
            if existing_user:
                old_account_id = existing_user[0]
                update_message = f"Your Vibe Account ID has been updated. Previous ID: {old_account_id}"
                
                # Update existing user
                c.execute(
                    'UPDATE users SET account_id = ?, last_updated = CURRENT_TIMESTAMP WHERE discord_id = ?',
                    (account_id, str(interaction.user.id))
                )
            else:
                # Insert new user
                c.execute(
                    'INSERT INTO users (discord_id, account_id) VALUES (?, ?)',
                    (str(interaction.user.id), account_id)
                )
            
            # Log the action
            c.execute(
                'INSERT INTO audit_log (action, discord_id, details) VALUES (?, ?, ?)',
                ('register', str(interaction.user.id), f'Updated Vibe Account ID: {account_id}')
            )
            
            conn.commit()
            
            # Create response embed
            if existing_user:
                embed = discord.Embed(
                    title="🔄 Registration Updated",
                    description=update_message,
                    color=discord.Color.blue()
                )
            else:
                embed = discord.Embed(
                    title="✅ Registration Successful",
                    description=f"You have successfully linked Vibe Account **{account_id}** to this Discord account!",
                    color=discord.Color.blue()
                )
            
            embed.add_field(name="Registered Vibe Account ID", value=account_id, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"User {interaction.user.id} registered Vibe Account ID: {account_id}")
    
    except Exception as e:
        logger.error(f"Error in register command: {str(e)}", exc_info=True)
        embed = discord.Embed(
            title="❌ Registration Error",
            description="An unexpected error occurred during registration.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="check", description="Check your registered Vibe Account ID")
async def check(interaction: discord.Interaction):
    """Let users check their registered profile details"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            
            # Get user's registration details
            user_details = c.execute(
                'SELECT account_id, timestamp, last_updated FROM users WHERE discord_id = ?', 
                (str(interaction.user.id),)
            ).fetchone()
            
            if not user_details:
                embed = discord.Embed(
                    title="Profile Not Found",
                    description="You haven't registered your Vibe Account ID yet. Use /register to add your Vibe Account ID.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            account_id, timestamp, last_updated = user_details
            
            # Create embed
            embed = discord.Embed(
                title="Profile Details",
                color=discord.Color.blue()
            )
            
            # Add user info to the top
            embed.set_author(
                name=interaction.user.name,
                icon_url=interaction.user.avatar.url if interaction.user.avatar else None
            )
            
            # Add field for Vibe Account ID
            embed.add_field(
                name="Vibe Account ID",
                value=account_id,
                inline=False
            )
            
            embed.add_field(
                name="Registration Date",
                value=timestamp if timestamp else "Unknown",
                inline=False
            )
            
            if last_updated and last_updated != timestamp:
                embed.add_field(
                    name="Last Updated",
                    value=last_updated,
                    inline=False
                )
            
            # Get user's roles
            roles = [role.name for role in interaction.user.roles if role.name != "@everyone"]
            
            embed.add_field(
                name="📋 Discord Roles", 
                value="\n".join(roles) if roles else "No roles", 
                inline=False
            )
            
            # Log the check action
            c.execute(
                'INSERT INTO audit_log (action, discord_id, details) VALUES (?, ?, ?)',
                ('check', str(interaction.user.id), 'User checked their profile details')
            )
            conn.commit()
            
            # Add the Update ID button for registered users
            update_view = UpdateIDView()
            await interaction.response.send_message(embed=embed, view=update_view, ephemeral=True)
            logger.info(f"User {interaction.user.id} checked their profile details")
            
    except Exception as e:
        logger.error(f"Error in check command: {str(e)}", exc_info=True)
        error_embed = discord.Embed(
            title="Error",
            description="An error occurred while retrieving your details.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed, ephemeral=True)

@bot.tree.command(name="search", description="Search for a user's registration details (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def search_user(interaction: discord.Interaction, user: discord.User):
    """
    Search for a user's registration details
    Requires administrator permissions
    """
    try:
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT account_id, timestamp, last_updated 
                FROM users 
                WHERE discord_id = ?
            ''', (str(user.id),))
            user_data = c.fetchone()
        
        if not user_data:
            await interaction.followup.send(f"🔍 {user.mention} is not registered in the database.", ephemeral=True)
            return
        
        # Fetch user's roles
        guild = interaction.guild
        try:
            member = await guild.fetch_member(user.id)
            roles = [role.name for role in member.roles if role.name != "@everyone"]
        except discord.NotFound:
            roles = ["User not in server"]
        except Exception as e:
            roles = ["Error fetching roles"]
            logger.error(f"Error fetching roles for {user.id}: {e}")
        
        account_id, timestamp, last_updated = user_data
        
        embed = discord.Embed(
            title=f"🔍 User Search Result for {user.name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(name="Discord ID", value=user.id, inline=False)
        embed.add_field(name="Username", value=user.name, inline=True)

        embed.add_field(
            name="📊 Registered Vibe Account ID", 
            value=account_id, 
            inline=False
        )
        
        embed.add_field(name="🕒 First Registered", value=timestamp, inline=True)
        embed.add_field(name="🔄 Last Updated", value=last_updated, inline=True)
        
        embed.add_field(
            name="📋 Discord Roles", 
            value="\n".join(roles) if roles else "No roles", 
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Admin {interaction.user.id} searched for user {user.id}")
    
    except Exception as e:
        logger.error(f"Error in search_user command: {str(e)}", exc_info=True)
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="users", description="List all registered users (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def list_users(interaction: discord.Interaction):
    """List all registered users with their Vibe Account IDs"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT discord_id, 
                       account_id,
                       timestamp 
                FROM users 
                ORDER BY timestamp DESC
            ''')
            users = c.fetchall()
        
        if not users:
            await interaction.followup.send("No users are currently registered.", ephemeral=True)
            return
        
        max_users_per_message = 20
        messages = []
        current_message = "🔍 **Registered Users** 🔍\n\n"
        current_message += "```\n"
        current_message += f"{'Username':<20} {'Vibe Account ID':<25} {'Registered On (UTC)'}\n"
        current_message += "-" * 80 + "\n"
        
        guild = interaction.guild
        
        for discord_id, account_id, timestamp in users:
            try:
                member = await guild.fetch_member(int(discord_id))
                username = member.name if member else "Unknown User"
            except discord.NotFound:
                username = "User Left Server"
            except Exception as e:
                username = "Fetch Error"
                logger.error(f"Error fetching user {discord_id}: {e}")
            
            truncated_username = (username[:17] + '...') if len(username) > 20 else username
            
            user_line = f"{truncated_username:<20} {account_id:<25} {timestamp}\n"
            
            if len(current_message + user_line) > 1900:
                current_message += "```"
                messages.append(current_message)
                current_message = "**Registered Users (continued)** 🔍\n\n"
                current_message += "```\n"
                current_message += f"{'Username':<20} {'Vibe Account ID':<25} {'Registered On'}\n"
                current_message += "-" * 80 + "\n"
            
            current_message += user_line
        
        current_message += "```"
        messages.append(current_message)
        
        for msg in messages:
            await interaction.followup.send(msg, ephemeral=True)
        
        logger.info(f"Admin {interaction.user.id} listed all registered users")
    
    except Exception as e:
        logger.error(f"Error in list_users command: {str(e)}", exc_info=True)
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="delete", description="Delete a user's registration (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def delete_user(interaction: discord.Interaction, user: discord.User):
    """Delete a user's registration from the database"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT account_id FROM users WHERE discord_id = ?', (str(user.id),))
            user_data = c.fetchone()
            
            if not user_data:
                await interaction.followup.send(
                    f"🔍 {user.mention} is not registered in the database.", 
                    ephemeral=True
                )
                return
            
            # Delete user from database
            c.execute('DELETE FROM users WHERE discord_id = ?', (str(user.id),))
            
            # Log the deletion in audit log
            c.execute(
                'INSERT INTO audit_log (action, discord_id, details) VALUES (?, ?, ?)',
                ('user_deletion', str(user.id), f'Deleted user: {user.name}')
            )
            
            conn.commit()
        
        # Prepare deletion message
        account_id = user_data[0]
        deletion_info = f"Vibe Account ID: {account_id}"
        
        embed = discord.Embed(
            title="👋 User Registration Deleted",
            description=f"Deleted registration for {user.mention}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Deleted Information", 
            value=deletion_info, 
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Admin {interaction.user.id} deleted registration for user {user.id}")
    
    except Exception as e:
        logger.error(f"Error in delete_user command: {str(e)}", exc_info=True)
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@app.get("/users/{account_id}")
@limiter.limit("1000/minute")
async def get_user_roles(
    request: Request,
    account_id: str,
    api_key: str = Depends(get_api_key)
):
    """Get Discord roles for a user by Vibe Account ID"""
    try:            
        with get_db() as conn:
            c = conn.cursor()
            
            c.execute('SELECT discord_id FROM users WHERE account_id = ?', (account_id,))
            
            result = c.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail="User not found")
            
            discord_id = result[0]
            
            # Get user's roles
            guild = bot.get_guild(int(os.getenv('GUILD_ID')))
            if not guild:
                raise HTTPException(status_code=404, detail="Guild not found")
            
            # Use run_coroutine_threadsafe for the fetch_member call
            member = asyncio.run_coroutine_threadsafe(
                guild.fetch_member(int(discord_id)),
                bot.loop
            ).result()
            
            if not member:
                raise HTTPException(status_code=404, detail="Member not found")
            
            roles = [role.name for role in member.roles if role.name != "@everyone"]
            
            # Log the API request
            c.execute(
                'INSERT INTO audit_log (action, discord_id, details) VALUES (?, ?, ?)',
                ('api_request', discord_id, f'Roles queried for {account_id}')
            )
            conn.commit()
            
            return {
                "discord_id": discord_id,
                "roles": roles,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    except Exception as e:
        logger.error(f"Error in get_user_roles: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/exists")
@limiter.limit("1000/minute")
async def check_user_existence(
    request: Request,
    account_id: str,
    api_key: str = Depends(get_api_key)
):
    """Check if a user exists in the database by Vibe Account ID"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            
            c.execute('SELECT COUNT(*) FROM users WHERE account_id = ?', (account_id,))
            
            result = c.fetchone()
            user_exists = result[0] > 0
            
            # Log the check
            c.execute(
                'INSERT INTO audit_log (action, details) VALUES (?, ?)',
                ('existence_check', f'Checked existence for: {account_id}')
            )
            conn.commit()
            
            return {
                "account_id": account_id,
                "registered_to_user": user_exists,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    except Exception as e:
        logger.error(f"Error in user existence check: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@bot.tree.command(name="setup", description="Setup the registration message in this channel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    """Setup the registration message with buttons"""
    try:
        embed = discord.Embed(
            title="Connect your Discord account to your Vibe account",
            description="Register your account to start earning Community Points.",
            color=discord.Color.blue()
        )
        
        # Check if setup image URL is set
        setup_image_url = os.getenv('SETUP_IMAGE_URL')
        if setup_image_url:
            embed.set_image(url=setup_image_url)
        else:
            logger.warning("SETUP_IMAGE_URL is not set in environment variables. Setup message will not have an image.")
        
        # Check if account ID image URL is set
        account_id_image = os.getenv('ACCOUNT_ID_IMAGE_URL')
        if not account_id_image:
            await interaction.response.send_message(
                "⚠️ Warning: ACCOUNT_ID_IMAGE_URL is not set in your environment variables. "
                "Users won't see an image guide when registering. "
                "Add this to your .env file to show an image.", 
                ephemeral=True
            )
            return
        
        view = RegistrationView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("Registration message has been set up!", ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in setup command: {str(e)}", exc_info=True)
        await interaction.response.send_message(
            "An error occurred while setting up the registration message.",
            ephemeral=True
        )

# Error handlers for admin commands
@search_user.error
@list_users.error
@delete_user.error
async def admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle permission errors for admin commands"""
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command. Administrator access required.", 
            ephemeral=True
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@bot.event
async def on_ready():
    try:
        logger.info(f'{bot.user} has connected to Discord!')
        logger.info(f'Bot ID: {bot.user.id}')
        
        # Print out all registered commands
        commands = await bot.tree.fetch_commands()
        logger.info("Registered Commands:")
        for cmd in commands:
            logger.info(f"- {cmd.name}: {cmd.description}")
        
        await bot.tree.sync()
        logger.info("Command tree synced")
        
    except Exception as e:
        logger.error(f"Error in on_ready event: {e}", exc_info=True)

async def run_bot():
    """Run the Discord bot"""
    try:
        await bot.start(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)

def run_api():
    """Run the FastAPI server"""
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv('PORT', '8000')),
        ssl_keyfile=os.getenv('SSL_KEYFILE'),
        ssl_certfile=os.getenv('SSL_CERTFILE')
    )

async def main():
    """Main function to run both bot and API"""
    setup_database()
    
    # Create task for API
    api_task = asyncio.create_task(
        asyncio.to_thread(run_api)
    )
    
    # Run both concurrently
    await asyncio.gather(
        run_bot(),
        api_task
    )

if __name__ == "__main__":
    asyncio.run(main())