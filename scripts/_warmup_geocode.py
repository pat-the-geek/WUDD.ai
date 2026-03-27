#!/usr/bin/env python3
"""Préchauffage one-shot du cache geocode pour les top entités GPE/LOC.
Appelle directement Wikipedia + Nominatim (sans passer par l'API Flask).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from utils.entity_index import get_entity_index

PROJECT_ROOT = Path(__file__).parent.parent

WIKIPEDIA_UA = (
    "WUDD.ai/2.1.0 (news monitoring tool; "
    "https://github.com/patrickostertag) python-requests"
)

def geocode_batch(names: list, cache: dict) -> dict:
    """Geocode une liste de noms via Wikipedia + Nominatim, en mettant à jour cache."""
    to_fetch = [n for n in names if n not in cache]
    if not to_fetch:
        return cache

    BATCH = 50
    for i in range(0, len(to_fetch), BATCH):
        batch = to_fetch[i:i + BATCH]
        titles_str = "|".join(batch)

        # Wikipedia pour lat/lon
        wiki_coords: dict = {}
        for lang in ("fr", "en"):
            try:
                r = requests.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={"action": "query", "titles": titles_str,
                            "prop": "coordinates", "format": "json", "origin": "*"},
                    headers={"User-Agent": WIKIPEDIA_UA},
                    timeout=10,
                )
                data = r.json()
                pages = data.get("query", {}).get("pages", {})
                normalized = {n["from"]: n["to"] for n in data.get("query", {}).get("normalized", [])}
                for page in pages.values():
                    if "coordinates" not in page:
                        continue
                    title = page.get("title", "")
                    coords = {"lat": page["coordinates"][0]["lat"], "lon": page["coordinates"][0]["lon"]}
                    wiki_coords[title] = coords
                    for orig, norm in normalized.items():
                        if norm == title:
                            wiki_coords[orig] = coords
            except Exception:
                continue
            if lang == "fr" and len(wiki_coords) >= len(batch):
                break

        # Nominatim pour polygones + fallback lat/lon
        for name in batch:
            try:
                time.sleep(0.15)
                nom_r = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": name, "format": "json", "limit": 1,
                            "polygon_geojson": 1, "polygon_threshold": "0.005"},
                    headers={"User-Agent": WIKIPEDIA_UA},
                    timeout=12,
                )
                results = nom_r.json()
                if results:
                    geojson = results[0].get("geojson")
                    nom_lat = float(results[0]["lat"])
                    nom_lon = float(results[0]["lon"])
                    if name in wiki_coords:
                        cache[name] = {"lat": wiki_coords[name]["lat"],
                                       "lon": wiki_coords[name]["lon"],
                                       "geojson": geojson}
                    else:
                        cache[name] = {"lat": nom_lat, "lon": nom_lon, "geojson": geojson}
                    continue
            except Exception:
                pass
            if name in wiki_coords:
                cache[name] = {**wiki_coords[name], "geojson": None}

    return cache


def main():
    eidx = get_entity_index(PROJECT_ROOT)
    entries = eidx.get_all_entries()
    gpe_loc = [
        (k.split(":", 1)[1], len(v))
        for k, v in entries.items()
        if k.startswith("GPE:") or k.startswith("LOC:")
    ]
    gpe_loc.sort(key=lambda x: -x[1])
    all_names = [n for n, _ in gpe_loc[:200]]

    cache_path = PROJECT_ROOT / "data" / "geocode_cache.json"
    cache = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            cache = {k: v for k, v in raw.items() if v is not None and "geojson" in v}
        except Exception:
            pass

    already = sum(1 for n in all_names if n in cache)
    to_do = len(all_names) - already
    print(f"Cache existant: {already}/{len(all_names)} — à geocoder: {to_do}")

    if to_do == 0:
        print("Rien à faire.")
        return

    CHUNK = 25
    for i in range(0, len(all_names), CHUNK):
        chunk = all_names[i:i + CHUNK]
        t0 = time.time()
        cache = geocode_batch(chunk, cache)
        elapsed = time.time() - t0
        cached_now = sum(1 for n in all_names if n in cache)
        print(f"  Lot {i // CHUNK + 1}: {cached_now}/{len(all_names)} en cache ({elapsed:.1f}s)")
        # Sauvegarde intermédiaire
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Cache préchauffé — {len(cache)} entrées.")


if __name__ == "__main__":
    main()

