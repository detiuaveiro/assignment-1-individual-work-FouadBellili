from bs4 import BeautifulSoup
import logging
import pathlib
import sqlite3

BASE_DIR = pathlib.Path(__file__).parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "ua_news"
BRONZE_DIR.mkdir(parents=True, exist_ok=True)

files = list(BRONZE_DIR.rglob("*.html"))

data = []
seen_urls = set()

for file in files:
    with open(file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")


    cards = soup.find_all('a', class_='news-card')

    for c in cards:
        source_url = "https://www.ua.pt" + c.get('href', '')

        if source_url in seen_urls:
            continue

        title = c.find('h3', class_='news-card-title')
        date = c.find('p', class_='news-card-date')
        desc = c.find('p', class_='news-card-text')

        c_data = {
            "title": title.get_text(strip=True) if title else None,
            "date": date.get_text(strip=True) if date else None,
            "description": desc.get_text(strip=True) if desc else None,
            "url": source_url
        }
        seen_urls.add(source_url)
        data.append(c_data)

conn = sqlite3.connect(BASE_DIR / "data" / "silver" / "ua_news.db")

with conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            date TEXT,
            description TEXT,
            url TEXT UNIQUE
        )
    """)
    for item in data:
        try:
            conn.execute("""
                INSERT INTO news (title, date, description, url) 
                VALUES (?, ?, ?, ?)
            """, (item['title'], item['date'], item['description'], item['url']))
        except sqlite3.IntegrityError:
            logging.warning(f"Duplicate URL skipped: {item['url']}")

conn.close()