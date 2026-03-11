import sqlite3
import re
import pathlib

BASE_DIR = pathlib.Path(__file__).parent.parent
SILVER_DIR = BASE_DIR / "data" / "silver" / "ua_news"
SILVER_DIR.mkdir(parents=True, exist_ok=True)

def analyze_news_data(silver_dir=SILVER_DIR):
    deadlines = []
    funding_amounts = []
    emails = []
    phone_numbers = []
    conn = sqlite3.connect(silver_dir / "ua_news.db")
    cursor = conn.cursor()

    cursor.execute("SELECT title, description FROM news")
    rows = cursor.fetchall()

    for title, description in rows:
        if title and description:
            deadline = re.search(r'\d{2}[-/\.]\d{2}[-/\.]\d{4}', description)
            if deadline:
                deadlines.append(deadline.group(0))
            deadline = re.search(r'\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}', description)
            if deadline:
                deadlines.append(deadline.group(0))
            funding_amount = re.search(r'[\d\.,]+\s?€|€\s?[\d\.,]+', description)
            if funding_amount:
                funding_amounts.append(funding_amount.group(0))
            email = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', description)
            if email:
                emails.append(email.group(0))
            phone_number = re.search(r'(?:\+351|00351)?\s?[29]\d{8}', description)
            if phone_number:
                phone_numbers.append(phone_number.group(0))

    conn.commit()
    conn.close()


    return {
        "deadlines": deadlines,
        "funding_amounts": funding_amounts,
        "emails": emails,
        "phone_numbers": phone_numbers
    }