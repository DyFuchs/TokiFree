import os
import sqlite3
import re
import logging
from datetime import datetime, timedelta
from datetime import datetime, timedelta, date
from flask import Flask, request
import requests
import pytz
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
@@ -82,18 +83,132 @@
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

def calculate_complex_date(text, now):
    """Calcula datas complexas como 'próxima segunda', 'último domingo do mês'"""
    text_lower = text.lower()
    current_weekday = now.weekday()  # 0=segunda, 6=domingo
    
    # Próxima segunda-feira
    if "próxima segunda" in text_lower or "proxima segunda" in text_lower:
        days_ahead = (7 - current_weekday) % 7
        if days_ahead == 0:  # Hoje é segunda
            days_ahead = 7
        return now.date() + timedelta(days=days_ahead)
    
    # Quarta-feira da semana que vem
    if "quarta-feira da semana que vem" in text_lower or "quarta da semana que vem" in text_lower:
        days_ahead = (2 - current_weekday) % 7  # 2 = quarta-feira
        if days_ahead <= 0:  # Já passou esta semana
            days_ahead += 7
        return now.date() + timedelta(days=days_ahead + 7)
    
    # Último domingo do mês que vem
    if "último domingo do mês que vem" in text_lower or "ultimo domingo do mes que vem" in text_lower:
        # Primeiro, encontra o primeiro dia do próximo mês
        next_month = now.replace(day=28) + timedelta(days=4)  # Avança para o próximo mês
        first_day_next_month = next_month.replace(day=1)
        
        # Encontra o último dia do próximo mês
        last_day_next_month = (first_day_next_month + relativedelta(months=1)) - timedelta(days=1)
        
        # Encontra o último domingo
        last_sunday = last_day_next_month
        while last_sunday.weekday() != 6:  # 6 = domingo
            last_sunday -= timedelta(days=1)
        
        return last_sunday
    
    # Próxima sexta-feira
    if "próxima sexta" in text_lower or "proxima sexta" in text_lower:
        days_ahead = (4 - current_weekday) % 7  # 4 = sexta-feira
        if days_ahead == 0:  # Hoje é sexta
            days_ahead = 7
        return now.date() + timedelta(days=days_ahead)
    
    # Primeiro dia do próximo mês
    if "primeiro dia do próximo mês" in text_lower or "primeiro dia do proximo mes" in text_lower:
        return (now.replace(day=1) + relativedelta(months=1)).date()
    
    # Último dia do mês atual
    if "último dia do mês" in text_lower or "ultimo dia do mes" in text_lower:
        return (now.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).date()
    
    return None

def parse_datetime(text):
    """Parser robusto com fuso horário"""
    """Parser robusto com suporte a datas complexas"""
    now = datetime.now(tz)
    text_lower = text.lower()

    # Caso especial: "daqui Xmin"
    if "daqui" in text_lower:
        min_match = re.search(r'daqui\s+(\d+)\s*min', text_lower)
        if min_match:
            minutes = int(min_match.group(1))
            return now + timedelta(minutes=minutes)

    # Caso especial: datas complexas
    complex_date = calculate_complex_date(text_lower, now)
    if complex_date:
        # Usa a hora atual se não especificada
        hour = now.hour
        minute = now.minute
        
        hour_match = re.search(r'(\d{1,2})[:h](\d{2})?', text_lower)
        if hour_match:
            hour = int(hour_match.group(1))
            minute = int(hour_match.group(2)) if hour_match.group(2) else 0
            if hour < 12 and ('pm' in text_lower or 'tarde' in text_lower or 'noite' in text_lower):
                hour += 12
            elif hour == 12 and ('am' in text_lower or 'manhã' in text_lower):
                hour = 0
        
        try:
            remind_time = datetime.combine(complex_date, datetime.min.time())
            remind_time = tz.localize(remind_time.replace(hour=hour, minute=minute))
            return remind_time
        except Exception as e:
            logger.error(f"Erro ao combinar data complexa: {str(e)}")
    
    # Detecta hora
    hour = now.hour
    minute = now.minute
@@ -160,15 +275,129 @@
            "• agendar \"Dentista\" hoje 15h\n"
            "• agendar \"Reunião\" amanhã 14:30\n"
            "• agendar \"Remédio\" 09/01/2026 12:05\n"
            "• agendar \"X\" daqui 5min\n\n"
            "• agendar \"X\" daqui 5min\n"
            "• agendar \"Y\" \"próxima segunda-feira\" 9h\n\n"
            f"⏰ Fuso horário: {TIMEZONE}\n\n"
            "🔧 Este bot precisa de um serviço externo para funcionar 24h.\n"
            "Acesse: https://cron-job.org e configure:\n"
            f"URL: https://tokifree-production.up.railway.app/send-reminders\n"
            "Frequência: every minute"
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
                send_message(chat_id, f"❌ Não consegui entender a nova data: '{new_datetime_str}'")
                return "OK"
            
            update_reminder_time(rid, new_time)
            send_message(chat_id, 
                f"✅ Lembrete ID={rid} remarcado!\n"
                f"Descrição: {reminder['desc']}\n"
                f"Nova data: {new_time.strftime('%d/%m/%Y %H:%M')}"
            )
        else:
            # Tenta extrair descrição entre aspas
            desc_match = re.search(r'"([^"]+)"', identifier)
            if desc_match:
                desc = desc_match.group(1).strip()
                # Parseia a nova data/hora
                new_time = parse_datetime(new_datetime_str)
                if not new_time:
                    send_message(chat_id, f"❌ Não consegui entender a nova data: '{new_datetime_str}'")
                    return "OK"
                
                count = update_reminder_time_by_desc(desc, new_time)
                if count > 0:
                    send_message(chat_id, 
                        f"✅ {count} lembrete(s) com descrição \"{desc}\" remarcado(s)!\n"
                        f"Nova data: {new_time.strftime('%d/%m/%Y %H:%M')}"
                    )
                else:
                    send_message(chat_id, f"❌ Nenhum lembrete encontrado com descrição \"{desc}\"")
            else:
                send_message(chat_id, "❌ Formato inválido para /remarcar\n\nUse:\n/remarcar \"descrição\" [nova data/hora]\nou\n/remarcar [ID] [nova data/hora]")
        
        return "OK"
    
    if text.lower().startswith("agendar "):
        full_input = text[8:].strip()

@@ -206,96 +435,83 @@
                f"❌ Não consegui entender a data em: '{clean_input}'\n\n"
                "✅ Exemplos válidos:\n"
                "• hoje 15h\n"
                "• amanhã 14:30\n"
                "• 09/01/2026 12:05\n"
                "• daqui 5min"
                "• daqui 5min\n"
                "• \"próxima segunda-feira\" 9h\n"
                "• \"último domingo do mês que vem\" 10h"
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

    if text.lower() == "/listar":
        reminders = load_reminders()
        now = datetime.now(tz)
        
        if not reminders:
            send_message(chat_id, "📭 Nenhum lembrete agendado.")
            return "OK"
        
        message = "📋 LEMBRETES AGENDADOS:\n\n"
        for r in reminders:
            status = "✅ ATIVO" if r["time"] > now else "⏳ PENDENTE"
            message += f"ID: {r['id']}\nDescrição: {r['desc']}\nData: {r['time'].strftime('%d/%m/%Y %H:%M')}\nStatus: {status}\n\n"
        
        message += f"\n⏰ Horário atual ({TIMEZONE}): {now.strftime('%d/%m/%Y %H:%M')}"
        send_message(chat_id, message)
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
