import sqlite3
from datetime import datetime

DB_NAME = "asistente.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recordatorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            texto TEXT NOT NULL,
            fecha_hora TEXT NOT NULL,
            enviado INTEGER DEFAULT 0,
            categoria TEXT DEFAULT 'general',
            prioridad TEXT DEFAULT 'media'
        )
    """)
    conn.commit()

    for columna, definicion in [("categoria", "TEXT DEFAULT 'general'"), ("prioridad", "TEXT DEFAULT 'media'"), ("google_event_id", "TEXT DEFAULT NULL")]:
        try:
            cursor.execute(f"ALTER TABLE recordatorios ADD COLUMN {columna} {definicion}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # La columna ya existe

    conn.close()

def agregar_recordatorio(chat_id: int, texto: str, fecha_hora: datetime, categoria: str = "general", prioridad: str = "media", google_event_id: str = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO recordatorios (chat_id, texto, fecha_hora, categoria, prioridad, google_event_id) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, texto, fecha_hora.isoformat(), categoria, prioridad, google_event_id)
    )
    conn.commit()
    nuevo_id = cursor.lastrowid
    conn.close()
    return nuevo_id

def obtener_recordatorios(chat_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, texto, fecha_hora, categoria, prioridad
        FROM recordatorios
        WHERE chat_id = ? AND enviado = 0
        ORDER BY
            CASE prioridad WHEN 'alta' THEN 1 WHEN 'media' THEN 2 WHEN 'baja' THEN 3 ELSE 2 END,
            fecha_hora
    """, (chat_id,))
    resultados = cursor.fetchall()
    conn.close()
    return resultados

def eliminar_recordatorio(recordatorio_id: int, chat_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM recordatorios WHERE id = ? AND chat_id = ?",
        (recordatorio_id, chat_id)
    )
    conn.commit()
    filas_afectadas = cursor.rowcount
    conn.close()
    return filas_afectadas > 0

def obtener_pendientes():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, chat_id, texto, fecha_hora FROM recordatorios WHERE enviado = 0"
    )
    resultados = cursor.fetchall()
    conn.close()
    return resultados

def marcar_enviado(recordatorio_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE recordatorios SET enviado = 1 WHERE id = ?", (recordatorio_id,))
    conn.commit()
    conn.close()

def obtener_google_event_id(recordatorio_id: int, chat_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT google_event_id FROM recordatorios WHERE id = ? AND chat_id = ?",
        (recordatorio_id, chat_id)
    )
    resultado = cursor.fetchone()
    conn.close()
    return resultado[0] if resultado else None
def obtener_recordatorios_de_hoy():
    """Trae los recordatorios pendientes de HOY, agrupados por chat_id, para el resumen diario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    hoy = datetime.now().date().isoformat()
    cursor.execute("""
        SELECT chat_id, id, texto, fecha_hora, categoria, prioridad
        FROM recordatorios
        WHERE enviado = 0 AND date(fecha_hora) = ?
        ORDER BY chat_id, fecha_hora
    """, (hoy,))
    resultados = cursor.fetchall()
    conn.close()
    return resultados

def obtener_chats_unicos():
    """Devuelve todos los chat_id que alguna vez usaron el bot (para saber a quién mandarle el resumen)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT chat_id FROM recordatorios")
    resultados = [fila[0] for fila in cursor.fetchall()]
    conn.close()
    return resultados