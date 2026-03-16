import logging
import pathlib
import time

from playwright.sync_api import sync_playwright, Page

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR = pathlib.Path(__file__).parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"

MAX_RETRIES = 3
RETRY_DELAY = 3


def scrape_page(page: Page, url: str, file_path: pathlib.Path, retries: int = MAX_RETRIES):
    """Visit a URL and save its HTML. Retries up to `retries` times on failure."""
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, timeout=15000)
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            logging.info(f"Saved: {url} → {file_path.name}")
            return
        except Exception as e:
            logging.warning(f"[Attempt {attempt}/{retries}] Error on {url}: {e}")
            if attempt < retries:
                logging.info(f"Retrying in {RETRY_DELAY}s …")
                time.sleep(RETRY_DELAY)
            else:
                logging.error(f"Failed after {retries} attempts: {url}")



def get_ua_article_links(page: Page) -> list[str]:
    """Paginate through all news and collect article links."""
    while page.get_by_role("button", name="Carregar mais").is_visible():
        try:
            page.get_by_role("button", name="Carregar mais").click(timeout=5000)
            page.wait_for_load_state("networkidle")
            time.sleep(1)
        except Exception as e:
            logging.error(f"[UA] Error clicking 'Carregar mais': {e}")
            break

    links = page.eval_on_selector_all(
        "a[href*='/pt/noticias/3/']",
        "elements => [...new Set(elements.map(el => el.href))]"
    )
    logging.info(f"[UA] Found {len(links)} article links")
    return links


def scrape_ua(page: Page):
    """Scrape all news articles from Universidade de Aveiro."""
    logging.info("Starting Universidade de Aveiro scrape")
    articles_dir = BRONZE_DIR / "ua_news"
    articles_dir.mkdir(parents=True, exist_ok=True)

    try:
        page.goto("https://www.ua.pt/pt/noticias/3")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
    except Exception as e:
        logging.error(f"[UA] Failed to navigate to main page: {e}")
        return

    links = get_ua_article_links(page)
    for i, url in enumerate(links, start=1):
        scrape_page(page, url, articles_dir / f"article_{i:04d}.html")

    logging.info(f"[UA] {len(links)} articles saved to {articles_dir}")




ANR_LISTING_URL = "https://anr.fr/fr/appels/"
ANR_BASE        = "https://anr.fr"


def get_anr_call_links(page: Page) -> list[str]:
    """
    Collect all call-for-proposals links from the ANR listing page.
    ANR uses a simple static list — no JS pagination needed.
    Article URLs follow the pattern /fr/detail/call/...
    """
    links = page.eval_on_selector_all(
        "a[href*='/fr/detail/call/'], a[href*='/fr/aapg']",
        """elements => [...new Set(
            elements
                .map(el => el.href)
                .filter(href =>
                    href.includes('anr.fr') &&
                    !href.includes('#')
                )
        )]"""
    )
    logging.info(f"[ANR] Found {len(links)} call links")
    return links


def scrape_anr(page: Page):
    """Scrape all open calls for proposals from ANR."""
    logging.info("Starting ANR scrape")
    anr_dir = BRONZE_DIR / "anr_appels"
    anr_dir.mkdir(parents=True, exist_ok=True)

    try:
        page.goto(ANR_LISTING_URL, timeout=20000)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
    except Exception as e:
        logging.error(f"[ANR] Failed to navigate to listing page: {e}")
        return

    links = get_anr_call_links(page)

    if not links:
        logging.warning("[ANR] No links found — saving listing page as fallback")
        scrape_page(page, ANR_LISTING_URL, anr_dir / "listing_page.html")
        return

    for i, url in enumerate(links, start=1):
        scrape_page(page, url, anr_dir / f"appel_{i:04d}.html")

    logging.info(f"[ANR] {len(links)} calls saved to {anr_dir}")



def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        scrape_ua(page)
        scrape_anr(page)

        browser.close()
        logging.info("All scraping complete.")


if __name__ == "__main__":
    main()
