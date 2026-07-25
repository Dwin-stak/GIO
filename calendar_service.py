import os
import json
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

def _preparar_archivos_desde_env():
    """Si estamos en un servidor (Railway), crea los archivos desde variables de entorno."""
    if not os.path.exists(CREDENTIALS_FILE):
        contenido = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if contenido:
            with open(CREDENTIALS_FILE, "w") as f:
                f.write(contenido)

    if not os.path.exists(TOKEN_FILE):
        contenido = os.getenv("GOOGLE_TOKEN_JSON")
        if contenido:
            with open(TOKEN_FILE, "w") as f:
                f.write(contenido)

def obtener_servicio_calendar():
    _preparar_archivos_desde_env()
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

def crear_evento(texto: str, fecha_hora: datetime.datetime, duracion_minutos: int = 30):
    try:
        service = obtener_servicio_calendar()
        fin = fecha_hora + datetime.timedelta(minutes=duracion_minutos)

        evento = {
            "summary": texto,
            "start": {"dateTime": fecha_hora.isoformat(), "timeZone": "America/Bogota"},
            "end": {"dateTime": fin.isoformat(), "timeZone": "America/Bogota"},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": 10}],
            },
        }

        resultado = service.events().insert(calendarId="primary", body=evento).execute()
        return resultado.get("id")
    except Exception as e:
        print("⚠️ Error creando evento en Calendar:", e)
        return None

def eliminar_evento(event_id: str) -> bool:
    try:
        service = obtener_servicio_calendar()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True
    except Exception as e:
        print("⚠️ Error eliminando evento de Calendar:", e)
        return False