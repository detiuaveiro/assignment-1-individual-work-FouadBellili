def main():
    from src.scraper import scrape_ua_news
    from src.parser import extract_data, store_data_in_db
    from src.analyzer import analyze_news_data

    scrape_ua_news()

    data = extract_data()
    store_data_in_db(data)


if __name__ == "__main__":
    main()
