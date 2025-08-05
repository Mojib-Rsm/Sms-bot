import telebot
import sqlite3
import datetime
import requests
import os
from flask import Flask, request
from telebot import types

# --- Environment Variables থেকে তথ্য লোড করা ---
# Railway-তে এই ভ্যারিয়েবলগুলো সেট করতে হবে।
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS")
SMS_API_URL = os.environ.get("SMS_API_URL")

# আপনার Railway অ্যাপের URL। এটিও Environment Variable হিসেবে সেট করা উচিত।
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") 

# --- 필수 (Essential) ভ্যারিয়েবল চেক ---
if not all([BOT_TOKEN, CHANNEL_ID, ADMIN_IDS_STR, SMS_API_URL, WEBHOOK_URL]):
    raise ValueError("Error: One or more required environment variables are not set.")

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

    cursor.execute("SELECT sms_sent, last_sms_date, bonus_sms FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    today = str(datetime.date.today())
    
    if not user_data:
        cursor.execute("INSERT INTO users (user_id, last_sms_date) VALUES (?, ?)", (user_id, today))
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

# --- সাধারণ মেসেজ হ্যান্ডলার (অ্যাডমিন ইনপুটের জন্য) ---
@bot.message_handler(func=lambda message: True)
def handle_admin_input(message):
    user_id = message.from_user.id
    cursor.execute("SELECT temp_admin_action FROM users WHERE user_id = ?", (user_id,))
    action = cursor.fetchone()

    if not action or not action[0]: return

    action_type = action[0]
    # ইনপুট পাওয়ার পর temp action ক্লিয়ার করে দেওয়া হয়
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
            cursor.execute("SELECT phone_number, timestamp FROM sms_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20", (target_user_id,))
            logs = cursor.fetchall()
            if not logs:
                bot.send_message(message.chat.id, f"ব্যবহারকারী {target_user_id} এর কোনো লগ নেই।")
                return

            log_text = f"📜 **ব্যবহারকারী {target_user_id} এর SMS লগ:**\n\n"
            for log in logs:
                dt_obj = datetime.datetime.fromisoformat(log[1])
                log_text += f"📞 নম্বর: `{log[0]}`\n🗓️ সময়: {dt_obj.strftime('%Y-%m-%d %H:%M')}\n---\n"
            bot.send_message(message.chat.id, log_text, parse_mode="Markdown")
        except ValueError:
            bot.send_message(message.chat.id, "❌ ভুল ইউজার আইডি। আবার চেষ্টা করুন।")


# --- বাটন ক্লিকের উত্তর ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    action = call.data

    if action == "main_menu":
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="মূল মেনু:", reply_markup=main_menu_keyboard(user_id))
    
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
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=history_text, reply_markup=keyboard, parse_mode="Markdown")
        
    # --- অ্যাডমিন কলব্যাক ---
    elif action == "admin_menu":
        if not is_admin(user_id): return
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="🔑 **অ্যাডমিন প্যানেল**", reply_markup=admin_menu_keyboard(), parse_mode="Markdown")

    elif action == "show_stats" or action == "refresh_stats":
        # ... (stats কোড আগের মতোই) ...

    elif action == "get_backup":
        if not is_admin(user_id): return
        try:
            with open('sms_bot.db', 'rb') as db_file:
                bot.send_document(call.message.chat.id, db_file, caption="ডাটাবেস ব্যাকআপ")
            bot.answer_callback_query(call.id, "ব্যাকআপ ফাইল পাঠানো হয়েছে।")
        except Exception as e:
            bot.answer_callback_query(call.id, f"ত্রুটি: {e}", show_alert=True)

    elif action == "prompt_set_bonus":
        if not is_admin(user_id): return
        cursor.execute("UPDATE users SET temp_admin_action = 'set_bonus' WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.send_message(call.message.chat.id, "যে ইউজারকে বোনাস দিতে চান, তার আইডি এবং বোনাস পরিমাণ দিন।\nফরম্যাট: `USER_ID <space> AMOUNT`\nযেমন: `12345678 50`")

    elif action == "prompt_user_sms":
        if not is_admin(user_id): return
        cursor.execute("UPDATE users SET temp_admin_action = 'get_user_sms' WHERE user_id = ?", (user_id,))
        conn.commit()
        bot.send_message(call.message.chat.id, "যে ইউজারের লগ দেখতে চান, তার আইডি দিন।\nযেমন: `12345678`")


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
    return "Webhook set successfully!", 200

if __name__ == "__main__":
    setup_database()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
