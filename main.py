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

# --- ডাটাবেস সেটআপ (নতুন টেবিল ও কলাম সহ) ---
conn = sqlite3.connect('sms_bot.db', check_same_thread=False)
cursor = conn.cursor()

def setup_database():
    # ইউজার টেবিল
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, sms_sent INTEGER DEFAULT 0,
        last_sms_date TEXT, bonus_sms INTEGER DEFAULT 0,
        temp_admin_action TEXT
    )''')
    # SMS লগ টেবিল (মেসেজ কন্টেন্ট সহ)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sms_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        phone_number TEXT, message TEXT, timestamp TEXT
    )''')
    # ড্রাফট মেসেজ টেবিল (নতুন ফিচার)
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

# --- বাটন (Keyboard) তৈরির ফাংশন ---
def main_menu_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("👤 আমার প্রোফাইল", callback_data="show_profile")
    btn2 = types.InlineKeyboardButton("📜 আমার History", callback_data="history_page_1")
    btn3 = types.InlineKeyboardButton("📝 ড্রাফট মেসেজ", callback_data="show_drafts")
    btn4 = types.InlineKeyboardButton("🔗 রেফারেল লিঙ্ক", callback_data="get_referral")
    btn5 = types.InlineKeyboardButton("❓ সহায়তা", callback_data="show_help")
    keyboard.add(btn1, btn2, btn3, btn4, btn5)
    if is_admin(user_id):
        btn6 = types.InlineKeyboardButton("🔑 অ্যাডমিন প্যানেল", callback_data="admin_menu")
        keyboard.add(btn6)
    return keyboard

def force_join_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    # আপনার চ্যানেলের লিংক এখানে দিন
    url_button = types.InlineKeyboardButton(text="➡️ প্রথমে চ্যানেলে যোগ দিন", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")
    keyboard.add(url_button)
    return keyboard

# (বাকি অ্যাডমিন কিবোর্ড কোডগুলো আগের মতোই থাকবে)
def admin_menu_keyboard():
    # ... আগের মতোই ...

# --- মূল কমান্ড হ্যান্ডলার ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id

    if not is_channel_member(user_id):
        bot.send_message(message.chat.id, 
                         "स्वागतम्!\n\nএই বটটি ব্যবহার করার জন্য আপনাকে অবশ্যই আমাদের চ্যানেলের সদস্য হতে হবে। অনুগ্রহ করে নিচের বাটনে ক্লিক করে চ্যানেলে যোগ দিন এবং তারপর আবার /start কমান্ড দিন।", 
                         reply_markup=force_join_keyboard())
        return

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, last_sms_date) VALUES (?, ?)", (user_id, str(datetime.date.today())))
        conn.commit()

    # রেফারেল হ্যান্ডলিং
    # ... আগের মতোই ...
    
    welcome_text = "স্বাগতম! 🎉\n\nআপনি এখন বটটি ব্যবহার করতে পারেন। নিচের বাটনগুলো থেকে আপনার পছন্দের অপশন বেছে নিন।"
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard(user_id))

@bot.message_handler(commands=['sms'])
def sms_command(message):
    # ... আগের মতোই সম্পূর্ণ কোড ...
    # শুধু sms_log এ message কন্টেন্ট সেভ করতে হবে
    # cursor.execute("INSERT INTO sms_log ... VALUES (?, ?, ?, ?)", (user_id, phone_number, sms_text, ...))

@bot.message_handler(commands=['profile', 'balance'])
def profile_command(message):
    if not is_channel_member(message.from_user.id):
        bot.reply_to(message, "অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", reply_markup=force_join_keyboard())
        return
    show_profile_info(message.chat.id, message.from_user.id)

def show_profile_info(chat_id, user_id):
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

    profile_text = (
        f"👤 **আপনার প্রোফাইল**\n\n"
        f"🔹 **দৈনিক লিমিট:**\n"
        f"   - ব্যবহৃত: {sms_sent_today} টি\n"
        f"   - বাকি আছে: {daily_limit - sms_sent_today} টি\n\n"
        f"🔸 **বোনাস:** {bonus_sms} টি SMS\n\n"
        f"✅ **আজ মোট পাঠাতে পারবেন:** {remaining_sms} টি\n\n"
        f"📈 **লাইফটাইম পরিসংখ্যান:**\n"
        f"   - মোট পাঠানো SMS: {total_sent_ever} টি"
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="show_profile"))
    bot.send_message(chat_id, profile_text, parse_mode="Markdown", reply_markup=keyboard)


@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "**📜 বট কমান্ড তালিকা**\n\n"
        "**সাধারণ কমান্ড:**\n"
        "`/start` - বট চালু করুন।\n"
        "`/sms <নম্বর> <মেসেজ>` - SMS পাঠান।\n"
        "`/profile` - আপনার প্রোফাইল ও ব্যালেন্স দেখুন।\n"
        "`/history` - আপনার পাঠানো SMS-এর লগ দেখুন।\n"
        "`/referral` - আপনার রেফারেল লিঙ্ক পান।\n"
        "`/resend` - আপনার শেষ পাঠানো SMSটি আবার পাঠান।\n"
        "`/draft <নম্বর> <মেসেজ>` - একটি মেসেজ ড্রাফট করে রাখুন।\n"
        "`/drafts` - আপনার সেভ করা সব ড্রাফট দেখুন।\n"
        "`/schedule` - SMS শিডিউল করুন (শীঘ্রই আসছে)।\n\n"
        "ℹ️ যেকোনো সমস্যায় অ্যাডমিনের সাথে যোগাযোগ করুন।"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['resend'])
def resend_command(message):
    # রিসেন্ড করার লজিক এখানে যুক্ত হবে
    user_id = message.from_user.id
    cursor.execute("SELECT phone_number, message FROM sms_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    last_sms = cursor.fetchone()
    if last_sms:
        # এখানে SMS পাঠানোর মূল ফাংশনটি আবার কল করা যেতে পারে
        # লিমিট চেক সহ
        bot.reply_to(message, f"`{last_sms[0]}` নম্বরে `{last_sms[1]}` মেসেজটি আবার পাঠানোর অনুরোধ করা হচ্ছে...")
    else:
        bot.reply_to(message, "আপনার কোনো পুরনো মেসেজ পাওয়া যায়নি।")


# --- বাটন ক্লিকের উত্তর (Callback Query Handler) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    action = call.data

    if not is_channel_member(user_id):
        bot.answer_callback_query(call.id, "এই সুবিধাটি ব্যবহার করতে, অনুগ্রহ করে প্রথমে চ্যানেলে যোগ দিন।", show_alert=True)
        return
    
    if action == "show_profile":
        show_profile_info(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id) # বাটন ক্লিক হয়েছে জানানোর জন্য

    # ... অন্যান্য সব callback handler আগের মতোই থাকবে ...
    # যেমন: history, admin_menu, show_stats ইত্যাদি।


# --- Flask Webhook সেটআপ ---
# ... আগের মতোই সম্পূর্ণ কোড ...

if __name__ == "__main__":
    setup_database()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
