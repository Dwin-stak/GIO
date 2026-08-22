import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import database as db
import nucleo

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

scheduler = AsyncIOScheduler()


async def post_init(app):
    scheduler.start()
    scheduler.add_job(
        enviar_resumen_diario,
        CronTrigger(hour=6, minute=0, timezone="America/Bogota"),
        id="resumen_diario",
        replace_existing=True
    )


async def enviar_recordatorio(chat_id: int, texto: str, recordatorio_id: int):
    app = Application.builder().token(TOKEN).build()
    async with app:
        await app.bot.send_message(chat_id=chat_id, text=f"🔔 Recordatorio: {texto}")
    db.marcar_enviado(recordatorio_id)


def programar_push(chat_id: int, recordatorio_id: int, texto: str, fecha_hora: datetime):
    """on_creado de nucleo.crear_recordatorio: programa el aviso por Telegram a la hora indicada."""
    scheduler.add_job(
        enviar_recordatorio,
        "date",
        run_date=fecha_hora,
        args=[chat_id, texto, recordatorio_id],
        id=f"recordatorio_{recordatorio_id}"
    )


def cancelar_push(recordatorio_id: int):
    """on_eliminado de nucleo.eliminar_recordatorio_por_id: cancela el aviso programado."""
    try:
        scheduler.remove_job(f"recordatorio_{recordatorio_id}")
    except Exception:
        pass


async def enviar_resumen_diario():
    app = Application.builder().token(TOKEN).build()
    recordatorios_hoy = db.obtener_recordatorios_de_hoy()

    por_chat = {}
    for chat_id, r_id, texto, fecha_hora, categoria, prioridad in recordatorios_hoy:
        por_chat.setdefault(chat_id, []).append((r_id, texto, fecha_hora, categoria, prioridad))

    async with app:
        for chat_id, items in por_chat.items():
            mensaje = "☀️ ¡Buenos días! Esto tenés para hoy:\n\n"
            for r_id, texto, fecha_hora, categoria, prioridad in items:
                fecha = datetime.fromisoformat(fecha_hora)
                emoji = nucleo.EMOJI_PRIORIDAD.get(prioridad, "🟡")
                mensaje += f"{emoji} {fecha.strftime('%H:%M')} — {texto} ({categoria})\n"
            await app.bot.send_message(chat_id=chat_id, text=mensaje)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! 👋 Soy tu asistente personal.\n\n"
        "Podés escribirme o mandarme un audio, como si le hablaras a una persona. Ej:\n"
        "• \"recordame comprar pan mañana a las 9am, es urgente\"\n"
        "• \"qué recordatorios tengo\"\n"
        "• \"cuál es el próximo partido del Junior\"\n"
        "• \"cómo está el clima hoy\"\n\n"
        "O usar comandos:\n"
        "📌 /recordar [texto] el [fecha/hora]\n"
        "📋 /misrecordatorios\n"
        "🗑️ /eliminar [id]"
    )


async def recordar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_completo = " ".join(context.args)
    if " el " not in texto_completo:
        await update.message.reply_text(
            "Formato: /recordar [texto] el [fecha/hora]\n"
            "Ejemplo: /recordar comprar pan el mañana a las 9am"
        )
        return
    texto, fecha_texto = texto_completo.rsplit(" el ", 1)
    resultado = await nucleo.crear_recordatorio(update.effective_chat.id, texto, fecha_texto, on_creado=programar_push)
    await update.message.reply_text(resultado)


async def mis_recordatorios_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(nucleo.listar_recordatorios(update.effective_chat.id))


async def eliminar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usá: /eliminar [id]\nEj: /eliminar 3")
        return
    try:
        recordatorio_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El id debe ser un número.")
        return
    resultado = nucleo.eliminar_recordatorio_por_id(update.effective_chat.id, recordatorio_id, on_eliminado=cancelar_push)
    await update.message.reply_text(resultado)


async def manejar_mensaje_telegram(update: Update, chat_id: int, mensaje_usuario: str):
    resultado = await nucleo.manejar_mensaje(chat_id, mensaje_usuario, on_creado=programar_push, on_eliminado=cancelar_push)
    await update.message.reply_text(resultado["texto"])
    if resultado.get("video_id"):
        await update.message.reply_text(f"https://www.youtube.com/watch?v={resultado['video_id']}")


async def procesar_lenguaje_natural(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await manejar_mensaje_telegram(update, chat_id, update.message.text)


async def procesar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        voice = update.message.voice
        archivo = await context.bot.get_file(voice.file_id)
        audio_bytes = await archivo.download_as_bytearray()

        mensaje_usuario = nucleo.transcribir_audio(bytes(audio_bytes), filename="audio.ogg")

        if not mensaje_usuario:
            await update.message.reply_text("No pude entender el audio 😅 Probá de nuevo o escribime el mensaje.")
            return

    except Exception as e:
        print("⚠️ Error transcribiendo audio:", e)
        await update.message.reply_text("No pude entender el audio 😅 Probá de nuevo o escribime el mensaje.")
        return

    await manejar_mensaje_telegram(update, chat_id, mensaje_usuario)


def main():
    db.init_db()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("recordar", recordar_cmd))
    app.add_handler(CommandHandler("misrecordatorios", mis_recordatorios_cmd))
    app.add_handler(CommandHandler("eliminar", eliminar_cmd))
    app.add_handler(MessageHandler(filters.VOICE, procesar_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_lenguaje_natural))

    print("Bot corriendo... (Ctrl+C para detener)")
    app.run_polling()


if __name__ == "__main__":
    main()
