import os
import sqlite3
import re
import logging
from datetime import datetime, timedelta
from flask import Flask, request
import requests
import pytz

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

def parse_pt_br_date(text, now):
    """Parser especializado para datas em português do Brasil"""
    text = text.lower()
    
    # Mapeamento de dias da semana (0=segunda, 6=domingo)
    weekdays = {
        'segunda': 0, 'segunda-feira': 0, 'segunda feira': 0,
        'terça': 1, 'terca': 1, 'terça-feira': 1, 'terca-feira': 1, 'terça feira': 1, 'terca feira': 1,
        'quarta': 2, 'quarta-feira': 2, 'quarta feira': 2,
        'quinta': 3, 'quinta-feira': 3, 'quinta feira': 3,
        'sexta': 4, 'sexta-feira': 4, 'sexta feira': 4,
        'sábado': 5, 'sabado': 5, 'sábado-feira': 5, 'sabado-feira': 5,
        'domingo': 6
    }
    
    # 1. Detecta dias da semana com modificadores
    for day_name, weekday_num in weekdays.items():
        # Padrões para "próxima segunda", "segunda que vem", etc.
        patterns = [
            rf'pr[oó]xim[ao]?\s+{day_name}',
            rf'{day_name}\s+que\s+ve[mn]',
            rf'pr[oó]x[ao]?\s+{day_name}',
            rf'{day_name}\s+da\s+semana\s+que\s+ve[mn]'
        ]
        
        for pattern in patterns:
            if re.search(pattern, text):
                # Calcula quantos dias até o próximo dia da semana especificado
                days_ahead = (weekday_num - now.weekday() + 7) % 7
                # Se for hoje ou já passou esta semana, vai para a próxima semana
                if days_ahead <= 0:
                    days_ahead += 7
                # Se tiver "que vem" ou "próxima", adiciona mais 7 dias
                if re.search(r'que\s+ve[mn]|pr[oó]xim[ao]', text):
                    days_ahead += 7
                return now.date() + timedelta(days=days_ahead)
    
    # 2. Datas relativas simples
    if "amanhã" in text or "amanha" in text:
        return now.date() + timedelta(days=1)
    if "hoje" in text:
        return now.date()
    if "depois de amanhã" in text or "depois de amanha" in text:
        return now.date() + timedelta(days=2)
    
    # 3. Último dia útil do mês
    if "último dia útil" in text or "ultimo dia util" in text or "ultimo dia útil" in text:
        # Encontra o último dia do mês atual
        next_month = now.replace(day=28) + timedelta(days=4)
        last_day = next_month - timedelta(days=next_month.day)
        
        # Se for final de semana, retrocede para sexta-feira
        while last_day.weekday() >= 5:  # 5=sábado, 6=domingo
            last_day -= timedelta(days=1)
        return last_day
    
    # 4. Primeiro dia útil do mês
    if "primeiro dia útil" in text or "primeiro dia util" in text:
        first_day = now.replace(day=1).date()
        # Se for final de semana, avança para segunda-feira
        while first_day.weekday() >= 5:
            first_day += timedelta(days=1)
        return first_day
    
    # 5. Última sexta-feira do mês
    if "última sexta-feira do mês" in text or "ultima sexta feira do mes" in text:
        # Encontra o último dia do mês
        next_month = now.replace(day=28) + timedelta(days=4)
        last_day = next_month - timedelta(days=next_month.day)
        
        # Retrocede até encontrar a última sexta-feira
        while last_day.weekday() != 4:  # 4=sexta-feira
            last_day -= timedelta(days=1)
        return last_day
    
    # 6. Primeira segunda-feira do mês
    if "primeira segunda-feira do mês" in text or "primeira segunda feira do mes" in text:
        first_day = now.replace(day=1).date()
        # Avança até encontrar a primeira segunda-feira
        while first_day.weekday() != 0:  # 0=segunda-feira
            first_day += timedelta(days=1)
        return first_day
    
    return None

def parse_datetime(text):
    """Parser completo para datas em português"""
    now = datetime.now(tz)
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
    
    # Padrões de hora: 15h, 15:30, 15h30, às 15h, as 15:30
    hour_patterns = [
        r'(\d{1,2})[:h](\d{2})',  # 15:30 ou 15h30
        r'(\d{1,2})\s*[hH]',      # 15h
        r'(\d{1,2})\s*horas?',    # 15 horas
        r'(\d{1,2})\s*[:h]\s*(\d{2})?\s*(?:h|horas?)?', # variações
    ]
    
    for pattern in hour_patterns:
        hour_match = re.search(pattern, text_lower)
        if hour_match:
            hour = int(hour_match.group(1))
            minute = int(hour_match.group(2)) if len(hour_match.groups()) > 1 and hour_match.group(2) else 0
            has_explicit_time = True
            
            # Normaliza hora 24h
            if hour < 12 and ('pm' in text_lower or 'tarde' in text_lower or 'noite' in text_lower):
                hour += 12
            elif hour == 12 and ('am' in text_lower or 'manhã' in text_lower or 'manha' in text_lower):
                hour = 0
            
            # Remove a parte da hora do texto para análise da data
            text_lower = re.sub(pattern, '', text_lower)
            text_lower = re.sub(r'\s+', ' ', text_lower).strip()
            break
    
    # Remove palavras que não são parte da data
    text_clean = re.sub(r'\b(?:para|as|às|a|o|aos|daqui|em|no|na)\b', '', text_lower)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    
    # Tenta parsear data complexa em português
    target_date = parse_pt_br_date(text_clean, now)
    
    if not target_date:
        # Fallback para data atual se não encontrar data explícita
        target_date = now.date()
    
    # Combina data e hora
    try:
        remind_time = datetime.combine(target_date, datetime.min.time())
        remind_time = tz.localize(remind_time.replace(hour=hour, minute=minute))
        
        # Se não tinha hora explícita e é hoje, usa o horário atual + 1h como padrão
        if not has_explicit_time and remind_time.date() == now.date() and remind_time < now:
            remind_time = remind_time.replace(hour=now.hour + 1, minute=0)
        
        # Se é hoje e a hora já passou, agenda para amanhã (só se não tiver data explícita)
        if remind_time.date() == now.date() and remind_time < now and not re.search(r'\d{1,2}[/-]\d{1,2}', text):
            remind_time += timedelta(days=1)
        
        return remind_time
    except Exception as e:
        logger.error(f"Erro ao combinar data e hora: {str(e)}")
        return now + timedelta(minutes=5)  # Fallback seguro

# ... (todos os outros endpoints permanecem IGUAIS, incluindo /webhook, /send-reminders, etc.)
# Mantenha exatamente o mesmo código a partir de @app.route("/webhook", methods=["POST"]) até o final do arquivo

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
