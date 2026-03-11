import logging
import pathlib
import time

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR = pathlib.Path(__file__).parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "ua_news"
ARTICLES_DIR = BRONZE_DIR / "articles"
BRONZE_DIR.mkdir(parents=True, exist_ok=True)
ARTICLES_DIR.mkdir(parents=True, exist_ok=True)


def get_all_article_links(page) -> list[str]:
    """Load all announcements by clicking 'Carregar mais', save each paginated page, then collect all article links."""
    i = 0

    while page.get_by_role("button", name="Carregar mais").is_visible():
        i += 1
        html_raw = page.content()
        file_path = BRONZE_DIR / f"page_{i}.html"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_raw)
        logging.info(f"Page {i} written to {file_path}")
        try:
            page.get_by_role("button", name="Carregar mais").click(timeout=5000)
            page.wait_for_load_state("networkidle")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Error clicking 'Carregar mais' button: {e}")
            break

    # Save the final page state (after the last click)
    i += 1
    html_raw = page.content()
    file_path = BRONZE_DIR / f"page_{i}.html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_raw)
    logging.info(f"Final page {i} written to {file_path}")

    # Match pattern: /pt/noticias/3/XXXXX (article links only, not category pages)
    links = page.eval_on_selector_all(
        "a[href*='/pt/noticias/3/']",
        "elements => [...new Set(elements.map(el => el.href))]"
    )
    logging.info(f"Found {len(links)} article links")
    return links


def scrape_article(page, url: str, index: int):
    """Visit a single article page and save its HTML."""
    try:
        page.goto(url, timeout=15000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        html = page.content()
        file_path = ARTICLES_DIR / f"article_{index:04d}.html"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html)
        logging.info(f"[{index}] Saved: {url} → {file_path.name}")

    except Exception as e:
        logging.error(f"[{index}] Error on {url}: {e}")


def scrape_ua_news():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to the main news page
        try:
            page.goto("https://www.ua.pt/pt/noticias/3")
            page.wait_for_load_state("networkidle")
        except Exception as e:
            logging.error(f"Failed to navigate to main page: {e}")
            browser.close()
            return

        # Paginate through all pages and collect article links
        links = get_all_article_links(page)

        # Visit each article and save its HTML
        for i, url in enumerate(links, start=1):
            scrape_article(page, url, i)

        browser.close()
        logging.info(f"Scraping complete — {len(links)} articles saved to {ARTICLES_DIR}")


if __name__ == "__main__":
    scrape_ua_news()