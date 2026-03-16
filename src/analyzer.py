# src/analyzer.py

import json
import logging
import pathlib
import re
import sqlite3
import unicodedata
from datetime import date
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "data" / "silver" / "jobs_and_news.db"

MONTH_MAP = {
    # Português
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    # Français
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

DEADLINE_TRIGGERS = re.compile(
    r"prazo|candidaturas?\s+at[eé]|submiss[aã]o\s+at[eé]|data.limite|at[eé]\s+ao?\s+dia|"
    r"deadline|closing\s+date|clôture|date\s+limite|fin\s+de\s+dépôt|jusqu'au",
    re.IGNORECASE,
)

DATE_PATTERNS = [
    # 30 de junho de 2025 / 30 juin 2025 / June 30, 2025
    re.compile(r"\b(\d{1,2})\s+(?:de\s+)?([a-z\u00C0-\u017F]+\.?)\s+(?:de\s+)?(\d{4})\b", re.IGNORECASE),
    # 30/06/2025 ou 30-06-2025
    re.compile(r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b"),
    # 2025/06/30
    re.compile(r"\b(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\b"),
]

def normalize_text(text: str) -> str:
    if not text: return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def _parse_date(match: re.Match, idx: int) -> Optional[date]:
    try:
        if idx == 0:
            day, month_str, year = match.groups()
            month = MONTH_MAP.get(normalize_text(month_str.rstrip(".")))
            return date(int(year), month, int(day)) if month else None
        elif idx == 1:
            day, month, year = match.groups()
            return date(int(year), int(month), int(day))
        elif idx == 2:
            year, month, day = match.groups()
            return date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None

def extract_deadlines(text: str) -> list[date]:
    found: list[date] = []
    for trigger in DEADLINE_TRIGGERS.finditer(text):
        start = max(0, trigger.start() - 50)
        end = min(len(text), trigger.end() + 150)
        window = text[start:end]
        
        for i, pat in enumerate(DATE_PATTERNS):
            for m in pat.finditer(window):
                d = _parse_date(m, i)
                if d and d not in found:
                    found.append(d)
    
    if not found:
        for i, pat in enumerate(DATE_PATTERNS):
            for m in pat.finditer(text):
                d = _parse_date(m, i)
                if d and d not in found:
                    found.append(d)
                    
    today = date.today()
    return sorted([d for d in found if d.year >= today.year - 1])


def extract_funding_amounts(text: str) -> list[str]:
    patterns = [
        re.compile(r"\b\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?\s*(?:€|EUR|euros?)\b", re.IGNORECASE),
        re.compile(r"(?:€|EUR)\s*\b\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?\b", re.IGNORECASE),
        re.compile(r"(?:financement|montant|bolsa|budget|dotation)\s+(?:de\s+)?\d[\d\s,.]*(?:€|EUR|euros?)", re.IGNORECASE)
    ]
    amounts = []
    for pat in patterns:
        for m in pat.finditer(text):
            raw = m.group(0).strip()
            if not any(raw in existing for existing in amounts):
                amounts = [e for e in amounts if e not in raw]
                amounts.append(raw)
    return amounts

def extract_emails(text: str) -> list[str]:
    return list(set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)))

def extract_phone_numbers(text: str) -> list[str]:
    # Patterns pour PT (+351) et FR (+33)
    patterns = [
        re.compile(r"(?:\+351|00351)?\s?[29]\d{2}\s?\d{3}\s?\d{3}"), # Portugal
        re.compile(r"(?:\+33|0)[1-9](?:\s?\d{2}){4}"),                # France
    ]
    phones = []
    for pat in patterns:
        for m in pat.finditer(text):
            cleaned = re.sub(r"[^\d+]", "", m.group(0))
            if len(cleaned) >= 9:
                phones.append(cleaned)
    return list(set(phones))


METADATA_COLUMNS = {
    "earliest_deadline": "TEXT",
    "deadlines":         "TEXT",
    "funding_amounts":   "TEXT",
    "emails":            "TEXT",
    "phone_numbers":     "TEXT",
    "normalized_text":   "TEXT",
}

def migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    for col, col_type in METADATA_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {col_type}")
    conn.commit()

def analyze_text(text: str) -> dict:
    if not text:
        return {k: "[]" if "s" in k else None for k in METADATA_COLUMNS.keys()}
        
    deadlines = extract_deadlines(text)
    return {
        "earliest_deadline": deadlines[0].isoformat() if deadlines else None,
        "deadlines":         json.dumps([d.isoformat() for d in deadlines]),
        "funding_amounts":   json.dumps(extract_funding_amounts(text), ensure_ascii=False),
        "emails":            json.dumps(extract_emails(text)),
        "phone_numbers":     json.dumps(extract_phone_numbers(text)),
        "normalized_text":   normalize_text(text),
    }

def run(db_path: pathlib.Path = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        migrate(conn)
        rows = conn.execute("SELECT id, source, body FROM items WHERE normalized_text IS NULL").fetchall()
        if not rows: return

        for row in rows:
            metadata = analyze_text(row["body"] or "")
            conn.execute("""
                UPDATE items SET
                    earliest_deadline = :earliest_deadline, deadlines = :deadlines,
                    funding_amounts = :funding_amounts, emails = :emails,
                    phone_numbers = :phone_numbers, normalized_text = :normalized_text
                WHERE id = :id
            """, {**metadata, "id": row["id"]})
        conn.commit()