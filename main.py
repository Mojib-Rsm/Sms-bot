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
    print("FATAL ERROR: A required variable was not found in Railway's 'Variables' tab. Please check for typos or missing variables.", file=sys.stderr)
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
    user_commands = [
        types.BotCommand("start", "▶️ বট চালু/রিস্টার্ট করুন"),
        types.BotCommand("sms", "💬 <নম্বর> <মেসেজ> - SMS পাঠান"),
        types.BotCommand("profile", "👤 আপনার প্রোফাইল ও ব্যালেন্স"),
        types.BotCommand("history", "📜 আপনার পাঠানো SMS-এর লগ"),
        types.BotCommand("referral", "🔗 আপনার রেফারেল লিঙ্ক"),
        types.BotCommand("help", "❓ সকল কমান্ডের তালিকা")
    ]
    if is_admin(user_id):
        admin_commands = [
            types.BotCommand("admin", "🔑 অ্যাডমিন প্যানেল দেখুন"),
            types.BotCommand("stats", "📊 বটের পরিসংখ্যান দেখুন")
        ]
        user_commands.extend(admin_commands)
    bot.set_my_commands(commands=user_commands, scope=types.BotCommandScopeChat(user_id))

# --- Keyboard Markup Functions ---
def main_menu_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    btn_send = types.InlineKeyboardButton("💬 একটি মেসেজ পাঠান", callback_data="send_message_start")
    btn1 = types.InlineKeyboardButton("👤 আমার প্রোফাইল", callback_data="show_profile")
    btn2 = types.InlineKeyboardButton("📜 আমার History", callback_data="history_page_1")
    btn4 = types.InlineKeyboardButton("🔗 রেফারেল লিঙ্ক", callback_data="get_referral")
    btn5 = types.InlineKeyboardButton("❓ সহায়তা", callback_data="show_help")
    keyboard.add(btn_send)
    keyboard.add(btn1, btn2, btn4, btn5)
    if is_admin(user_id):
        btn6 = types.InlineKeyboardButton("🔑 অ্যাডমিন প্যানেল", callback_data="admin_menu")
        keyboard.add(btn6)
    return keyboard

def force_join_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    try:
        channel_link = bot.export_chat_invite_link(CHANNEL_ID)
        url_button = types.InlineKeyboardButton(text="➡️ প্রথমে চ্যানেলে যোগ দিন", url=channel_link)
    except Exception:
        url_button = types.InlineKeyboardButton(text="➡️ প্রথমে চ্যানেলে যোগ দিন", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")
    keyboard.add(url_button)
    return keyboard

def admin_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(types.InlineKeyboardButton("📊 বট Stats", callback_data="show_stats"), types.InlineKeyboardButton("👥 সব ইউজার দেখুন", callback_data="userlist_page_1"))
    keyboard.add(types.InlineKeyboardButton("🎁 বোনাস দিন", callback_data="prompt_set_bonus"), types.InlineKeyboardButton("🗒️ ইউজারের লগ", callback_data="prompt_user_sms"))
    keyboard.add(types.InlineKeyboardButton("💾 ব্যাকআপ", callback_data="get_backup"))
    keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu"))
    return keyboard

def back_to_main_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu"))
    return keyboard

# --- Command & Logic Handlers ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user = message.from_user
    set_user_commands(user_id)
    if not is_channel_member(user_id):
        bot.send_message(message.chat.id, "स्वागतम्!\n\nএই বটটি ব্যবহার করার জন্য আপনাকে অবশ্যই আমাদের চ্যানেলের সদস্য হতে হবে। অনুগ্রহ করে নিচের বাটনে ক্লিক করে চ্যানেলে যোগ দিন এবং তারপর আবার /start কমান্ড দিন।", reply_markup=force_join_keyboard())
        return
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    is_old_user = cursor.fetchone()
    if not is_old_user:
        cursor.execute("INSERT INTO users (user_id, first_name, username, last_sms_date) VALUES (?, ?, ?, ?)", (user_id, user.first_name, user.username, str(datetime.date.today())))
        conn.commit()
        notification_message = f"**নাম:** {user.first_name}\n**ইউজারনেম:** @{user.username}\n**ইউজার আইডি:** `{user_id}`\nবটটি স্টার্ট করেছে।"
        alert_admins(notification_message)
    else:
        cursor.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?", (user.first_name, user.username, user_id))
        conn.commit()
    parts = message.text.split()
    if len(parts) > 1:
        try:
            referrer_id = int(parts[1])
            if referrer_id != user_id:
                cursor.execute("UPDATE users SET bonus_sms = bonus_sms + 3 WHERE user_id = ?", (referrer_id,))
                conn.commit()
                bot.send_message(referrer_id, "অভিনন্দন! আপনার রেফারেল লিঙ্কে একজন নতুন সদস্য যোগ দিয়েছেন। আপনি ৩টি বোনাস SMS পেয়েছেন।")
        except (IndexError, ValueError):
            pass
    welcome_text = "স্বাগতম! 🎉\n\nআপনি এখন বটটি ব্যবহার করতে পারেন। নিচের বাটনগুলো থেকে আপনার পছন্দের অপশন বেছে নিন।"
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard(user_id))

@bot.message_handler(commands=['sms'])
def sms_command(message):
    user_id = message.from_user.id
    if not is_channel_member(user_id):
        bot.reply_to(message, "অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", reply_markup=force_join_keyboard())
        return
    try:
        _, phone_number, sms_text = message.text.split(maxsplit=2)
    except ValueError:
        bot.reply_to(message, "❌ ভুল ফরম্যাট।\nসঠিক ফরম্যাট: `/sms <নম্বর> <মেসেজ>`")
        return
    cursor.execute("SELECT sms_sent, last_sms_date, bonus_sms FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    today = str(datetime.date.today())
    if not user_data:
        cursor.execute("INSERT INTO users (user_id, last_sms_date) VALUES (?, ?)", (user_id, today))
        conn.commit()
        sms_sent, bonus_sms = 0, 0
    else:
        if user_data[1] != today:
            cursor.execute("UPDATE users SET sms_sent = 0, last_sms_date = ? WHERE user_id = ?", (today, user_id))
            conn.commit()
            sms_sent = 0
        else: sms_sent = user_data[0]
        bonus_sms = user_data[2]
    total_limit = 10 + bonus_sms
    if sms_sent >= total_limit:
        bot.reply_to(message, f"আপনি আপনার দৈনিক SMS পাঠানোর সীমা ({total_limit} টি) অতিক্রম করেছেন।")
        return
    cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ? AND phone_number = ? AND DATE(timestamp) = ?", (user_id, phone_number, today))
    same_number_count = cursor.fetchone()[0]
    if same_number_count >= 4:
        bot.reply_to(message, "আপনি এই নম্বরে দিনে সর্বোচ্চ ৪টি SMS পাঠাতে পারবেন।")
        return
    try:
        response = requests.get(SMS_API_URL, params={'number': phone_number, 'sms': sms_text}, timeout=30)
        if response.status_code == 200:
            cursor.execute("UPDATE users SET sms_sent = sms_sent + 1 WHERE user_id = ?", (user_id,))
            cursor.execute("INSERT INTO sms_log (user_id, phone_number, message, timestamp) VALUES (?, ?, ?, ?)", (user_id, phone_number, sms_text, datetime.datetime.now().isoformat()))
            conn.commit()
            bot.reply_to(message, f"✅ '{phone_number}' নম্বরে আপনার SMS সফলভাবে পাঠানোর জন্য অনুরোধ করা হয়েছে।")
        else:
            bot.reply_to(message, f"SMS পাঠানো সম্ভব হয়নি। API থেকে সমস্যা হয়েছে। অ্যাডমিনের সাথে যোগাযোগ করুন।")
            error_details = f"**ব্যবহারকারী:** {message.from_user.first_name} (`{user_id}`)\n**নম্বর:** `{phone_number}`\n**স্ট্যাটাস কোড:** `{response.status_code}`\n**API রেসপন্স:** `{response.text}`"
            alert_admins(error_details, is_error=True)
    except requests.exceptions.RequestException as e:
        bot.reply_to(message, "SMS পাঠানো সম্ভব হয়নি। API সার্ভারের সাথে সংযোগ করা যাচ্ছে না।")
        error_details = f"**ব্যবহারকারী:** {message.from_user.first_name} (`{user_id}`)\n**নম্বর:** `{phone_number}`\n**এরর টাইপ:** Connection Error\n**বিস্তারিত:** `{str(e)}`"
        alert_admins(error_details, is_error=True)

@bot.message_handler(commands=['help'])
def help_command(message):
    # (Implementation is the same as the previous complete version)
    pass
    
# --- Stateful Message Handler ---
@bot.message_handler(func=lambda message: not message.text.startswith('/'))
def handle_stateful_messages(message):
    user_id = message.from_user.id
    cursor.execute("SELECT current_action, temp_data FROM users WHERE user_id = ?", (user_id,))
    state_data = cursor.fetchone()
    if state_data and state_data[0]:
        action = state_data[0]
        if action == 'awaiting_number':
            phone_number = message.text.strip()
            if not phone_number.isdigit() or len(phone_number) < 10:
                bot.reply_to(message, "❌ এটি একটি সঠিক ফোন নম্বর নয়। অনুগ্রহ করে আবার চেষ্টা করুন।")
                return
            cursor.execute("UPDATE users SET current_action = 'awaiting_message', temp_data = ? WHERE user_id = ?", (phone_number, user_id))
            conn.commit()
            bot.reply_to(message, f"✅ নম্বর `({phone_number})` সেভ করা হয়েছে। এখন আপনার মেসেজটি লিখুন।", parse_mode="Markdown")
        elif action == 'awaiting_message':
            sms_text = message.text
            phone_number = state_data[1]
            cursor.execute("UPDATE users SET current_action = NULL, temp_data = NULL WHERE user_id = ?", (user_id,))
            conn.commit()
            # Create a fake message object to pass to the sms_command
            fake_message = types.Message(message_id=0, from_user=message.from_user, date=message.date, chat=message.chat, content_type='text', options={}, json_string="")
            fake_message.text = f"/sms {phone_number} {sms_text}"
            sms_command(fake_message)
    else:
        handle_admin_input(message)

def handle_admin_input(message):
    user_id = message.from_user.id
    cursor.execute("SELECT temp_admin_action FROM users WHERE user_id = ?", (user_id,))
    action_data = cursor.fetchone()
    if not action_data or not action_data[0]: return
    action_type = action_data[0]
    cursor.execute("UPDATE users SET temp_admin_action = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    if action_type == "set_bonus":
        try:
            target_user_id, bonus_amount = map(int, message.text.split())
            cursor.execute("UPDATE users SET bonus_sms = bonus_sms + ? WHERE user_id = ?", (bonus_amount, target_user_id))
            conn.commit()
            bot.send_message(message.chat.id, f"✅ ব্যবহারকারী {target_user_id} কে {bonus_amount}টি বোনাস SMS দেওয়া হয়েছে।")
            bot.send_message(target_user_id, f"🎉 অভিনন্দন! অ্যাডমিন আপনাকে {bonus_amount}টি বোনাস SMS দিয়েছেন।")
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "❌ ভুল ফরম্যাট। আবার চেষ্টা করুন।")
    elif action_type == "get_user_sms":
        try:
            target_user_id = int(message.text)
            cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ?", (target_user_id,))
            total_sms_sent = cursor.fetchone()[0]
            cursor.execute("SELECT phone_number, timestamp FROM sms_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20", (target_user_id,))
            logs = cursor.fetchall()
            if not logs:
                bot.send_message(message.chat.id, f"ব্যবহারকারী {target_user_id} এর কোনো লগ নেই।")
                return
            log_text = f"📜 **ব্যবহারকারী {target_user_id} এর SMS লগ:**\n\n📊 **মোট পাঠানো SMS:** {total_sms_sent} টি\n-------------------------------------\n\n"
            for log in logs:
                dt_obj = datetime.datetime.fromisoformat(log[1])
                formatted_time = dt_obj.strftime('%Y-%m-%d %H:%M')
                log_text += f"📞 **নম্বর:** `{log[0]}`\n🗓️ **সময়:** {formatted_time}\n---\n"
            bot.send_message(message.chat.id, log_text, parse_mode="Markdown")
        except ValueError:
            bot.send_message(message.chat.id, "❌ ভুল ইউজার আইডি। শুধুমাত্র সংখ্যা ব্যবহার করুন।")

# --- Callback Query Handler (Fully Implemented) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    action = call.data
    message = call.message
    if not is_channel_member(user_id):
        bot.answer_callback_query(call.id, "এই সুবিধাটি ব্যবহার করতে, অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", show_alert=True)
        return
    if action == "main_menu":
        bot.edit_message_text("মূল মেনু:", message.chat.id, message.message_id, reply_markup=main_menu_keyboard(user_id))
    elif action == "show_profile":
        cursor.execute("SELECT sms_sent, last_sms_date, bonus_sms FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        sms_sent_today = user_data[0] if user_data and user_data[1] == str(datetime.date.today()) else 0
        bonus_sms = user_data[2] if user_data else 0
        daily_limit = 10
        remaining_sms = (daily_limit - sms_sent_today) + bonus_sms
        cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ?", (user_id,))
        total_sent_ever = cursor.fetchone()[0]
        profile_text = f"👤 **আপনার প্রোফাইল**\n\n🔹 **দৈনিক লিমিট:**\n   - ব্যবহৃত: {sms_sent_today} টি\n   - বাকি আছে: {daily_limit - sms_sent_today} টি\n\n🔸 **বোনাস:** {bonus_sms} টি SMS\n\n✅ **আজ মোট পাঠাতে পারবেন:** {remaining_sms} টি\n\n📈 **লাইফটাইম পরিসংখ্যান:**\n   - মোট পাঠানো SMS: {total_sent_ever} টি"
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="show_profile"))
        keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu"))
        bot.edit_message_text(profile_text, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=keyboard)
    elif action.startswith("history_page_"):
        page = int(action.split('_')[2])
        per_page = 10
        offset = (page - 1) * per_page
        cursor.execute("SELECT phone_number, timestamp FROM sms_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?", (user_id, per_page, offset))
        logs = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ?", (user_id,))
        total_logs = cursor.fetchone()[0]
        total_pages = (total_logs + per_page - 1) // per_page or 1
        if not logs:
            bot.answer_callback_query(call.id, "আপনার কোনো SMS পাঠানোর ইতিহাস নেই।", show_alert=True)
            return
        history_text = f"📜 **আপনার SMS History** (পেজ: {page}/{total_pages})\n\n"
        for log in logs:
            dt_obj = datetime.datetime.fromisoformat(log[1])
            history_text += f"📞 নম্বর: `{log[0]}`\n🗓️ সময়: {dt_obj.strftime('%Y-%m-%d %H:%M')}\n---\n"
        row = []
        keyboard = types.InlineKeyboardMarkup()
        if page > 1: row.append(types.InlineKeyboardButton("⬅️ আগের", callback_data=f"history_page_{page-1}"))
        if page < total_pages: row.append(types.InlineKeyboardButton("পরের ➡️", callback_data=f"history_page_{page+1}"))
        keyboard.add(*row)
        keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu"))
        bot.edit_message_text(history_text, message.chat.id, message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    elif action == "show_help":
        help_text = "❓ **সহায়তা কেন্দ্র**\n\nএই বটটি ব্যবহার করে আপনি বিনামূল্যে SMS পাঠাতে পারবেন।\n\n**অতিরিক্ত SMS প্রয়োজন?**\nআপনার দৈনিক লিমিট শেষ হয়ে গেলে বা আরও বেশি SMS পাঠানোর প্রয়োজন হলে, অনুগ্রহ করে অ্যাডমিনের সাথে যোগাযোগ করুন।\n👨‍💼 **অ্যাডমিন:** @Mojibrsm"
        bot.edit_message_text(help_text, message.chat.id, message.message_id, reply_markup=back_to_main_menu_keyboard(), parse_mode="Markdown")
    elif action == "get_referral":
        bot_info = bot.get_me()
        referral_link = f"https://t.me/{bot_info.username}?start={user_id}"
        referral_text = f"**🔗 আপনার রেফারেল লিঙ্ক**\n\nএই লিংকটি আপনার বন্ধুদের সাথে শেয়ার করুন। প্রতিটি সফল রেফারেলের জন্য আপনি **৩টি বোনাস SMS** পাবেন!\n\n`{referral_link}`\n\n_(লিংকটির উপর ক্লিক করলে এটি কপি হয়ে যাবে।)_"
        bot.edit_message_text(referral_text, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=back_to_main_menu_keyboard())
    elif action == "send_message_start":
        cursor.execute("UPDATE users SET current_action = 'awaiting_number' WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.edit_message_text("বেশ! অনুগ্রহ করে যে নম্বরে SMS পাঠাতে চান, সেটি পাঠান।", message.chat.id, message.message_id, reply_markup=back_to_main_menu_keyboard())
    elif action == "admin_menu":
        if not is_admin(user_id): return
        bot.edit_message_text("🔑 **অ্যাডমিন প্যানেল**", message.chat.id, message.message_id, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
    elif action.startswith("userlist_page_"):
        if not is_admin(user_id): return
        page = int(action.split('_')[2])
        per_page = 10
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
                userlist_text += f"👤 **{fname}** (@{uname})\n   - আইডি: `{uid}`\n   - মোট SMS: **{sms_count}**\n---\n"
        row = []
        keyboard = types.InlineKeyboardMarkup()
        if page > 1: row.append(types.InlineKeyboardButton("⬅️ আগের", callback_data=f"userlist_page_{page-1}"))
        if page < total_pages: row.append(types.InlineKeyboardButton("পরের ➡️", callback_data=f"userlist_page_{page+1}"))
        keyboard.add(*row)
        keyboard.add(types.InlineKeyboardButton("🔙 অ্যাডমিন মেনু", callback_data="admin_menu"))
        bot.edit_message_text(userlist_text, call.message.chat.id, message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    elif action == "show_stats" or action == "refresh_stats":
        if not is_admin(user_id): return
        cursor.execute("SELECT COUNT(*) FROM users"); total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sms_log"); total_sms = cursor.fetchone()[0]
        today = str(datetime.date.today()); cursor.execute("SELECT COUNT(*) FROM sms_log WHERE DATE(timestamp) = ?", (today,)); today_sms = cursor.fetchone()[0]
        stats_text = f"📊 **বট পরিসংখ্যান**\n\n👨‍👩‍👧‍👦 মোট ব্যবহারকারী: {total_users}\n📤 মোট পাঠানো SMS: {total_sms}\n📈 আজ পাঠানো SMS: {today_sms}"
        keyboard = types.InlineKeyboardMarkup(); keyboard.add(types.InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="refresh_stats")); keyboard.add(types.InlineKeyboardButton("🔙 অ্যাডমিন মেনু", callback_data="admin_menu"))
        try: bot.edit_message_text(stats_text, call.message.chat.id, message.message_id, reply_markup=keyboard, parse_mode="Markdown")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e): raise e
            else: bot.answer_callback_query(call.id, "Stats up-to-date.")
    elif action == "get_backup":
        if not is_admin(user_id): return
        try:
            with open('sms_bot.db', 'rb') as db_file: bot.send_document(call.message.chat.id, db_file, caption="ডাটাবেস ব্যাকআপ")
            bot.answer_callback_query(call.id, "ব্যাকআপ ফাইল পাঠানো হয়েছে।")
        except Exception as e: bot.answer_callback_query(call.id, f"ত্রুটি: {e}", show_alert=True)
    elif action == "prompt_set_bonus":
        if not is_admin(user_id): return
        cursor.execute("UPDATE users SET temp_admin_action = 'set_bonus' WHERE user_id = ?", (user_id,)); conn.commit()
        bot.send_message(call.message.chat.id, "যে ইউজারকে বোনাস দিতে চান, তার আইডি এবং বোনাস পরিমাণ দিন।\nফরম্যাট: `USER_ID AMOUNT`\nযেমন: `12345678 50`", parse_mode="Markdown")
    elif action == "prompt_user_sms":
        if not is_admin(user_id): return
        cursor.execute("UPDATE users SET temp_admin_action = 'get_user_sms' WHERE user_id = ?", (user_id,)); conn.commit()
        bot.send_message(call.message.chat.id, "যে ইউজারের লগ দেখতে চান, তার আইডি দিন।\nযেমন: `12345678`")

# --- Flask Webhook Setup ---
@app.route('/' + BOT_TOKEN, methods=['POST'])
def get_message():
    json_string = request.get_data().decode('utf-8'); update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update]); return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook(); bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    return "Webhook has been set successfully!", 200

if __name__ == "__main__":
    setup_database()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
