import os
import sqlite3
import re
from datetime import datetime, timedelta
from flask import Flask, request
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

def parse_datetime_fallback(text):
    """Parser manual para formatos comuns em português"""
    now = datetime.now()
    text = text.lower()
    
    # Detecta hora no formato HH:MM ou HHh
    hour_match = re.search(r'(\d{1,2})[:h](\d{2})?', text)
    hour = minute = 0
    if hour_match:
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2)) if hour_match.group(2) else 0
        # Remove a hora do texto para facilitar detecção de data
        text = re.sub(r'\d{1,2}[:h]\d{0,2}', '', text)
    
    # Detecta datas relativas
    if "amanhã" in text:
        target_date = now.date() + timedelta(days=1)
    elif "hoje" in text:
        target_date = now.date()
    else:
        # Tenta detectar data no formato DD/MM
        date_match = re.search(r'(\d{1,2})[/-](\d{1,2})', text)
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year = now.year
            if month < now.month or (month == now.month and day < now.day):
                year += 1
            try:
                target_date = datetime(year, month, day).date()
            except:
                target_date = now.date() + timedelta(days=1)
        else:
            # Default para amanhã se não encontrar data
            target_date = now.date() + timedelta(days=1)
    
    # Combina data e hora
    try:
        remind_time = datetime.combine(target_date, datetime.min.time())
        remind_time = remind_time.replace(hour=hour, minute=minute)
        # Se a hora já passou hoje, agenda para amanhã
        if remind_time < now:
            remind_time += timedelta(days=1)
        return remind_time
    except:
        return None

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
            "✅ Funciona com estes formatos:\n"
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
        
        # Limpeza básica
        user_input_clean = re.sub(r'\bpara\b', ' ', user_input, flags=re.IGNORECASE)
        user_input_clean = re.sub(r'\s+', ' ', user_input_clean).strip()
        
        # Primeiro tenta com parser manual (mais confiável para este caso)
        parsed = parse_datetime_fallback(user_input_clean)
        
        if not parsed:
            send_message(chat_id, 
                f"❌ Não entendi a data em: '{user_input}'\n"
                "✅ Use exatamente: 'agendar [descrição] amanhã 15h'"
            )
            return "OK"
        
        # Extrai descrição removendo palavras-chave de data/hora
        desc = user_input
        for kw in ["amanhã", "hoje", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo", 
                  "todo dia", "diariamente", "toda semana", "para", "às", "as", "h"]:
            desc = re.sub(rf'\b{kw}\b', '', desc, flags=re.IGNORECASE)
        # Remove horários e datas
        desc = re.sub(r'\d{1,2}[:h]\d{0,2}', '', desc)
        desc = re.sub(r'\d{1,2}[/-]\d{1,2}', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()
        
        if not desc:
            desc = "Lembrete"
        
        save_reminder(desc, parsed, recurrence)
        rec_msg = f" (🔁 {recurrence})" if recurrence else ""
        send_message(chat_id, 
            f"✅ Lembrete salvo!{rec_msg}\n"
            f"⏰ {desc}\n"
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
