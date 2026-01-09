import os
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, request
import dateparser
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

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

def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})

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

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "OK"
    
    message = data["message"]
    chat_id = message["from"]["id"]
    text = message.get("text", "").strip()
    
    if text == "/start":
        send_message(chat_id, "Use: agendar [descrição] [data/hora]\nEx: agendar Dentista amanhã 15h")
        return "OK"
    
    if text.lower().startswith("agendar "):
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
            send_message(chat_id, "Não entendi a data. Tente: 'agendar X amanhã 15h'")
            return "OK"
        
        save_reminder(desc, parsed, recurrence)
        rec_msg = f" (🔁 {recurrence})" if recurrence else ""
        send_message(chat_id, f"Lembrete salvo!{rec_msg}\n⏰ {desc}\n📅 {parsed.strftime('%d/%m %H:%M')}")
        return "OK"
    
    return "OK"

@app.route("/send-reminders", methods=["GET"])
def send_reminders_manual():
    now = datetime.now()
    for r in load_reminders():
        if r["time"] <= now:
            send_message(CHAT_ID, f"🔔 Lembrete: {r['desc']}")
            delete_reminder(r["id"])
            if r["recurrence"] == "daily":
                save_reminder(r["desc"], r["time"] + timedelta(days=1), "daily")
            elif r["recurrence"] == "weekly":
                save_reminder(r["desc"], r["time"] + timedelta(weeks=1), "weekly")
    return "OK"

@app.route("/")
def home():
    webhook_url = f"https://{request.host}/webhook"
    res = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})
    return f"Webhook status: {res.json()}"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
