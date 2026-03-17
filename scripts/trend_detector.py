#!/usr/bin/env python3
"""Détecteur de tendances : compare le volume de mentions des entités
sur les fenêtres 24h et 7j glissants et génère des alertes.

Sortie : data/alertes.json (liste d'alertes triées par ratio décroissant)

Les règles (seuils, types surveillés, filtres, notifications) sont configurables
dans config/alert_rules.json. Les options CLI permettent de surcharger les valeurs
par défaut à la volée.

Usage :
    python3 scripts/trend_detector.py [--top N] [--threshold RATIO] [--dry-run]

Options :
    --top N           Nombre d'entités alertes à conserver (défaut: valeur config)
    --threshold RATIO Ratio minimal 24h/7j global (surcharge la config)
    --dry-run         Affiche les alertes sans écrire alertes.json
    --no-notify       Désactive les notifications webhook même si configurées
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Résolution robuste de la racine du projet
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from utils.logging import default_logger
from utils.config import get_config
from utils.date_utils import parse_article_date
from utils.entity_index import get_entity_index


# ── Constantes ───────────────────────────────────────────────────────────────

# Types d'entités surveillés par défaut (surchargeables via alert_rules.json)
_DEFAULT_MONITORED_TYPES = {
    "PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "NORP", "LOC", "FAC"
}

_OUTPUT_FILE = _PROJECT_ROOT / "data" / "alertes.json"
_RULES_FILE  = _PROJECT_ROOT / "config" / "alert_rules.json"


# ── Chargement des règles ────────────────────────────────────────────────────

def _load_alert_rules() -> dict:
    """Charge config/alert_rules.json. Retourne un dict vide si absent."""
    if not _RULES_FILE.exists():
        default_logger.warning(
            f"Fichier de règles introuvable : {_RULES_FILE}. "
            "Utilisation des valeurs par défaut."
        )
        return {}
    try:
        return json.loads(_RULES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        default_logger.error(f"Erreur de lecture de alert_rules.json : {exc}")
        return {}


def _build_monitored_types(rules: dict) -> set[str]:
    """Retourne l'ensemble des types d'entités à surveiller selon la config."""
    types_cfg = rules.get("types_entites", {})
    if not types_cfg:
        return _DEFAULT_MONITORED_TYPES
    return {etype for etype, cfg in types_cfg.items() if cfg.get("enabled", True)}


def _get_type_threshold(rules: dict, etype: str, global_threshold: float) -> tuple[float, int]:
    """Retourne (ratio_seuil, min_mentions) pour un type d'entité donné."""
    types_cfg = rules.get("types_entites", {})
    cfg = types_cfg.get(etype, {})
    ratio = cfg.get("threshold_ratio", global_threshold)
    min_m = cfg.get("min_mentions", rules.get("global", {}).get("min_mentions_24h", 2))
    return ratio, min_m


def _niveau_from_rules(rules: dict, ratio: float) -> str:
    """Détermine le niveau d'alerte à partir des règles configurées."""
    niveaux = rules.get("niveaux", {})
    if not niveaux:
        # Fallback hardcodé
        if ratio >= 5.0:
            return "critique"
        if ratio >= 3.0:
            return "élevé"
        return "modéré"

    # Parcourt les niveaux dans l'ordre croissant de ratio_min
    sorted_niveaux = sorted(
        niveaux.items(),
        key=lambda kv: kv[1].get("ratio_min", 0),
        reverse=True,
    )
    for _, cfg in sorted_niveaux:
        if ratio >= cfg.get("ratio_min", 0):
            return cfg.get("label", "modéré")
    return "modéré"


# ── Parsing de date ───────────────────────────────────────────────────────────

def _parse_date(date_str: str):
    """Retourne un datetime UTC naïf ou None (délègue à utils.date_utils)."""
    dt = parse_article_date(date_str)
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc)


# ── Collecte des entités ──────────────────────────────────────────────────────

def _collect_from_index(
    project_root: Path,
    cutoff,
    monitored_types: set[str],
    exclude_entities: set[str],
    len_min: int,
    len_max: int,
) -> dict[str, int]:
    """Compte les mentions via entity_index (O(k) sur les clés d'index)."""
    counts: dict[str, int] = defaultdict(int)
    eidx = get_entity_index(project_root)
    all_entries = eidx.get_all_entries()  # { "TYPE:value": [{file, idx, date}, ...] }
    for key, refs in all_entries.items():
        parts = key.split(":", 1)
        if len(parts) != 2:
            continue
        etype, value = parts[0], parts[1]
        if etype not in monitored_types:
            continue
        value = value.strip()
        if not value:
            continue
        if len(value) < len_min or len(value) > len_max:
            continue
        if value.lower() in exclude_entities:
            continue
        for ref in refs:
            dt = _parse_date(ref.get("date", ""))
            if dt is not None and dt >= cutoff:
                counts[key] += 1
    return counts


def collect_entity_mentions(
    project_root: Path,
    window_days: int,
    monitored_types: set[str] | None = None,
    filters: dict | None = None,
) -> dict[str, int]:
    """Compte les mentions de chaque entité dans la fenêtre temporelle.

    Essaie d'abord l'entity_index (rapide), puis bascule sur rglob si l'index
    est vide ou non disponible.

    Args:
        project_root    : racine du projet
        window_days     : fenêtre temporelle en jours
        monitored_types : ensemble des types d'entités à surveiller
        filters         : dict de filtres (exclure_entites, longueur_min/max)

    Returns:
        { "TYPE:valeur" : count }
    """
    if monitored_types is None:
        monitored_types = _DEFAULT_MONITORED_TYPES
    if filters is None:
        filters = {}

    exclude_entities: set[str] = {e.lower() for e in filters.get("exclure_entites", [])}
    len_min: int = filters.get("longueur_min_entite", 3)
    len_max: int = filters.get("longueur_max_entite", 80)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # ── Tentative via l'index (C) ─────────────────────────────────────────────
    try:
        counts = _collect_from_index(
            project_root, cutoff, monitored_types, exclude_entities, len_min, len_max
        )
        if counts:
            default_logger.debug(
                f"collect_entity_mentions: {len(counts)} entités via index (window={window_days}j)"
            )
            return dict(counts)
    except Exception as _e:
        default_logger.warning(f"collect_entity_mentions: index indisponible ({_e}), fallback rglob")

    # ── Fallback DuckDB (IO parallèle, plus rapide que rglob) ────────────────
    try:
        from utils.db import get_db
        db = get_db(project_root)
        if db.available:
            rows = db.articles_with_entities_in_window(window_days)
            if rows:
                counts: dict[str, int] = defaultdict(int)
                for row in rows:
                    # Re-filtrer par date côté Python (DuckDB filtre best-effort)
                    dt = _parse_date(row.get("date", ""))
                    if dt is not None and dt < cutoff:
                        continue
                    entities_json = row.get("entities_json")
                    if not entities_json:
                        continue
                    try:
                        import json as _json
                        ents = _json.loads(entities_json)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(ents, dict):
                        continue
                    for etype, values in ents.items():
                        if etype not in monitored_types:
                            continue
                        if not isinstance(values, list):
                            continue
                        for v in values:
                            if not isinstance(v, str):
                                continue
                            v = v.strip()
                            if not v or len(v) < len_min or len(v) > len_max:
                                continue
                            if v.lower() in exclude_entities:
                                continue
                            counts[f"{etype}:{v}"] += 1
                if counts:
                    default_logger.debug(
                        f"collect_entity_mentions: {len(counts)} entités via DuckDB"
                        f" (window={window_days}j)"
                    )
                    return dict(counts)
    except Exception as _e:
        default_logger.debug(
            f"collect_entity_mentions: DuckDB indisponible ({_e}), fallback rglob"
        )

    # ── Fallback rglob ────────────────────────────────────────────────────────
    counts = defaultdict(int)
    scan_dirs = [
        project_root / "data" / "articles",
        project_root / "data" / "articles-from-rss",
    ]

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for json_file in scan_dir.rglob("*.json"):
            if "cache" in json_file.relative_to(scan_dir).parts:
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(data, list):
                    continue
            except (json.JSONDecodeError, OSError):
                continue

            for article in data:
                dt = _parse_date(article.get("Date de publication", ""))
                if dt is None or dt < cutoff:
                    continue
                entities = article.get("entities")
                if not isinstance(entities, dict):
                    continue
                for etype, values in entities.items():
                    if etype not in monitored_types:
                        continue
                    if not isinstance(values, list):
                        continue
                    for v in values:
                        if not isinstance(v, str):
                            continue
                        v = v.strip()
                        if not v:
                            continue
                        if len(v) < len_min or len(v) > len_max:
                            continue
                        if v.lower() in exclude_entities:
                            continue
                        counts[f"{etype}:{v}"] += 1

    return dict(counts)


# ── Génération des alertes ────────────────────────────────────────────────────

def detect_trends(
    counts_24h: dict[str, int],
    counts_7j: dict[str, int],
    threshold: float,
    top_n: int,
    rules: dict | None = None,
) -> list[dict]:
    """Compare les deux fenêtres et retourne les entités en tendance.

    Une alerte est déclenchée si ratio (count_24h / avg_per_day_7j) >= threshold.
    Les seuils peuvent varier par type d'entité selon les règles configurées.

    Args:
        counts_24h : mentions sur 24h  { "TYPE:valeur": count }
        counts_7j  : mentions sur 7j
        threshold  : seuil global par défaut (surcharge possible par type)
        top_n      : nombre maximum d'alertes à retourner
        rules      : règles issues de alert_rules.json (optionnel)
    """
    if rules is None:
        rules = {}

    alerts = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for key, count_24h in counts_24h.items():
        etype, value = key.split(":", 1)

        # Seuil et min_mentions spécifiques au type (ou globaux si absent)
        type_threshold, min_mentions = _get_type_threshold(rules, etype, threshold)

        if count_24h < min_mentions:
            continue

        avg_per_day_7j = counts_7j.get(key, 0) / 7.0
        if avg_per_day_7j == 0:
            # Entité absente des 7j : nouveauté absolue
            ratio = float("inf") if count_24h >= min_mentions else 0.0
        else:
            ratio = count_24h / avg_per_day_7j

        if ratio < type_threshold:
            continue

        ratio_display = round(ratio, 2) if ratio != float("inf") else 999.9
        alerts.append({
            "entity_type": etype,
            "entity_value": value,
            "count_24h": count_24h,
            "count_7j": counts_7j.get(key, 0),
            "ratio": ratio_display,
            "niveau": _niveau_from_rules(rules, ratio_display),
            "detected_at": now_iso,
        })

    alerts.sort(key=lambda a: a["ratio"], reverse=True)
    return alerts[:top_n]


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Détecteur de tendances WUDD.ai")
    parser.add_argument("--top", type=int, default=None, help="Nombre max d'alertes")
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Ratio 24h/7j minimal global pour déclencher une alerte (surcharge la config)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans sauvegarder")
    parser.add_argument("--no-notify", action="store_true", help="Désactive les notifications webhook")
    return parser.parse_args()


def _send_notifications(alerts: list[dict], rules: dict) -> None:
    """Envoie des notifications webhook pour les alertes de niveau configuré."""
    notif_cfg = rules.get("notifications", {})

    niveaux_notifies = set(notif_cfg.get("niveaux_notifies", ["élevé", "critique"]))
    alertes_a_notifier = [a for a in alerts if a.get("niveau") in niveaux_notifies]
    if not alertes_a_notifier:
        return

    try:
        from utils.exporters.webhook import notify_alerts
    except ImportError:
        default_logger.warning("Module webhook introuvable, notifications ignorées.")
        return

    results = notify_alerts(alertes_a_notifier, title="WUDD.ai · Alertes tendances")
    for platform, success in results.items():
        if success:
            default_logger.info(f"Notification {platform} envoyée.")
        else:
            default_logger.warning(f"Échec notification {platform}.")


def main():
    args = parse_args()
    rules = _load_alert_rules()

    # Priorité : CLI > config > défaut hardcodé
    global_cfg = rules.get("global", {})
    threshold = args.threshold or global_cfg.get("threshold_ratio", 2.0)
    top_n     = args.top      or global_cfg.get("top_n", 20)

    monitored_types = _build_monitored_types(rules)
    filters = rules.get("filtres", {})

    try:
        config = get_config()
        project_root = config.project_root
    except Exception:
        project_root = _PROJECT_ROOT

    default_logger.info("=== Détecteur de tendances WUDD.ai ===")
    default_logger.info(f"Seuil global : ratio ≥ {threshold} | Top {top_n}")
    default_logger.info(f"Types surveillés : {', '.join(sorted(monitored_types))}")

    default_logger.info("Collecte des mentions (fenêtre 24h)…")
    counts_24h = collect_entity_mentions(project_root, window_days=1,
                                          monitored_types=monitored_types, filters=filters)
    default_logger.info(f"  → {len(counts_24h)} entités trouvées sur 24h")

    default_logger.info("Collecte des mentions (fenêtre 7j)…")
    counts_7j = collect_entity_mentions(project_root, window_days=7,
                                         monitored_types=monitored_types, filters=filters)
    default_logger.info(f"  → {len(counts_7j)} entités trouvées sur 7j")

    alerts = detect_trends(counts_24h, counts_7j, threshold, top_n, rules=rules)
    default_logger.info(f"{len(alerts)} alerte(s) détectée(s)")

    if not alerts:
        default_logger.info("Aucune tendance significative détectée.")
    else:
        for a in alerts[:10]:
            default_logger.info(
                f"  [{a['niveau'].upper()}] {a['entity_type']}:{a['entity_value']} "
                f"— {a['count_24h']} mentions/24h vs {a['count_7j']} /7j "
                f"(ratio {a['ratio']})"
            )

    if args.dry_run:
        default_logger.info("[DRY-RUN] Résultats non sauvegardés.")
        print(json.dumps(alerts, ensure_ascii=False, indent=2))
        return

    _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_FILE.write_text(
        json.dumps(alerts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    default_logger.info(f"Alertes sauvegardées dans {_OUTPUT_FILE}")

    # Notifications webhook (si non désactivées par --no-notify)
    if not args.no_notify:
        _send_notifications(alerts, rules)


if __name__ == "__main__":
    main()
