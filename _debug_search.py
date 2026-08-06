import os
import traceback
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELO = "gemini-3.1-flash-lite"

try:
    response = client.models.generate_content(
        model=MODELO,
        contents="Consulta: clima hoy en Bogotá",
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )
    print("OK")
    print(response.text)
except Exception:
    traceback.print_exc()
