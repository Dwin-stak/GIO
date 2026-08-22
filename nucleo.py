"""Cerebro del asistente: entiende lenguaje natural, busca en la web y maneja recordatorios.
No sabe nada de Telegram ni de la web — bot.py y web_app.py lo usan como adaptadores."""

import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
from tavily import TavilyClient
import dateparser
import yt_dlp

import database as db
import calendar_service

load_dotenv()
GROQ_KEY = os.getenv("GROQ_API_KEY")
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

groq_client = Groq(api_key=GROQ_KEY)
tavily_client = TavilyClient(api_key=TAVILY_KEY)

MODELO_CHAT = "llama-3.3-70b-versatile"
MODELO_AUDIO = "whisper-large-v3"

EMOJI_PRIORIDAD = {"alta": "🔴", "media": "🟡", "baja": "🟢"}

# Memoria de conversación en RAM: chat_id -> lista de últimas líneas (usuario/asistente)
HISTORIAL = {}
MAX_HISTORIAL = 10  # últimos 5 intercambios (usuario + asistente)


def agregar_historial(chat_id, rol: str, texto: str):
    HISTORIAL.setdefault(chat_id, [])
    HISTORIAL[chat_id].append(f"{rol}: {texto}")
    HISTORIAL[chat_id] = HISTORIAL[chat_id][-MAX_HISTORIAL:]


def obtener_contexto(chat_id) -> str:
    return "\n".join(HISTORIAL.get(chat_id, [])) or "(sin conversación previa)"


async def crear_recordatorio(chat_id, texto: str, fecha_texto: str, categoria: str = "general", prioridad: str = "media", on_creado=None) -> str:
    """on_creado(chat_id, recordatorio_id, texto, fecha_hora), opcional: para que el canal (Telegram)
    programe el aviso push. Si no se pasa, el recordatorio queda guardado y sincronizado con Calendar
    pero sin aviso push (es el caso de la web, que no tiene push propio todavía)."""
    fecha_texto_limpia = fecha_texto.strip()
    for articulo in ["el ", "El ", "la ", "La ", "los ", "Los ", "las ", "Las ", "en ", "En "]:
        if fecha_texto_limpia.startswith(articulo):
            fecha_texto_limpia = fecha_texto_limpia[len(articulo):]
            break

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

    if on_creado:
        on_creado(chat_id, recordatorio_id, texto.strip(), fecha_hora)

    calendario_txt = "\n📆 Sincronizado con Google Calendar" if google_event_id else ""

    return (
        f"✅ Recordatorio guardado (#{recordatorio_id}):\n"
        f"\"{texto.strip()}\"\n"
        f"📅 {fecha_hora.strftime('%d/%m/%Y %H:%M')}\n"
        f"🏷️ {categoria} | {EMOJI_PRIORIDAD.get(prioridad, '🟡')} {prioridad}"
        f"{calendario_txt}"
    )


def listar_recordatorios(chat_id) -> str:
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


def eliminar_recordatorio_por_id(chat_id, recordatorio_id: int, on_eliminado=None) -> str:
    """on_eliminado(recordatorio_id), opcional: para que el canal cancele el aviso push programado."""
    event_id = db.obtener_google_event_id(recordatorio_id, chat_id)
    eliminado = db.eliminar_recordatorio(recordatorio_id, chat_id)
    if eliminado:
        if on_eliminado:
            on_eliminado(recordatorio_id)
        if event_id:
            calendar_service.eliminar_evento(event_id)
        return f"🗑️ Recordatorio #{recordatorio_id} eliminado."
    return "No encontré ese recordatorio."


def buscar_web(consulta: str) -> str:
    """Busca información actual en la web con Tavily y la redacta naturalmente con Groq."""
    try:
        resultados = tavily_client.search(
            query=consulta,
            search_depth="advanced",
            include_answer=True,
            max_results=5
        )

        respuesta_tavily = resultados.get("answer", "") or ""
        fragmentos = "\n".join(
            f"- {r.get('title', '')}: {r.get('content', '')[:400]}"
            for r in resultados.get("results", [])[:5]
        )

        contenido_busqueda = f"{respuesta_tavily}\n\n{fragmentos}".strip()

        if not contenido_busqueda:
            return "No encontré información sobre eso 😕 Probá reformular la pregunta."

        response = groq_client.chat.completions.create(
            model=MODELO_CHAT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Respondé en español, de forma natural, cálida, cercana y completa, "
                        "como lo haría una persona bien informada charlando con un amigo (no digas frases robóticas "
                        "como 'según mis fuentes' ni menciones que sos una IA). Usá la información que te paso para "
                        "dar una respuesta concreta y actualizada. Si tiene sentido, cerrá con una pregunta o "
                        "sugerencia breve y natural relacionada al tema, sin forzarlo si no aplica."
                    )
                },
                {
                    "role": "user",
                    "content": f"Consulta: {consulta}\n\nInformación encontrada en la web:\n{contenido_busqueda}"
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("⚠️ Error buscando en la web:", e)
        return "No pude buscar esa información justo ahora 😕 Probá de nuevo en un momento."


def buscar_youtube(consulta: str, cantidad: int = 5) -> list[dict]:
    """Busca una canción en YouTube (sin API key, vía yt-dlp) y devuelve varios candidatos
    [{"video_id":..., "titulo":...}, ...]. Varios candidatos porque no todos los videos
    permiten ser embebidos fuera de youtube.com (lo decide el dueño del video); si el primero
    falla al reproducir, el frontend prueba con el siguiente."""
    opciones = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            resultado = ydl.extract_info(f"ytsearch{cantidad}:{consulta}", download=False)
            entradas = resultado.get("entries") or []
            return [
                {"video_id": v.get("id"), "titulo": v.get("title") or consulta}
                for v in entradas if v.get("id")
            ]
    except Exception as e:
        print("⚠️ Error buscando en YouTube:", e)
        return []


PROMPT_SISTEMA = """Sos el cerebro de un asistente personal cercano y natural, como un amigo con mucho conocimiento — nunca sonás robótico ni mencionás que sos una IA. Te hablan por Telegram o por una interfaz web propia, da igual, respondé siempre igual.

Vas a recibir el HISTORIAL reciente de la conversación (puede estar vacío) y el MENSAJE NUEVO del usuario. Usá el historial para entender si el usuario sigue hablando del mismo tema (ej: "y mañana?" después de preguntar el clima de hoy) o si cambió de tema completamente. Si sigue el mismo tema, completá el contexto que falte.

Respondé SOLO con un JSON (sin markdown, sin texto extra, sin explicaciones) con esta estructura exacta:

{
  "accion": "crear_recordatorio" | "listar" | "eliminar" | "buscar" | "musica" | "charla",
  "texto": "string, solo si accion es crear_recordatorio: qué hay que recordar",
  "fecha_texto": "string, solo si accion es crear_recordatorio: la fecha/hora tal cual la dijo el usuario",
  "categoria": "string, solo si accion es crear_recordatorio: 'trabajo', 'personal', 'salud', 'estudio', 'general', etc.",
  "prioridad": "'alta' | 'media' | 'baja', solo si accion es crear_recordatorio",
  "id": número entero, solo si accion es eliminar,
  "consulta": "string, solo si accion es buscar: la pregunta completa y autocontenida para buscar en la web, resolviendo pronombres o referencias usando el historial si hace falta",
  "cancion": "string, solo si accion es musica: qué canción, artista o playlist pidió, tal cual lo dijo (ej: 'bohemian rhapsody queen', 'algo de bad bunny')",
  "respuesta": "string, solo si accion es charla: tu respuesta natural, cálida y completa. Si tiene sentido, cerrá con una pregunta o sugerencia breve relacionada, sin forzarlo",
  "mensaje_usuario_texto": "string SIEMPRE: repetí exactamente el mensaje del usuario tal como te llegó"
}

Usá "buscar" para CUALQUIER cosa que necesite información actual o externa: resultados deportivos, próximos partidos, clima, noticias, precios, quién es alguien actualmente, cuándo es un evento, cualquier dato que pueda haber cambiado o que no sepas con certeza.

Usá "musica" cuando el usuario pida escuchar, poner, reproducir o pausar una canción, artista o playlist (ej: "ponme música de...", "quiero escuchar...", "poné algo de..."). Si simplemente pregunta datos SOBRE música (quién canta tal canción, cuándo sale un álbum) sin pedir que la reproduzcas, usá "buscar" o "charla" según corresponda, no "musica".

Usá "charla" solo para saludos, charla casual, opiniones, o preguntas de conocimiento general estable que no requieran datos actuales.

Ejemplos:
Usuario: "recordame comprar pan mañana a las 9am"
{"accion": "crear_recordatorio", "texto": "comprar pan", "fecha_texto": "mañana a las 9am", "categoria": "personal", "prioridad": "media", "mensaje_usuario_texto": "recordame comprar pan mañana a las 9am"}

Usuario: "cual es el proximo partido del Junior"
{"accion": "buscar", "consulta": "próximo partido del Junior de Barranquilla, fecha y hora", "mensaje_usuario_texto": "cual es el proximo partido del Junior"}

Historial: "Usuario: cual es el proximo partido del Junior\\nAsistente: [resumen del partido]"
Usuario: "y contra quien es el siguiente"
{"accion": "buscar", "consulta": "partido del Junior de Barranquilla después del próximo, rival y fecha", "mensaje_usuario_texto": "y contra quien es el siguiente"}

Usuario: "qué recordatorios tengo"
{"accion": "listar", "mensaje_usuario_texto": "qué recordatorios tengo"}

Usuario: "eliminá el recordatorio 2"
{"accion": "eliminar", "id": 2, "mensaje_usuario_texto": "eliminá el recordatorio 2"}

Usuario: "hola como estas"
{"accion": "charla", "respuesta": "¡Todo bien por acá! ¿Cómo va tu día?", "mensaje_usuario_texto": "hola como estas"}

Usuario: "poneme bohemian rhapsody"
{"accion": "musica", "cancion": "bohemian rhapsody queen", "mensaje_usuario_texto": "poneme bohemian rhapsody"}

Respondé ÚNICAMENTE con el objeto JSON, nada más."""


def extraer_json(texto: str) -> dict:
    texto = texto.strip()
    decoder = json.JSONDecoder()
    datos, _ = decoder.raw_decode(texto)
    return datos


async def ejecutar_accion(datos: dict, chat_id, on_creado=None, on_eliminado=None) -> dict:
    """Devuelve {"texto": str, "video_id": str|None}. video_id solo viene poblado cuando accion es 'musica'."""
    accion = datos.get("accion")

    if accion == "crear_recordatorio":
        texto = await crear_recordatorio(
            chat_id,
            datos.get("texto", ""),
            datos.get("fecha_texto", ""),
            datos.get("categoria", "general"),
            datos.get("prioridad", "media"),
            on_creado=on_creado
        )
        return {"texto": texto, "video_id": None}
    elif accion == "listar":
        return {"texto": listar_recordatorios(chat_id), "video_id": None}
    elif accion == "eliminar":
        rid = datos.get("id")
        if rid is None:
            return {"texto": "¿Cuál recordatorio querés eliminar? Decime el número.", "video_id": None}
        return {"texto": eliminar_recordatorio_por_id(chat_id, int(rid), on_eliminado=on_eliminado), "video_id": None}
    elif accion == "buscar":
        consulta = datos.get("consulta") or datos.get("mensaje_usuario_texto") or ""
        if not consulta:
            return {"texto": "¿Qué querés que busque?", "video_id": None}
        return {"texto": buscar_web(consulta), "video_id": None}
    elif accion == "musica":
        cancion = datos.get("cancion") or datos.get("mensaje_usuario_texto") or ""
        if not cancion:
            return {"texto": "¿Qué canción querés escuchar?", "video_id": None}
        candidatos = buscar_youtube(cancion)
        if not candidatos:
            return {"texto": f"No encontré \"{cancion}\" en YouTube 😕", "video_id": None}
        return {
            "texto": f"🎵 Poniendo: {candidatos[0]['titulo']}",
            "video_id": candidatos[0]["video_id"],
            "video_candidatos": candidatos,
        }
    elif accion == "charla":
        return {"texto": datos.get("respuesta", "¿En qué te ayudo?"), "video_id": None}
    else:
        return {"texto": "No entendí bien eso, ¿podés reformularlo?", "video_id": None}


async def manejar_mensaje(chat_id, mensaje_usuario: str, on_creado=None, on_eliminado=None) -> dict:
    """Punto de entrada único: clasifica el mensaje con Groq, ejecuta la acción y devuelve
    {"texto": str, "video_id": str|None}. No sabe si viene de Telegram o de la web."""
    contexto = obtener_contexto(chat_id)

    try:
        response = groq_client.chat.completions.create(
            model=MODELO_CHAT,
            messages=[
                {"role": "system", "content": PROMPT_SISTEMA},
                {
                    "role": "user",
                    "content": f"Historial reciente:\n{contexto}\n\nMensaje nuevo del usuario: \"{mensaje_usuario}\""
                }
            ],
            response_format={"type": "json_object"}
        )
        datos = extraer_json(response.choices[0].message.content)
    except Exception as e:
        print("⚠️ Error con Groq:", e)
        return {"texto": "Tuve un problema entendiendo eso 😅 Probá de nuevo.", "video_id": None}

    resultado = await ejecutar_accion(datos, chat_id, on_creado=on_creado, on_eliminado=on_eliminado)

    texto_usuario_log = datos.get("mensaje_usuario_texto", mensaje_usuario)
    agregar_historial(chat_id, "Usuario", texto_usuario_log)
    agregar_historial(chat_id, "Asistente", resultado["texto"])

    return resultado


def transcribir_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    transcripcion = groq_client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model=MODELO_AUDIO,
        language="es"
    )
    return transcripcion.text.strip()
