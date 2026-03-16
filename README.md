# Grant Scraper — Data Engineering Assignment 1

A web scraping and text analysis pipeline that collects grant announcements from the University of Aveiro (UA) news portal and the French National Research Agency (ANR), extracts structured information, and makes them searchable via a CLI.

---

## Architecture

```
project/
├── src/
│   ├── scraper.py      # Playwright scraper (UA + ANR)
│   ├── parser.py       # HTML → structured dict + SQLite
│   ├── analyzer.py     # Regex analysis: deadlines, amounts, contacts, categories
│   ├── cli.py          # CLI: scrape / search / export / stats
│   ├── scheduler.py    # Periodic scraping daemon
│   └── main.py         # Entry point (delegates to cli.py)
├── data/
│   ├── bronze/
│   │   ├── ua_news/        # Raw HTML pages (UA)
│   │   └── anr_appels/     # Raw HTML pages (ANR)
│   ├── silver/
│   │   └── jobs_and_news.db  # SQLite database
│   └── exports/            # CSV / JSON exports
├── pyproject.toml
└── README.md
```

### Data layers

| Layer  | Format | Description |
|--------|--------|-------------|
| Bronze | `.html` files | Raw scraped pages, never modified |
| Silver | SQLite | Parsed + analyzed structured data |
| Export | CSV / JSON | User-facing exports |

---

## Setup

### Requirements

- Python ≥ 3.11
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install

```bash
# With uv (recommended)
uv sync
uv run playwright install chromium

# Or with pip
pip install -e ".[dev]"
playwright install chromium
```

### Dev tools

```bash
# Linting
uv run ruff check src/

# Type checking
uv run pyright src/
```

---

## Usage

### Run the full pipeline

```bash
python main.py scrape               # scrape UA + ANR
python main.py scrape --source ua   # UA only
python main.py scrape --source anr  # ANR only
```

### Search grants

```bash
# Basic keyword search
python main.py search bolsa

# Filter by source
python main.py search doutoramento --source ua --limit 10

# Filter by research field and grant type
python main.py search data --field "Informática e IA" --type "Bolsa Doutoral"

# Filter by deadline range
python main.py search candidatura --from 2025-01-01 --until 2025-12-31
```

**Available research fields:**
- Ciências da Saúde
- Engenharia e Tecnologia
- Informática e IA
- Ciências Naturais
- Ciências Sociais
- Humanidades
- Geral (default)

**Available grant types:**
- Bolsa Doutoral
- Bolsa Pós-Doutoral
- Bolsa de Investigação
- Projeto / Appel
- Prémio / Distinção
- Mobilidade / Intercâmbio
- Outro (default)

### Export data

```bash
python main.py export                         # CSV + JSON (default)
python main.py export --format csv
python main.py export --format json --output ./my_exports
```

### Show statistics

```bash
python main.py stats
```

---

## Periodic Automation

Run the scraper in the background on a schedule:

```bash
# Every day at 06:00 (default)
python src/scheduler.py

# Every 6 hours
python src/scheduler.py --interval 6h

# Every 30 minutes
python src/scheduler.py --interval 30m

# Run immediately, then schedule daily
python src/scheduler.py --run-now --interval 1d --time 08:00
```

### Run as a background process (Linux/macOS)

```bash
nohup python src/scheduler.py --interval 1d > logs/scheduler.log 2>&1 &
```

### Or with cron (alternative)

```cron
# crontab -e
0 6 * * * cd /path/to/project && python main.py scrape >> logs/cron.log 2>&1
```

---

## Database Schema

```sql
CREATE TABLE items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,          -- 'ua' or 'anr'
    title             TEXT,
    date              TEXT,
    description       TEXT,
    body              TEXT,
    url               TEXT UNIQUE,
    attachments       TEXT,                   -- JSON array of attachment URLs
    -- Analyzed columns (added by analyzer.py)
    earliest_deadline TEXT,                   -- ISO date of soonest deadline
    deadlines         TEXT,                   -- JSON array of all dates found
    funding_amounts   TEXT,                   -- JSON array of amount strings
    emails            TEXT,                   -- JSON array
    phone_numbers     TEXT,                   -- JSON array
    normalized_text   TEXT,                   -- accent-free lowercase for search
    research_field    TEXT,                   -- e.g. 'Informática e IA'
    grant_type        TEXT                    -- e.g. 'Bolsa Doutoral'
);
```

---

## Sources

| Source | URL | Language |
|--------|-----|----------|
| Universidade de Aveiro | https://www.ua.pt/pt/noticias/3 | Portuguese |
| ANR — Appels à projets | https://anr.fr/fr/appels/ | French |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `playwright` | JavaScript-rendered page scraping |
| `beautifulsoup4` | HTML parsing |
| `schedule` | Periodic job scheduling |
| `lxml` | Fast HTML parser backend |
| `ruff` (dev) | Linting & formatting |
| `pyright` (dev) | Static type checking |
