"""
Migration one-shot : ajoute terme_declencheur aux articles existants qui ne l'ont pas.
Relit la logique de correspondance de get-keyword-from-rss.py pour retrouver
le terme qui a déclenché la sélection de l'article.
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEYWORDS_PATH = PROJECT_ROOT / "config/keyword-to-search.json"
OUTPUT_DIR = PROJECT_ROOT / "data/articles-from-rss"

with open(KEYWORDS_PATH, encoding="utf-8") as f:
    keywords = json.load(f)
kw_map = {k["keyword"]: k for k in keywords}

total_updated = 0
total_files = 0

for json_file in sorted(OUTPUT_DIR.glob("*.json")):
    if json_file.stem.startswith("_"):
        continue
    with open(json_file, encoding="utf-8") as f:
        articles = json.load(f)

    updated = 0
    for art in articles:
        if "terme_declencheur" in art:
            continue
        kw = art.get("mot_cle")
        if not kw or kw not in kw_map:
            continue
        kw_obj = kw_map[kw]
        title_lower = art.get("Titre", "").lower()

        trigger = None
        if re.search(r'\b' + re.escape(kw.lower()) + r'\b', title_lower):
            trigger = kw
        if trigger is None:
            for w in kw_obj.get("or", []):
                if re.search(r'\b' + re.escape(w.lower()) + r'\b', title_lower):
                    trigger = w
                    break
        if trigger is None:
            trigger = kw  # fallback : mot-clé principal

        art["terme_declencheur"] = trigger
        updated += 1

    if updated > 0:
        tmp = json_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=4), encoding="utf-8")
        tmp.replace(json_file)
        print(f"  ✓ {json_file.name}: {updated} articles mis à jour")
        total_updated += updated
        total_files += 1

print(f"\nTotal: {total_updated} articles enrichis dans {total_files} fichiers.")
