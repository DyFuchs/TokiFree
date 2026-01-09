import os
import json
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import dateparser

# Configurações
BOT_TOKEN = "8504622577:AAFIdt9CI9boPlGbnYwDWvIu2PEH3yjzdLw"
CHAT_ID = 1378751322
DB_PATH = "reminders.db"

# Inicializa banco SQLite
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            remind_time TEXT,
            recurrence TEXT  -- daily, weekly, monthly ou null
        )
    """)
    conn.commit()
    conn.close()

# Salva lembrete no banco
def save_reminder(desc: str, remind_time: datetime, recurrence: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO reminders (description, remind_time, recurrence) VALUES (?, ?, ?)",
              (desc, remind_time.isoformat(), recurrence))
    conn.commit()
    conn.close()

# Carrega todos os lembretes do banco
def load_reminders():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, description, remind_time, recurrence FROM reminders")
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "desc": r[1],
            "time": datetime.fromisoformat(r[2]),
            "recurrence": r[3]
        }
        for r in rows
    ]

# Remove lembrete pelo ID
def delete_reminder(rid: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

# Usa IA para interpretar comando (modelo leve via Hugging Face)
def parse_with_ai(text: str):
    # Exemplo com modelo de extração de intenção + entidade (substitua conforme necessidade)
    # Aqui usamos regras simples + dateparser como fallback barato
    desc = text
    recurrence = None

    # Detecta recorrência básica
    if any(kw in text.lower() for kw in ["todo dia", "diariamente"]):
        recurrence = "daily"
        desc = text.lower().replace("todo dia", "").replace("diariamente", "").strip()
    elif "toda semana" in text.lower():
        recurrence = "weekly"
        desc = text.lower().replace("toda semana", "").strip()

    # Tenta extrair data/hora com dateparser
    now = datetime.now()
    parsed = dateparser.parse(desc, settings={'RELATIVE_BASE': now, 'PREFER_DATES_FROM': 'future'})
    if parsed:
        # Remove a parte reconhecida da descrição (heurística simples)
        desc_clean = desc
        for fmt in ["%d/%m", "%d-%m", "%Y", "%H:%M", "amanhã", "hoje", "sexta", "segunda"]:
            try:
                test_str = parsed.strftime(fmt)
                if test_str in desc:
                    desc_clean = desc.replace(test_str, "")
            except:
                pass
        desc = " ".join(desc_clean.split())
        return desc.strip(), parsed, recurrence
    else:
        return None, None, None

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Oi! Envie uma mensagem como:\n"
        "• 'agendar Dentista amanhã às 15h'\n"
        "• 'agendar Tomar remédio todo dia às 8h'\n"
        "• 'agendar Reunião toda semana sexta 14h'"
    )

# Processa mensagens
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.lower().startswith("agendar "):
        await update.message.reply_text("Use 'agendar ...' para criar lembretes.")
        return

    user_input = text[8:].strip()
    desc, remind_time, recurrence = parse_with_ai(user_input)

    if not remind_time:
        await update.message.reply_text("Não entendi a data/hora. Tente: 'agendar X amanhã 15h'")
        return

    save_reminder(desc, remind_time, recurrence)
    rec_str = f" (🔁 {recurrence})" if recurrence else ""
    await update.message.reply_text(
        f"Lembrete salvo!{rec_str}\n⏰ {desc}\n📅 {remind_time.strftime('%d/%m/%Y %H:%M')}"
    )

# Envia lembretes pendentes e reagenda recorrentes
def send_reminders(app):
    now = datetime.now()
    reminders = load_reminders()
    to_send = []
    for r in reminders:
        if r["time"] <= now:
            to_send.append(r)
            delete_reminder(r["id"])
            # Reagenda se recorrente
            if r["recurrence"] == "daily":
                new_time = r["time"] + timedelta(days=1)
                save_reminder(r["desc"], new_time, "daily")
            elif r["recurrence"] == "weekly":
                new_time = r["time"] + timedelta(weeks=1)
                save_reminder(r["desc"], new_time, "weekly")
    for r in to_send:
        msg = f"🔔 Lembrete: {r['desc']}"
        app.bot.send_message(chat_id=CHAT_ID, text=msg)

# Inicialização
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BlockingScheduler()
    scheduler.add_job(send_reminders, 'interval', minutes=1, args=[app])

    import threading
    bot_thread = threading.Thread(target=lambda: app.run_polling(drop_pending_updates=True))
    bot_thread.start()

    try:
        scheduler.start()
    except KeyboardInterrupt:
        scheduler.shutdown()