#!/usr/bin/env python3
"""Enrichissement des articles avec un résumé Markdown formaté (champ `Résumé_md`).

Ajoute le champ `Résumé_md` aux articles qui n'en disposent pas encore : une
version Markdown du `Résumé` (chapitres ###, **gras**/*italique* parcimonieux)
destinée à l'affichage enrichi dans le viewer. Le champ `Résumé` (texte brut)
reste la source de vérité (newsletter, Atom, TTS, dédup, scoring inchangés).

Le reformatage passe par `utils.summary_formatter.format_summary_markdown`
(Ollama local privilégié, fallback cloud). En cas d'échec, l'article est ignoré
(pas de champ écrit) et sera retenté à la prochaine passe.

Mode Round-Robin (défaut sans --flux ni --keyword) :
  - Traite les fichiers en tournant, plafonné à --max-articles reformatages/run
  - État mémorisé dans data/enrich_summary_format_state.json

Usage :
    python3 scripts/enrich_summary_format.py                 # Round-robin
    python3 scripts/enrich_summary_format.py --all           # Tous les fichiers
    python3 scripts/enrich_summary_format.py --keyword openai
    python3 scripts/enrich_summary_format.py --flux Intelligence-artificielle
    python3 scripts/enrich_summary_format.py --dry-run
    python3 scripts/enrich_summary_format.py --force         # Régénère même si Résumé_md existe
    python3 scripts/enrich_summary_format.py --all --since 2026-06-01   # Limiter à une période
    python3 scripts/enrich_summary_format.py --status
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
from utils.logging import default_logger
from utils.summary_formatter import format_summary_markdown
from utils.date_utils import parse_article_date

_STATE_FILE = _PROJECT_ROOT / "data" / "enrich_summary_format_state.json"
_MIN_RESUME_LEN = 60          # En deçà, inutile de structurer en chapitres
_ERROR_PREFIXES = (
    "erreur", "désolé", "je suis désolé", "impossible de générer",
    "je ne peux pas", "i'm sorry", "i am sorry",
)
SAVE_EVERY = 20               # Sauvegarde intermédiaire toutes les N reformatages


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

def collect_all_json_files(config) -> list[Path]:
    """Liste triée des fichiers JSON d'articles (rss + flux), hors cache.

    Exclut `_WUDD.AI_` : ce sont des fichiers DÉRIVÉS (48-heures.json, merged…)
    reconstruits par flux_watcher — les enrichir est inutile et leur Résumé_md
    serait immédiatement écrasé. Les articles sources (fichiers par flux/mot-clé)
    sont enrichis directement.
    """
    files = []
    rss_dir = config.project_root / "data" / "articles-from-rss"
    if rss_dir.exists():
        for f in sorted(rss_dir.rglob("*.json")):
            parts = f.relative_to(rss_dir).parts
            if "cache" in parts or "_WUDD.AI_" in parts:
                continue
            files.append(f)
    flux_dir = config.project_root / "data" / "articles"
    if flux_dir.exists():
        for f in sorted(flux_dir.rglob("*.json")):
            if "cache" not in f.relative_to(flux_dir).parts:
                files.append(f)
    return files


def collect_json_files(config, flux: str = None, keyword: str = None) -> list[Path]:
    """Liste des fichiers JSON pour --flux ou --keyword."""
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


def _looks_like_error(resume: str) -> bool:
    low = resume.strip().lower()
    return any(low.startswith(p) for p in _ERROR_PREFIXES)


# ── Enrichissement ───────────────────────────────────────────────────────────

def _in_period(article: dict, since, until) -> bool:
    """True si la date de publication de l'article est dans [since, until]."""
    if since is None and until is None:
        return True
    dt = parse_article_date(article.get("Date de publication", ""))
    if dt is None:
        return False  # Date inexploitable : exclue d'un filtre de période explicite
    d = dt.date()
    if since is not None and d < since:
        return False
    if until is not None and d > until:
        return False
    return True


def enrich_file(json_file: Path, dry_run: bool, force: bool, delay: float,
                max_articles: int = -1, since=None, until=None) -> tuple[int, int]:
    """Ajoute `Résumé_md` aux articles éligibles. Retourne (enrichis, ignorés)."""
    try:
        articles = json.loads(json_file.read_text(encoding="utf-8"))
        if not isinstance(articles, list):
            return 0, 0
    except (json.JSONDecodeError, OSError) as e:
        default_logger.warning(f"Impossible de lire {json_file}: {e}")
        return 0, 0

    enriched = 0
    skipped = 0
    results: dict[str, str] = {}   # URL → Résumé_md généré (appliqué en merge à l'écriture)

    for article in articles:
        if not _in_period(article, since, until):
            skipped += 1
            continue
        resume = article.get("Résumé", "")
        if not isinstance(resume, str) or len(resume) < _MIN_RESUME_LEN or _looks_like_error(resume):
            skipped += 1
            continue
        if article.get("Résumé_md") and not force:
            skipped += 1
            continue
        if max_articles >= 0 and enriched >= max_articles:
            break

        default_logger.info(
            f"  Reformatage : {article.get('Sources', '?')} — "
            f"{article.get('Date de publication', '')[:10]}"
        )
        if dry_run:
            default_logger.info("  [DRY-RUN] Reformatage simulé")
            enriched += 1
            continue

        md = format_summary_markdown(resume)
        if md:
            url = (article.get("URL") or article.get("url") or "").strip()
            if url:
                results[url] = md
                enriched += 1
            else:
                skipped += 1
        else:
            # Échec IA : on n'écrit rien, l'article sera retenté plus tard.
            skipped += 1

        if results and enriched % SAVE_EVERY == 0:
            n = _merge_write(json_file, results)
            default_logger.info(f"  ↳ Sauvegarde intermédiaire ({n} appliqués) → {json_file.name}")

        if delay > 0:
            time.sleep(delay)

    if results and not dry_run:
        n = _merge_write(json_file, results)
        default_logger.info(f"  Sauvegardé ({n} appliqués) → {json_file.name}")

    return enriched, skipped


def _merge_write(json_file: Path, results: dict) -> int:
    """Applique les Résumé_md générés sur la version DISQUE la plus récente.

    Re-lit le fichier juste avant d'écrire et ne pose `Résumé_md` que sur les
    articles dont l'URL correspond. Évite d'écraser les modifications concurrentes
    (enrichissements NER/sentiment, ajout d'articles par un watcher) survenues
    pendant le reformatage. Écriture atomique.
    """
    try:
        current = json.loads(json_file.read_text(encoding="utf-8"))
        if not isinstance(current, list):
            return 0
    except (json.JSONDecodeError, OSError) as e:
        default_logger.warning(f"  Relecture impossible avant écriture {json_file}: {e}")
        return 0

    applied = 0
    for art in current:
        if not isinstance(art, dict):
            continue
        url = (art.get("URL") or art.get("url") or "").strip()
        if url in results:
            art["Résumé_md"] = results[url]
            applied += 1

    tmp = json_file.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=4), encoding="utf-8")
        tmp.replace(json_file)
    except OSError as e:
        default_logger.error(f"  Erreur d'écriture {json_file}: {e}")
        if tmp.exists():
            tmp.unlink()
        return 0
    return applied


# ── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Enrichissement Résumé_md (Markdown) WUDD.ai")
    p.add_argument("--flux", help="Nom du flux (dossier sous data/articles/)")
    p.add_argument("--keyword", help="Mot-clé (fichier sous data/articles-from-rss/)")
    p.add_argument("--all", action="store_true", dest="all_files",
                   help="Traite tous les fichiers (désactive le Round-Robin)")
    p.add_argument("--dry-run", action="store_true", help="Simule sans sauvegarder")
    p.add_argument("--force", action="store_true", help="Régénère même si Résumé_md existe")
    p.add_argument("--delay", type=float, default=0.2, help="Délai entre appels IA (s, défaut 0.2)")
    p.add_argument("--max-articles", type=int, default=80, dest="max_articles",
                   help="Plafond de reformatages par exécution (défaut 80, -1 = illimité)")
    p.add_argument("--since", help="Ne traiter que les articles publiés à partir de cette date (YYYY-MM-DD)")
    p.add_argument("--until", help="Ne traiter que les articles publiés jusqu'à cette date incluse (YYYY-MM-DD)")
    p.add_argument("--status", action="store_true", help="Affiche l'état Round-Robin et quitte")
    return p.parse_args()


def _parse_bound(value: str | None):
    """Parse une borne de date YYYY-MM-DD en date, ou None."""
    if not value:
        return None
    from datetime import date as _date
    try:
        y, m, d = (int(x) for x in value.split("-"))
        return _date(y, m, d)
    except (ValueError, AttributeError):
        default_logger.warning(f"Date invalide ignorée : {value!r} (format attendu YYYY-MM-DD)")
        return None


def main():
    args = parse_args()
    config = get_config()

    if args.status:
        state = _load_state()
        all_files = collect_all_json_files(config)
        total = len(all_files)
        idx = state.get("last_file_idx", -1)
        next_idx = (idx + 1) % total if total else 0
        print("=== État Round-Robin enrichissement Résumé_md ===")
        print(f"  Fichiers disponibles : {total}")
        print(f"  Dernier traité (#{idx}) : {state.get('last_file', 'aucun')}")
        print(f"  Dernier passage       : {state.get('last_run', 'jamais')}")
        print(f"  Dernier enrichis      : {state.get('last_enriched', 0)}")
        print(f"  Prochain (#{next_idx}) : {all_files[next_idx].relative_to(config.project_root) if total else '—'}")
        return

    default_logger.info("=== Enrichissement Résumé_md (Markdown) WUDD.ai ===")
    if args.dry_run:
        default_logger.info("[DRY-RUN activé — aucune modification sauvegardée]")
    limit = args.max_articles
    default_logger.info(
        f"[Plafond : {limit} reformatages/run]" if limit >= 0 else "[Plafond : illimité]"
    )
    since = _parse_bound(args.since)
    until = _parse_bound(args.until)
    if since or until:
        default_logger.info(f"[Filtre période : {since or '…'} → {until or '…'}]")

    # ── Mode ciblé (--flux / --keyword) ──────────────────────────────────────
    if args.flux or args.keyword:
        files = collect_json_files(config, flux=args.flux, keyword=args.keyword)
        if not files:
            default_logger.info("Aucun fichier JSON trouvé.")
            return
        total_e = total_s = 0
        for f in files:
            remaining = (limit - total_e) if limit >= 0 else -1
            if limit >= 0 and remaining <= 0:
                break
            default_logger.info(f"→ {f.relative_to(config.project_root)}")
            e, s = enrich_file(f, args.dry_run, args.force, args.delay, max_articles=remaining, since=since, until=until)
            total_e += e
            total_s += s
        default_logger.info(f"=== Terminé : {total_e} enrichis, {total_s} ignorés ===")
        return

    all_files = collect_all_json_files(config)
    if not all_files:
        default_logger.info("Aucun fichier JSON trouvé.")
        return

    # ── Mode --all ───────────────────────────────────────────────────────────
    if args.all_files:
        default_logger.info(f"Mode --all : {len(all_files)} fichier(s)")
        total_e = total_s = 0
        for f in all_files:
            remaining = (limit - total_e) if limit >= 0 else -1
            if limit >= 0 and remaining <= 0:
                default_logger.info(f"Plafond de {limit} atteint — arrêt.")
                break
            default_logger.info(f"→ {f.relative_to(config.project_root)}")
            e, s = enrich_file(f, args.dry_run, args.force, args.delay, max_articles=remaining, since=since, until=until)
            total_e += e
            total_s += s
        default_logger.info(f"=== Terminé : {total_e} enrichis, {total_s} ignorés ===")
        return

    # ── Mode Round-Robin (défaut) ────────────────────────────────────────────
    total = len(all_files)
    state = _load_state()
    next_idx = (state.get("last_file_idx", -1) + 1) % total
    total_e = total_s = 0
    last_idx = next_idx

    for offset in range(total):
        cur_idx = (next_idx + offset) % total
        json_file = all_files[cur_idx]
        rel = str(json_file.relative_to(config.project_root))
        remaining = (limit - total_e) if limit >= 0 else -1
        if limit >= 0 and remaining <= 0:
            break
        default_logger.info(f"Round-Robin — fichier {cur_idx + 1}/{total} → {rel}")
        e, s = enrich_file(json_file, args.dry_run, args.force, args.delay, max_articles=remaining, since=since, until=until)
        total_e += e
        total_s += s
        last_idx = cur_idx
        if not args.dry_run:
            _save_state(cur_idx, total, rel, e)
        if e > 0:
            break  # Laisser les autres fichiers leur tour aux prochains passages

    next_after = (last_idx + 1) % total
    default_logger.info(
        f"=== Terminé : {total_e} enrichis, {total_s} ignorés "
        f"— prochain : fichier {next_after + 1}/{total} ==="
    )


if __name__ == "__main__":
    main()
