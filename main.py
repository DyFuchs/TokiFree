import os
import sqlite3
import re
import logging
from datetime import datetime, timedelta
from flask import Flask, request
import requests
import pytz
import parsedatetime as pdt

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
# Parser de datas em linguagem natural (suporta português)
cal = pdt.Calendar(pdt.Constants(localeID="pt_BR"))

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

def parse_natural_language_date(text):
    """Parser genérico para datas em linguagem natural (português)"""
    now = datetime.now(tz)
    
    # Remove aspas e normaliza
    text = text.replace('"', '').strip()
    
    # Parse com parsedatetime (suporta português)
    try:
        # parsedatetime espera timestamp em segundos
        now_ts = now.timestamp()
        result = cal.parse(text, now_ts)
        
        # Resultado: (struct_time, status)
        if result[1] > 0:  # status > 0 = parsing bem-sucedido
            parsed_time = datetime(*result[0][:6])
            # Localiza no fuso horário
            if parsed_time.tzinfo is None:
                parsed_time = tz.localize(parsed_time)
            return parsed_time
    except Exception as e:
        logger.error(f"Erro no parsedatetime: {str(e)}")
    
    # Fallback para datas relativas simples
    if "amanhã" in text.lower():
        tomorrow = now.date() + timedelta(days=1)
        return tz.localize(datetime.combine(tomorrow, datetime.min.time()))
    
    if "hoje" in text.lower():
        return tz.localize(datetime.combine(now.date(), datetime.min.time()))
    
    return None

def parse_datetime(text):
    """Parser completo que combina hora explícita com data em linguagem natural"""
    now = datetime.now(tz)
    text_lower = text.lower()
    
    # Caso especial: "daqui Xmin"
    if "daqui" in text_lower:
        min_match = re.search(r'daqui\s+(\d+)\s*min', text_lower)
        if min_match:
            minutes = int(min_match.group(1))
            return now + timedelta(minutes=minutes)
    
    # Primeiro, tenta extrair hora explícita
    hour = now.hour
    minute = now.minute
    has_explicit_time = False
    
    hour_match = re.search(r'(\d{1,2})[:h](\d{2})?', text_lower)
    if hour_match:
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2)) if hour_match.group(2) else 0
        has_explicit_time = True
        
        # Normaliza hora 24h
        if hour < 12 and ('pm' in text_lower or 'tarde' in text_lower or 'noite' in text_lower):
            hour += 12
        elif hour == 12 and ('am' in text_lower or 'manhã' in text_lower):
            hour = 0
    
    # Remove a parte de hora do texto para parsing da data
    clean_text = re.sub(r'\d{1,2}[:h]\d{0,2}', '', text_lower)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # Parse da data em linguagem natural
    parsed_date = parse_natural_language_date(clean_text)
    
    if not parsed_date:
        # Fallback para data atual se não encontrar data explícita
        parsed_date = tz.localize(datetime.combine(now.date(), datetime.min.time()))
    
    # Combina data e hora
    try:
        result = parsed_date.replace(hour=hour, minute=minute)
        
        # Se não tinha hora explícita e é hoje, usa o horário atual
        if not has_explicit_time and result.date() == now.date() and result < now:
            result = result.replace(hour=now.hour, minute=now.minute)
        
        # Se é hoje e a hora já passou, agenda para amanhã (só se não tiver data explícita)
        if result.date() == now.date() and result < now and "hoje" not in text_lower and not re.search(r'\d{1,2}[/-]\d{1,2}', text):
            result += timedelta(days=1)
        
        return result
    except Exception as e:
        logger.error(f"Erro ao combinar data e hora: {str(e)}")
        return now + timedelta(minutes=5)  # Fallback seguro

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
            "• agendar \"Remédio\" 09/01/2026 12:05\n"
            "• agendar \"X\" daqui 5min\n"
            "• agendar \"Y\" \"próxima segunda-feira\" 9h\n"
            "• agendar \"Z\" \"terça-feira da semana que vem\" 10h\n"
            "• agendar \"Aniversário\" \"último domingo do mês\" 15h\n\n"
            f"⏰ Fuso horário: {TIMEZONE}\n\n"
            "🔧 Este bot precisa de um serviço externo para funcionar 24h.\n"
            "Acesse: https://cron-job.org e configure:\n"
            f"URL: https://tokifree-production.up.railway.app/send-reminders\n"
            "Frequência: every minute\n\n"
            "📋 COMANDOS ADICIONAIS:\n"
            "/listar - Ver todos os lembretes\n"
            "/cancelar \"descrição\" ou [ID] - Cancelar lembrete\n"
            "/cancelartodos - Cancelar todos\n"
            "/remarcar \"descrição\" ou [ID] [nova data]"
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
        # Extrai o argumento (pode ser ID ou descrição entre aspas)
        arg = text[9:].strip()
        
        # Tenta interpretar como ID primeiro
        if arg.isdigit():
            rid = int(arg)
            reminders = load_reminders()
            reminder = next((r for r in reminders if r["id"] == rid), None)
            
            if reminder:
                delete_reminder(rid)
                send_message(chat_id, f"✅ Lembrete ID={rid} cancelado com sucesso!\nDescrição: {reminder['desc']}")
            else:
                send_message(chat_id, f"❌ Lembrete ID={rid} não encontrado.")
        else:
            # Tenta extrair descrição entre aspas
            desc_match = re.search(r'"([^"]+)"', arg)
            if desc_match:
                desc = desc_match.group(1).strip()
                count = delete_reminder_by_desc(desc)
                if count > 0:
                    send_message(chat_id, f"✅ {count} lembrete(s) com descrição \"{desc}\" cancelado(s)!")
                else:
                    send_message(chat_id, f"❌ Nenhum lembrete encontrado com descrição \"{desc}\"")
            else:
                send_message(chat_id, "❌ Formato inválido para /cancelar\n\nUse:\n/cancelar \"descrição\"\nou\n/cancelar [ID]")
        
        return "OK"
    
    if text.lower() == "/cancelartodos":
        count = delete_all_reminders()
        send_message(chat_id, f"✅ Todos os {count} lembretes foram cancelados!")
        return "OK"
    
    if text.lower().startswith("/remarcar "):
        # Formato: /remarcar "descrição" nova_data_hora  ou  /remarcar ID nova_data_hora
        parts = text[10:].strip().split(maxsplit=1)
        if len(parts) < 2:
            send_message(chat_id, "❌ Formato inválido para /remarcar\n\nUse:\n/remarcar \"descrição\" [nova data/hora]\nou\n/remarcar [ID] [nova data/hora]")
            return "OK"
        
        identifier = parts[0]
        new_datetime_str = parts[1]
        
        # Tenta interpretar como ID
        if identifier.isdigit():
            rid = int(identifier)
            reminders = load_reminders()
            reminder = next((r for r in reminders if r["id"] == rid), None)
            
            if not reminder:
                send_message(chat_id, f"❌ Lembrete ID={rid} não encontrado.")
                return "OK"
            
            # Parseia a nova data/hora
            new_time = parse_datetime(new_datetime_str)
            if not new_time:
                send_message(chat_id, f"❌ Não consegui entender a nova  '{new_datetime_str}'")
                return "OK"
            
            update_reminder_time(rid, new_time)
            send_message(chat_id, 
                f"✅ Lembrete ID={rid} remarcado!\n"
                f"Descrição: {reminder['desc']}\n"
                f"Nova  {new_time.strftime('%d/%m/%Y %H:%M')}"
            )
        else:
            # Tenta extrair descrição entre aspas
            desc_match = re.search(r'"([^"]+)"', identifier)
            if desc_match:
                desc = desc_match.group(1).strip()
                # Parseia a nova data/hora
                new_time = parse_datetime(new_datetime_str)
                if not new_time:
                    send_message(chat_id, f"❌ Não consegui entender a nova  '{new_datetime_str}'")
                    return "OK"
                
                count = update_reminder_time_by_desc(desc, new_time)
                if count > 0:
                    send_message(chat_id, 
                        f"✅ {count} lembrete(s) com descrição \"{desc}\" remarcado(s)!\n"
                        f"Nova  {new_time.strftime('%d/%m/%Y %H:%M')}"
                    )
                else:
                    send_message(chat_id, f"❌ Nenhum lembrete encontrado com descrição \"{desc}\"")
            else:
                send_message(chat_id, "❌ Formato inválido para /remarcar\n\nUse:\n/remarcar \"descrição\" [nova data/hora]\nou\n/remarcar [ID] [nova data/hora]")
        
        return "OK"
    
    if text.lower().startswith("agendar "):
        full_input = text[8:].strip()
        
        # Extrai descrição entre aspas
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
        
        # Faz parsing
        parsed = parse_datetime(clean_input)
        
        if not parsed:
            send_message(chat_id, 
                f"❌ Não consegui entender a data em: '{clean_input}'\n\n"
                "✅ Exemplos válidos:\n"
                "• hoje 15h\n"
                "• amanhã 14:30\n"
                "• 09/01/2026 12:05\n"
                "• daqui 5min\n"
                "• \"próxima segunda-feira\" 9h\n"
                "• \"terça-feira da semana que vem\" 10h\n"
                "• \"último domingo do mês\" 15h"
            )
            return "OK"
        
        # Salva no banco
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
                message += f"\n🔄 Este lembrete é {r['recurrence']}"
            send_message(CHAT_ID, message)
            sent_count += 1
            
            # Reagenda recorrentes ANTES de deletar o original
            if r["recurrence"] == "daily":
                new_time = r["time"] + timedelta(days=1)
                save_reminder(r["desc"], new_time, "daily")
                logger.info(f"↻ Lembrete diário reagendado para: {new_time}")
            elif r["recurrence"] == "weekly":
                new_time = r["time"] + timedelta(weeks=1)
                save_reminder(r["desc"], new_time, "weekly")
                logger.info(f"↻ Lembrete semanal reagendado para: {new_time}")
            
            # Deleta o lembrete original
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
        f"URL para cron-job.org: https://{request.host}/send-reminders"
    )

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
