#!/usr/bin/env python3
"""
scheduler.py — Run the full scrape → parse → analyze pipeline periodically.

Usage:
    python src/scheduler.py              # runs every day at 06:00 (default)
    python src/scheduler.py --interval 12h
    python src/scheduler.py --interval 30m
    python src/scheduler.py --run-now    # one-shot, then exit

Supported interval suffixes: m (minutes), h (hours), d (days).
"""

import argparse
import logging
import pathlib
import sys
import time

try:
    import schedule
except ImportError:
    print("Missing dependency: pip install schedule", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "data" / "silver" / "jobs_and_news.db"


def run_pipeline(source: str = "all") -> None:
    """Execute the full scrape → parse → analyze pipeline."""
    logger.info(f"[Scheduler] Starting pipeline (source={source})")

    #Scrape
    try:
        from playwright.sync_api import sync_playwright

        from src.scraper import scrape_anr, scrape_ua

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            if source in ("ua", "all"):
                scrape_ua(page)
            if source in ("anr", "all"):
                scrape_anr(page)
            browser.close()
        logger.info("[Scheduler] Scraping complete.")
    except Exception as e:
        logger.error(f"[Scheduler] Scraping failed: {e}")
        return

    #Parse
    try:
        from src.parser import process
        process()
        logger.info("[Scheduler] Parsing complete.")
    except Exception as e:
        logger.error(f"[Scheduler] Parsing failed: {e}")
        return

    #Analyze
    try:
        from src.analyzer import run as analyze_run
        analyze_run(DB_PATH)
        logger.info("[Scheduler] Analysis complete.")
    except Exception as e:
        logger.error(f"[Scheduler] Analysis failed: {e}")

    logger.info("[Scheduler] Pipeline finished successfully.")


def _parse_interval(raw: str) -> tuple[int, str]:
    """Parse '12h', '30m', '1d' → (value, unit). Default: (1, 'd')."""
    raw = raw.strip().lower()
    if raw.endswith("m"):
        return int(raw[:-1]), "minutes"
    if raw.endswith("h"):
        return int(raw[:-1]), "hours"
    if raw.endswith("d"):
        return int(raw[:-1]), "days"
    raise ValueError(f"Unknown interval format: '{raw}'. Use e.g. 30m, 6h, 1d.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Periodic Grant Scraper scheduler")
    parser.add_argument("--interval", default="1d",
                        help="Scraping interval, e.g. 30m / 6h / 1d (default: 1d)")
    parser.add_argument("--time",     default="06:00",
                        help="Daily run time HH:MM when --interval is days (default: 06:00)")
    parser.add_argument("--source",   choices=["ua", "anr", "all"], default="all")
    parser.add_argument("--run-now",  action="store_true",
                        help="Run pipeline immediately, then start the scheduler")
    args = parser.parse_args()

    try:
        value, unit = _parse_interval(args.interval)
    except ValueError as e:
        logger.error(e)
        sys.exit(1)

    def job():
        run_pipeline(args.source)

    if unit == "minutes":
        schedule.every(value).minutes.do(job)
        logger.info(f"[Scheduler] Scheduled every {value} minute(s).")
    elif unit == "hours":
        schedule.every(value).hours.do(job)
        logger.info(f"[Scheduler] Scheduled every {value} hour(s).")
    elif unit == "days":
        schedule.every(value).days.at(args.time).do(job)
        logger.info(f"[Scheduler] Scheduled every {value} day(s) at {args.time}.")

    if args.run_now:
        logger.info("[Scheduler] Running pipeline immediately (--run-now).")
        run_pipeline(args.source)

    logger.info("[Scheduler] Scheduler running. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("[Scheduler] Stopped.")


if __name__ == "__main__":
    main()
