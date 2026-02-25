import logging
import pathlib
import time

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


BASE_DIR = pathlib.Path(__file__).parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "ua_news"
BRONZE_DIR.mkdir(parents=True, exist_ok=True)

def scrape_ua_news():
    i=0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto("https://www.ua.pt/pt/noticias/3")
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Error navigating to the page: {e}")


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
                time.sleep(2)
            except Exception as e:
                print(f"Error clicking 'Carregar mais' button: {e}")
                break
            
        browser.close()