import sys
sys.path.insert(0, "src")

from src.cli import build_parser

if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "scrape": __import__("src.cli", fromlist=["cmd_scrape"]).cmd_scrape,
        "search": __import__("src.cli", fromlist=["cmd_search"]).cmd_search,
        "export": __import__("src.cli", fromlist=["cmd_export"]).cmd_export,
        "stats":  __import__("src.cli", fromlist=["cmd_stats"]).cmd_stats,
    }
    dispatch[args.command](args)