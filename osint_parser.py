import requests
import sqlite3
import random

DB_NAME = "recycle_local.db"

def fetch_and_save():
    print("Подключение к OpenStreetMap (Overpass API)...")
    query = """
    [out:json][timeout:25];
    area["name"="Белгород"]->.searchArea;
    (
      node["amenity"="recycling"](area.searchArea);
      way["amenity"="recycling"](area.searchArea);
    );
    out center;
    """
    
    try:
        response = requests.get("http://overpass-api.de/api/interpreter", params={'data': query}, timeout=30)
        data = response.json()
    except Exception as e:
        print(f"Ошибка сети при парсинге: {e}")
        return

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
        if not lat or not lon:
            continue
            
        name = el.get('tags', {}).get('name', f"Пункт приема (OSM ID: {el['id']})")
        price = round(random.uniform(25.0, 55.0), 2)
        days_ago = random.randint(0, 10)
        status = "GREEN" if days_ago <= 3 else ("YELLOW" if days_ago <= 7 else "GREY")
        
        c.execute("INSERT INTO points (name, lat, lon, sku_code, price, last_updated, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (name, lat, lon, "PET-MIX", price, "2026-10-29", status))
        count += 1
        
    conn.commit()
    conn.close()
    print(f"Успех! В базу загружено {count} реальных точек.")

if __name__ == "__main__":
    fetch_and_save()