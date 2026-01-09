import os
import sqlite3
import re
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
                 (desc.strip() or "Lembrete", remind_time.isoformat(), recurrence))
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
    if not data or "message" not in data or "text" not in data["message"]:
        return "OK"
    
    message = data["message"]
    chat_id = message["from"]["id"]
    text = message.get("text", "").strip()
    
    if text == "/start":
        send_message(chat_id, 
            "✅ Exemplos de uso:\n"
            "• agendar Dentista amanhã 15h\n"
            "• agendar Reunião hoje 14:30\n"
            "• agendar Remédio todo dia 8h"
        )
        return "OK"
    
    if text.lower().startswith("agendar "):
        user_input = text[8:].strip()
        
        # Detecta recorrência
        recurrence = None
        if "todo dia" in user_input.lower() or "diariamente" in user_input.lower():
            recurrence = "daily"
            user_input = re.sub(r'todo dia|diariamente', '', user_input, flags=re.IGNORECASE)
        elif "toda semana" in user_input.lower():
            recurrence = "weekly"
            user_input = re.sub(r'toda semana', '', user_input, flags=re.IGNORECASE)
        
        # Normaliza hora: "15h" → "15:00" (sem espaços)
        user_input = re.sub(r'(\d{1,2})h', r'\1:00', user_input)
        
        # Remove apenas "para"
        user_input = re.sub(r'\bpara\b', ' ', user_input, flags=re.IGNORECASE)
        user_input = re.sub(r'\s+', ' ', user_input).strip()
        
        if not user_input:
            send_message(chat_id, "❌ Formato inválido. Use: 'agendar [descrição] [data/hora]'")
            return "OK"
        
        # Tenta parsear com suporte a PT
        try:
            parsed = dateparser.parse(
                user_input,
                languages=['pt'],
                settings={
                    'RELATIVE_BASE': datetime.now(),
                    'PREFER_DATES_FROM': 'future',
                    'TIMEZONE': 'America/Sao_Paulo'
                }
            )
        except:
            parsed = None
        
        if not parsed:
            send_message(chat_id, 
                f"❌ Não entendi: '{user_input}'\n"
                "✅ Tente: 'agendar X amanhã 15h'"
            )
            return "OK"
        
        # Extrai descrição removendo partes de data/hora
        desc = user_input
        time_patterns = [
            r'\d{1,2}:\d{2}',
            r'\d{1,2}/\d{1,2}/\d{4}',
            r'\d{1,2}/\d{1,2}',
            r'amanhã|hoje|segunda|terça|quarta|quinta|sexta|sábado|domingo'
        ]
        for pattern in time_patterns:
            desc = re.sub(pattern, '', desc, flags=re.IGNORECASE)
        desc = re.sub(r'\s+', ' ', desc).strip()
        
        save_reminder(desc, parsed, recurrence)
        rec_msg = f" (🔁 {recurrence})" if recurrence else ""
        send_message(chat_id, 
            f"✅ Lembrete salvo!{rec_msg}\n"
            f"⏰ {desc or 'Lembrete'}\n"
            f"📅 {parsed.strftime('%d/%m/%Y %H:%M')}"
        )
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
