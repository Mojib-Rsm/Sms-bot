import sqlite3
import requests
import datetime
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

TOKEN = "8266303588:AAHICu6OCrlJhTfSCIECli0RDtvRAmUeAgc"
CHANNEL_USERNAME = "@MrTools_BD"
DB_PATH = "sms_bot.db"
ADMINS = [2003008418, 1875687264]

user_states = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS sms_logs (
        user_id INTEGER,
        phone TEXT,
        message TEXT,
        sent_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_limits (
        user_id INTEGER PRIMARY KEY,
        daily_sent INTEGER,
        last_sent TEXT,
        referrals INTEGER,
        bonus_sms INTEGER
    )""")
    conn.commit()
    conn.close()

def is_member(chat_member):
    return chat_member.status in ["member", "administrator", "creator"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM user_limits WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO user_limits (user_id, daily_sent, last_sent, referrals, bonus_sms) VALUES (?, ?, ?, ?, ?)",
                  (user_id, 0, str(datetime.date.today()), 0, 0))
        conn.commit()
    conn.close()
    await update.message.reply_text("👋 স্বাগতম! SMS পাঠাতে নাম্বার দিন (ex: 016XXXXXXX):")
    user_states[user_id] = {"step": "awaiting_number"}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # চ্যানেল মেম্বার চেক
    chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
    if not is_member(chat_member):
        await update.message.reply_text("❗️ আপনাকে আমাদের চ্যানেল join করতে হবে:\n👉 " + CHANNEL_USERNAME)
        return

    state = user_states.get(user_id, {})
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(datetime.date.today())

    c.execute("SELECT daily_sent, last_sent, bonus_sms FROM user_limits WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        await start(update, context)
        conn.close()
        return
    daily_sent, last_sent, bonus_sms = row
    if last_sent != today:
        daily_sent = 0
        c.execute("UPDATE user_limits SET daily_sent=?, last_sent=? WHERE user_id=?", (0, today, user_id))

    if state.get("step") == "awaiting_number":
        # নম্বর পাওয়া গেছে, এখন মেসেজ চাওয়া হবে
        user_states[user_id] = {"number": text, "step": "awaiting_message"}
        await update.message.reply_text("✏️ এখন SMS টেক্সট দিন:")
    elif state.get("step") == "awaiting_message":
        number = state["number"]
        message = text

        # ১ নম্বরে ৪ SMS/day চেক
        c.execute("SELECT COUNT(*) FROM sms_logs WHERE user_id=? AND phone=? AND sent_at=?", (user_id, number, today))
        per_number_count = c.fetchone()[0]

        if per_number_count >= 4:
            await update.message.reply_text("⚠️ আপনি আজ এই নাম্বারে ৪টি SMS পাঠিয়েছেন।")
        elif daily_sent + 1 > 10 + bonus_sms:
            await update.message.reply_text("🚫 আজকের SMS লিমিট শেষ।")
        else:
            api_url = f"http://209.145.55.60:8000/send?number={number}&sms={message}"
            try:
                res = requests.get(api_url)
                if res.status_code == 200:
                    c.execute("INSERT INTO sms_logs VALUES (?, ?, ?, ?)", (user_id, number, message, today))
                    c.execute("UPDATE user_limits SET daily_sent=? WHERE user_id=?", (daily_sent + 1, user_id))
                    await update.message.reply_text("✅ SMS পাঠানো হয়েছে!")
                else:
                    await update.message.reply_text("❌ সমস্যা হয়েছে SMS পাঠাতে।")
            except Exception as e:
                await update.message.reply_text(f"❌ সমস্যা হয়েছে SMS পাঠাতে।\nError: {e}")

        conn.commit()
        user_states[user_id] = {"step": "awaiting_number"}
        await update.message.reply_text("📲 আবার নতুন নাম্বার দিন:")
    conn.close()

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT phone, message, sent_at FROM sms_logs WHERE user_id=? ORDER BY sent_at DESC", (user_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📭 আপনি এখনো কোন SMS পাঠাননি।")
        return

    # প্রথম পেজ 0
    await send_history_page(update, context, user_id, rows, page=0)

async def send_history_page(update, context, user_id, rows, page=0):
    ITEMS_PER_PAGE = 5
    total_pages = (len(rows) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))  # পেজ রেঞ্জে রাখি

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_rows = rows[start:end]

    text_lines = [f"✅ {start+i+1}. {r[0]} \n💬 \"{r[1]}\"\n📅 {r[2]}" for i, r in enumerate(page_rows)]
    text = "📜 SMS History (Page {}/{}):\n\n".format(page + 1, total_pages) + "\n\n".join(text_lines)
    text += f"\n\nTotal Messages: {len(rows)}\nPage: {page + 1} of {total_pages}"

    # বোতামগুলো
    keyboard = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"history_{page-1}"),
            InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton("Next ➡️", callback_data=f"history_{page+1}")
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_history"),
            InlineKeyboardButton("📊 Stats", callback_data="show_stats"),
        ],
        [
            InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_menu")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # যদি callback থেকে আসে
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data.startswith("history_"):
        try:
            page = int(data.split("_")[1])
        except:
            page = 0
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT phone, message, sent_at FROM sms_logs WHERE user_id=? ORDER BY sent_at DESC", (user_id,))
        rows = c.fetchall()
        conn.close()

        total_pages = (len(rows) + 4) // 5
        if page < 0 or page >= total_pages:
            # Invalid page ignore
            await query.answer()
            return

        await send_history_page(update, context, user_id, rows, page)
    elif data == "refresh_history":
        # Refresh current page, ধরে নিচ্ছি প্রথম পেজ
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT phone, message, sent_at FROM sms_logs WHERE user_id=? ORDER BY sent_at DESC", (user_id,))
        rows = c.fetchall()
        conn.close()
        await send_history_page(update, context, user_id, rows, 0)
    elif data == "show_stats":
        # Admin হলে স্ট্যাটস দেখাবে, নাহলে না
        if user_id in ADMINS:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            today = str(datetime.date.today())
            c.execute("SELECT COUNT(DISTINCT user_id) FROM user_limits")
            users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM sms_logs")
            total_sms = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM sms_logs WHERE sent_at=?", (today,))
            daily_sms = c.fetchone()[0]
            conn.close()
            await query.answer()
            await query.edit_message_text(f"👥 মোট ব্যবহারকারী: {users}\n📨 মোট SMS: {total_sms}\n📅 আজকের SMS: {daily_sms}")
        else:
            await query.answer("আপনার অনুমতি নেই।", show_alert=True)
    elif data == "back_to_menu":
        # Start menu / start কমান্ড কল করতে পারো অথবা মেসেজ পাঠাতে পারো
        await query.answer()
        await query.edit_message_text("🏠 মেনুতে স্বাগতম!\n\n"
                                      "কমান্ড গুলো:\n"
                                      "/start - শুরু করুন\n"
                                      "/history - SMS ইতিহাস দেখুন\n"
                                      "/referral - রেফারেল লিঙ্ক\n"
                                      "/stats - পরিসংখ্যান (Admin)\n"
                                      "/admin - অ্যাডমিন প্যানেল\n\n"
                                      "SMS পাঠাতে নাম্বার দিন।")
    else:
        await query.answer()

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    await update.message.reply_text(f"🎁 আপনার রেফারেল লিংক:\n{ref_link}")

async def handle_referral_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        try:
            ref_user_id = int(context.args[0])
            user_id = update.effective_user.id
            if ref_user_id != user_id:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT * FROM user_limits WHERE user_id=?", (user_id,))
                if not c.fetchone():
                    c.execute("INSERT INTO user_limits VALUES (?, ?, ?, ?, ?)", (user_id, 0, str(datetime.date.today()), 0, 0))
                    c.execute("UPDATE user_limits SET bonus_sms = bonus_sms + 3 WHERE user_id=?", (ref_user_id,))
                    conn.commit()
                conn.close()
        except:
            pass
    await start(update, context)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(datetime.date.today())
    c.execute("SELECT COUNT(DISTINCT user_id) FROM user_limits")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sms_logs")
    total_sms = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM sms_logs WHERE sent_at=?", (today,))
    daily_sms = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(f"👥 মোট ব্যবহারকারী: {users}\n📨 মোট SMS: {total_sms}\n📅 আজকের SMS: {daily_sms}")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMINS:
        await update.message.reply_text("🔧 Admin Panel:\n"
                                        "/setlimit USER_ID BONUS\n"
                                        "/usersms USER_ID\n"
                                        "/backup\n"
                                        "/stats")
    else:
        await update.message.reply_text("❌ অনুমতি নেই।")

async def setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return
    try:
        user_id = int(context.args[0])
        bonus = int(context.args[1])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE user_limits SET bonus_sms=? WHERE user_id=?", (bonus, user_id))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Bonus SMS আপডেট হয়েছে।")
    except:
        await update.message.reply_text("⚠️ Format: /setlimit USER_ID BONUS")

async def usersms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return
    try:
        user_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT phone, message, sent_at FROM sms_logs WHERE user_id=? ORDER BY sent_at DESC LIMIT 10", (user_id,))
        rows = c.fetchall()
        conn.close()
        if rows:
            msg = "\n".join([f"{r[2]} - {r[0]}: {r[1]}" for r in rows])
            await update.message.reply_text("📋 ইউজারের SMS লগ:\n\n" + msg)
        else:
            await update.message.reply_text("এই ইউজারের কোন SMS নেই।")
    except:
        await update.message.reply_text("⚠️ Format: /usersms USER_ID")

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return
    await update.message.reply_document(document=open(DB_PATH, "rb"))

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", handle_referral_start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("setlimit", setlimit))
    app.add_handler(CommandHandler("usersms", usersms))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
