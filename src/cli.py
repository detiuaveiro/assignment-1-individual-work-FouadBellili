#!/usr/bin/env python3
"""
cli.py — Command-line interface for the Grant Scraper pipeline.

Usage:
    python cli.py scrape [--source ua|anr|all]
    python cli.py search <term> [--source ua|anr] [--limit N]
    python cli.py export [--format csv|json|both] [--output DIR]
    python cli.py stats
"""

import argparse
import csv
import json
import logging
import pathlib
import sqlite3
import sys
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR   = pathlib.Path(__file__).parent.parent  # project root (one level above src/)
DB_PATH    = BASE_DIR / "data" / "silver" / "jobs_and_news.db"
EXPORT_DIR = BASE_DIR / "data" / "exports"



def get_connection(db_path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}. Run 'scrape' first.")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _print_table(rows: list[dict], columns: list[str], max_width: int = 40):
    """Pretty-print rows as a table."""
    if not rows:
        print("  (no results)")
        return

    col_widths = {c: max(len(c), max((len(str(r.get(c, "") or "")) for r in rows), default=0)) for c in columns}
    col_widths = {c: min(w, max_width) for c, w in col_widths.items()}

    header = "  ".join(c.upper().ljust(col_widths[c]) for c in columns)
    separator = "  ".join("─" * col_widths[c] for c in columns)
    print(header)
    print(separator)
    for row in rows:
        line = "  ".join(str(row.get(c, "") or "")[:col_widths[c]].ljust(col_widths[c]) for c in columns)
        print(line)




def cmd_scrape(args):
    """Run the full scrape → parse → analyze pipeline."""
    source = args.source.lower() if args.source else "all"

    print(f"\n Starting scrape (source={source}) …\n")

    try:
        from src.scraper import scrape_ua, scrape_anr
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            if source in ("ua", "all"):
                scrape_ua(page)
            if source in ("anr", "all"):
                scrape_anr(page)
            browser.close()
    except ImportError as e:
        logger.error(f"Could not import scraper: {e}")
        sys.exit(1)

    print("\n Parsing HTML → database …\n")
    try:
        from src.parser import process
        process()
    except ImportError as e:
        logger.error(f"Could not import parser: {e}")
        sys.exit(1)

    print("\n Analyzing text (deadlines, amounts, contacts) …\n")
    try:
        from src.analyzer import run as analyze_run
        analyze_run(DB_PATH)
    except ImportError as e:
        logger.error(f"Could not import analyzer: {e}")
        sys.exit(1)

    print("\n Pipeline complete. Run 'stats' to see results.\n")




def cmd_search(args):
    """Accent-insensitive keyword search across title and body."""
    term  = args.term
    source = args.source
    limit  = args.limit or 20

    conn = get_connection()

    try:
        from src.analyzer import normalize_text, search_items
        rows = search_items(conn, term, source=source, limit=limit)
    except ImportError:
        import unicodedata, re
        def normalize_text(t):
            t = t.lower()
            t = unicodedata.normalize("NFD", t)
            return "".join(c for c in t if unicodedata.category(c) != "Mn")
        conn.create_function("norm", 1, normalize_text)
        normalized = normalize_text(term)
        params = [f"%{normalized}%", f"%{normalized}%"]
        src_filter = ""
        if source:
            src_filter = "AND source = ?"
            params.append(source)
        params.append(limit)
        rows = _rows_to_dicts(conn.execute(f"""
            SELECT id, source, title, date, url,
                   earliest_deadline, funding_amounts, emails,
                   SUBSTR(body, 1, 200) AS excerpt
            FROM items
            WHERE (norm(normalized_text) LIKE ? OR norm(title) LIKE ?)
            {src_filter}
            ORDER BY date DESC LIMIT ?
        """, params).fetchall())

    print(f"\n🔎  Search: '{term}'  ({len(rows)} result(s))\n")
    if not rows:
        print("  No results found.")
        return

    for r in rows:
        amounts = r.get("funding_amounts") or "[]"
        try:
            amounts_list = json.loads(amounts)
            amounts_str = ", ".join(amounts_list) if amounts_list else "—"
        except Exception:
            amounts_str = "—"

        emails = r.get("emails") or "[]"
        try:
            emails_list = json.loads(emails)
            emails_str = ", ".join(emails_list) if emails_list else "—"
        except Exception:
            emails_str = "—"

        print(f"  [{r['source'].upper()}] #{r['id']}  {r['date'] or '—'}")
        print(f"  Title   : {r['title'] or '—'}")
        print(f"  Deadline: {r['earliest_deadline'] or '—'}")
        print(f"  Amounts : {amounts_str}")
        print(f"  Emails  : {emails_str}")
        print(f"  URL     : {r['url'] or '—'}")
        excerpt = (r.get("excerpt") or "").replace("\n", " ")
        if excerpt:
            print(f"  Excerpt : {excerpt[:160]}…")
        print()

    conn.close()



def _all_items(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("""
        SELECT id, source, title, date, description, url,
               earliest_deadline, deadlines, funding_amounts,
               emails, phone_numbers
        FROM items
        ORDER BY source, date DESC
    """).fetchall())


def export_csv(rows: list[dict], output_dir: pathlib.Path) -> pathlib.Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"grants_{timestamp}.csv"
    if not rows:
        logger.warning("No rows to export.")
        return path
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return path


def export_json(rows: list[dict], output_dir: pathlib.Path) -> pathlib.Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"grants_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    return path


def cmd_export(args):
    fmt    = (args.format or "both").lower()
    out    = pathlib.Path(args.output) if args.output else EXPORT_DIR

    conn = get_connection()
    rows = _all_items(conn)
    conn.close()

    print(f"\n Exporting {len(rows)} items …\n")

    if fmt in ("csv", "both"):
        p = export_csv(rows, out)
        print(f"   CSV  → {p}")

    if fmt in ("json", "both"):
        p = export_json(rows, out)
        print(f"   JSON → {p}")

    print()


def cmd_stats(_args):
    conn = get_connection()

    total       = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    by_source   = conn.execute("SELECT source, COUNT(*) FROM items GROUP BY source").fetchall()
    with_deadline = conn.execute("SELECT COUNT(*) FROM items WHERE earliest_deadline IS NOT NULL").fetchone()[0]
    with_amount   = conn.execute("SELECT COUNT(*) FROM items WHERE funding_amounts IS NOT NULL AND funding_amounts != '[]'").fetchone()[0]
    with_email    = conn.execute("SELECT COUNT(*) FROM items WHERE emails IS NOT NULL AND emails != '[]'").fetchone()[0]
    with_phone    = conn.execute("SELECT COUNT(*) FROM items WHERE phone_numbers IS NOT NULL AND phone_numbers != '[]'").fetchone()[0]

    upcoming = conn.execute("""
        SELECT id, source, title, earliest_deadline
        FROM items
        WHERE earliest_deadline >= ?
        ORDER BY earliest_deadline ASC
        LIMIT 5
    """, (date.today().isoformat(),)).fetchall()

    top_amounts = conn.execute("""
        SELECT source, title, funding_amounts
        FROM items
        WHERE funding_amounts IS NOT NULL AND funding_amounts != '[]'
        ORDER BY id DESC
        LIMIT 5
    """).fetchall()

    print("\n" + "═" * 50)
    print("  DATABASE STATISTICS")
    print("═" * 50)
    print(f"  Total items     : {total}")
    for src, count in by_source:
        print(f"    [{src.upper()}]          : {count}")
    print(f"  With deadline   : {with_deadline}")
    print(f"  With amounts    : {with_amount}")
    print(f"  With email      : {with_email}")
    print(f"  With phone      : {with_phone}")

    print("\n  UPCOMING DEADLINES (next 5)")
    print("  " + "─" * 46)
    if upcoming:
        for row in upcoming:
            title = (row["title"] or "—")[:45]
            print(f"  {row['earliest_deadline']}  [{row['source'].upper()}]  {title}")
    else:
        print("  No upcoming deadlines found.")

    print("\n  RECENT ITEMS WITH FUNDING")
    print("  " + "─" * 46)
    for row in top_amounts:
        title = (row["title"] or "—")[:35]
        try:
            amounts = json.loads(row["funding_amounts"] or "[]")
            amt_str = ", ".join(amounts[:2])
        except Exception:
            amt_str = "—"
        print(f"  [{row['source'].upper()}]  {title:<35}  {amt_str}")

    print("═" * 50 + "\n")
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Grant Scraper CLI — scrape, search, export, stats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py scrape --source ua
  python cli.py search bolsa --source ua --limit 10
  python cli.py export --format json --output ./out
  python cli.py stats
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="Run the full scrape → parse → analyze pipeline")
    p_scrape.add_argument("--source", choices=["ua", "anr", "all"], default="all",
                          help="Which source to scrape (default: all)")

    # search
    p_search = sub.add_parser("search", help="Search grants by keyword")
    p_search.add_argument("term", help="Keyword(s) to search")
    p_search.add_argument("--source", choices=["ua", "anr"], default=None,
                          help="Filter by source")
    p_search.add_argument("--limit", type=int, default=20,
                          help="Max results (default: 20)")

    # export
    p_export = sub.add_parser("export", help="Export data to CSV and/or JSON")
    p_export.add_argument("--format", choices=["csv", "json", "both"], default="both",
                          help="Export format (default: both)")
    p_export.add_argument("--output", default=None,
                          help="Output directory (default: data/exports/)")

    # stats
    sub.add_parser("stats", help="Show database statistics")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "scrape": cmd_scrape,
        "search": cmd_search,
        "export": cmd_export,
        "stats":  cmd_stats,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
