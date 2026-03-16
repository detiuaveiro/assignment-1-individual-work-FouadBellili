# src/parser.py

from bs4 import BeautifulSoup
import logging
import pathlib
import sqlite3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR   = pathlib.Path(__file__).parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"
SILVER_DIR = BASE_DIR / "data" / "silver"
UA_DIR     = BRONZE_DIR / "ua_news"
ANR_DIR    = BRONZE_DIR / "anr_appels"
DB_PATH    = SILVER_DIR / "jobs_and_news.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_ATTACHMENT_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".ppt", ".pptx"}


def _extract_attachments(soup: BeautifulSoup, base_url: str = "") -> list[str]:
    """Return a list of attachment URLs (PDFs, docs, etc.) found in the page."""
    links = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # keep only links with a known document extension
        if any(href.lower().endswith(ext) for ext in _ATTACHMENT_EXTS):
            # make absolute if needed
            if href.startswith("http"):
                links.append(href)
            elif base_url:
                links.append(base_url.rstrip("/") + "/" + href.lstrip("/"))
            else:
                links.append(href)
    return list(dict.fromkeys(links))  # deduplicate while preserving order


def _clean_text(text: str | None) -> str | None:
    """Remove excess whitespace and common HTML artefacts."""
    if not text:
        return None
    import re, html
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def extract_ua_article(file: pathlib.Path) -> dict | None:
    with open(file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    url_tag = soup.find("meta", attrs={"name": "url"})
    url = url_tag.get("content") if url_tag else None

    title_tag = soup.find("p", class_="hIhIhv")
    title = _clean_text(title_tag.get_text(strip=True) if title_tag else None)

    date_tag = soup.find("p", class_="hBdxXc")
    date = _clean_text(date_tag.get_text(strip=True) if date_tag else None)

    desc_tag = soup.find("p", class_="eNJsUb")
    description = _clean_text(desc_tag.get_text(strip=True) if desc_tag else None)

    body_tag = soup.find("div", class_="markdown")
    body = _clean_text(body_tag.get_text(separator=" ", strip=True) if body_tag else None)

    base = "/".join(url.split("/")[:3]) if url else ""
    attachments = _extract_attachments(soup, base)

    return {
        "source":      "ua",
        "title":       title,
        "date":        date,
        "description": description,
        "body":        body,
        "url":         url,
        "attachments": attachments,
    }


def extract_anr_call(file: pathlib.Path) -> dict | None:
    with open(file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    url_tag = soup.find("meta", property="og:url")
    url = url_tag.get("content") if url_tag else None

    title_tag = soup.find("h1")
    title = _clean_text(title_tag.get_text(strip=True) if title_tag else None)

    date = None
    date_tag = soup.find(class_="news-tile__date")
    if date_tag:
        date = _clean_text(date_tag.get_text(strip=True))

    desc_tag = soup.find("p", class_="teaser")
    description = _clean_text(desc_tag.get_text(strip=True) if desc_tag else None)

    content_parts = []
    main_content = soup.find("section", class_="content-style")
    if main_content:
        content_parts.append(main_content.get_text(separator=" ", strip=True))
    info_section = soup.find("div", id="infos")
    if info_section:
        content_parts.append(info_section.get_text(separator=" ", strip=True))
    body = _clean_text(" ".join(content_parts) if content_parts else None)

    if body and "cookie" in body[:300].lower() and len(body) < 500:
        logging.warning(f"[ANR] Skipping boilerplate page: {file.name}")
        return None

    base = "https://anr.fr"
    attachments = _extract_attachments(soup, base)

    return {
        "source":      "anr",
        "title":       title,
        "date":        date,
        "description": description,
        "body":        body,
        "url":         url,
        "attachments": attachments,
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
            url         TEXT UNIQUE,
            attachments TEXT
        )
    """)
    # add attachments column to existing databases (idempotent)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "attachments" not in existing:
        conn.execute("ALTER TABLE items ADD COLUMN attachments TEXT")
    conn.commit()


def insert_item(conn: sqlite3.Connection, item: dict):
    import json
    try:
        conn.execute(
            """INSERT INTO items (source, title, date, description, body, url, attachments)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                item["source"], item["title"], item["date"],
                item["description"], item["body"], item["url"],
                json.dumps(item.get("attachments") or []),
            ),
        )
    except sqlite3.IntegrityError:
        logging.warning(f"Duplicate skipped: {item['url']}")


def process():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    ua_files  = list(UA_DIR.glob("*.html"))
    anr_files = list(ANR_DIR.glob("*.html")) if ANR_DIR.exists() else []

    logging.info(
        f"Processing {len(ua_files)} UA articles and {len(anr_files)} ANR calls"
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
