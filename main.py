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

def parse_datetime(text, is_explicit_date=False):
    """Parser robusto para datas em português"""
    now = datetime.now()
    text_lower = text.lower()
    
    # Detecta hora primeiro
    hour = now.hour
    minute = now.minute
    hour_match = re.search(r'(\d{1,2})[:h](\d{2})?', text_lower)
    if hour_match:
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2)) if hour_match.group(2) else 0
        # Normaliza hora 24h
        if hour < 12 and ('pm' in text_lower or 'tarde' in text_lower or 'noite' in text_lower):
            hour += 12
        elif hour == 12 and ('am' in text_lower or 'manhã' in text_lower):
            hour = 0
    
    # Detecta data
    target_date = now.date()
    date_found = False
    is_relative = False  # Flag para datas relativas (hoje/amanhã)
    
    # 1. Data explícita no formato DD/MM ou DD/MM/AAAA
    date_match = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?', text_lower)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now.year
        
        try:
            target_date = datetime(year, month, day).date()
            date_found = True
            is_explicit_date = True  # Marca como data explícita
        except ValueError:
            pass
    
    # 2. Datas relativas (só se não encontrou data explícita)
    if not date_found:
        if "amanhã" in text_lower:
            target_date = now.date() + timedelta(days=1)
            is_relative = True
        elif "hoje" in text_lower:
            target_date = now.date()
            is_relative = True
        elif "segunda" in text_lower:
            days_ahead = (7 - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = now.date() + timedelta(days=days_ahead)
            is_relative = True
    
    # Combina data e hora
    try:
        remind_time = datetime.combine(target_date, datetime.min.time())
        remind_time = remind_time.replace(hour=hour, minute=minute)
        
        # Só ajusta para amanhã se for data RELATIVA e a hora já passou
        if is_relative and remind_time < now:
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
            "✅ Formatos corrigidos:\n"
            "• agendar Dentista hoje 15h\n"
            "• agendar Reunião amanhã 14:30\n"
            "• agendar Remédio 09/01/2026 11:55\n"
            "• agendar X todo dia 8h"
        )
        return "OK"
    
    if text.lower().startswith("agendar "):
        full_input = text[8:].strip()
        user_input = full_input
        
        # Detecta recorrência
        recurrence = None
        if "todo dia" in user_input.lower() or "diariamente" in user_input.lower():
            recurrence = "daily"
            user_input = re.sub(r'todo dia|diariamente', '', user_input, flags=re.IGNORECASE)
        elif "toda semana" in user_input.lower():
            recurrence = "weekly"
            user_input = re.sub(r'toda semana', '', user_input, flags=re.IGNORECASE)
        
        # Verifica se tem data explícita no formato DD/MM
        has_explicit_date = bool(re.search(r'\d{1,2}[/-]\d{1,2}', user_input))
        
        # Limpeza para parsing
        clean_input = re.sub(r'\bpara\b', ' ', user_input, flags=re.IGNORECASE)
        clean_input = re.sub(r'\s+', ' ', clean_input).strip()
        
        # Faz parsing da data/hora (passando se é data explícita)
        parsed = parse_datetime(clean_input, has_explicit_date)
        
        if not parsed:
            send_message(chat_id, 
                f"❌ Não consegui agendar: '{full_input}'\n"
                "✅ Use um destes formatos:\n"
                "• hoje 15h\n"
                "• amanhã 14:30\n"
                "• 09/01/2026 11:55"
            )
            return "OK"
        
        # Extrai descrição
        desc = full_input
        
        # Remove padrões de data/hora específicos
        patterns_to_remove = [
            r'\bhoje\b', r'\bamanhã\b',
            r'\bsegunda\b', r'\bterça\b', r'\bquarta\b', r'\bquinta\b', r'\bsexta\b', r'\bsábado\b', r'\bdomingo\b',
            r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?\b',
            r'\b\d{1,2}[:h]\d{0,2}\b',
            r'\btodo dia\b', r'\bdiariamente\b', r'\btoda semana\b',
            r'\bpara\b', r'\bàs?\b', r'\bdas\b', r'\bde\b'
        ]
        
        for pattern in patterns_to_remove:
            desc = re.sub(pattern, '', desc, flags=re.IGNORECASE)
        
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
