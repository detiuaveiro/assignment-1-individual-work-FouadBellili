from bs4 import BeautifulSoup
import logging
import pathlib
import sqlite3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR  = pathlib.Path(__file__).parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"
SILVER_DIR = BASE_DIR / "data" / "silver"
UA_DIR    = BRONZE_DIR / "ua_news"
ANR_DIR   = BRONZE_DIR / "anr_appels"
DB_PATH   = SILVER_DIR / "jobs_and_news.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def extract_ua_article(file: pathlib.Path) -> dict | None:
    """Extract fields from a UA news article page."""
    with open(file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    url_tag = soup.find("meta", attrs={"name": "url"})
    url = url_tag.get("content") if url_tag else None

    title_tag = soup.find("p", class_="hIhIhv")
    title = title_tag.get_text(strip=True) if title_tag else None

    date_tag = soup.find("p", class_="hBdxXc")
    date = date_tag.get_text(strip=True) if date_tag else None

    desc_tag = soup.find("p", class_="eNJsUb")
    description = desc_tag.get_text(strip=True) if desc_tag else None

    body_tag = soup.find("div", class_="markdown")
    body = body_tag.get_text(separator=" ", strip=True) if body_tag else None

    return {
        "source": "ua",
        "title": title,
        "date": date,
        "description": description,
        "body": body,
        "url": url,
    }


def extract_anr_call(file: pathlib.Path) -> dict | None:
    """
    Extract fields from an ANR call-for-proposals page.

    ANR uses a standard Drupal/TYPO3 layout:
      - Title      : <h1> (unique per page)
      - Date       : <span class="news-date"> or <time datetime="...">
      - Description: first <p> inside .news-text-intro or .field-introduction
      - Body       : <div class="news-text"> or <div class="content-main">
    """
    with open(file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # ── URL ──────────────────────────────────────────────────
    url_tag = soup.find("meta", attrs={"name": "url"})
    url = url_tag.get("content") if url_tag else None

    # ── Title ────────────────────────────────────────────────
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else None
    if not title or "cookie" in title.lower():
        logging.warning(f"[ANR] Skipping junk page: {file.name}")
        return None

    # ── Date ─────────────────────────────────────────────────
    date = None
    time_tag = soup.find("time")
    if time_tag:
        date = time_tag.get("datetime") or time_tag.get_text(strip=True)
    if not date:
        for cls in ["news-date", "date", "field-date", "publication-date"]:
            tag = soup.find(class_=cls)
            if tag:
                date = tag.get_text(strip=True)
                break

    # ── Short description ────────────────────────────────────
    description = None
    for cls in ["news-text-intro", "field-introduction", "chapeau", "intro", "lead"]:
        tag = soup.find(class_=cls)
        if tag:
            description = tag.get_text(strip=True)[:500]
            break

    # ── Full body ────────────────────────────────────────────
    body = None
    for cls in ["news-text", "content-main", "field-body", "main-content", "content"]:
        tag = soup.find(class_=cls)
        if tag:
            for noise in tag.find_all(["nav", "header", "footer", "script", "style"]):
                noise.decompose()
            body = tag.get_text(separator=" ", strip=True)
            break

    if not body:
        main = soup.find("main") or soup.find("article")
        if main:
            for noise in main.find_all(["nav", "header", "footer", "script", "style"]):
                noise.decompose()
            body = main.get_text(separator=" ", strip=True)

    if body and "cookie" in body[:300].lower() and len(body) < 500:
        logging.warning(f"[ANR] Skipping boilerplate page: {file.name}")
        return None

    return {
        "source": "anr",
        "title": title,
        "date": date,
        "description": description,
        "body": body,
        "url": url,
    }


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,
            title       TEXT,
            date        TEXT,
            description TEXT,
            body        TEXT,
            url         TEXT UNIQUE
        )
    """)
    conn.commit()


def insert_item(conn: sqlite3.Connection, item: dict):
    try:
        conn.execute(
            """INSERT INTO items (source, title, date, description, body, url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item["source"], item["title"], item["date"],
             item["description"], item["body"], item["url"])
        )
    except sqlite3.IntegrityError:
        logging.warning(f"Duplicate skipped: {item['url']}")


def process():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    ua_files  = list(UA_DIR.glob("*.html"))
    anr_files = list(ANR_DIR.glob("*.html")) if ANR_DIR.exists() else []

    logging.info(
        f"Processing {len(ua_files)} UA articles and "
        f"{len(anr_files)} ANR calls"
    )

    for file in ua_files:
        item = extract_ua_article(file)
        if item:
            insert_item(conn, item)

    for file in anr_files:
        item = extract_anr_call(file)
        if item:
            insert_item(conn, item)

    conn.commit()
    conn.close()
    logging.info(f"Data stored in {DB_PATH}")
