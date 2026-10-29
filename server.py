from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import sqlite3
import os
import threading
import time

DB_NAME = "recycle_local.db"


def database_has_points():
    if not os.path.exists(DB_NAME):
        return False
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM points")
        count = c.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def ensure_database():
    # База наполняется в фоне: сервер поднимается сразу, точки появляются через ~30 секунд
    try:
        if database_has_points():
            return
        from osint_parser import fetch_and_save
        for attempt in range(3):
            if fetch_and_save():
                return
            print(f"Попытка {attempt + 1}/3 не удалась, повтор через 20 секунд")
            time.sleep(20)
    except Exception as e:
        print(f"Не удалось наполнить базу при старте: {e}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=ensure_database, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html", media_type="text/html")
    return HTMLResponse("<h3>index.html not found</h3>")


@app.get("/health")
def health():
    points = 0
    if os.path.exists(DB_NAME):
        try:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM points")
            points = c.fetchone()[0]
            conn.close()
        except Exception:
            pass
    return JSONResponse(content={"status": "ok", "points": points})


@app.get("/api/points")
def get_points():
    # Если база еще не создана (сервер только включился), вернем пустой список
    if not os.path.exists(DB_NAME):
        return JSONResponse(content=[])

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, lat, lon, sku_code, price, status FROM points")
    points = [
        {"name": r[0], "lat": r[1], "lon": r[2], "sku": r[3], "price": r[4], "status": r[5]}
        for r in c.fetchall()
    ]
    conn.close()
    return JSONResponse(content=points)
