import os
import sqlite3
import re
import logging
from datetime import datetime, timedelta, date
from flask import Flask, request, jsonify
import requests
import pytz
from dateutil.relativedelta import relativedelta

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configurações
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
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
    try:
        response = requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})
        logger.info(f"Mensagem enviada para {chat_id}: {text[:50]}... | Status: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {str(e)}")
        return None

def save_reminder(desc, remind_time, recurrence=None):
    conn = sqlite3.connect("reminders.db")
    conn.execute("INSERT INTO reminders (description, remind_time, recurrence) VALUES (?, ?, ?)",
                 (desc.strip() or "Lembrete", remind_time.isoformat(), recurrence))
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    logger.info(f"Lembrete salvo ID={rid} | {desc} | {remind_time} | {recurrence}")
    return rid

def load_reminders():
    conn = sqlite3.connect("reminders.db")
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
    conn = sqlite3.connect("reminders.db")
    conn.execute("DELETE FROM reminders WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    logger.info(f"Lembrete ID={rid} deletado")

def delete_reminder_by_desc(description):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE description = ?", (description,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"{count} lembrete(s) com descrição '{description}' deletado(s)")
    return count

def delete_all_reminders():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders")
    count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"Todos os {count} lembretes foram deletados")
    return count

def update_reminder_time(rid, new_time):
    conn = sqlite3.connect("reminders.db")
    conn.execute("UPDATE reminders SET remind_time = ? WHERE id = ?", 
                 (new_time.isoformat(), rid))
    conn.commit()
    conn.close()
    logger.info(f"Lembrete ID={rid} atualizado para {new_time}")

def update_reminder_time_by_desc(description, new_time):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET remind_time = ? WHERE description = ?", 
                  (new_time.isoformat(), description))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"{count} lembrete(s) com descrição '{description}' atualizado(s) para {new_time}")
    return count

def get_next_weekday(current_date, weekday):
    """Retorna a próxima ocorrência de um dia da semana (0=segunda, 6=domingo)"""
    days_ahead = weekday - current_date.weekday()
    if days_ahead <= 0:  # Se hoje é ou já passou esse dia
        days_ahead += 7
    return current_date + timedelta(days=days_ahead)

def get_last_weekday_of_month(year, month, weekday):
    """Retorna a última ocorrência de um dia da semana em um mês"""
    # Primeiro, vai para o último dia do mês
    last_day = date(year, month, 1) + relativedelta(months=1, days=-1)
    # Depois retrocede até encontrar o dia da semana desejado
    days_behind = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=days_behind)

def get_first_weekday_of_month(year, month, weekday):
    """Retorna a primeira ocorrência de um dia da semana em um mês"""
    first_day = date(year, month, 1)
    days_ahead = (weekday - first_day.weekday()) % 7
    return first_day + timedelta(days=days_ahead)

def get_last_business_day_of_month(year, month):
    """Retorna o último dia útil do mês"""
    last_day = date(year, month, 1) + relativedelta(months=1, days=-1)
    # Retrocede até encontrar um dia útil (segunda a sexta)
    while last_day.weekday() >= 5:  # 5=sábado, 6=domingo
        last_day -= timedelta(days=1)
    return last_day

def get_first_business_day_of_month(year, month):
    """Retorna o primeiro dia útil do mês"""
    first_day = date(year, month, 1)
    # Avança até encontrar um dia útil
    while first_day.weekday() >= 5:
        first_day += timedelta(days=1)
    return first_day

def parse_pt_br_date(text, now):
    """Parser preciso para datas em português do Brasil"""
    text = text.lower().strip()
    current_date = now.date()
    
    # 1. Último domingo do mês ATUAL
    if "último domingo do mês" in text or "ultimo domingo do mes" in text:
        last_sunday = get_last_weekday_of_month(current_date.year, current_date.month, 6)  # 6=domingo
        return last_sunday
    
    # 2. Primeiro domingo do mês QUE VEM
    if "primeiro domingo do mês que vem" in text or "primeiro domingo do mes que vem" in text:
        next_month = current_date + relativedelta(months=1)
        first_sunday = get_first_weekday_of_month(next_month.year, next_month.month, 6)
        return first_sunday
    
    # 3. Último dia útil do mês ATUAL
    if "último dia útil do mês" in text or "ultimo dia util do mes" in text:
        last_business_day = get_last_business_day_of_month(current_date.year, current_date.month)
        return last_business_day
    
    # 4. Primeiro dia útil do mês QUE VEM
    if "primeiro dia útil do mês que vem" in text or "primeiro dia util do mes que vem" in text:
        next_month = current_date + relativedelta(months=1)
        first_business_day = get_first_business_day_of_month(next_month.year, next_month.month)
        return first_business_day
    
    # 5. Dias da semana específicos
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
        # Verifica se contém o nome do dia
        if day_name in text:
            # Verifica modificadores
            next_week = False
            this_week = False
            
            # Identifica "semana que vem"
            if any(phrase in text for phrase in ["semana que vem", "próxima semana", "proxima semana", "da semana que vem"]):
                next_week = True
            
            # Identifica "esta semana"
            if any(phrase in text for phrase in ["esta semana", "nesta semana", "desta semana"]):
                this_week = True
            
            if next_week:
                # Calcula o dia da próxima semana
                target_date = get_next_weekday(current_date, weekday_num)
                # Se já é depois do dia dessa semana, vai para a próxima
                if target_date <= current_date:
                    target_date += timedelta(weeks=1)
                return target_date
            else:
                # Próxima ocorrência do dia (pode ser esta semana ou próxima)
                return get_next_weekday(current_date, weekday_num)
    
    # 6. Datas relativas simples
    if "amanhã" in text or "amanha" in text:
        return current_date + timedelta(days=1)
    if "hoje" in text:
        return current_date
    if "depois de amanhã" in text or "depois de amanha" in text:
        return current_date + timedelta(days=2)
    
    return None

def parse_datetime(text):
    """Parser completo para datas em português"""
    now = datetime.now(tz)
    original_text = text
    text_lower = text.lower()
    
    # Caso especial: "daqui Xmin"
    if "daqui" in text_lower:
        min_match = re.search(r'daqui\s+(\d+)\s*min', text_lower)
        if min_match:
            minutes = int(min_match.group(1))
            return now + timedelta(minutes=minutes)
    
    # Detecta hora primeiro
    hour = now.hour
    minute = now.minute
    has_explicit_time = False
    
    # Padrões de hora
    hour_patterns = [
        r'(\d{1,2})[:h](\d{2})',  # 15:30 ou 15h30
        r'(\d{1,2})\s*[hH]',      # 15h
        r'(\d{1,2})\s*horas?',    # 15 horas
    ]
    
    extracted_hour = None
    extracted_minute = None
    
    for pattern in hour_patterns:
        hour_match = re.search(pattern, text_lower)
        if hour_match:
            extracted_hour = int(hour_match.group(1))
            extracted_minute = int(hour_match.group(2)) if hour_match.lastindex > 1 and hour_match.group(2) else 0
            has_explicit_time = True
            
            # Remove a parte da hora do texto
            text_lower = re.sub(pattern, '', text_lower, 1)
            text_lower = re.sub(r'\s+', ' ', text_lower).strip()
            break
    
    # Normaliza hora 24h se encontrou hora explícita
    if extracted_hour is not None:
        hour = extracted_hour
        minute = extracted_minute
        
        # Contexto para AM/PM
        if hour < 12:
            if 'tarde' in text_lower or 'noite' in text_lower or 'pm' in text_lower:
                hour += 12
        elif hour == 12:
            if 'manhã' in text_lower or 'manha' in text_lower or 'am' in text_lower:
                hour = 0
    
    # Remove palavras que não são parte da data
    text_clean = re.sub(r'\b(?:para|as|às|a|o|aos|daqui|em|no|na|de|do|da|as|às|com)\b', '', text_lower)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    
    # Tenta parsear data complexa em português
    target_date = parse_pt_br_date(text_clean, now)
    
    if not target_date:
        # Fallback para data atual
        target_date = now.date()
    
    # Combina data e hora
    try:
        remind_time = datetime.combine(target_date, datetime.min.time())
        remind_time = tz.localize(remind_time.replace(hour=hour, minute=minute))
        
        # Se não tinha hora explícita e é hoje, usa horário atual + 1h
        if not has_explicit_time and remind_time.date() == now.date() and remind_time < now:
            remind_time = remind_time.replace(hour=now.hour + 1, minute=0)
        
        # Se é hoje e a hora já passou, agenda para amanhã (só se não tiver data explícita)
        if remind_time.date() == now.date() and remind_time < now and not re.search(r'\d{1,2}[/-]\d{1,2}', original_text):
            remind_time += timedelta(days=1)
        
        return remind_time
    except Exception as e:
        logger.error(f"Erro ao combinar data e hora: {str(e)}")
        return now + timedelta(minutes=5)  # Fallback seguro

# ... (todas as rotas @app.route permanecem EXATAMENTE IGUAIS às do código anterior)
# Mantenha /webhook, /send-reminders, /debug-time, /listar, etc. IGUAIS

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "8000"))  # Garante string para int()
    app.run(host="0.0.0.0", port=port)
