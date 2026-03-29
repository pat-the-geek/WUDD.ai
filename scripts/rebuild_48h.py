#!/usr/bin/env python3
"""
Reconstruit data/articles-from-rss/_WUDD.AI_/48-heures.json
en agrégeant tous les articles datés des dernières 48h depuis
tous les fichiers JSON du répertoire articles-from-rss/.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RSS_DIR = PROJECT_ROOT / "data" / "articles-from-rss"
WUDD_PATH = RSS_DIR / "_WUDD.AI_" / "48-heures.json"

NOW = datetime.now()
TWO_DAYS_AGO = NOW - timedelta(hours=48)

FORMATS = [
    "%d/%m/%Y",                    # format standard projet
    "%a, %d %b %Y %H:%M:%S %z",   # RFC 2822 avec timezone
    "%a, %d %b %Y %H:%M:%S",      # RFC 2822 sans timezone
    "%Y-%m-%dT%H:%M:%SZ",         # ISO 8601 UTC
    "%Y-%m-%dT%H:%M:%S",          # ISO 8601 sans Z
]


def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except ValueError:
            pass
    return None


seen_urls: set = set()
articles_48h: list = []
files_processed = 0
files_error = 0

for json_file in sorted(RSS_DIR.glob("*.json")):
    try:
        with open(json_file, encoding="utf-8") as f:
            file_articles = json.load(f)
        if not isinstance(file_articles, list):
            continue
        files_processed += 1
        for article in file_articles:
            url = article.get("URL", "")
            if not url or url in seen_urls:
                continue
            pub_dt = parse_date(article.get("Date de publication", ""))
            if pub_dt and pub_dt >= TWO_DAYS_AGO:
                seen_urls.add(url)
                articles_48h.append(article)
    except Exception as e:
        print(f"  ERREUR {json_file.name}: {e}")
        files_error += 1

articles_48h.sort(
    key=lambda a: parse_date(a.get("Date de publication", "")) or datetime.min,
    reverse=True,
)

WUDD_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(WUDD_PATH, "w", encoding="utf-8") as f:
    json.dump(articles_48h, f, ensure_ascii=False, indent=4)

print(f"✓ {len(articles_48h)} articles des 48 dernières heures reconstitués")
print(f"  Fichiers lus : {files_processed}  |  Erreurs : {files_error}")
print(f"  Fenêtre : {TWO_DAYS_AGO.strftime('%d/%m/%Y %H:%M')} → {NOW.strftime('%d/%m/%Y %H:%M')}")
print(f"  Sauvegardé dans : {WUDD_PATH}")
