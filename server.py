from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import sqlite3
import os

app = FastAPI()
DB_NAME = "recycle_local.db"

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

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