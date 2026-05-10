#!/usr/bin/env python3
"""Détecteur de tendances : compare le volume de mentions des entités
sur les fenêtres 24h et 7j glissants et génère des alertes.

Sortie : data/alertes.json (liste d'alertes triées par ratio décroissant)

Deux types d'alertes sont générés :
  - ``tendance`` (défaut, champ ``type`` absent) : entité dont les mentions
    sur 24h dépassent le ratio seuil (count_24h / avg_per_day_7j >= threshold).
  - ``silence`` : entité habituellement active (moy. >= 3/j sur 7j) mais
    absente des dernières 24h. Détecte la disparition brusque d'un sujet.

Les règles (seuils, types surveillés, filtres, notifications) sont configurables
dans config/alert_rules.json. Les options CLI permettent de surcharger les valeurs
par défaut à la volée.

Usage :
    python3 scripts/trend_detector.py [--top N] [--threshold RATIO] [--dry-run]

Options :
    --top N                  Nombre d'entités alertes à conserver (défaut: valeur config)
    --threshold RATIO        Ratio minimal 24h/7j global (surcharge la config)
    --silence-threshold AVG  Moyenne journalière minimale pour alerte silence (défaut: 3.0)
    --no-silence             Désactive la détection des silences
    --dry-run                Affiche les alertes sans écrire alertes.json
    --no-notify              Désactive les notifications webhook même si configurées
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

_OUTPUT_FILE    = _PROJECT_ROOT / "data" / "alertes.json"
_RULES_FILE     = _PROJECT_ROOT / "config" / "alert_rules.json"
_WATCHED_FILE   = _PROJECT_ROOT / "data" / "watched_entities.json"


# ── Chargement des règles ────────────────────────────────────────────────────

def _load_watched_entities() -> list[dict]:
    """Charge data/watched_entities.json. Retourne [] si absent ou invalide."""
    if not _WATCHED_FILE.exists():
        return []
    try:
        data = json.loads(_WATCHED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


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
    dt = parse_article_date(date_str, date_only_policy="end")
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
    # NOTE : l'index n'est PAS utilisé comme retour anticipé ici.
    # Raison : l'index ne contient que les articles batch-enrichis (nuit précédente).
    # Les articles collectés dans les dernières 24h (flux_watcher, get-keyword-from-rss)
    # ne sont pas encore indexés. Si l'on retourne l'index pour la fenêtre 7j (non vide
    # grâce à d'autres entités), les entités nouvellement apparues (absentes de l'index
    # pour les 7j) auraient count_7j=0 alors que count_24h>0, ce qui génère des ratios
    # infinis (×999.9) incorrects.
    # On passe toujours par rglob pour garantir la cohérence des deux fenêtres.
    try:
        counts_idx = _collect_from_index(
            project_root, cutoff, monitored_types, exclude_entities, len_min, len_max
        )
        if counts_idx:
            default_logger.debug(
                f"collect_entity_mentions: index disponible ({len(counts_idx)} entités) "
                f"mais on continue via rglob pour inclure les articles non-indexés (window={window_days}j)"
            )
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


def detect_watched_alerts(
    watched: list[dict],
    counts_24h: dict[str, int],
    counts_7j: dict[str, int],
    rules: dict | None = None,
    watched_threshold: float = 1.0,
) -> list[dict]:
    """Génère des alertes pour les entités surveillées.

    Contrairement à detect_trends, ces alertes utilisent un seuil réduit
    (défaut 1.0) pour être sensibles à toute hausse des entités que
    l'utilisateur a explicitement ajoutées à sa liste de surveillance.
    Une entité surveillée absent sur 24h génère tout de même une entrée
    avec count_24h=0 pour signaler le silence.

    Toutes les alertes produites portent le champ ``"watched": True``.
    """
    if not watched:
        return []
    if rules is None:
        rules = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    alerts: list[dict] = []
    for w in watched:
        etype = (w.get("type") or "").upper()
        value = (w.get("value") or "").strip()
        if not etype or not value:
            continue
        key = f"{etype}:{value}"
        count_24h = counts_24h.get(key, 0)
        count_7j  = counts_7j.get(key, 0)
        avg_per_day_7j = count_7j / 7.0
        if avg_per_day_7j == 0:
            ratio = 999.9 if count_24h >= 1 else 0.0
        else:
            ratio = round(count_24h / avg_per_day_7j, 2)
        if ratio < watched_threshold and count_24h == 0:
            # Silence d’une entité surveillée : inclure quand même
            niveau = "info"
        else:
            niveau = _niveau_from_rules(rules, ratio)
        alerts.append({
            "entity_type": etype,
            "entity_value": value,
            "count_24h": count_24h,
            "count_7j": count_7j,
            "ratio": ratio,
            "niveau": niveau,
            "detected_at": now_iso,
            "watched": True,
        })
    return alerts


def _linear_predict_minutes(values: list[float], interval_minutes: int = 60) -> float:
    """Prévoit le prochain point via régression linéaire sur les dernières valeurs.

    Args:
        values           : liste de comptes horaires (du plus ancien au plus récent)
        interval_minutes : intervalle entre chaque point (défaut 60 min)

    Returns:
        Valeur prévue au prochain intervalle. Retourne 0 si données insuffisantes.
    """
    n = len(values)
    if n < 2:
        return 0.0
    # Régression linéaire simple : y = a*x + b
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return mean_y
    slope = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    predicted = slope * n + intercept
    return max(0.0, predicted)


def _build_hourly_series(entity_key: str, project_root: "Path", hours: int = 6) -> list[float]:
    """Construit une série horaire de mentions depuis entity_timeline.json.

    Retourne une liste de `hours` valeurs (les plus récentes d'abord).
    """
    tl_path = project_root / "data" / "entity_timeline.json"
    if not tl_path.exists():
        return []
    try:
        timeline = json.loads(tl_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    # Chercher la clé (format "TYPE:value" ou juste "value")
    data = timeline.get(entity_key, timeline.get(entity_key.split(":", 1)[-1], None))
    if not data or not isinstance(data, dict):
        return []

    mentions = data.get("mentions", [])
    if not mentions:
        return []

    # Agréger par heure sur les `hours` dernières heures
    now = datetime.now(timezone.utc)
    hourly: dict[str, float] = {}
    for m in mentions:
        d = m.get("date", "")
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now - dt).total_seconds() <= hours * 3600:
                hour_key = dt.strftime("%Y-%m-%dT%H:00")
                hourly[hour_key] = hourly.get(hour_key, 0) + m.get("count", 1)
        except Exception:
            pass

    # Construire la série ordonnée par heure
    sorted_keys = sorted(hourly.keys())
    return [hourly[k] for k in sorted_keys]


def add_predictions(alerts: list[dict], project_root: "Path") -> list[dict]:
    """Ajoute le champ `prediction_seuil_dans_minutes` aux alertes en tendance.

    Pour chaque alerte, construit une série horaire et projette le moment
    où le seuil "élevé" (ratio ≥ 4.0) pourrait être atteint.

    Args:
        alerts       : liste d'alertes issues de detect_trends/detect_watched_alerts
        project_root : racine du projet (pour accéder à entity_timeline.json)

    Returns:
        La même liste avec le champ `prediction_seuil_dans_minutes` ajouté.
    """
    SEUIL_CRITIQUE = 4.0  # ratio à partir duquel on prédit le seuil critique

    for alert in alerts:
        if alert.get("niveau") not in ("élevé", "critique", "modéré"):
            continue
        entity_key = f"{alert['entity_type']}:{alert['entity_value']}"
        series = _build_hourly_series(entity_key, project_root, hours=6)
        if len(series) < 2:
            continue
        # Projection : combien d'intervalles horaires jusqu'à SEUIL_CRITIQUE × avg ?
        avg_per_day = alert.get("count_7j", 0) / 7.0
        if avg_per_day <= 0:
            continue
        current_ratio = alert.get("ratio", 0)
        if current_ratio >= SEUIL_CRITIQUE:
            alert["prediction_seuil_dans_minutes"] = 0
            continue
        # Valeur prédite au prochain intervalle (60 min)
        predicted_next = _linear_predict_minutes(series, interval_minutes=60)
        predicted_ratio = predicted_next / avg_per_day if avg_per_day > 0 else 0
        if predicted_ratio >= SEUIL_CRITIQUE:
            # Atteint dans moins d'une heure
            frac = (SEUIL_CRITIQUE - current_ratio) / max(predicted_ratio - current_ratio, 0.01)
            minutes = int(frac * 60)
            alert["prediction_seuil_dans_minutes"] = max(0, min(minutes, 60))
        # Si la tendance linéaire dépasse le seuil à horizon 2-3h
        elif len(series) >= 3:
            predicted_2h = _linear_predict_minutes(series + [predicted_next], interval_minutes=60)
            ratio_2h = predicted_2h / avg_per_day if avg_per_day > 0 else 0
            if ratio_2h >= SEUIL_CRITIQUE:
                alert["prediction_seuil_dans_minutes"] = 120

    return alerts


def detect_silences(
    counts_24h: dict[str, int],
    counts_7j: dict[str, int],
    min_baseline_avg: float = 3.0,
    top_n: int = 10,
    rules: dict | None = None,
) -> list[dict]:
    """Détecte les entités habituellement actives qui ont disparu sur 24h.

    Une alerte de silence est émise pour chaque entité vérifiant :
      - Moyenne journalière sur 7j >= ``min_baseline_avg``
      - Aucune mention sur les dernières 24h (count_24h == 0)

    Les silences indiquent qu'un sujet habituellement couvert a brusquement
    disparu de l'agenda médiatique, information tout aussi précieuse que
    la détection d'une tendance à la hausse.

    Args:
        counts_24h       : mentions sur 24h  { "TYPE:valeur": count }
        counts_7j        : mentions sur 7j   { "TYPE:valeur": count }
        min_baseline_avg : seuil minimal de mentions/jour sur 7j pour
                           déclencher une alerte de silence (défaut : 3.0)
        top_n            : nombre maximum de silences à retourner
        rules            : règles issues de alert_rules.json (optionnel)

    Returns:
        Liste d'alertes de silence triées par baseline_avg_per_day décroissant,
        chacune ayant un champ ``"type": "silence"``.
    """
    if rules is None:
        rules = {}

    monitored_types = _build_monitored_types(rules)
    now_iso = datetime.now(timezone.utc).isoformat()

    silences: list[dict] = []

    for key, count_7j in counts_7j.items():
        etype = key.split(":", 1)[0]

        # Ignorer les types non surveillés
        if monitored_types and etype not in monitored_types:
            continue

        avg_per_day = count_7j / 7.0
        if avg_per_day < min_baseline_avg:
            continue

        # Silence détecté si l'entité est absente des 24h
        if counts_24h.get(key, 0) > 0:
            continue

        value = key.split(":", 1)[1]
        niveau = "élevé" if avg_per_day >= 10.0 else "modéré"

        silences.append({
            "type": "silence",
            "entity_type": etype,
            "entity_value": value,
            "count_24h": 0,
            "count_7j": count_7j,
            "baseline_avg_per_day": round(avg_per_day, 2),
            "niveau": niveau,
            "detected_at": now_iso,
        })

    # Trier par fréquence de référence décroissante (sujets les plus actifs d'abord)
    silences.sort(key=lambda s: s["baseline_avg_per_day"], reverse=True)
    return silences[:top_n]


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Détecteur de tendances WUDD.ai")
    parser.add_argument("--top", type=int, default=None, help="Nombre max d'alertes")
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Ratio 24h/7j minimal global pour déclencher une alerte (surcharge la config)"
    )
    parser.add_argument(
        "--silence-threshold", type=float, default=None,
        help="Moyenne journalière minimale (sur 7j) pour déclencher une alerte de silence "
             "(défaut : 3.0)"
    )
    parser.add_argument("--no-silence", action="store_true",
                        help="Désactive la détection des silences")
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans sauvegarder")
    parser.add_argument("--no-notify", action="store_true", help="Désactive les notifications webhook")
    return parser.parse_args()


def _send_notifications(alerts: list[dict], rules: dict) -> None:
    """Envoie des notifications webhook pour les alertes de niveau configuré."""
    notif_cfg = rules.get("notifications", {})
    watched_threshold = rules.get("global", {}).get("watched_threshold_ratio", 1.0)

    def _to_float(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    niveaux_notifies = set(notif_cfg.get("niveaux_notifies", ["élevé", "critique"]))
    by_level = [a for a in alerts if a.get("niveau") in niveaux_notifies]

    # Veille prioritaire : notifier explicitement les entités surveillées dès
    # qu'elles franchissent le seuil dédié, même si leur niveau n'est pas élevé.
    watched_crossing = [
        a for a in alerts
        if a.get("watched") is True
        and int(a.get("count_24h", 0) or 0) > 0
        and _to_float(a.get("ratio", 0.0), 0.0) >= float(watched_threshold)
    ]

    # Fusion sans doublon (clé type+valeur), priorité à l'alerte watched.
    merged: dict[str, dict] = {}
    for a in by_level:
        key = f"{a.get('entity_type', '')}:{a.get('entity_value', '')}"
        merged[key] = a
    for a in watched_crossing:
        key = f"{a.get('entity_type', '')}:{a.get('entity_value', '')}"
        merged[key] = a

    alertes_a_notifier = list(merged.values())
    if not alertes_a_notifier:
        return

    try:
        from utils.exporters.webhook import notify_alerts
    except ImportError:
        default_logger.warning("Module webhook introuvable, notifications ignorées.")
        return

    results = notify_alerts(alertes_a_notifier, title="WUDD.ai · Alertes tendances & veille prioritaire")
    for platform, success in results.items():
        if success:
            default_logger.info(f"Notification {platform} envoyée.")
        else:
            default_logger.warning(f"Échec notification {platform}.")

    if watched_crossing:
        default_logger.info(
            f"{len(watched_crossing)} entité(s) surveillée(s) notifiée(s) "
            f"(seuil watched ≥ {watched_threshold})."
        )


def main():
    args = parse_args()
    rules = _load_alert_rules()

    # Priorité : CLI > config > défaut hardcodé
    global_cfg = rules.get("global", {})
    threshold = args.threshold or global_cfg.get("threshold_ratio", 2.0)
    top_n     = args.top      or global_cfg.get("top_n", 20)
    silence_baseline_avg = args.silence_threshold or global_cfg.get("silence_baseline_avg", 3.0)

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
    default_logger.info(f"{len(alerts)} alerte(s) de tendance détectée(s)")

    # Alertes prédictives : projeter le franchissement de seuil critique
    alerts = add_predictions(alerts, project_root)
    predicted_count = sum(1 for a in alerts if a.get("prediction_seuil_dans_minutes") is not None)
    if predicted_count:
        default_logger.info(f"{predicted_count} alerte(s) avec prédiction de seuil")

    if not alerts:
        default_logger.info("Aucune tendance significative détectée.")
    else:
        for a in alerts[:10]:
            default_logger.info(
                f"  [{a['niveau'].upper()}] {a['entity_type']}:{a['entity_value']} "
                f"— {a['count_24h']} mentions/24h vs {a['count_7j']} /7j "
                f"(ratio {a['ratio']})"
            )

    # Détection des silences (entités habituellement actives absentes sur 24h)
    silences: list[dict] = []
    if not args.no_silence:
        silences = detect_silences(
            counts_24h, counts_7j,
            min_baseline_avg=silence_baseline_avg,
            top_n=top_n,
            rules=rules,
        )
        default_logger.info(f"{len(silences)} alerte(s) de silence détectée(s)")
        for s in silences[:5]:
            default_logger.info(
                f"  [SILENCE/{s['niveau'].upper()}] {s['entity_type']}:{s['entity_value']} "
                f"— 0 mentions/24h (moy. {s['baseline_avg_per_day']:.1f}/j sur 7j)"
            )

    all_alerts = alerts + silences

    # ── Entités surveillées ──────────────────────────────────────────────────
    # Charger la liste watched et générer des alertes à seuil réduit.
    # Les entités déjà présentes dans all_alerts reçoivent juste le flag
    # watched=True ; les autres sont ajoutées en tête (visibilité garantie).
    watched_threshold = rules.get("global", {}).get("watched_threshold_ratio", 1.0)
    watched_entities = _load_watched_entities()
    if watched_entities:
        watched_alerts = detect_watched_alerts(
            watched_entities, counts_24h, counts_7j, rules=rules,
            watched_threshold=watched_threshold,
        )
        # Déduplication : si une entité surveillée est déjà dans all_alerts,
        # on lui ajoute watched=True et on ne la duplique pas.
        existing_keys = {
            f"{a['entity_type']}:{a['entity_value']}" for a in all_alerts
        }
        for wa in watched_alerts:
            key = f"{wa['entity_type']}:{wa['entity_value']}"
            if key in existing_keys:
                for a in all_alerts:
                    if f"{a['entity_type']}:{a['entity_value']}" == key:
                        a["watched"] = True
            else:
                all_alerts.insert(0, wa)  # en tête pour visibilité
        default_logger.info(
            f"{len(watched_entities)} entité(s) surveillée(s) — "
            f"{len(watched_alerts)} alerte(s) générée(s)"
        )

    if args.dry_run:
        default_logger.info("[DRY-RUN] Résultats non sauvegardés.")
        print(json.dumps(all_alerts, ensure_ascii=False, indent=2))
        return

    _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_FILE.write_text(
        json.dumps(all_alerts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    default_logger.info(
        f"Alertes sauvegardées dans {_OUTPUT_FILE} "
        f"({len(alerts)} tendances + {len(silences)} silences)"
    )

    # Notifications webhook (si non désactivées par --no-notify)
    if not args.no_notify:
        _send_notifications(all_alerts, rules)


if __name__ == "__main__":
    main()
