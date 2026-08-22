from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import nucleo

# chat_id reservado para la interfaz web. Los chat_id de Telegram siempre son
# enteros positivos grandes, así que -1 nunca va a chocar con uno real.
WEB_CHAT_ID = -1

app = FastAPI(title="Asistente personal - Web")


@app.on_event("startup")
def startup():
    db.init_db()


class MensajeIn(BaseModel):
    texto: str


def _empaquetar(resultado: dict, transcripcion: str = "") -> dict:
    return {
        "respuesta": resultado["texto"],
        "video_id": resultado.get("video_id"),
        "video_candidatos": resultado.get("video_candidatos") or (
            [{"video_id": resultado["video_id"]}] if resultado.get("video_id") else []
        ),
        "transcripcion": transcripcion,
    }


@app.post("/api/mensaje")
async def api_mensaje(payload: MensajeIn):
    texto = (payload.texto or "").strip()
    if not texto:
        return {"respuesta": "Decime algo primero 🙂", "video_id": None, "video_candidatos": [], "transcripcion": ""}
    resultado = await nucleo.manejar_mensaje(WEB_CHAT_ID, texto)
    return _empaquetar(resultado)


@app.post("/api/audio")
async def api_audio(archivo: UploadFile = File(...)):
    """Para navegadores sin reconocimiento de voz nativo (Safari/iOS, Firefox):
    graban el audio en el navegador y lo mandan acá para transcribir con Whisper (Groq),
    el mismo motor que ya usa el bot de Telegram."""
    audio_bytes = await archivo.read()
    nombre = archivo.filename or "audio.webm"

    try:
        texto = nucleo.transcribir_audio(audio_bytes, filename=nombre)
    except Exception as e:
        print("⚠️ Error transcribiendo audio (web):", e)
        texto = ""

    if not texto:
        return {
            "respuesta": "No pude entender el audio 😅 Probá de nuevo o escribí el mensaje.",
            "video_id": None,
            "video_candidatos": [],
            "transcripcion": "",
        }

    resultado = await nucleo.manejar_mensaje(WEB_CHAT_ID, texto)
    return _empaquetar(resultado, transcripcion=texto)


app.mount("/", StaticFiles(directory="static", html=True), name="static")
