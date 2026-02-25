import sqlite3
import re

def analyze_news_data(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    