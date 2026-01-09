import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import dateparser

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
CHAT_ID = int(os.getenv("CHAT_ID"))

app_flask = Flask(__name__)

# Inicializa e prepara o Application globalmente
async def init_application():
    application = Application.builder().token(BOT_TOKEN).build()
    
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Use: agendar [descrição] [data/hora]")
    
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        if not text.lower().startswith("agendar "):
            return
        user_input = text[8:].strip()
        desc = user_input
        recurrence = None
        if "todo dia" in user_input.lower():
            recurrence = "daily"
            desc = user_input.lower().replace("todo dia", "").strip()
        elif "toda semana" in user_input.lower():
            recurrence = "weekly"
            desc = user_input.lower().replace("toda semana", "").strip()
        parsed = dateparser.parse(desc, settings={'RELATIVE_BASE': datetime.now(), 'PREFER_DATES_FROM': 'future'})
        if not parsed:
            await update.message.reply_text("Não entendi a data.")
            return
        save_reminder(desc, parsed, recurrence)
        rec_msg = f" (🔁 {recurrence})" if recurrence else ""
        await update.message.reply_text(f"Lembrete salvo!{rec_msg}\n⏰ {desc}\n📅 {parsed.strftime('%d/%m %H:%M')}")
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await application.initialize()
    return application

# Funções do banco (fora da função assíncrona)
def init_db():
    conn = sqlite3.connect("reminders.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            remind_time TEXT,
            recurrence TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_reminder(desc, remind_time, recurrence=None):
    conn = sqlite3.connect("reminders.db")
    conn.execute("INSERT INTO reminders (description, remind_time, recurrence) VALUES (?, ?, ?)",
                 (desc, remind_time.isoformat(), recurrence))
    conn.commit()
    conn.close()

def load_reminders():
    conn = sqlite3.connect("reminders.db")
    c = conn.cursor()
    c.execute("SELECT id, description, remind_time, recurrence FROM reminders")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "desc": r[1], "time": datetime.fromisoformat(r[2]), "recurrence": r[3]} for r in rows]

def delete_reminder(rid):
    conn = sqlite3.connect("reminders.db")
    conn.execute("DELETE FROM reminders WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

# Inicializa o Application globalmente
application = asyncio.run(init_application())

@app_flask.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(), application.bot)
    asyncio.run(application.process_update(update))
    return jsonify({"ok": True})

@app_flask.route("/send-reminders", methods=["GET"])
def send_reminders_manual():
    bot = Bot(token=BOT_TOKEN)
    now = datetime.now()
    for r in load_reminders():
        if r["time"] <= now:
            bot.send_message(chat_id=CHAT_ID, text=f"🔔 Lembrete: {r['desc']}")
            delete_reminder(r["id"])
            if r["recurrence"] == "daily":
                save_reminder(r["desc"], r["time"] + timedelta(days=1), "daily")
            elif r["recurrence"] == "weekly":
                save_reminder(r["desc"], r["time"] + timedelta(weeks=1), "weekly")
    return "OK"

@app_flask.route("/")
def home():
    import requests
    webhook_url = f"https://{request.host}{WEBHOOK_PATH}"
    res = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook", json={"url": webhook_url})
    return f"Webhook status: {res.json()}"

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 8000))
    app_flask.run(host="0.0.0.0", port=port)
