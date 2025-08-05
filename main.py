import sqlite3
import requests
import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

TOKEN = "8266303588:AAHICu6OCrlJhTfSCIECli0RDtvRAmUeAgc"
CHANNEL_USERNAME = "@MrTools_BD"
DB_PATH = "sms_bot.db"

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

    # Check channel join
    chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
    if not is_member(chat_member):
        await update.message.reply_text("❗️আপনাকে আমাদের চ্যানেল join করতে হবে:\n👉 " + CHANNEL_USERNAME)
        return

    state = user_states.get(user_id, {})
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = str(datetime.date.today())

    # reset daily if date changed
    c.execute("SELECT daily_sent, last_sent, bonus_sms FROM user_limits WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        await start(update, context)
        return
    daily_sent, last_sent, bonus_sms = row
    if last_sent != today:
        daily_sent = 0
        c.execute("UPDATE user_limits SET daily_sent=?, last_sent=? WHERE user_id=?", (0, today, user_id))

    if state.get("step") == "awaiting_number":
        user_states[user_id]["number"] = text
        user_states[user_id]["step"] = "awaiting_message"
        await update.message.reply_text("✏️ এখন SMS টেক্সট দিন:")
    elif state.get("step") == "awaiting_message":
        number = state["number"]
        message = text

        # count per number
        c.execute("SELECT COUNT(*) FROM sms_logs WHERE user_id=? AND phone=? AND sent_at=?", (user_id, number, today))
        per_number_count = c.fetchone()[0]

        if per_number_count >= 4:
            await update.message.reply_text("⚠️ আপনি আজ এই নাম্বারে ৪টি SMS পাঠিয়েছেন।")
        elif daily_sent + 1 > 10 + bonus_sms:
            await update.message.reply_text("🚫 আজকের SMS লিমিট শেষ।")
        else:
            api_url = f"http://209.145.55.60:8000/send?number={number}&sms={message}"
            res = requests.get(api_url)

            if res.status_code == 200:
                c.execute("INSERT INTO sms_logs VALUES (?, ?, ?, ?)", (user_id, number, message, today))
                c.execute("UPDATE user_limits SET daily_sent=? WHERE user_id=?", (daily_sent + 1, user_id))
                await update.message.reply_text("✅ SMS পাঠানো হয়েছে!")
            else:
                await update.message.reply_text("❌ সমস্যা হয়েছে SMS পাঠাতে।")
        conn.commit()
        user_states[user_id] = {"step": "awaiting_number"}
        await update.message.reply_text("📲 আবার নতুন নাম্বার দিন:")
    conn.close()

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT phone, message, sent_at FROM sms_logs WHERE user_id=? ORDER BY sent_at DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    if rows:
        msg = "\n".join([f"{r[2]} - {r[0]}: {r[1]}" for r in rows])
        await update.message.reply_text("📜 আপনার শেষ SMS গুলো:\n\n" + msg)
    else:
        await update.message.reply_text("📭 আপনি এখনো কোন SMS পাঠাননি।")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    await update.message.reply_text(f"🎁 আপনার রেফারেল লিংক:\n{ref_link}")

async def handle_referral_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
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
    await start(update, context)

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", handle_referral_start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
