import os
import re
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import dateparser
from google import genai
from google.genai import types

import database as db
import calendar_service

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

scheduler = AsyncIOScheduler()
gemini_client = genai.Client(api_key=GEMINI_KEY)
MODELO = "gemini-3.1-flash-lite"

EMOJI_PRIORIDAD = {"alta": "🔴", "media": "🟡", "baja": "🟢"}

async def post_init(app):
    scheduler.start()

async def crear_recordatorio(chat_id: int, texto: str, fecha_texto: str, categoria: str = "general", prioridad: str = "media") -> str:
    fecha_texto_limpia = fecha_texto.strip()
    for articulo in ["el ", "El ", "la ", "La ", "los ", "Los ", "las ", "Las ", "en ", "En "]:
        if fecha_texto_limpia.startswith(articulo):
            fecha_texto_limpia = fecha_texto_limpia[len(articulo):]
            break

    # Convertir "de la mañana/tarde/noche" a am/pm para evitar ambigüedad con "mañana" (tomorrow)
    fecha_texto_limpia = re.sub(r"\s+de\s+la\s+mañana\b", " am", fecha_texto_limpia, flags=re.IGNORECASE)
    fecha_texto_limpia = re.sub(r"\s+de\s+la\s+tarde\b", " pm", fecha_texto_limpia, flags=re.IGNORECASE)
    fecha_texto_limpia = re.sub(r"\s+de\s+la\s+noche\b", " pm", fecha_texto_limpia, flags=re.IGNORECASE)

    fecha_hora = dateparser.parse(
        fecha_texto_limpia,
        languages=["es"],
        settings={"PREFER_DATES_FROM": "future"}
    )

    if not fecha_hora:
        return f"No pude entender la fecha '{fecha_texto}' 😕 Probá con algo como 'mañana a las 9am'."

    if prioridad not in ("alta", "media", "baja"):
        prioridad = "media"
    if not categoria:
        categoria = "general"

    google_event_id = calendar_service.crear_evento(texto.strip(), fecha_hora)

    recordatorio_id = db.agregar_recordatorio(chat_id, texto.strip(), fecha_hora, categoria, prioridad, google_event_id)

    scheduler.add_job(
        enviar_recordatorio,
        "date",
        run_date=fecha_hora,
        args=[chat_id, texto.strip(), recordatorio_id],
        id=f"recordatorio_{recordatorio_id}"
    )

    calendario_txt = "\n📆 Sincronizado con Google Calendar" if google_event_id else ""

    return (
        f"✅ Recordatorio guardado (#{recordatorio_id}):\n"
        f"\"{texto.strip()}\"\n"
        f"📅 {fecha_hora.strftime('%d/%m/%Y %H:%M')}\n"
        f"🏷️ {categoria} | {EMOJI_PRIORIDAD.get(prioridad, '🟡')} {prioridad}"
        f"{calendario_txt}"
    )

async def enviar_recordatorio(chat_id: int, texto: str, recordatorio_id: int):
    app = Application.builder().token(TOKEN).build()
    await app.bot.send_message(chat_id=chat_id, text=f"🔔 Recordatorio: {texto}")
    db.marcar_enviado(recordatorio_id)

def listar_recordatorios(chat_id: int) -> str:
    recordatorios = db.obtener_recordatorios(chat_id)
    if not recordatorios:
        return "No tenés recordatorios pendientes 📭"

    mensaje = "📋 Tus recordatorios:\n\n"
    for r_id, texto, fecha_hora, categoria, prioridad in recordatorios:
        fecha = datetime.fromisoformat(fecha_hora)
        emoji = EMOJI_PRIORIDAD.get(prioridad, "🟡")
        mensaje += (
            f"{emoji} #{r_id} — {texto}\n"
            f"📅 {fecha.strftime('%d/%m/%Y %H:%M')} | 🏷️ {categoria}\n\n"
        )
    return mensaje

def eliminar_recordatorio_por_id(chat_id: int, recordatorio_id: int) -> str:
    event_id = db.obtener_google_event_id(recordatorio_id, chat_id)
    eliminado = db.eliminar_recordatorio(recordatorio_id, chat_id)
    if eliminado:
        try:
            scheduler.remove_job(f"recordatorio_{recordatorio_id}")
        except Exception:
            pass
        if event_id:
            calendar_service.eliminar_evento(event_id)
        return f"🗑️ Recordatorio #{recordatorio_id} eliminado."
    return "No encontré ese recordatorio."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! 👋 Soy tu asistente personal.\n\n"
        "Podés escribirme o mandarme un audio, como si le hablaras a una persona. Ej:\n"
        "• \"recordame comprar pan mañana a las 9am, es urgente\"\n"
        "• \"qué recordatorios tengo\"\n"
        "• \"eliminá el recordatorio 2\"\n\n"
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
    resultado = await crear_recordatorio(update.effective_chat.id, texto, fecha_texto)
    await update.message.reply_text(resultado)

async def mis_recordatorios_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(listar_recordatorios(update.effective_chat.id))

async def eliminar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usá: /eliminar [id]\nEj: /eliminar 3")
        return
    try:
        recordatorio_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El id debe ser un número.")
        return
    await update.message.reply_text(
        eliminar_recordatorio_por_id(update.effective_chat.id, recordatorio_id)
    )

PROMPT_SISTEMA = """Sos el cerebro de un bot de Telegram asistente personal. Vas a recibir un mensaje (texto o audio hablado) del usuario. Analizalo y respondé SOLO con un JSON (sin markdown, sin texto extra, sin explicaciones) con esta estructura exacta:

{
  "accion": "crear_recordatorio" | "listar" | "eliminar" | "charla",
  "texto": "string, solo si accion es crear_recordatorio: qué hay que recordar",
  "fecha_texto": "string, solo si accion es crear_recordatorio: la fecha/hora en texto natural tal cual la dijo el usuario",
  "categoria": "string, solo si accion es crear_recordatorio: una palabra corta como 'trabajo', 'personal', 'salud', 'estudio', 'general', la que mejor aplique según el contexto",
  "prioridad": "'alta' | 'media' | 'baja', solo si accion es crear_recordatorio: inferí la urgencia según palabras como 'urgente', 'importante', 'cuando pueda', o el tipo de tarea. Si no hay pistas, usá 'media'",
  "id": número entero, solo si accion es eliminar,
  "respuesta": "string, solo si accion es charla: tu respuesta natural y breve"
}

Ejemplos:
Usuario: "recordame comprar pan mañana a las 9am"
{"accion": "crear_recordatorio", "texto": "comprar pan", "fecha_texto": "mañana a las 9am", "categoria": "personal", "prioridad": "media"}

Usuario: "urgente, recordame pagar el arriendo el viernes, es importante"
{"accion": "crear_recordatorio", "texto": "pagar el arriendo", "fecha_texto": "el viernes", "categoria": "personal", "prioridad": "alta"}

Usuario: "recordame la reunión con el equipo mañana a las 10am"
{"accion": "crear_recordatorio", "texto": "reunión con el equipo", "fecha_texto": "mañana a las 10am", "categoria": "trabajo", "prioridad": "media"}

Usuario: "qué recordatorios tengo"
{"accion": "listar"}

Usuario: "eliminá el recordatorio 2"
{"accion": "eliminar", "id": 2}

Usuario: "hola como estas"
{"accion": "charla", "respuesta": "¡Todo bien! ¿En qué te ayudo hoy?"}

Si el mensaje es un audio, primero entendé qué dijo la persona y después aplicá la misma lógica de arriba.

Respondé ÚNICAMENTE con el objeto JSON, nada más."""

def extraer_json(texto: str) -> dict:
    texto = texto.strip()
    decoder = json.JSONDecoder()
    datos, _ = decoder.raw_decode(texto)
    return datos

async def ejecutar_accion(datos: dict, chat_id: int) -> str:
    accion = datos.get("accion")

    if accion == "crear_recordatorio":
        return await crear_recordatorio(
            chat_id,
            datos.get("texto", ""),
            datos.get("fecha_texto", ""),
            datos.get("categoria", "general"),
            datos.get("prioridad", "media")
        )
    elif accion == "listar":
        return listar_recordatorios(chat_id)
    elif accion == "eliminar":
        rid = datos.get("id")
        if rid is None:
            return "¿Cuál recordatorio querés eliminar? Decime el número."
        return eliminar_recordatorio_por_id(chat_id, int(rid))
    elif accion == "charla":
        return datos.get("respuesta", "¿En qué te ayudo?")
    else:
        return "No entendí bien eso, ¿podés reformularlo?"

async def procesar_lenguaje_natural(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje_usuario = update.message.text
    chat_id = update.effective_chat.id

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        response = gemini_client.models.generate_content(
            model=MODELO,
            contents=f"{PROMPT_SISTEMA}\n\nUsuario: \"{mensaje_usuario}\"",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        datos = extraer_json(response.text)
    except Exception as e:
        print("⚠️ Error con Gemini:", e)
        await update.message.reply_text("Tuve un problema entendiendo eso 😅 Probá de nuevo.")
        return

    await update.message.reply_text(await ejecutar_accion(datos, chat_id))

async def procesar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        voice = update.message.voice
        archivo = await context.bot.get_file(voice.file_id)
        audio_bytes = await archivo.download_as_bytearray()

        response = gemini_client.models.generate_content(
            model=MODELO,
            contents=[
                PROMPT_SISTEMA,
                types.Part.from_bytes(data=bytes(audio_bytes), mime_type="audio/ogg"),
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        datos = extraer_json(response.text)
    except Exception as e:
        print("⚠️ Error procesando audio:", e)
        await update.message.reply_text("No pude entender el audio 😅 Probá de nuevo o escribime el mensaje.")
        return

    await update.message.reply_text(await ejecutar_accion(datos, chat_id))

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