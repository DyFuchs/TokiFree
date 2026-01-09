import os
import sqlite3
import re
from datetime import datetime, timedelta
from flask import Flask, request
import requests
import pytz

# Configurações
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")  # Fuso horário padrão
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)
tz = pytz.timezone(TIMEZONE)

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

def parse_datetime(text):
    """Parser robusto com fuso horário"""
    now = datetime.now(tz)
    text_lower = text.lower()
    
    # Detecta hora primeiro
    hour = now.hour
    minute = now.minute
    
    # Caso especial: "daqui Xmin"
    if "daqui" in text_lower:
        min_match = re.search(r'daqui\s+(\d+)\s*min', text_lower)
        if min_match:
            minutes = int(min_match.group(1))
            return now + timedelta(minutes=minutes)
    
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
    is_relative = False
    
    # 1. Data explícita no formato DD/MM ou DD/MM/AAAA
    date_match = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?', text_lower)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now.year
        
        try:
            target_date = datetime(year, month, day).date()
        except ValueError:
            pass
    
    # 2. Datas relativas
    if "amanhã" in text_lower:
        target_date = now.date() + timedelta(days=1)
        is_relative = True
    elif "hoje" in text_lower:
        target_date = now.date()
        is_relative = True
    
    # Combina data e hora
    try:
        remind_time = datetime.combine(target_date, datetime.min.time())
        remind_time = tz.localize(remind_time.replace(hour=hour, minute=minute))
        
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
            "✅ Formato CORRETO:\n"
            "• agendar \"Dentista\" hoje 15h\n"
            "• agendar \"Reunião\" amanhã 14:30\n"
            "• agendar \"Remédio\" 09/01/2026 12:05\n"
            "• agendar \"X\" daqui 5min\n\n"
            f"⏰ Fuso horário atual: {TIMEZONE}"
        )
        return "OK"
    
    if text.lower().startswith("agendar "):
        full_input = text[8:].strip()
        
        # Extrai descrição entre aspas (prioridade máxima)
        desc_match = re.search(r'"([^"]+)"', full_input)
        if desc_match:
            desc = desc_match.group(1).strip()
            # Remove a descrição entre aspas do texto para parsing
            clean_input = full_input.replace(f'"{desc}"', '').strip()
        else:
            # Fallback para formato antigo (não recomendado)
            desc = "Lembrete"
            clean_input = full_input
        
        # Detecta recorrência
        recurrence = None
        if "todo dia" in clean_input.lower() or "diariamente" in clean_input.lower():
            recurrence = "daily"
            clean_input = re.sub(r'todo dia|diariamente', '', clean_input, flags=re.IGNORECASE)
        elif "toda semana" in clean_input.lower():
            recurrence = "weekly"
            clean_input = re.sub(r'toda semana', '', clean_input, flags=re.IGNORECASE)
        
        # Limpeza final
        clean_input = re.sub(r'\bpara\b|\bdaqui\b', ' ', clean_input, flags=re.IGNORECASE)
        clean_input = re.sub(r'\s+', ' ', clean_input).strip()
        
        # Faz parsing da data/hora
        parsed = parse_datetime(clean_input)
        
        if not parsed:
            send_message(chat_id, 
                f"❌ Formato inválido: '{full_input}'\n\n"
                "✅ Use SEMPRE este formato:\n"
                "agendar \"DESCRIÇÃO\" [data/hora]\n\n"
                "Exemplos:\n"
                "• agendar \"Dentista\" hoje 15h\n"
                "• agendar \"Reunião\" daqui 10min"
            )
            return "OK"
        
        save_reminder(desc, parsed, recurrence)
        rec_msg = f" (🔁 {recurrence})" if recurrence else ""
        send_message(chat_id, 
            f"✅ Lembrete salvo!{rec_msg}\n"
            f"⏰ {desc}\n"
            f"📅 {parsed.strftime('%d/%m/%Y %H:%M')}\n"
            f"🕒 Fuso: {TIMEZONE}"
        )
        return "OK"
    
    return "OK"

@app.route("/send-reminders", methods=["GET"])
def send_reminders_manual():
    now = datetime.now(tz)
    for r in load_reminders():
        remind_time = tz.localize(r["time"])
        if remind_time <= now:
            send_message(CHAT_ID, f"🔔 LEMBRETE:\n⏰ {r['desc']}\n📅 {remind_time.strftime('%d/%m/%Y %H:%M')}")
            delete_reminder(r["id"])
            if r["recurrence"] == "daily":
                new_time = remind_time + timedelta(days=1)
                save_reminder(r["desc"], new_time, "daily")
            elif r["recurrence"] == "weekly":
                new_time = remind_time + timedelta(weeks=1)
                save_reminder(r["desc"], new_time, "weekly")
    return "OK"

@app.route("/")
def home():
    webhook_url = f"https://{request.host}/webhook"
    res = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})
    return f"Webhook status: {res.json()}<br>Fuso horário: {TIMEZONE}"

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
