import requests
import sqlite3
import random
import time
import json
import os
import math
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

# Т1: мягкий фильтр — убираем объекты, которые точно не являются пунктами
# приёма вторсырья, но попали в OSM с тегом amenity=recycling
JUNK_NAME_PARTS = [
    "свалка", "слив", "ферма", "полигон", "навоз", "гной",
    "мусоросжиг", "мусороперегруз", "отстойник", "стихийн",
]

# Т2: словарь «тег OSM → что принимают» для карточки точки
ACCEPTED_MAP = {
    "recycling:glass": "стекло",
    "recycling:glass_bottles": "стеклобой",
    "recycling:paper": "макулатура",
    "recycling:cardboard": "картон",
    "recycling:plastic": "пластик",
    "recycling:plastic_bottles": "ПЭТ-бутылки",
    "recycling:pet": "ПЭТ",
    "recycling:metal": "металл",
    "recycling:scrap_metal": "металлолом",
    "recycling:aluminium": "алюминий",
    "recycling:steel": "жесть",
    "recycling:cans": "банки",
    "recycling:clothes": "одежда",
    "recycling:batteries": "батарейки",
    "recycling:e_waste": "электроника",
    "recycling:green_waste": "органика",
    # часто встречающиеся теги OSM — чтобы чипы не сыпались английскими
    "recycling:plastic_packaging": "пластиковая упаковка",
    "recycling:plastic_bags": "пластиковые пакеты",
    "recycling:PET": "ПЭТ",
    "recycling:hazardous_waste": "опасные отходы",
    "recycling:low_energy_bulbs": "энергосберегающие лампы",
    "recycling:light_bulbs": "лампы",
    "recycling:books": "книги",
    "recycling:magazines": "журналы",
    "recycling:cartons": "картонная упаковка",
    "recycling:newspaper": "газеты",
    "recycling:paper_packaging": "бумажная упаковка",
    "recycling:beverage_cartons": "тетрапак",
    "recycling:glass_jars": "стеклянные банки",
    "recycling:tyres": "шины",
    "recycling:shoes": "обувь",
    "recycling:oil": "масла",
    "recycling:engine_oil": "моторное масло",
    "recycling:cooking_oil": "растительное масло",
    "recycling:small_appliances": "мелкая электроника",
    "recycling:white_goods": "крупная бытовая техника",
    "recycling:fluorescent_tubes": "люминесцентные лампы",
    "recycling:printer_cartridges": "картриджи",
    "recycling:food_waste": "пищевые отходы",
    "recycling:wood": "дерево",
}


def extract_accepted(tags):
    parts = []
    for key, value in tags.items():
        if not key.startswith("recycling:"):
            continue
        if str(value).lower() not in ("yes", "only"):
            continue
        label = ACCEPTED_MAP.get(key, key.replace("recycling:", "").replace("_", " "))
        if label not in parts:
            parts.append(label)
    return ", ".join(parts) if parts else None


def extract_phone(tags):
    return tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile")


# Города полигона для фильтра «город» на карте: точка относится к ближайшему
# центру в радиусе CITY_RADIUS_KM (формула гаверсинуса), иначе — запасная метка
CITIES = [
    ("Краснодар", 45.035, 38.975),
    ("Сочи", 43.586, 39.723),
    ("Новороссийск", 44.724, 37.768),
    ("Армавир", 44.989, 41.123),
    ("Майкоп", 44.610, 40.106),
    ("Ейск", 46.710, 38.276),
    ("Кропоткин", 45.433, 40.575),
    ("Славянск-на-Кубани", 45.259, 38.128),
    ("Туапсе", 44.102, 39.076),
    ("Анапа", 44.890, 37.317),
    ("Геленджик", 44.562, 38.085),
    ("Тихорецк", 45.854, 40.128),
    ("Тимашевск", 45.617, 38.938),
    ("Белореченск", 44.764, 39.866),
    ("Приморско-Ахтарск", 46.049, 38.168),
    ("Лабинск", 44.632, 40.731),
    ("Абинск", 44.869, 38.156),
    ("Усть-Лабинск", 45.216, 39.684),
    ("Крымск", 44.931, 37.990),
    ("Темрюк", 45.272, 37.380),
    ("Горячий Ключ", 44.630, 39.134),
    ("Апшеронск", 44.467, 39.737),
    ("Кореновск", 45.468, 39.452),
]
CITY_RADIUS_KM = 30
CITY_FALLBACK = "Пригороды и районы"


def detect_city(lat, lon):
    best, best_d = CITY_FALLBACK, CITY_RADIUS_KM
    for name, clat, clon in CITIES:
        dlat = math.radians(clat - lat)
        dlon = math.radians(clon - lon)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat)) * math.cos(math.radians(clat)) * math.sin(dlon / 2) ** 2)
        d = 12742 * math.asin(math.sqrt(a))
        if d < best_d:
            best, best_d = name, d
    return best

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
        sku_code TEXT, price REAL, last_updated TEXT, status TEXT,
        accepted TEXT, phone TEXT, city TEXT)""")
    try:
        c.execute("ALTER TABLE points ADD COLUMN accepted TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE points ADD COLUMN phone TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE points ADD COLUMN city TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("DELETE FROM points")
    
    count = 0
    for el in data.get('elements', []):
        lat = el.get('lat') or el.get('center', {}).get('lat')
        lon = el.get('lon') or el.get('center', {}).get('lon')
        if lat is None or lon is None:
            continue
            
        tags = el.get('tags', {})
        name = tags.get('name', f"Пункт приема (OSM ID: {el['id']})")
        if any(part in name.lower() for part in JUNK_NAME_PARTS):
            continue
        accepted = extract_accepted(tags)
        phone = extract_phone(tags)
        price = round(random.uniform(25.0, 55.0), 2)
        days_ago = random.randint(0, 10)
        status = "GREEN" if days_ago <= 3 else ("YELLOW" if days_ago <= 7 else "GREY")
        last_updated = (date.today() - timedelta(days=days_ago)).isoformat()
        
        c.execute("INSERT INTO points (name, lat, lon, sku_code, price, last_updated, status, accepted, phone, city) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (name, lat, lon, "PET-MIX", price, last_updated, status, accepted, phone, detect_city(lat, lon)))
        count += 1
        
    conn.commit()
    conn.close()
    print(f"Успех! В базу загружено {count} реальных точек.")
    return True

if __name__ == "__main__":
    fetch_and_save()