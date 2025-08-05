import telebot
import sqlite3
import datetime
import requests
import os
import sys
from flask import Flask, request
from telebot import types

# --- Environment Variables from Railway ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS")
SMS_API_URL = os.environ.get("SMS_API_URL")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# --- Essential Variable Check ---
if not all([BOT_TOKEN, CHANNEL_ID, ADMIN_IDS_STR, SMS_API_URL, WEBHOOK_URL]):
    print("FATAL ERROR: A required variable was not found in Railway's 'Variables' tab.", file=sys.stderr)
    raise ValueError("Error: One or more required environment variables are not set in Railway.")

ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]

# --- Database Setup (Updated Schema) ---
conn = sqlite3.connect('sms_bot.db', check_same_thread=False)
cursor = conn.cursor()

def setup_database():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        sms_sent INTEGER DEFAULT 0,
        last_sms_date TEXT,
        bonus_sms INTEGER DEFAULT 0,
        temp_admin_action TEXT,
        current_action TEXT,
        temp_data TEXT
    )''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sms_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone_number TEXT,
        message TEXT,
        timestamp TEXT
    )''')
    conn.commit()

setup_database()
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Helper Functions ---
def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_channel_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

def alert_admins(message, is_error=False):
    prefix = "⚠️ **SMS পাঠানোর এরর লগ** ⚠️\n\n" if is_error else "🔔 **নতুন ব্যবহারকারীর নোটিফিকেশন** 🔔\n\n"
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, prefix + message, parse_mode="Markdown")
        except Exception as e:
            print(f"Failed to send notification to admin {admin_id}: {e}")

# --- Dynamic Command Menu ---
def set_user_commands(user_id):
    # (Code is unchanged, but essential)
    pass

# --- Keyboard Markup Functions ---
def main_menu_keyboard(user_id):
    # (Code is unchanged)
    pass
    
def admin_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(types.InlineKeyboardButton("📊 বট Stats", callback_data="show_stats"), types.InlineKeyboardButton("👥 সব ইউজার দেখুন", callback_data="userlist_page_1"))
    keyboard.add(types.InlineKeyboardButton("🎁 বোনাস দিন", callback_data="prompt_set_bonus"), types.InlineKeyboardButton("🗒️ ইউজারের লগ", callback_data="prompt_user_sms"))
    keyboard.add(types.InlineKeyboardButton("💾 ব্যাকআপ", callback_data="get_backup"))
    keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu"))
    return keyboard

# ... (Other keyboard functions are unchanged)

# --- Command & Logic Handlers ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user = message.from_user
    set_user_commands(user_id)
    
    if not is_channel_member(user_id):
        bot.send_message(message.chat.id, "स्वागतम्!\n\nএই বটটি ব্যবহার করার জন্য আপনাকে অবশ্যই আমাদের চ্যানেলের সদস্য হতে হবে।...", reply_markup=force_join_keyboard())
        return

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    is_old_user = cursor.fetchone()

    if not is_old_user:
        cursor.execute("INSERT INTO users (user_id, first_name, username, last_sms_date) VALUES (?, ?, ?, ?)",
                       (user_id, user.first_name, user.username, str(datetime.date.today())))
        conn.commit()
        # New User Notification
        notification_message = (
            f"**নাম:** {user.first_name}\n"
            f"**ইউজারনেম:** @{user.username}\n"
            f"**ইউজার আইডি:** `{user_id}`\n"
            f"বটটি স্টার্ট করেছে।"
        )
        alert_admins(notification_message)
    else:
        # Update user's name and username if they have changed
        cursor.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?", (user.first_name, user.username, user_id))
        conn.commit()

    # ... (Referral logic is unchanged)

    welcome_text = "স্বাগতম! 🎉\n\nআপনি এখন বটটি ব্যবহার করতে পারেন। নিচের বাটনগুলো থেকে আপনার পছন্দের অপশন বেছে নিন।"
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard(user_id))

@bot.message_handler(commands=['sms'])
def sms_command(message):
    user_id = message.from_user.id
    # ... (Initial checks are unchanged)

    # --- SMS Sending Logic with Error Logging ---
    try:
        response = requests.get(SMS_API_URL, params={'number': phone_number, 'sms': sms_text}, timeout=10)
        
        if response.status_code == 200:
            # (Success logic is unchanged)
            bot.reply_to(message, f"✅ '{phone_number}' নম্বরে আপনার SMS সফলভাবে পাঠানোর জন্য অনুরোধ করা হয়েছে।")
        else:
            # API returned an error
            bot.reply_to(message, f"SMS পাঠানো সম্ভব হয়নি। API থেকে সমস্যা হয়েছে। অ্যাডমিনের সাথে যোগাযোগ করুন।")
            error_details = (
                f"**ব্যবহারকারী:** {message.from_user.first_name} (`{user_id}`)\n"
                f"**নম্বর:** `{phone_number}`\n"
                f"**স্ট্যাটাস কোড:** `{response.status_code}`\n"
                f"**API রেসপন্স:** `{response.text}`"
            )
            alert_admins(error_details, is_error=True)

    except requests.exceptions.RequestException as e:
        # Network or connection error
        bot.reply_to(message, "SMS পাঠানো সম্ভব হয়নি। API সার্ভারের সাথে সংযোগ করা যাচ্ছে না।")
        error_details = (
            f"**ব্যবহারকারী:** {message.from_user.first_name} (`{user_id}`)\n"
            f"**নম্বর:** `{phone_number}`\n"
            f"**এরর টাইপ:** Connection Error\n"
            f"**বিস্তারিত:** `{str(e)}`"
        )
        alert_admins(error_details, is_error=True)

# ... (Stateful message handler is unchanged)

# --- Callback Query Handler (Updated for User List) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    action = call.data
    # ... (Initial checks are unchanged)

    if action.startswith("userlist_page_"):
        if not is_admin(user_id): return
        page = int(action.split('_')[2])
        per_page = 10  # Show 10 users per page
        offset = (page - 1) * per_page
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        total_pages = (total_users + per_page - 1) // per_page or 1
        
        cursor.execute("SELECT user_id, first_name, username FROM users ORDER BY user_id DESC LIMIT ? OFFSET ?", (per_page, offset))
        users_on_page = cursor.fetchall()

        userlist_text = f"👥 **সকল ব্যবহারকারীর তালিকা** (পেজ: {page}/{total_pages})\n\n"
        
        if not users_on_page:
            userlist_text += "কোনো ব্যবহারকারী পাওয়া যায়নি।"
        else:
            for user in users_on_page:
                uid, fname, uname = user
                cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ?", (uid,))
                sms_count = cursor.fetchone()[0]
                userlist_text += f"👤 **{fname}** (@{uname})\n"
                userlist_text += f"   - আইডি: `{uid}`\n"
                userlist_text += f"   - মোট SMS: **{sms_count}**\n---\n"
        
        row = []
        keyboard = types.InlineKeyboardMarkup()
        if page > 1: row.append(types.InlineKeyboardButton("⬅️ আগের", callback_data=f"userlist_page_{page-1}"))
        if page < total_pages: row.append(types.InlineKeyboardButton("পরের ➡️", callback_data=f"userlist_page_{page+1}"))
        keyboard.add(*row)
        keyboard.add(types.InlineKeyboardButton("🔙 অ্যাডমিন মেনু", callback_data="admin_menu"))
        
        bot.edit_message_text(userlist_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")

    # ... (All other callback handlers are now fully implemented and unchanged from the previous complete version)
    

# --- Flask Webhook Setup ---
# (Unchanged)

if __name__ == "__main__":
    setup_database()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
