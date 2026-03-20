#!/usr/bin/env python3
"""Enrichissement des articles avec analyse de sentiment et ton éditorial.

Ajoute les champs suivants aux articles qui n'en disposent pas encore :
  - sentiment      : "positif" | "neutre" | "négatif"
  - score_sentiment: int 1-5
  - ton_editorial  : "factuel" | "alarmiste" | "promotionnel" | "critique" | "analytique"
  - score_ton      : int 1-5

Mode Round-Robin (comportement par défaut sans --flux ni --keyword) :
  - Traite UN seul fichier/source par exécution, en tournant sur tous les fichiers
  - L'état est mémorisé dans data/enrich_sentiment_state.json
  - Idéal en cron quotidien : chaque jour une source différente est enrichie

Usage :
    python3 scripts/enrich_sentiment.py                         # Round-robin : 1 fichier
    python3 scripts/enrich_sentiment.py --all                   # Tous les fichiers d'un coup
    python3 scripts/enrich_sentiment.py --flux Intelligence-artificielle
    python3 scripts/enrich_sentiment.py --keyword OpenAI
    python3 scripts/enrich_sentiment.py --dry-run
    python3 scripts/enrich_sentiment.py --force   # Réanalyse même les articles déjà enrichis
    python3 scripts/enrich_sentiment.py --status  # Affiche l'état Round-Robin sans traiter
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.config import get_config
from utils.api_client import get_ai_client
from utils.logging import default_logger
from utils.article_index import get_article_index

_STATE_FILE = _PROJECT_ROOT / "data" / "enrich_sentiment_state.json"


# ── État Round-Robin ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_file_idx": -1, "last_run": None, "last_file": None, "total_files": 0}


def _save_state(idx: int, total: int, file_path: str, enriched: int) -> None:
    _STATE_FILE.write_text(
        json.dumps({
            "last_file_idx": idx,
            "last_file": file_path,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "total_files": total,
            "last_enriched": enriched,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Collecte ─────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Enrichissement sentiment WUDD.ai")
    parser.add_argument("--flux", help="Nom du flux (dossier sous data/articles/)")
    parser.add_argument("--keyword", help="Mot-clé (fichier sous data/articles-from-rss/)")
    parser.add_argument("--all", action="store_true", dest="all_files",
                        help="Traite tous les fichiers (désactive le Round-Robin)")
    parser.add_argument("--dry-run", action="store_true", help="Analyse sans sauvegarder")
    parser.add_argument("--force", action="store_true", help="Réanalyse même les articles déjà enrichis")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Délai entre appels API en secondes (défaut: 0.5)")
    parser.add_argument("--status", action="store_true",
                        help="Affiche l'état Round-Robin et quitte")
    return parser.parse_args()


def collect_all_json_files(config) -> list[Path]:
    """Retourne la liste triée des fichiers JSON pour le Round-Robin.

    Parcourt les deux répertoires :
      - data/articles-from-rss/  (articles par mot-clé RSS / web)
      - data/articles/<flux>/    (articles par flux JSON)
    """
    files = []
    # Articles par mot-clé RSS
    rss_dir = config.project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for f in sorted(rss_dir.rglob("*.json")):
            if "cache" not in f.relative_to(rss_dir).parts:
                files.append(f)
    # Articles par flux JSON
    flux_dir = config.project_root / "data" / "articles"
    if flux_dir.exists():
        for f in sorted(flux_dir.rglob("*.json")):
            parts = f.relative_to(flux_dir).parts
            if "cache" not in parts:
                files.append(f)
    return files


def collect_json_files(config, flux: str = None, keyword: str = None) -> list[Path]:
    """Retourne la liste des fichiers JSON pour --flux ou --keyword."""
    files = []
    if keyword:
        target = config.project_root / "data" / "articles-from-rss" / f"{keyword}.json"
        if target.exists():
            files.append(target)
        else:
            rss_dir = config.project_root / "data" / "articles-from-rss"
            for f in rss_dir.glob("*.json"):
                if f.stem.lower() == keyword.lower():
                    files.append(f)
    elif flux:
        flux_dir = config.project_root / "data" / "articles" / flux
        if flux_dir.exists():
            files.extend(sorted(flux_dir.rglob("*.json")))
    return [f for f in files if "cache" not in str(f)]


# ── Enrichissement ───────────────────────────────────────────────────────────

SAVE_EVERY = 50  # Sauvegarde intermédiaire toutes les N enrichissements

def enrich_file(json_file: Path, client, dry_run: bool, force: bool, delay: float) -> tuple[int, int]:
    """Enrichit les articles d'un fichier JSON. Retourne (enrichis, ignorés)."""
    try:
        articles = json.loads(json_file.read_text(encoding="utf-8"))
        if not isinstance(articles, list):
            return 0, 0
    except (json.JSONDecodeError, OSError) as e:
        default_logger.warning(f"Impossible de lire {json_file}: {e}")
        return 0, 0

    enriched = 0
    skipped = 0
    modified = False

    for article in articles:
        resume = article.get("Résumé", "")
        if not isinstance(resume, str) or len(resume) < 50:
            skipped += 1
            continue

        already_done = "sentiment" in article and "ton_editorial" in article
        if already_done and not force:
            skipped += 1
            continue

        default_logger.info(
            f"  Analyse sentiment : {article.get('Sources', '?')} — "
            f"{article.get('Date de publication', '')[:10]}"
        )

        if dry_run:
            default_logger.info("  [DRY-RUN] Analyse simulée")
            enriched += 1
            continue

        result = client.generate_sentiment(resume)
        if result is None:
            # echec_parse : réponse reçue mais JSON non extractible
            article["enrichissement_statut"] = "echec_parse"
            modified = True
            default_logger.warning("  Réponse sentiment non parseable (echec_parse)")
            skipped += 1
        elif result:
            article.update(result)
            article["enrichissement_statut"] = "ok"
            enriched += 1
            modified = True
        else:
            # {} : echec_api (exception réseau)
            article["enrichissement_statut"] = "echec_api"
            modified = True
            default_logger.warning("  Analyse sentiment vide ou erreur API")
            skipped += 1

        # Sauvegarde intermédiaire toutes les SAVE_EVERY enrichissements (atomique)
        if modified and not dry_run and enriched % SAVE_EVERY == 0:
            try:
                _tmp = json_file.with_suffix(".tmp")
                _tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
                _tmp.replace(json_file)
                default_logger.info(f"  ↳ Sauvegarde intermédiaire ({enriched} enrichis) → {json_file.name}")
            except OSError as e:
                default_logger.error(f"  Erreur d'écriture {json_file}: {e}")

        if delay > 0:
            time.sleep(delay)

    if modified and not dry_run:
        try:
            _tmp = json_file.with_suffix(".tmp")
            _tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
            _tmp.replace(json_file)
            default_logger.info(f"  Sauvegardé → {json_file.name}")
            # Mise à jour de l'article_index après enrichissement sentiment (proposition 1)
            rel = str(json_file.relative_to(_PROJECT_ROOT)).replace("\\", "/")
            try:
                get_article_index(_PROJECT_ROOT).update(articles, rel)
            except Exception as _idx_e:
                default_logger.warning(f"  Index non mis à jour : {_idx_e}")
        except OSError as e:
            default_logger.error(f"  Erreur d'écriture {json_file}: {e}")

    return enriched, skipped


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    config = get_config()

    # ── Mode --status ────────────────────────────────────────────────────────
    if args.status:
        state = _load_state()
        all_files = collect_all_json_files(config)
        total = len(all_files)
        idx = state.get("last_file_idx", -1)
        next_idx = (idx + 1) % total if total else 0
        print(f"=== État Round-Robin enrichissement sentiment ===")
        print(f"  Fichiers disponibles : {total}")
        print(f"  Dernier traité (#{idx}) : {state.get('last_file', 'aucun')}")
        print(f"  Dernier passage       : {state.get('last_run', 'jamais')}")
        print(f"  Dernier enrichis      : {state.get('last_enriched', 0)}")
        print(f"  Prochain (#{next_idx}) : {all_files[next_idx].relative_to(config.project_root) if total else '—'}")
        print(f"  Cycle complet estimé  : {total} jour(s)")
        return

    client = get_ai_client()

    default_logger.info("=== Enrichissement sentiment WUDD.ai ===")
    if args.dry_run:
        default_logger.info("[DRY-RUN activé — aucune modification ne sera sauvegardée]")

    # ── Mode ciblé (--flux ou --keyword) ─────────────────────────────────────
    if args.flux or args.keyword:
        files = collect_json_files(config, flux=args.flux, keyword=args.keyword)
        if not files:
            default_logger.info("Aucun fichier JSON trouvé.")
            return
        default_logger.info(f"{len(files)} fichier(s) à traiter")
        total_enriched = 0
        total_skipped = 0
        for json_file in files:
            default_logger.info(f"→ {json_file.relative_to(config.project_root)}")
            e, s = enrich_file(json_file, client, args.dry_run, args.force, args.delay)
            total_enriched += e
            total_skipped += s
        default_logger.info(
            f"=== Terminé : {total_enriched} enrichis, {total_skipped} ignorés ==="
        )
        return

    # ── Mode --all ────────────────────────────────────────────────────────────
    all_files = collect_all_json_files(config)
    if not all_files:
        default_logger.info("Aucun fichier JSON trouvé.")
        return

    if args.all_files:
        default_logger.info(f"Mode --all : {len(all_files)} fichier(s) à traiter")
        total_enriched = 0
        total_skipped = 0
        for json_file in all_files:
            default_logger.info(f"→ {json_file.relative_to(config.project_root)}")
            e, s = enrich_file(json_file, client, args.dry_run, args.force, args.delay)
            total_enriched += e
            total_skipped += s
        default_logger.info(
            f"=== Terminé : {total_enriched} enrichis, {total_skipped} ignorés ==="
        )
        return

    # ── Mode Round-Robin (défaut) ─────────────────────────────────────────────
    total = len(all_files)
    state = _load_state()
    next_idx = (state.get("last_file_idx", -1) + 1) % total
    json_file = all_files[next_idx]
    rel_path = str(json_file.relative_to(config.project_root))

    default_logger.info(f"Mode Round-Robin — fichier {next_idx + 1}/{total}")
    default_logger.info(f"→ {rel_path}")

    enriched, skipped = enrich_file(json_file, client, args.dry_run, args.force, args.delay)

    if not args.dry_run:
        _save_state(next_idx, total, rel_path, enriched)

    default_logger.info(
        f"=== Terminé : {enriched} enrichis, {skipped} ignorés "
        f"— prochain : fichier {(next_idx + 1) % total + 1}/{total} ==="
    )


if __name__ == "__main__":
    main()
