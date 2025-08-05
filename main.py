import telebot
import sqlite3
import datetime
import requests
import os
import sys
from flask import Flask, request
from telebot import types

# --- Environment Variables থেকে তথ্য লোড করা ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS")
SMS_API_URL = os.environ.get("SMS_API_URL")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# --- ভ্যারিয়েবল আছে কিনা তা চেক করা ---
if not all([BOT_TOKEN, CHANNEL_ID, ADMIN_IDS_STR, SMS_API_URL, WEBHOOK_URL]):
    print("FATAL ERROR: A required variable was not found in Railway's 'Variables' tab.", file=sys.stderr)
    raise ValueError("Error: One or more required environment variables are not set in Railway.")

ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]

# --- ডাটাবেস সেটআপ ---
conn = sqlite3.connect('sms_bot.db', check_same_thread=False)
cursor = conn.cursor()

def setup_database():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, sms_sent INTEGER DEFAULT 0,
        last_sms_date TEXT, bonus_sms INTEGER DEFAULT 0,
        temp_admin_action TEXT
    )''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sms_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        phone_number TEXT, message TEXT, timestamp TEXT
    )''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS drafts (
        draft_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        phone_number TEXT, message TEXT, created_at TEXT
    )''')
    conn.commit()

setup_database()
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- সহায়ক ফাংশন ---
def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_channel_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

# --- ডাইনামিক কমান্ড মেনু সেট করার ফাংশন ---
def set_user_commands(user_id):
    user_commands = [
        types.BotCommand("start", "▶️ বট চালু/রিস্টার্ট করুন"),
        types.BotCommand("sms", "💬 <নম্বর> <মেসেজ> - SMS পাঠান"),
        types.BotCommand("profile", "👤 আপনার প্রোফাইল ও ব্যালেন্স"),
        types.BotCommand("history", "📜 আপনার পাঠানো SMS-এর লগ"),
        types.BotCommand("referral", "🔗 আপনার রেফারেল লিঙ্ক"),
        types.BotCommand("resend", "🔁 শেষ মেসেজটি আবার পাঠান"),
        types.BotCommand("draft", "📝 <নম্বর> <মেসেজ> - মেসেজ ড্রাফট করুন"),
        types.BotCommand("drafts", "🗒️ আপনার সব ড্রাফট দেখুন"),
        types.BotCommand("help", "❓ সকল কমান্ডের তালিকা")
    ]
    
    if is_admin(user_id):
        admin_commands = [
            types.BotCommand("admin", "🔑 অ্যাডমিন প্যানেল দেখুন"),
            types.BotCommand("stats", "📊 বটের পরিসংখ্যান দেখুন")
        ]
        user_commands.extend(admin_commands)
    
    bot.set_my_commands(commands=user_commands, scope=types.BotCommandScopeChat(user_id))

# --- বাটন (Keyboard) তৈরির ফাংশন ---
def main_menu_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("👤 আমার প্রোফাইল", callback_data="show_profile")
    btn2 = types.InlineKeyboardButton("📜 আমার History", callback_data="history_page_1")
    btn3 = types.InlineKeyboardButton("📝 ড্রাফট মেসেজ", callback_data="show_drafts_page_1")
    btn4 = types.InlineKeyboardButton("🔗 রেফারেল লিঙ্ক", callback_data="get_referral")
    btn5 = types.InlineKeyboardButton("❓ সহায়তা", callback_data="show_help")
    keyboard.add(btn1, btn2, btn3, btn4, btn5)
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
    btn1 = types.InlineKeyboardButton("📊 বট Stats", callback_data="show_stats")
    btn2 = types.InlineKeyboardButton("💾 ব্যাকআপ", callback_data="get_backup")
    btn3 = types.InlineKeyboardButton("🎁 বোনাস দিন", callback_data="prompt_set_bonus")
    btn4 = types.InlineKeyboardButton("🗒️ ইউজারের লগ", callback_data="prompt_user_sms")
    btn5 = types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu")
    keyboard.add(btn1, btn2, btn3, btn4, btn5)
    return keyboard

# --- মূল কমান্ড হ্যান্ডলার ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    set_user_commands(user_id)

    if not is_channel_member(user_id):
        bot.send_message(message.chat.id, "स्वागतम्!\n\nএই বটটি ব্যবহার করার জন্য আপনাকে অবশ্যই আমাদের চ্যানেলের সদস্য হতে হবে। অনুগ্রহ করে নিচের বাটনে ক্লিক করে চ্যানেলে যোগ দিন এবং তারপর আবার /start কমান্ড দিন।", reply_markup=force_join_keyboard())
        return

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, last_sms_date) VALUES (?, ?)", (user_id, str(datetime.date.today())))
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
        else:
            sms_sent = user_data[0]
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
        response = requests.get(SMS_API_URL, params={'number': phone_number, 'sms': sms_text})
        if response.status_code == 200:
            cursor.execute("UPDATE users SET sms_sent = sms_sent + 1 WHERE user_id = ?", (user_id,))
            cursor.execute("INSERT INTO sms_log (user_id, phone_number, message, timestamp) VALUES (?, ?, ?, ?)", (user_id, phone_number, sms_text, datetime.datetime.now().isoformat()))
            conn.commit()
            bot.reply_to(message, f"✅ '{phone_number}' নম্বরে আপনার SMS সফলভাবে পাঠানোর জন্য অনুরোধ করা হয়েছে।")
        else:
            bot.reply_to(message, f"API থেকে সমস্যা হয়েছে। স্ট্যাটাস কোড: {response.status_code}")
    except requests.exceptions.RequestException:
        bot.reply_to(message, "API সার্ভারের সাথে সংযোগ করা যাচ্ছে না।")

@bot.message_handler(commands=['profile', 'balance'])
def profile_command(message):
    if not is_channel_member(message.from_user.id):
        bot.reply_to(message, "অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", reply_markup=force_join_keyboard())
        return
    show_profile_info(message.chat.id, message.from_user.id, message.message_id)

def show_profile_info(chat_id, user_id, message_id=None):
    cursor.execute("SELECT sms_sent, last_sms_date, bonus_sms FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    
    sms_sent_today = 0
    if user_data and user_data[1] == str(datetime.date.today()):
        sms_sent_today = user_data[0]
    
    bonus_sms = user_data[2] if user_data else 0
    daily_limit = 10
    remaining_sms = (daily_limit - sms_sent_today) + bonus_sms

    cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ?", (user_id,))
    total_sent_ever = cursor.fetchone()[0]

    profile_text = f"👤 **আপনার প্রোফাইল**\n\n🔹 **দৈনিক লিমিট:**\n   - ব্যবহৃত: {sms_sent_today} টি\n   - বাকি আছে: {daily_limit - sms_sent_today} টি\n\n🔸 **বোনাস:** {bonus_sms} টি SMS\n\n✅ **আজ মোট পাঠাতে পারবেন:** {remaining_sms} টি\n\n📈 **লাইফটাইম পরিসংখ্যান:**\n   - মোট পাঠানো SMS: {total_sent_ever} টি"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="show_profile"))
    
    if message_id:
        bot.edit_message_text(profile_text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, profile_text, parse_mode="Markdown", reply_markup=keyboard)

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = "📜 **বট কমান্ড তালিকা**\n\n**সাধারণ কমান্ড:**\n`/start` - বট চালু করুন।\n`/sms <নম্বর> <মেসেজ>` - SMS পাঠান।\n`/profile` - আপনার প্রোফাইল ও ব্যালেন্স দেখুন।\n`/history` - আপনার পাঠানো SMS-এর লগ দেখুন।\n`/referral` - আপনার রেফারেল লিঙ্ক পান।\n`/resend` - আপনার শেষ পাঠানো SMSটি আবার পাঠান।\n`/draft <নম্বর> <মেসেজ>` - একটি মেসেজ ড্রাফট করে রাখুন।\n`/drafts` - আপনার সেভ করা সব ড্রাফট দেখুন।\n\nℹ️ যেকোনো সমস্যায় অ্যাডমিনের সাথে যোগাযোগ করুন।"
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['resend'])
def resend_command(message):
    user_id = message.from_user.id
    if not is_channel_member(user_id):
        bot.reply_to(message, "অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", reply_markup=force_join_keyboard())
        return
    
    cursor.execute("SELECT phone_number, message FROM sms_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    last_sms = cursor.fetchone()
    if last_sms:
        # এখানে SMS পাঠানোর মূল ফাংশনটি আবার কল করা যেতে পারে
        message.text = f"/sms {last_sms[0]} {last_sms[1]}"
        sms_command(message)
    else:
        bot.reply_to(message, "আপনার কোনো পুরনো মেসেজ পাওয়া যায়নি।")

@bot.message_handler(commands=['draft'])
def draft_command(message):
    user_id = message.from_user.id
    try:
        _, phone_number, sms_text = message.text.split(maxsplit=2)
        cursor.execute("INSERT INTO drafts (user_id, phone_number, message, created_at) VALUES (?, ?, ?, ?)", (user_id, phone_number, sms_text, datetime.datetime.now().isoformat()))
        conn.commit()
        bot.reply_to(message, "✅ মেসেজটি সফলভাবে ড্রাফটে সেভ করা হয়েছে।")
    except ValueError:
        bot.reply_to(message, "❌ ভুল ফরম্যাট।\nসঠিক ফরম্যাট: `/draft <নম্বর> <মেসেজ>`")


# --- সাধারণ মেসেজ হ্যান্ডলার (অ্যাডমিন ইনপুটের জন্য) ---
@bot.message_handler(func=lambda message: True)
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


# --- বাটন ক্লিকের উত্তর ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    action = call.data

    if not is_channel_member(user_id):
        bot.answer_callback_query(call.id, "এই সুবিধাটি ব্যবহার করতে, অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", show_alert=True)
        return

    if action == "main_menu":
        bot.edit_message_text("মূল মেনু:", call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id))
    
    elif action == "show_profile":
        try:
            show_profile_info(call.message.chat.id, user_id, call.message.message_id)
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                bot.answer_callback_query(call.id, "প্রোফাইল আপ-টু-ডেট আছে।")
            else: raise e
        bot.answer_callback_query(call.id)

    elif action == "get_referral":
        bot_info = bot.get_me()
        referral_link = f"https://t.me/{bot_info.username}?start={user_id}"
        bot.answer_callback_query(call.id, text=f"আপনার রেফারেল লিংক:\n{referral_link}", show_alert=True)

    elif action.startswith("history_page_"):
        page = int(action.split('_')[2])
        per_page = 5
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
        bot.edit_message_text(history_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")
    
    # --- অ্যাডমিন কলব্যাক ---
    elif action == "admin_menu":
        if not is_admin(user_id): return
        bot.edit_message_text("🔑 **অ্যাডমিন প্যানেল**", call.message.chat.id, call.message.message_id, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")

    elif action == "show_stats" or action == "refresh_stats":
        if not is_admin(user_id): return
        # ... (stats এর কোড আগের মতোই) ...
    
    elif action == "get_backup":
        # ... (backup এর কোড আগের মতোই) ...

    elif action == "prompt_set_bonus":
        # ... (prompt_set_bonus এর কোড আগের মতোই) ...
        
    elif action == "prompt_user_sms":
        # ... (prompt_user_sms এর কোড আগের মতোই) ...

# --- Flask Webhook সেটআপ ---
@app.route('/' + BOT_TOKEN, methods=['POST'])
def get_message():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    return "Webhook has been set successfully!", 200

if __name__ == "__main__":
    setup_database()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
