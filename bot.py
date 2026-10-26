import logging
import os
import psycopg2
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Load configuration from Render environment variables
TOKEN = os.environ.get("8835811515:AAG5QxiaKuBDk6aivOnYAw3OD4CyPMdLyZk
")
DATABASE_URL = os.environ.get("postgresql://postgres:[YOUR-PASSWORD]@db.kmoiitbghivimjgrfxev.supabase.co:5432/postgres")

# Telegram User IDs of Bot Admins allowed to add/remove database entries
ADMIN_IDS = [@sulegsm]  # Replace with your Telegram User ID

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DATABASE SETUP (POSTGRESQL / SUPABASE) =================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            status TEXT CHECK(status IN ('SCAMMER', 'VERIFIED')),
            notes TEXT
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Database initialized successfully.")

def add_or_update_user(telegram_id, username, full_name, status, notes=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    if username:
        username = username.lstrip("@").lower()
    
    cursor.execute("""
        INSERT INTO users (telegram_id, username, full_name, status, notes)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (telegram_id) DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            status = EXCLUDED.status,
            notes = EXCLUDED.notes
    """, (telegram_id, username, full_name, status, notes))
    conn.commit()
    cursor.close()
    conn.close()

def search_user(identifier):
    conn = get_db_connection()
    cursor = conn.cursor()
    identifier_str = str(identifier).lstrip("@").strip()
    
    if identifier_str.isdigit():
        cursor.execute("SELECT telegram_id, username, full_name, status, notes FROM users WHERE telegram_id = %s", (int(identifier_str),))
    else:
        cursor.execute("SELECT telegram_id, username, full_name, status, notes FROM users WHERE LOWER(username) = LOWER(%s)", (identifier_str,))
        
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def delete_user(telegram_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE telegram_id = %s", (telegram_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return deleted

# ================= HELPER FUNCTIONS =================
def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def format_user_info(db_row):
    tg_id, username, full_name, status, notes = db_row
    username_str = f"@{username}" if username else "No username"
    
    if status == "SCAMMER":
        return (
            "🚨 **SCAMMER ALERT DETECTED!** 🚨\n\n"
            f"👤 **Name:** {full_name or 'N/A'}\n"
            f"🔗 **Username:** {username_str}\n"
            f"🆔 **Telegram ID:** `{tg_id}`\n"
            f"⚠️ **Status:** 🔴 **BLACK-LISTED SCAMMER**\n"
            f"📝 **Details/Notes:** {notes or 'No details provided'}\n\n"
            "⚠️ **Warning:** Do not conduct any transaction with this user!"
        )
    elif status == "VERIFIED":
        return (
            "✅ **VERIFIED USER** ✅\n\n"
            f"👤 **Name:** {full_name or 'N/A'}\n"
            f"🔗 **Username:** {username_str}\n"
            f"🆔 **Telegram ID:** `{tg_id}`\n"
            f"🛡️ **Status:** 🟢 **VERIFIED TRUSTED USER**\n"
            f"📝 **Details/Notes:** {notes or 'Verified user'}"
        )

# ================= EVENT HANDLERS =================

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
            
        row = search_user(member.id) or (search_user(member.username) if member.username else None)
        
        if row and row[3] == "SCAMMER":
            msg = format_user_info(row)
            await update.message.reply_text(msg, parse_mode="Markdown")
            
            try:
                await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=member.id)
                await update.message.reply_text(f"🚫 Automatically removed scammer **{member.full_name}** from the group.")
            except Exception as e:
                logger.warning(f"Failed to auto-kick user: {e}")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "ℹ️ **Usage:** `/check <@username or Telegram_ID>`\n"
            "Example: `/check @john_doe` or `/check 123456789`",
            parse_mode="Markdown"
        )
        return

    query = context.args[0]
    row = search_user(query)

    if row:
        msg = format_user_info(row)
    else:
        msg = (
            f"🔍 **Search Results for:** `{query}`\n\n"
            "⚪ **Status:** NOT IN DATABASE\n"
            "This user is neither marked as verified nor blacklisted. Always use caution when dealing with strangers."
        )
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to manage the database.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("ℹ️ **Usage:** `/blacklist <telegram_id> [username] [notes...]`", parse_mode="Markdown")
        return

    try:
        tg_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Telegram ID must be a valid number.")
        return

    username = context.args[1] if len(context.args) > 1 and context.args[1].startswith("@") else ""
    notes_start_idx = 2 if username else 1
    notes = " ".join(context.args[notes_start_idx:]) if len(context.args) > notes_start_idx else "Marked as scammer"

    add_or_update_user(tg_id, username, "", "SCAMMER", notes)
    await update.message.reply_text(f"🔴 User `{tg_id}` successfully added to the **BLACKLIST**.", parse_mode="Markdown")

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to manage the database.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("ℹ️ **Usage:** `/verify <telegram_id> [username] [notes...]`", parse_mode="Markdown")
        return

    try:
        tg_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Telegram ID must be a number.")
        return

    username = context.args[1] if len(context.args) > 1 and context.args[1].startswith("@") else ""
    notes_start_idx = 2 if username else 1
    notes = " ".join(context.args[notes_start_idx:]) if len(context.args) > notes_start_idx else "Verified Member"

    add_or_update_user(tg_id, username, "", "VERIFIED", notes)
    await update.message.reply_text(f"🟢 User `{tg_id}` successfully added as **VERIFIED**.", parse_mode="Markdown")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to manage the database.")
        return

    if not context.args:
        await update.message.reply_text("ℹ️ **Usage:** `/remove <telegram_id>`", parse_mode="Markdown")
        return

    try:
        tg_id = int(context.args[0])
        if delete_user(tg_id):
            await update.message.reply_text(f"🗑️ User `{tg_id}` removed from database.", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ User not found in database.")
    except ValueError:
        await update.message.reply_text("❌ Telegram ID must be a number.")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ **Anti-Scam Bot Active (Cloud DB Connected)**\n\n"
        "Commands:\n"
        "• `/check <@username or Telegram_ID>` - Check user status\n\n"
        "Admin Commands:\n"
        "• `/blacklist <id> @username [notes]`\n"
        "• `/verify <id> @username [notes]`\n"
        "• `/remove <id>`",
        parse_mode="Markdown"
    )

def main():
    init_db()
    
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("blacklist", blacklist_command))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))

    logger.info("Anti-Scam Bot is running via long-polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
