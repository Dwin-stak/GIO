# Asistente personal (Telegram + Web)

Asistente personal con IA que funciona por Telegram y desde una página web. Le hablas como a una persona, por texto o por audio, y:

- Crea recordatorios a partir de frases como *"recuérdame comprar pan mañana a las 9am, es urgente"* y te avisa por Telegram a la hora indicada.
- Sincroniza los recordatorios con Google Calendar.
- Te manda un resumen cada mañana a las 6:00 con lo que tienes para el día.
- Busca información en internet (resultados de partidos, clima, noticias).
- Busca canciones en YouTube.
- Entiende notas de voz (transcripción con Whisper).

<!-- Agrega aquí una captura del bot o de la web: ![Captura](docs/captura.png) -->

## Cómo funciona

`nucleo.py` es el cerebro: recibe el mensaje, le pide a un modelo de lenguaje (Llama 3.3 en Groq) que decida qué acción tomar (crear, listar o eliminar recordatorios, buscar, música o charla) y la ejecuta. Telegram (`bot.py`) y la web (`web_app.py`) son solo dos entradas distintas al mismo núcleo.

```
Telegram (bot.py) ─┐
                   ├─> nucleo.py ─> Groq (IA), Tavily (búsqueda), YouTube
Web (web_app.py) ──┘        │
                            └─> database.py (SQLite) y calendar_service.py (Google Calendar)
```

## Tecnologías

Python, python-telegram-bot, FastAPI, SQLite, APScheduler, Groq (Llama 3.3 y Whisper), Tavily, Google Calendar API, yt-dlp.

## Cómo correrlo

Requisitos: Python 3.11 o superior.

```bash
python -m venv venv
venv\Scripts\activate      # en Windows
source venv/bin/activate   # en Mac/Linux
pip install -r requirements.txt
```

Crea un archivo `.env` con:

```
TELEGRAM_TOKEN=token_de_tu_bot      # se crea con @BotFather en Telegram
GROQ_API_KEY=tu_api_key             # https://console.groq.com
TAVILY_API_KEY=tu_api_key           # https://tavily.com
```

Para Google Calendar, descarga `credentials.json` desde Google Cloud Console (API de Calendar, credenciales OAuth de escritorio) y ponlo en la carpeta del proyecto. La primera vez se abre el navegador para autorizar y se guarda `token.json`.

Para el bot de Telegram:

```bash
python bot.py
```

Para la versión web:

```bash
uvicorn web_app:app --reload
```

y abre `http://localhost:8000`.

## Próximos pasos

- Guardar el historial de conversación en la base de datos en vez de en memoria.
- Avisos push también en la versión web.
