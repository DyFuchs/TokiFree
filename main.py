import os
import sqlite3
import re
import logging
from datetime import datetime, timedelta, date
from flask import Flask, request, jsonify
import requests
import pytz
from dateutil.relativedelta import relativedelta

os.environ["FLASK_ENV"] = "production"
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)
tz = pytz.timezone(TIMEZONE)

def init_db():
    conn = sqlite3.connect("/tmp/reminders.db")
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
    try:
        response = requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})
        logger.info(f"Mensagem enviada para {chat_id}: {text[:50]}... | Status: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {str(e)}")
        return None

def save_reminder(desc, remind_time, recurrence=None):
    conn = sqlite3.connect("/tmp/reminders.db")
    conn.execute("INSERT INTO reminders (description, remind_time, recurrence) VALUES (?, ?, ?)",
                 (desc.strip() or "Lembrete", remind_time.isoformat(), recurrence))
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    logger.info(f"Lembrete salvo ID={rid} | {desc} | {remind_time} | {recurrence}")
    return rid

def load_reminders():
    conn = sqlite3.connect("/tmp/reminders.db")
    c = conn.cursor()
    c.execute("SELECT id, description, remind_time, recurrence FROM reminders")
    rows = c.fetchall()
    conn.close()
    reminders = []
    for r in rows:
        try:
            remind_time = datetime.fromisoformat(r[2])
            if remind_time.tzinfo is None:
                remind_time = tz.localize(remind_time)
            reminders.append({
                "id": r[0],
                "desc": r[1],
                "time": remind_time,
                "recurrence": r[3]
            })
        except Exception as e:
            logger.error(f"Erro ao carregar lembrete ID={r[0]}: {str(e)}")
    logger.info(f"Carregados {len(reminders)} lembretes do banco")
    return reminders

def delete_reminder(rid):
    conn = sqlite3.connect("/tmp/reminders.db")
    conn.execute("DELETE FROM reminders WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    logger.info(f"Lembrete ID={rid} deletado")

def delete_reminder_by_desc(description):
    conn = sqlite3.connect("/tmp/reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE description = ?", (description,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"{count} lembrete(s) com descrição '{description}' deletado(s)")
    return count

def delete_all_reminders():
    conn = sqlite3.connect("/tmp/reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders")
    count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"Todos os {count} lembretes foram deletados")
    return count

def update_reminder_time(rid, new_time):
    conn = sqlite3.connect("/tmp/reminders.db")
    conn.execute("UPDATE reminders SET remind_time = ? WHERE id = ?", 
                 (new_time.isoformat(), rid))
    conn.commit()
    conn.close()
    logger.info(f"Lembrete ID={rid} atualizado para {new_time}")

def update_reminder_time_by_desc(description, new_time):
    conn = sqlite3.connect("/tmp/reminders.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET remind_time = ? WHERE description = ?", 
                  (new_time.isoformat(), description))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"{count} lembrete(s) com descrição '{description}' atualizado(s) para {new_time}")
    return count

def get_next_weekday(current_date, weekday):
    days_ahead = weekday - current_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return current_date + timedelta(days=days_ahead)

def get_last_weekday_of_month(year, month, weekday):
    last_day = date(year, month, 1) + relativedelta(months=1, days=-1)
    days_behind = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=days_behind)

def get_first_weekday_of_month(year, month, weekday):
    first_day = date(year, month, 1)
    days_ahead = (weekday - first_day.weekday()) % 7
    return first_day + timedelta(days=days_ahead)

def get_last_business_day_of_month(year, month):
    last_day = date(year, month, 1) + relativedelta(months=1, days=-1)
    while last_day.weekday() >= 5:
        last_day -= timedelta(days=1)
    return last_day

def get_first_business_day_of_month(year, month):
    first_day = date(year, month, 1)
    while first_day.weekday() >= 5:
        first_day += timedelta(days=1)
    return first_day

def parse_pt_br_date(text, now):
    text = text.lower().strip()
    current_date = now.date()
    
    if "último domingo do mês" in text or "ultimo domingo do mes" in text:
        last_sunday = get_last_weekday_of_month(current_date.year, current_date.month, 6)
        return last_sunday
    
    if "primeiro domingo do mês que vem" in text or "primeiro domingo do mes que vem" in text:
        next_month = current_date + relativedelta(months=1)
        first_sunday = get_first_weekday_of_month(next_month.year, next_month.month, 6)
        return first_sunday
    
    if "último dia útil do mês" in text or "ultimo dia util do mes" in text:
        last_business_day = get_last_business_day_of_month(current_date.year, current_date.month)
        return last_business_day
    
    if "primeiro dia útil do mês que vem" in text or "primeiro dia util do mes que vem" in text:
        next_month = current_date + relativedelta(months=1)
        first_business_day = get_first_business_day_of_month(next_month.year, next_month.month)
        return first_business_day
    
    weekdays_map = {
        'segunda': 0, 'segunda-feira': 0, 'segunda feira': 0,
        'terça': 1, 'terca': 1, 'terça-feira': 1, 'terca-feira': 1, 'terça feira': 1, 'terca feira': 1,
        'quarta': 2, 'quarta-feira': 2, 'quarta feira': 2,
        'quinta': 3, 'quinta-feira': 3, 'quinta feira': 3,
        'sexta': 4, 'sexta-feira': 4, 'sexta feira': 4,
        'sábado': 5, 'sabado': 5,
        'domingo': 6
    }
    
    for day_name, weekday_num in weekdays_map.items():
        if day_name in text:
            next_week = False
            if any(phrase in text for phrase in ["semana que vem", "próxima semana", "proxima semana", "da semana que vem"]):
                next_week = True
            
            if next_week:
                target_date = get_next_weekday(current_date, weekday_num)
                if target_date <= current_date:
                    target_date += timedelta(weeks=1)
                return target_date
            else:
                return get_next_weekday(current_date, weekday_num)
    
    if "amanhã" in text or "amanha" in text:
        return current_date + timedelta(days=1)
    if "hoje" in text:
        return current_date
    if "depois de amanhã" in text or "depois de amanha" in text:
        return current_date + timedelta(days=2)
    
    return None

def parse_datetime(text):
    now = datetime.now(tz)
    original_text = text
    text_lower = text.lower()
    
    if "daqui" in text_lower:
        min_match = re.search(r'daqui\s+(\d+)\s*min', text_lower)
        if min_match:
            minutes = int(min_match.group(1))
            return now + timedelta(minutes=minutes)
    
    hour = now.hour
    minute = now.minute
    has_explicit_time = False
    
    hour_patterns = [
        r'(\d{1,2})[:h](\d{2})',
        r'(\d{1,2})\s*[hH]',
        r'(\d{1,2})\s*horas?',
    ]
    
    extracted_hour = None
    extracted_minute = None
    
    for pattern in hour_patterns:
        hour_match = re.search(pattern, text_lower)
        if hour_match:
            extracted_hour = int(hour_match.group(1))
            extracted_minute = int(hour_match.group(2)) if hour_match.lastindex > 1 and hour_match.group(2) else 0
            has_explicit_time = True
            text_lower = re.sub(pattern, '', text_lower, 1)
            text_lower = re.sub(r'\s+', ' ', text_lower).strip()
            break
    
    if extracted_hour is not None:
        hour = extracted_hour
        minute = extracted_minute
        if hour < 12:
            if 'tarde' in text_lower or 'noite' in text_lower or 'pm' in text_lower:
                hour += 12
        elif hour == 12:
            if 'manhã' in text_lower or 'manha' in text_lower or 'am' in text_lower:
                hour = 0
    
    text_clean = re.sub(r'\b(?:para|as|às|a|o|aos|daqui|em|no|na|de|do|da|as|às|com)\b', '', text_lower)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    
    target_date = parse_pt_br_date(text_clean, now)
    
    if not target_date:
        target_date = now.date()
    
    try:
        remind_time = datetime.combine(target_date, datetime.min.time())
        remind_time = tz.localize(remind_time.replace(hour=hour, minute=minute))
        
        if not has_explicit_time and remind_time.date() == now.date() and remind_time < now:
            remind_time = remind_time.replace(hour=now.hour + 1, minute=0)
        
        if remind_time.date() == now.date() and remind_time < now and not re.search(r'\d{1,2}[/-]\d{1,2}', original_text):
            remind_time += timedelta(days=1)
        
        return remind_time
    except Exception as e:
        logger.error(f"Erro ao combinar data e hora: {str(e)}")
        return now + timedelta(minutes=5)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data or "text" not in data["message"]:
        return "OK"
    
    message = data["message"]
    chat_id = message["from"]["id"]
    text = message.get("text", "").strip()
    logger.info(f"Recebida mensagem de {chat_id}: {text}")
    
    if text == "/start":
        send_message(chat_id, 
            "✅ Formato CORRETO:\n"
            "• agendar \"Dentista\" hoje 15h\n"
            "• agendar \"Reunião\" amanhã 14:30\n"
            "• agendar \"X\" \"segunda-feira que vem\" 15h\n"
            "• agendar \"Y\" \"último domingo do mês\" 13h\n"
            "• agendar \"Z\" \"primeiro domingo do mês que vem\" 10h\n\n"
            f"⏰ Fuso horário: {TIMEZONE}\n\n"
            "🔧 Este bot precisa de um serviço externo para funcionar 24h.\n"
            "Acesse: https://cron-job.org e configure:\n"
            f"URL: https://{request.host}/send-reminders\n"
            "Frequência: every minute\n\n"
            "📋 COMANDOS:\n"
            "/listar - Ver lembretes\n"
            "/cancelar \"descrição\" ou [ID]\n"
            "/cancelartodos - Cancelar todos\n"
            "/remarcar \"descrição\" [nova data] ou [ID] [nova data]"
        )
        return "OK"
    
    if text.lower() == "/listar":
        reminders = load_reminders()
        now = datetime.now(tz)
        
        if not reminders:
            send_message(chat_id, "📭 Nenhum lembrete agendado.")
            return "OK"
        
        message = "📋 LEMBRETES AGENDADOS:\n\n"
        for r in reminders:
            status = "✅ ATIVO" if r["time"] > now else "⏳ PENDENTE"
            message += f"ID: {r['id']}\nDescrição: {r['desc']}\nData: {r['time'].strftime('%d/%m/%Y %H:%M')}\nStatus: {status}\nRecorrência: {r['recurrence'] or 'Nenhuma'}\n\n"
        
        message += f"\n⏰ Horário atual ({TIMEZONE}): {now.strftime('%d/%m/%Y %H:%M')}"
        send_message(chat_id, message)
        return "OK"
    
    if text.lower().startswith("/cancelar "):
        arg = text[9:].strip()
        
        if arg.isdigit():
            rid = int(arg)
            reminders = load_reminders()
            reminder = next((r for r in reminders if r["id"] == rid), None)
            
            if reminder:
                delete_reminder(rid)
                send_message(chat_id, f"✅ Lembrete ID={rid} cancelado!\nDescrição: {reminder['desc']}")
            else:
                send_message(chat_id, f"❌ Lembrete ID={rid} não encontrado.")
        else:
            desc_match = re.search(r'"([^"]+)"', arg)
            if desc_match:
                desc = desc_match.group(1).strip()
                count = delete_reminder_by_desc(desc)
                if count > 0:
                    send_message(chat_id, f"✅ {count} lembrete(s) \"{desc}\" cancelado(s)!")
                else:
                    send_message(chat_id, f"❌ Nenhum lembrete com descrição \"{desc}\"")
            else:
                send_message(chat_id, "❌ Formato inválido\nUse:\n/cancelar \"descrição\"\nou\n/cancelar [ID]")
        
        return "OK"
    
    if text.lower() == "/cancelartodos":
        count = delete_all_reminders()
        send_message(chat_id, f"✅ Todos os {count} lembretes foram cancelados!")
        return "OK"
    
    if text.lower().startswith("/remarcar "):
        text_clean = text[10:].strip()
        
        desc_match = re.match(r'^"([^"]+)"\s+(.+)$', text_clean)
        if desc_match:
            desc = desc_match.group(1).strip()
            new_datetime_str = desc_match.group(2).strip()
            
            new_time = parse_datetime(new_datetime_str)
            if not new_time:
                send_message(chat_id, f"❌ Não entendi a nova data '{new_datetime_str}'")
                return "OK"
            
            count = update_reminder_time_by_desc(desc, new_time)
            if count > 0:
                send_message(chat_id, 
                    f"✅ {count} lembrete(s) \"{desc}\" remarcado(s)!\n"
                    f"Nova data: {new_time.strftime('%d/%m/%Y %H:%M')}"
                )
            else:
                send_message(chat_id, f"❌ Nenhum lembrete com descrição \"{desc}\"")
            return "OK"
        
        parts = text_clean.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            rid = int(parts[0])
            new_datetime_str = parts[1]
            
            reminders = load_reminders()
            reminder = next((r for r in reminders if r["id"] == rid), None)
            
            if not reminder:
                send_message(chat_id, f"❌ Lembrete ID={rid} não encontrado.")
                return "OK"
            
            new_time = parse_datetime(new_datetime_str)
            if not new_time:
                send_message(chat_id, f"❌ Não entendi a nova data: '{new_datetime_str}'")
                return "OK"
            
            update_reminder_time(rid, new_time)
            send_message(chat_id, 
                f"✅ Lembrete ID={rid} remarcado!\n"
                f"Descrição: {reminder['desc']}\n"
                f"Nova data: {new_time.strftime('%d/%m/%Y %H:%M')}"
            )
            return "OK"
        
        send_message(chat_id, 
            "❌ Formato inválido para /remarcar\n\n"
            "✅ Formatos corretos:\n"
            "/remarcar \"descrição\" nova data\n"
            "/remarcar [ID] nova data\n\n"
            "Exemplos:\n"
            "/remarcar \"Dentista\" amanhã 15h\n"
            "/remarcar 42 \"último domingo do mês\" 10h"
        )
        return "OK"
    
    if text.lower().startswith("agendar "):
        full_input = text[8:].strip()
        
        desc_match = re.search(r'"([^"]+)"', full_input)
        if desc_match:
            desc = desc_match.group(1).strip()
            clean_input = full_input.replace(f'"{desc}"', '').strip()
        else:
            send_message(chat_id, 
                "❌ ERRO: Descrição deve estar entre aspas!\n\n"
                "✅ Formato correto:\n"
                "agendar \"Sua descrição\" hoje 15h"
            )
            return "OK"
        
        recurrence = None
        if "todo dia" in clean_input.lower() or "diariamente" in clean_input.lower():
            recurrence = "daily"
            clean_input = re.sub(r'todo dia|diariamente', '', clean_input, flags=re.IGNORECASE)
        elif "toda semana" in clean_input.lower():
            recurrence = "weekly"
            clean_input = re.sub(r'toda semana', '', clean_input, flags=re.IGNORECASE)
        
        clean_input = re.sub(r'\bpara\b', ' ', clean_input, flags=re.IGNORECASE)
        clean_input = re.sub(r'\s+', ' ', clean_input).strip()
        
        parsed = parse_datetime(clean_input)
        
        if not parsed:
            send_message(chat_id, 
                f"❌ Não entendi a data '{clean_input}'\n\n"
                "✅ Exemplos válidos:\n"
                "• hoje 15h\n"
                "• amanhã 14:30\n"
                "• \"segunda-feira que vem\" 15h\n"
                "• \"último domingo do mês\" 13h\n"
                "• \"primeiro domingo do mês que vem\" 10h"
            )
            return "OK"
        
        rid = save_reminder(desc, parsed, recurrence)
        
        rec_msg = f" (🔁 {recurrence})" if recurrence else ""
        response = (
            f"✅ LEMBRETE SALVO (ID={rid})!{rec_msg}\n"
            f"⏰ {desc}\n"
            f"📅 {parsed.strftime('%d/%m/%Y %H:%M')}\n"
            f"🕒 Fuso: {TIMEZONE}"
        )
        send_message(chat_id, response)
        return "OK"
    
    return "OK"

@app.route("/send-reminders", methods=["GET"])
def send_reminders_manual():
    logger.info("=== INICIANDO VERIFICAÇÃO DE LEMBRETES ===")
    now = datetime.now(tz)
    logger.info(f"Horário atual ({TIMEZONE}): {now.strftime('%d/%m/%Y %H:%M:%S')}")
    
    reminders = load_reminders()
    logger.info(f"Total de lembretes no banco: {len(reminders)}")
    
    sent_count = 0
    for r in reminders:
        logger.info(f"Verificando lembrete ID={r['id']}: {r['desc']} | Agendado para: {r['time']} | Agora: {now}")
        
        if r["time"] <= now:
            logger.info(f"🕗 Lembrete ID={r['id']} está na hora! Enviando...")
            
            message = f"🔔 LEMBRETE:\n⏰ {r['desc']}\n📅 {r['time'].strftime('%d/%m/%Y %H:%M')}"
            if r["recurrence"]:
                message += f"\n🔄 Recorrência: {r['recurrence']}"
            send_message(CHAT_ID, message)
            sent_count += 1
            
            if r["recurrence"] == "daily":
                new_time = r["time"] + timedelta(days=1)
                save_reminder(r["desc"], new_time, "daily")
                logger.info(f"↻ Lembrete diário reagendado para: {new_time}")
            elif r["recurrence"] == "weekly":
                new_time = r["time"] + timedelta(weeks=1)
                save_reminder(r["desc"], new_time, "weekly")
                logger.info(f"↻ Lembrete semanal reagendado para: {new_time}")
            
            delete_reminder(r["id"])
    
    logger.info(f"✅ Verificação concluída. {sent_count} lembretes enviados.")
    return f"OK - {sent_count} lembretes processados"

@app.route("/debug-time", methods=["GET"])
def debug_time():
    now = datetime.now(tz)
    return f"Hora atual ({TIMEZONE}): {now.strftime('%d/%m/%Y %H:%M:%S')}"

@app.route("/")
def home():
    webhook_url = f"https://{request.host}/webhook"
    res = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url})
    return (
        f"Webhook status: {res.json()}<br>"
        f"Fuso horário: {TIMEZONE}<br>"
        f"URL para cron-job.org: https://{request.host}/send-reminders<br>"
        "<br>✅ Bot está funcionando corretamente!"
    )

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=False)
