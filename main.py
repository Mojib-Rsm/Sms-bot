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

# --- Database Setup ---
conn = sqlite3.connect('sms_bot.db', check_same_thread=False)
cursor = conn.cursor()

def setup_database():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, sms_sent INTEGER DEFAULT 0,
        last_sms_date TEXT, bonus_sms INTEGER DEFAULT 0,
        temp_admin_action TEXT,
        current_action TEXT,
        temp_data TEXT
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

# --- Helper Functions ---
def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_channel_member(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

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
    btn3 = types.InlineKeyboardButton("📝 ড্রাফট মেসেজ", callback_data="show_drafts_page_1")
    btn4 = types.InlineKeyboardButton("🔗 রেফারেল লিঙ্ক", callback_data="get_referral")
    btn5 = types.InlineKeyboardButton("❓ সহায়তা", callback_data="show_help")
    keyboard.add(btn_send)
    keyboard.add(btn1, btn2, btn3, btn4, btn5)
    if is_admin(user_id):
        btn6 = types.InlineKeyboardButton("🔑 অ্যাডমিন প্যানেল", callback_data="admin_menu")
        keyboard.add(btn6)
    return keyboard

def force_join_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    try: channel_link = bot.export_chat_invite_link(CHANNEL_ID); url_button = types.InlineKeyboardButton(text="➡️ প্রথমে চ্যানেলে যোগ দিন", url=channel_link)
    except Exception: url_button = types.InlineKeyboardButton(text="➡️ প্রথমে চ্যানেলে যোগ দিন", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")
    keyboard.add(url_button); return keyboard

def admin_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(types.InlineKeyboardButton("📊 বট Stats", callback_data="show_stats"), types.InlineKeyboardButton("💾 ব্যাকআপ", callback_data="get_backup"))
    keyboard.add(types.InlineKeyboardButton("🎁 বোনাস দিন", callback_data="prompt_set_bonus"), types.InlineKeyboardButton("🗒️ ইউজারের লগ", callback_data="prompt_user_sms"))
    keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu")); return keyboard
    
def back_to_main_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup(); keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu")); return keyboard

# --- Command Handlers ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    set_user_commands(user_id)
    if not is_channel_member(user_id):
        bot.send_message(message.chat.id, "स्वागतम्!\n\nএই বটটি ব্যবহার করার জন্য আপনাকে অবশ্যই আমাদের চ্যানেলের সদস্য হতে হবে। অনুগ্রহ করে নিচের বাটনে ক্লিক করে চ্যানেলে যোগ দিন এবং তারপর আবার /start কমান্ড দিন।", reply_markup=force_join_keyboard()); return
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,));
    if not cursor.fetchone(): cursor.execute("INSERT INTO users (user_id, last_sms_date) VALUES (?, ?)", (user_id, str(datetime.date.today()))); conn.commit()
    parts = message.text.split()
    if len(parts) > 1:
        try:
            referrer_id = int(parts[1])
            if referrer_id != user_id: cursor.execute("UPDATE users SET bonus_sms = bonus_sms + 3 WHERE user_id = ?", (referrer_id,)); conn.commit(); bot.send_message(referrer_id, "অভিনন্দন! আপনার রেফারেল লিঙ্কে একজন নতুন সদস্য যোগ দিয়েছেন। আপনি ৩টি বোনাস SMS পেয়েছেন।")
        except (IndexError, ValueError): pass
    welcome_text = "স্বাগতম! 🎉\n\nআপনি এখন বটটি ব্যবহার করতে পারেন। নিচের বাটনগুলো থেকে আপনার পছন্দের অপশন বেছে নিন।"
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard(user_id))

@bot.message_handler(commands=['sms'])
def sms_command(message):
    user_id = message.from_user.id
    # (Implementation is the same as before, shortened for brevity)
    pass

# --- Stateful Message Handler ---
@bot.message_handler(func=lambda message: not message.text.startswith('/'))
def handle_stateful_messages(message):
    user_id = message.from_user.id
    cursor.execute("SELECT current_action, temp_data FROM users WHERE user_id = ?", (user_id,)); state_data = cursor.fetchone()
    if state_data and state_data[0]:
        action = state_data[0]
        if action == 'awaiting_number':
            phone_number = message.text.strip()
            if not phone_number.isdigit() or len(phone_number) < 10:
                bot.reply_to(message, "❌ এটি একটি সঠিক ফোন নম্বর নয়। অনুগ্রহ করে আবার চেষ্টা করুন।"); return
            cursor.execute("UPDATE users SET current_action = 'awaiting_message', temp_data = ? WHERE user_id = ?", (phone_number, user_id)); conn.commit()
            bot.reply_to(message, "✅ নম্বরটি সেভ করা হয়েছে। এখন আপনার মেসেজটি লিখুন।")
        elif action == 'awaiting_message':
            sms_text = message.text; phone_number = state_data[1]
            cursor.execute("UPDATE users SET current_action = NULL, temp_data = NULL WHERE user_id = ?", (user_id,)); conn.commit()
            fake_message = message; fake_message.text = f"/sms {phone_number} {sms_text}"; sms_command(fake_message)
    else:
        handle_admin_input(message)

def handle_admin_input(message):
    # (Implementation is the same as before, shortened for brevity)
    pass
        
# --- Callback Query Handler (Updated) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id; action = call.data; message = call.message
    if not is_channel_member(user_id):
        bot.answer_callback_query(call.id, "এই সুবিধাটি ব্যবহার করতে, অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", show_alert=True); return
    
    if action == "main_menu":
        bot.edit_message_text("মূল মেনু:", message.chat.id, message.message_id, reply_markup=main_menu_keyboard(user_id))
    
    elif action == "show_help":
        help_text = "❓ **সহায়তা কেন্দ্র**\n\nএই বটটি ব্যবহার করে আপনি বিনামূল্যে SMS পাঠাতে পারবেন।\n\n**অতিরিক্ত SMS প্রয়োজন?**\nআপনার দৈনিক লিমিট শেষ হয়ে গেলে বা আরও বেশি SMS পাঠানোর প্রয়োজন হলে, অনুগ্রহ করে অ্যাডমিনের সাথে যোগাযোগ করুন।\n👨‍💼 **অ্যাডমিন:** @Mojibrsm"
        bot.edit_message_text(help_text, message.chat.id, message.message_id, reply_markup=back_to_main_menu_keyboard(), parse_mode="Markdown")
        
    elif action == "get_referral":
        bot_info = bot.get_me(); referral_link = f"https://t.me/{bot_info.username}?start={user_id}"
        referral_text = f"**🔗 আপনার রেফারেল লিঙ্ক**\n\nএই লিংকটি আপনার বন্ধুদের সাথে শেয়ার করুন। প্রতিটি সফল রেফারেলের জন্য আপনি **৩টি বোনাস SMS** পাবেন!\n\n`{referral_link}`\n\n_(লিংকটির উপর ক্লিক করলে এটি কপি হয়ে যাবে।)_"
        bot.edit_message_text(referral_text, message.chat.id, message.message_id, parse_mode="Markdown", reply_markup=back_to_main_menu_keyboard())

    elif action == "send_message_start":
        cursor.execute("UPDATE users SET current_action = 'awaiting_number' WHERE user_id = ?", (user_id,)); conn.commit()
        bot.edit_message_text("বেশ! অনুগ্রহ করে যে নম্বরে SMS পাঠাতে চান, সেটি পাঠান।", message.chat.id, message.message_id, reply_markup=back_to_main_menu_keyboard())

    # --- Other callback handlers remain the same but will now use the back button ---
    elif action == "show_profile":
        # show_profile_info function should now use back_to_main_menu_keyboard() in its reply_markup
        pass
    
    elif action.startswith("history_page_"):
        # history function should add the back button to its keyboard
        pass

    elif action == "admin_menu":
        bot.edit_message_text("🔑 **অ্যাডমিন প্যানেল**", message.chat.id, message.message_id, reply_markup=admin_menu_keyboard(), parse_mode="Markdown")

    # (Add full logic for all other callbacks here)


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
