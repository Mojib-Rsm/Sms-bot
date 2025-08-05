import telebot
import sqlite3
import datetime
import requests
import os
from flask import Flask, request
from telebot import types

# --- আপনার দেওয়া তথ্য এবং পরিবেশ থেকে ভ্যারিয়েবল লোড ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8266303588:AAHICu6OCrlJhTfSCIECli0RDtvRAmUeAgc")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@MrTools_BD")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "2003008418, 1875687264")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
SMS_API_URL = os.environ.get("SMS_API_URL", "http://209.145.55.60:8000/send")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") "https://sms-bot-production.up.railway.app/"

# --- ডাটাবেস সেটআপ ---
conn = sqlite3.connect('sms_bot.db', check_same_thread=False)
cursor = conn.cursor()

def setup_database():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, sms_sent INTEGER DEFAULT 0,
        last_sms_date TEXT, bonus_sms INTEGER DEFAULT 0
    )''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sms_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        phone_number TEXT, timestamp TEXT
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

# --- ইনলাইন বাটন (Keyboard) তৈরির ফাংশন ---
def main_menu_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("📜 আমার History", callback_data="history_page_1")
    btn2 = types.InlineKeyboardButton("🔗 রেফারেল লিঙ্ক", callback_data="get_referral")
    keyboard.add(btn1, btn2)
    if is_admin(user_id):
        btn3 = types.InlineKeyboardButton("🔑 অ্যাডমিন প্যানেল", callback_data="admin_menu")
        keyboard.add(btn3)
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

# --- কমান্ড হ্যান্ডলার ---
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, last_sms_date) VALUES (?, ?)", (user_id, str(datetime.date.today())))
        conn.commit()

    # রেফারেল হ্যান্ডলিং (আগের মতোই)
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

    welcome_text = "স্বাগতম!\n\n➡️ SMS পাঠাতে, নিচের ফরম্যাট অনুসরণ করুন:\n`/sms <নম্বর> <মেসেজ>`\n\nঅন্যান্য অপশনের জন্য নিচের বাটন ব্যবহার করুন। 👇"
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu_keyboard(user_id))

# --- মূল SMS পাঠানোর কমান্ড ---
@bot.message_handler(commands=['sms'])
def sms_command(message):
    user_id = message.from_user.id
    if not is_channel_member(user_id):
        bot.reply_to(message, f"এই সুবিধাটি ব্যবহার করতে অনুগ্রহ করে আমাদের চ্যানেলে যোগ দিন: {CHANNEL_ID}")
        return

    try:
        _, phone_number, sms_text = message.text.split(maxsplit=2)
    except ValueError:
        bot.reply_to(message, "❌ ভুল ফরম্যাট।\nসঠিক ফরম্যাট: `/sms <নম্বর> <মেসেজ>`")
        return
    
    # ইউজার লিমিট চেক করা (আগের মতোই)
    # ... (এই অংশটি সংক্ষিপ্ততার জন্য দেখানো হলো না, এটি উপরের কোডের মতোই)
    
    # --- SMS API কল ---
    try:
        response = requests.get(SMS_API_URL, params={'number': phone_number, 'sms': sms_text})
        if response.status_code == 200:
            # ডাটাবেস আপডেট (আগের মতোই)
            # ...
            bot.reply_to(message, f"✅ '{phone_number}' নম্বরে আপনার SMS সফলভাবে পাঠানোর জন্য অনুরোধ করা হয়েছে।")
        else:
            bot.reply_to(message, f"API থেকে সমস্যা হয়েছে। স্ট্যাটাস কোড: {response.status_code}")
    except requests.exceptions.RequestException as e:
        bot.reply_to(message, "API সার্ভারের সাথে সংযোগ করা যাচ্ছে না।")


# --- বাটন ক্লিকের উত্তর (Callback Query Handler) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    
    # Main Menu
    if call.data == "main_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="মূল মেনু:",
            reply_markup=main_menu_keyboard(user_id)
        )

    # Referral Link
    elif call.data == "get_referral":
        bot_info = bot.get_me()
        referral_link = f"https://t.me/{bot_info.username}?start={user_id}"
        bot.answer_callback_query(call.id, text=f"আপনার রেফারেল লিংক:\n{referral_link}", show_alert=True)

    # History
    elif call.data.startswith("history_page_"):
        page = int(call.data.split('_')[2])
        per_page = 5
        offset = (page - 1) * per_page
        
        cursor.execute("SELECT phone_number, timestamp FROM sms_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?", (user_id, per_page, offset))
        logs = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM sms_log WHERE user_id = ?", (user_id,))
        total_logs = cursor.fetchone()[0]
        total_pages = (total_logs + per_page - 1) // per_page

        if not logs:
            bot.answer_callback_query(call.id, "আপনার কোনো SMS পাঠানোর ইতিহাস নেই।", show_alert=True)
            return

        history_text = f"📜 **আপনার SMS History** (পেজ: {page}/{total_pages})\n\n"
        for log in logs:
            dt_obj = datetime.datetime.fromisoformat(log[1])
            history_text += f"📞 নম্বর: `{log[0]}`\n🗓️ সময়: {dt_obj.strftime('%Y-%m-%d %H:%M')}\n---\n"
            
        # History নেভিগেশন বাটন
        keyboard = types.InlineKeyboardMarkup()
        row = []
        if page > 1:
            row.append(types.InlineKeyboardButton("⬅️ আগের", callback_data=f"history_page_{page-1}"))
        if page < total_pages:
            row.append(types.InlineKeyboardButton("পরের ➡️", callback_data=f"history_page_{page+1}"))
        keyboard.add(*row)
        keyboard.add(types.InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=history_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    # Admin Menu
    elif call.data == "admin_menu":
        if not is_admin(user_id): return
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🔑 **অ্যাডমিন প্যানেল**",
            reply_markup=admin_menu_keyboard(),
            parse_mode="Markdown"
        )

    # Stats
    elif call.data == "show_stats" or call.data == "refresh_stats":
        if not is_admin(user_id): return
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sms_log")
        total_sms = cursor.fetchone()[0]
        today = str(datetime.date.today())
        cursor.execute("SELECT COUNT(*) FROM sms_log WHERE DATE(timestamp) = ?", (today,))
        today_sms = cursor.fetchone()[0]
        stats_text = f"📊 **বট পরিসংখ্যান**\n\n" \
                     f"👨‍👩‍👧‍👦 মোট ব্যবহারকারী: {total_users}\n" \
                     f"📤 মোট পাঠানো SMS: {total_sms}\n" \
                     f"📈 আজ পাঠানো SMS: {today_sms}"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("🔄 রিফ্রেশ", callback_data="refresh_stats"))
        keyboard.add(types.InlineKeyboardButton("🔙 অ্যাডমিন মেনু", callback_data="admin_menu"))
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=stats_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    # Backup
    elif call.data == "get_backup":
        if not is_admin(user_id): return
        try:
            with open('sms_bot.db', 'rb') as db_file:
                bot.send_document(call.message.chat.id, db_file, caption="ডাটাবেস ব্যাকআপ")
            bot.answer_callback_query(call.id, "ব্যাকআপ ফাইল পাঠানো হয়েছে।")
        except Exception as e:
            bot.answer_callback_query(call.id, f"ত্রুটি: {e}", show_alert=True)
    
    # অন্যান্য অ্যাডমিন অপশনের জন্য ইউজারকে ইনপুট দিতে বলা
    # ... (এখানে /setlimit এবং /usersms এর জন্য কোড যুক্ত হবে)


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
    bot.set_webhook(url=WEBHOOK_URL + '/' + BOT_TOKEN)
    return "Webhook set successfully!", 200

if __name__ == "__main__":
    setup_database()
    # Railway.app এ gunicorn এটি চালাবে, সরাসরি নয়
    # app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
