# src/analyzer.py

import json
import logging
import pathlib
import re
import sqlite3
import unicodedata
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "data" / "silver" / "jobs_and_news.db"

#Month names (PT / FR / EN)
MONTH_MAP = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

#Deadline extraction
DEADLINE_TRIGGERS = re.compile(
    r"prazo|candidaturas?\s+at[eé]|submiss[aã]o\s+at[eé]|data.limite|at[eé]\s+ao?\s+dia|"
    r"deadline|closing\s+date|clôture|date\s+limite|fin\s+de\s+dépôt|jusqu'au",
    re.IGNORECASE,
)

DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s+(?:de\s+)?([a-z\u00C0-\u017F]+\.?)\s+(?:de\s+)?(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b"),
    re.compile(r"\b(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\b"),
]


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _parse_date(match: re.Match, idx: int) -> date | None:
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
        end   = min(len(text), trigger.end() + 150)
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


#Funding amounts
def extract_funding_amounts(text: str) -> list[str]:
    patterns = [
        re.compile(r"\b\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?\s*(?:€|EUR|euros?)\b", re.IGNORECASE),
        re.compile(r"(?:€|EUR)\s*\b\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?\b", re.IGNORECASE),
        re.compile(
            r"(?:financement|montant|bolsa|budget|dotation)\s+(?:de\s+)?\d[\d\s,.]*(?:€|EUR|euros?)",
            re.IGNORECASE,
        ),
    ]
    amounts: list[str] = []
    for pat in patterns:
        for m in pat.finditer(text):
            raw = m.group(0).strip()
            if not any(raw in existing for existing in amounts):
                amounts = [e for e in amounts if e not in raw]
                amounts.append(raw)
    return amounts


#Contact extraction
def extract_emails(text: str) -> list[str]:
    pattern = re.compile(
        r"[a-zA-Z0-9._%+\-]+(?:\s*@\s*|\s*\(at\)\s*|\s*\[at\]\s*)[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    )
    found = pattern.findall(text)
    cleaned: list[str] = []
    for email in found:
        clean = re.sub(r"\s*\(at\)\s*|\s*\[at\]\s*|\s*@\s*", "@", email).lower()
        if clean not in cleaned:
            cleaned.append(clean)
    return cleaned


def extract_phone_numbers(text: str) -> list[str]:
    patterns = [
        re.compile(r"(?:\+351|00351)?\s?[29]\d{2}\s?\d{3}\s?\d{3}"),
        re.compile(r"(?:\+33|0)[1-9](?:\s?\d{2}){4}"),
    ]
    phones: list[str] = []
    for pat in patterns:
        for m in pat.finditer(text):
            cleaned = re.sub(r"[^\d+]", "", m.group(0))
            if len(cleaned) >= 9:
                phones.append(cleaned)
    return list(set(phones))


#Grant categorization
# Each tuple: (research_field, grant_type, keyword_list)
# For field rules: grant_type is ignored. For type rules: field = "Geral".
CATEGORY_RULES: list[tuple[str, str, list[str]]] = [
    #Research fields
    ("Ciências da Saúde",       "Investigação", ["saude", "medic", "clinico", "farmac", "biomedic", "cancer", "sante", "health", "medical"]),
    ("Engenharia e Tecnologia", "Investigação", ["engenharia", "eletrotecnia", "mecanica", "civil", "engineering", "tecnologia", "technology"]),
    ("Informática e IA",        "Investigação", ["computacao", "informatica", "inteligencia artificial", "machine learning", "ia", "ai", "software", "dados", "data"]),
    ("Ciências Naturais",       "Investigação", ["fisica", "quimica", "biologia", "geologia", "ambiente", "ecologia", "physics", "chemistry", "biology", "environment"]),
    ("Ciências Sociais",        "Investigação", ["sociologia", "psicologia", "economia", "gestao", "direito", "educacao", "social", "economics", "law"]),
    ("Humanidades",             "Investigação", ["historia", "filosofia", "letras", "linguistica", "artes", "cultura", "history", "philosophy", "humanities"]),
    #Grant types
    ("Geral", "Bolsa Doutoral",           ["bolsa de doutoramento", "phd grant", "these de doctorat", "doutoramento"]),
    ("Geral", "Bolsa Pós-Doutoral",       ["pos-doutoramento", "post-doc", "postdoc", "post doc"]),
    ("Geral", "Bolsa de Investigação",    ["bolsa de investigacao", "research grant", "bourse de recherche"]),
    ("Geral", "Projeto / Appel",          ["appel a projets", "call for proposals", "candidatura a projeto", "financiamento de projeto"]),
    ("Geral", "Prémio / Distinção",       ["premio", "award", "distinction", "reconhecimento"]),
    ("Geral", "Mobilidade / Intercâmbio", ["mobilidade", "intercambio", "erasmus", "mobilite", "exchange"]),
]


def categorize(title: str, description: str) -> tuple[str, str]:
    """Return (research_field, grant_type) for a grant item."""
    combined = normalize_text(f"{title or ''} {description or ''}")

    field = "Geral"
    grant_type = "Outro"

    for f, _t, keywords in CATEGORY_RULES:
        if f == "Geral":
            continue
        if any(kw in combined for kw in keywords):
            field = f
            break

    for _f, t, keywords in CATEGORY_RULES:
        if _f != "Geral":
            continue
        if any(kw in combined for kw in keywords):
            grant_type = t
            break

    return field, grant_type


#DB migration & analysis
METADATA_COLUMNS = {
    "earliest_deadline": "TEXT",
    "deadlines":         "TEXT",
    "funding_amounts":   "TEXT",
    "emails":            "TEXT",
    "phone_numbers":     "TEXT",
    "normalized_text":   "TEXT",
    "research_field":    "TEXT",
    "grant_type":        "TEXT",
}


def migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    for col, col_type in METADATA_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {col_type}")
    conn.commit()


def analyze_text(title: str, description: str, body: str) -> dict:
    text = f"{title or ''} {description or ''} {body or ''}"
    if not text.strip():
        return {
            k: ("[]" if k in ("deadlines", "funding_amounts", "emails", "phone_numbers") else None)
            for k in METADATA_COLUMNS
        }

    deadlines = extract_deadlines(text)
    field, grant_type = categorize(title, description)
    return {
        "earliest_deadline": deadlines[0].isoformat() if deadlines else None,
        "deadlines":         json.dumps([d.isoformat() for d in deadlines]),
        "funding_amounts":   json.dumps(extract_funding_amounts(text), ensure_ascii=False),
        "emails":            json.dumps(extract_emails(text)),
        "phone_numbers":     json.dumps(extract_phone_numbers(text)),
        "normalized_text":   normalize_text(text),
        "research_field":    field,
        "grant_type":        grant_type,
    }


def run(db_path: pathlib.Path = DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        migrate(conn)
        rows = conn.execute(
            "SELECT id, source, title, description, body FROM items WHERE normalized_text IS NULL"
        ).fetchall()
        if not rows:
            logger.info("Nothing to analyze.")
            return

        for row in rows:
            metadata = analyze_text(
                row["title"] or "",
                row["description"] or "",
                row["body"] or "",
            )
            conn.execute(
                """
                UPDATE items SET
                    earliest_deadline = :earliest_deadline,
                    deadlines         = :deadlines,
                    funding_amounts   = :funding_amounts,
                    emails            = :emails,
                    phone_numbers     = :phone_numbers,
                    normalized_text   = :normalized_text,
                    research_field    = :research_field,
                    grant_type        = :grant_type
                WHERE id = :id
                """,
                {**metadata, "id": row["id"]},
            )
        conn.commit()
        logger.info(f"Analyzed {len(rows)} items.")


#Search helper
def search_items(
    conn: sqlite3.Connection,
    term: str,
    source: str | None = None,
    field: str | None = None,
    grant_type: str | None = None,
    date_from: str | None = None,
    date_until: str | None = None,
    limit: int = 20,
) -> list[dict]:
    conn.create_function("norm", 1, normalize_text)
    normalized = normalize_text(term)

    clauses = ["(norm(normalized_text) LIKE ? OR norm(title) LIKE ?)"]
    params: list = [f"%{normalized}%", f"%{normalized}%"]

    if source:
        clauses.append("source = ?")
        params.append(source)
    if field:
        clauses.append("research_field = ?")
        params.append(field)
    if grant_type:
        clauses.append("grant_type = ?")
        params.append(grant_type)
    if date_from:
        clauses.append("earliest_deadline >= ?")
        params.append(date_from)
    if date_until:
        clauses.append("earliest_deadline <= ?")
        params.append(date_until)

    params.append(limit)
    where = " AND ".join(clauses)

    rows = conn.execute(
        f"""
        SELECT id, source, title, date, url,
               earliest_deadline, funding_amounts, emails,
               research_field, grant_type,
               SUBSTR(body, 1, 200) AS excerpt
        FROM items
        WHERE {where}
        ORDER BY date DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]
