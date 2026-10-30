import requests
import sqlite3
import random
import time
import json
import os
from datetime import date, timedelta

DB_NAME = "recycle_local.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Overpass отклоняет запросы без осмысленного User-Agent (HTTP 406/429),
# поэтому обходим несколько зеркал по очереди
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

HEADERS = {
    "User-Agent": "RecycleRadar/0.1 (OSINT MVP; Belgorod recycling points)",
    "Accept": "application/json",
}

def fetch_and_save():
    print("Подключение к OpenStreetMap (Overpass API)...")
    # Краснодарский край целиком: bbox (юг, запад, север, восток).
    # Bbox-запрос быстрее и надёжнее поиска area по имени региона
    query = """
    [out:json][timeout:90];
    (
      node["amenity"="recycling"](43.3,36.6,46.9,41.6);
      way["amenity"="recycling"](43.3,36.6,46.9,41.6);
    );
    out center;
    """
    
    data = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = requests.get(endpoint, params={'data': query}, headers=HEADERS, timeout=45)
            if response.status_code != 200:
                print(f"{endpoint}: HTTP {response.status_code}, пробую следующее зеркало")
                time.sleep(2)
                continue
            data = response.json()
            break
        except Exception as e:
            print(f"{endpoint}: ошибка сети ({e}), пробую следующее зеркало")
            time.sleep(2)
    if data is None:
        print("Ошибка: ни одно зеркало Overpass не ответило")
        return False

    print("Подключение к локальной БД...")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS points (
        id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL, 
        sku_code TEXT, price REAL, last_updated TEXT, status TEXT)""")
    c.execute("DELETE FROM points")
    
    count = 0
    for el in data.get('elements', []):
        lat = el.get('lat') or el.get('center', {}).get('lat')
        lon = el.get('lon') or el.get('center', {}).get('lon')
        if lat is None or lon is None:
            continue
            
        name = el.get('tags', {}).get('name', f"Пункт приема (OSM ID: {el['id']})")
        price = round(random.uniform(25.0, 55.0), 2)
        days_ago = random.randint(0, 10)
        status = "GREEN" if days_ago <= 3 else ("YELLOW" if days_ago <= 7 else "GREY")
        last_updated = (date.today() - timedelta(days=days_ago)).isoformat()
        
        c.execute("INSERT INTO points (name, lat, lon, sku_code, price, last_updated, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (name, lat, lon, "PET-MIX", price, last_updated, status))
        count += 1
        
    conn.commit()
    conn.close()
    print(f"Успех! В базу загружено {count} реальных точек.")
    return True

if __name__ == "__main__":
    fetch_and_save()