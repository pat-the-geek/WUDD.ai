"""
utils/quota.py — Gestionnaire de quotas adaptatif WUDD.ai

Régule le nombre d'articles importés par jour en garantissant :
  - Un plafond global journalier (limiter les appels API EurIA)
  - Un plafond par mot-clé (éviter 200 articles "Trump" en un jour)
  - Un plafond par source pour un mot-clé donné (diversité des sites)
  - Un tri adaptatif : les mots-clés les moins consommés sont traités
    en priorité (redistribution du budget inutilisé)

Config : config/quota.json
État   : data/quota_state.json  (auto-réinitialisé chaque jour)
"""

import json
import threading
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from .date_utils import parse_article_date
from .file_io import json_read, json_write

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUOTA_CONFIG_PATH = PROJECT_ROOT / "config" / "quota.json"
QUOTA_STATE_PATH  = PROJECT_ROOT / "data"   / "quota_state.json"
WUDD_48H_PATH     = PROJECT_ROOT / "data"   / "articles-from-rss" / "_WUDD.AI_" / "48-heures.json"

# ── Valeurs par défaut ────────────────────────────────────────────────────────
DEFAULT_CONFIG: dict = {
    "enabled": True,
    "global_daily_limit": 150,
    "per_keyword_daily_limit": 30,
    "per_source_daily_limit": 5,
    "per_entity_daily_limit": 10,
    "per_run_limit": 30,
    "global_source_daily_limit": 15,
    "adaptive_sorting": True,
    "summary_max_lines": 20,
    "ignored_entity_types": ["DATE", "TIME", "CARDINAL", "ORDINAL", "PERCENT", "MONEY", "QUANTITY"],
}

# Types d'entités considérées comme structurelles (ignorées du quota entité par défaut)
_DEFAULT_IGNORED_TYPES: frozenset = frozenset(DEFAULT_CONFIG["ignored_entity_types"])


def _domain(source_name: str) -> str:
    """Extrait le domaine d'un nom de source (URL ou titre court)."""
    if source_name.startswith("http"):
        return urlparse(source_name).netloc.lower().removeprefix("www.")
    return source_name.lower().strip()


class QuotaManager:
    """Thread-safe gestionnaire de quotas journaliers adaptatifs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config: dict = {}
        self._state: dict = {}
        self._config_mtime_ns = 0
        self._state_mtime_ns = 0
        self._last_disk_sync_ts = 0.0
        self._disk_sync_interval_seconds = 2.0
        self._reload()
        # Reset au démarrage si la date de l'état ne correspond pas à aujourd'hui
        # (évite de conserver des compteurs d'un jour précédent si le process
        #  a tourné sans interruption à minuit sans que _maybe_reset_day soit appelé)
        self._startup_reset_if_stale()

    # ─── Chargement ──────────────────────────────────────────────────────────

    def _reload(self) -> None:
        """Charge la config et l'état quota depuis disque (fallback 48h si nécessaire)."""
        self._config = self._load_config_from_disk()
        today = str(date.today())
        self._state = self._load_state_from_disk(today)

        # Si aucun état valide n'existe, reconstruire depuis 48h puis persister.
        if not self._state:
            self._state = self._build_state_from_48h(today)
            self._persist()

        self._config_mtime_ns = self._safe_mtime_ns(QUOTA_CONFIG_PATH)
        self._state_mtime_ns = self._safe_mtime_ns(QUOTA_STATE_PATH)
        self._last_disk_sync_ts = time.monotonic()

    def _persist(self) -> None:
        """Écriture atomique de l'état dans data/quota_state.json."""
        json_write(QUOTA_STATE_PATH, self._state)
        self._state_mtime_ns = self._safe_mtime_ns(QUOTA_STATE_PATH)

    # ─── API publique ─────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", True))

    @property
    def adaptive_sorting(self) -> bool:
        return bool(self._config.get("adaptive_sorting", True))

    @property
    def per_run_limit(self) -> int:
        """Plafond d'articles par passage d'exécution (0 = désactivé)."""
        return int(self._config.get("per_run_limit", DEFAULT_CONFIG["per_run_limit"]))

    @property
    def _ignored_entity_types(self) -> frozenset:
        """Types d'entités NER exclus du quota entité."""
        types = self._config.get("ignored_entity_types", DEFAULT_CONFIG["ignored_entity_types"])
        return frozenset(t.upper() for t in types)

    def is_global_exhausted(self) -> bool:
        """True si le plafond global journalier est atteint."""
        if not self.enabled:
            return False
        limit = int(self._config.get("global_daily_limit", DEFAULT_CONFIG["global_daily_limit"]))
        return self._state["global_count"] >= limit

    def can_process(self, keyword: str, source: str, keyword_limit: int | None = None) -> bool:
        """
        Vérifie si un article peut être traité selon les quatre plafonds.
          keyword       : mot-clé correspondant
          source        : nom ou URL de la source (ex. "Le Monde", "https://lemonde.fr/...")
          keyword_limit : quota individuel pour ce mot-clé (quota_override) — écrase la config
        """
        if not self.enabled:
            return True
        with self._lock:
            self._maybe_reset_day()
            # Plafond global
            if self.is_global_exhausted():
                return False
            # Plafond par mot-clé (quota individuel si fourni, sinon config globale)
            kw_limit = keyword_limit if keyword_limit is not None else int(
                self._config.get("per_keyword_daily_limit", DEFAULT_CONFIG["per_keyword_daily_limit"])
            )
            kw_data = self._state["keywords"].get(keyword, {"total": 0, "sources": {}})
            if kw_data["total"] >= kw_limit:
                return False
            # Plafond par source (pour ce mot-clé)
            src_key = _domain(source)
            src_limit = int(self._config.get("per_source_daily_limit", DEFAULT_CONFIG["per_source_daily_limit"]))
            if kw_data["sources"].get(src_key, 0) >= src_limit:
                return False
            # Plafond global par source (cross-keyword)
            global_src_limit = int(
                self._config.get("global_source_daily_limit", DEFAULT_CONFIG["global_source_daily_limit"])
            )
            if global_src_limit > 0:
                global_sources = self._state.get("global_sources", {})
                if global_sources.get(src_key, 0) >= global_src_limit:
                    return False
            return True

    def can_process_entities(self, entities: dict) -> tuple[bool, str]:
        """
        Vérifie si un article peut être importé selon le plafond par entité.
        Les types dans ignored_entity_types (DATE, CARDINAL…) sont ignorés.
        Retourne (True, '') si autorisé, ou (False, nom_entite) si une entité
        a atteint son quota journalier.
        Si quota désactivé, aucune entité détectée ou limite <= 0, retourne toujours (True, '').
        """
        if not self.enabled:
            return True, ""
        limit = int(self._config.get("per_entity_daily_limit", DEFAULT_CONFIG["per_entity_daily_limit"]))
        if limit <= 0:
            return True, ""
        ignored = self._ignored_entity_types
        with self._lock:
            self._maybe_reset_day()
            entity_counts = self._state.get("entities", {})
            for etype, etype_list in entities.items():
                if etype.upper() in ignored:
                    continue
                if isinstance(etype_list, list):
                    for name in etype_list:
                        if entity_counts.get(name, 0) >= limit:
                            return False, name
        return True, ""

    def record_article(self, keyword: str, source: str, entities: dict | None = None) -> None:
        """Incrémente les compteurs après ajout réel d'un article."""
        with self._lock:
            self._maybe_reset_day()
            src_key = _domain(source)
            self._apply_article_to_state(keyword, src_key, entities)
            self._persist()

    def sort_by_priority(
        self,
        keywords: list[str],
        keyword_limits: dict[str, int] | None = None,
    ) -> list[str]:
        """
        Trie les mots-clés du moins consommé au plus consommé (tri adaptatif).
        keyword_limits : dict {keyword → quota_override} pour tenir compte
            des quotas individuels lors du calcul du ratio.
        Si adaptive_sorting est désactivé, retourne l'ordre d'origine.
        """
        if not self.enabled or not self.adaptive_sorting:
            return keywords
        default_kw_limit = int(self._config.get("per_keyword_daily_limit", DEFAULT_CONFIG["per_keyword_daily_limit"]))

        def _ratio(kw: str) -> float:
            limit = (keyword_limits or {}).get(kw) or default_kw_limit
            total = self._state["keywords"].get(kw, {}).get("total", 0)
            return total / limit if limit > 0 else 0.0

        return sorted(keywords, key=_ratio)

    def get_stats(
        self,
        top_keywords: int | None = None,
        top_sources_per_keyword: int | None = None,
        top_entities: int | None = 20,
        top_global_sources: int | None = 20,
    ) -> dict:
        """
        Retourne les statistiques de consommation du jour.
        Relit toujours le fichier depuis le disque pour rester synchronisé
        avec les modifications externes (rebuild_quota, autre processus…).
        Utilisé par l'API Flask pour l'interface Quota.
        """
        with self._lock:
            self._sync_from_disk_if_needed()
        kw_limit    = int(self._config.get("per_keyword_daily_limit", DEFAULT_CONFIG["per_keyword_daily_limit"]))
        global_limit = int(self._config.get("global_daily_limit", DEFAULT_CONFIG["global_daily_limit"]))
        src_limit   = int(self._config.get("per_source_daily_limit", DEFAULT_CONFIG["per_source_daily_limit"]))

        keywords_stats = {}
        keyword_items = sorted(
            self._state.get("keywords", {}).items(),
            key=lambda item: -int(item[1].get("total", 0)),
        )
        if top_keywords is not None and top_keywords > 0:
            keyword_items = keyword_items[:top_keywords]

        for kw, data in keyword_items:
            sources_items = sorted(
                data.get("sources", {}).items(),
                key=lambda item: -int(item[1]),
            )
            if top_sources_per_keyword is not None and top_sources_per_keyword > 0:
                sources_items = sources_items[:top_sources_per_keyword]
            keywords_stats[kw] = {
                "total": data["total"],
                "limit": kw_limit,
                "pct": round(data["total"] / kw_limit * 100) if kw_limit > 0 else 0,
                "sources": {
                    src: {"count": cnt, "limit": src_limit, "saturated": cnt >= src_limit}
                    for src, cnt in sources_items
                },
            }

        entity_limit = int(self._config.get("per_entity_daily_limit", DEFAULT_CONFIG["per_entity_daily_limit"]))
        entity_counts = self._state.get("entities", {})
        entities_items = sorted(entity_counts.items(), key=lambda x: -x[1])
        if top_entities is not None and top_entities > 0:
            entities_items = entities_items[:top_entities]
        entities_stats = {
            name: {
                "count": cnt,
                "limit": entity_limit,
                "pct": round(cnt / entity_limit * 100) if entity_limit > 0 else 0,
                "saturated": cnt >= entity_limit,
            }
            for name, cnt in entities_items
        }

        global_src_limit = int(self._config.get("global_source_daily_limit", DEFAULT_CONFIG["global_source_daily_limit"]))
        global_sources = self._state.get("global_sources", {})
        global_sources_items = sorted(global_sources.items(), key=lambda x: -x[1])
        if top_global_sources is not None and top_global_sources > 0:
            global_sources_items = global_sources_items[:top_global_sources]
        global_sources_stats = {
            src: {
                "count": cnt,
                "limit": global_src_limit,
                "pct": round(cnt / global_src_limit * 100) if global_src_limit > 0 else 0,
                "saturated": cnt >= global_src_limit,
            }
            for src, cnt in global_sources_items
        }

        return {
            "date": self._state["date"],
            "global": {
                "count": self._state["global_count"],
                "limit": global_limit,
                "pct": round(self._state["global_count"] / global_limit * 100) if global_limit > 0 else 0,
                "exhausted": self.is_global_exhausted(),
            },
            "keywords": keywords_stats,
            "entities": entities_stats,
            "global_sources": global_sources_stats,
            "per_run_limit": self.per_run_limit,
        }

    def reset_day(self) -> None:
        """Réinitialise manuellement tous les compteurs du jour."""
        with self._lock:
            self._state = {
                "date": str(date.today()),
                "global_count": 0,
                "keywords": {},
                "entities": {},
                "global_sources": {},
            }
            self._persist()

    def save_config(self, new_config: dict) -> None:
        """Sauvegarde une nouvelle configuration (depuis l'UI)."""
        allowed_keys = {
            "enabled", "global_daily_limit", "per_keyword_daily_limit",
            "per_source_daily_limit", "per_entity_daily_limit",
            "per_run_limit", "global_source_daily_limit",
            "adaptive_sorting", "summary_max_lines",
            "ignored_entity_types",
        }
        config = {k: v for k, v in new_config.items() if k in allowed_keys}
        # Validation des entiers
        for int_key in ("global_daily_limit", "per_keyword_daily_limit", "per_source_daily_limit",
                        "per_entity_daily_limit", "per_run_limit", "global_source_daily_limit",
                        "summary_max_lines"):
            if int_key in config:
                config[int_key] = max(1, int(config[int_key]))
        json_write(QUOTA_CONFIG_PATH, config)
        with self._lock:
            self._config = config
            self._config_mtime_ns = self._safe_mtime_ns(QUOTA_CONFIG_PATH)

    # ─── Interne ─────────────────────────────────────────────────────────────

    def _startup_reset_if_stale(self) -> None:
        """Force un reset au démarrage si la date stockée ≠ aujourd'hui.

        Garantit que même si le process Flask/cron redémarre après minuit sans
        avoir déclenché _maybe_reset_day (ex: redémarrage Docker en journée),
        les compteurs du jour précédent ne sont pas réutilisés.
        """
        today = str(date.today())
        if self._state.get("date") != today:
            import sys as _sys
            print(
                f"[QuotaManager] Démarrage : date stockée ({self._state.get('date', '?')}) "
                f"≠ aujourd'hui ({today}) — reset des quotas.",
                file=_sys.stderr,
                flush=True,
            )
            with self._lock:
                self._state = {"date": today, "global_count": 0, "keywords": {}, "entities": {}, "global_sources": {}}
                self._persist()

    def _maybe_reset_day(self) -> None:
        """Réinitialise l'état si on est passé à un nouveau jour."""
        today = str(date.today())
        if self._state.get("date") != today:
            self._state = self._build_state_from_48h(today)
            self._persist()

    def _sync_from_disk_if_needed(self) -> None:
        """Resynchronise config/état depuis disque avec un coût borné.

        - Pas plus d'une vérification toutes les N secondes (TTL court)
        - Rechargement uniquement si mtime a changé
        - Pas de rebuild 48h sur le chemin chaud des stats
        """
        now = time.monotonic()
        if (now - self._last_disk_sync_ts) < self._disk_sync_interval_seconds:
            return

        self._last_disk_sync_ts = now
        today = str(date.today())

        config_mtime = self._safe_mtime_ns(QUOTA_CONFIG_PATH)
        if config_mtime != self._config_mtime_ns:
            self._config = self._load_config_from_disk()
            self._config_mtime_ns = config_mtime

        state_mtime = self._safe_mtime_ns(QUOTA_STATE_PATH)
        if state_mtime != self._state_mtime_ns:
            disk_state = self._load_state_from_disk(today)
            if disk_state:
                self._state = disk_state
                self._state_mtime_ns = state_mtime

    def _safe_mtime_ns(self, path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    def _load_config_from_disk(self) -> dict:
        if not QUOTA_CONFIG_PATH.exists():
            return dict(DEFAULT_CONFIG)
        try:
            data = json_read(QUOTA_CONFIG_PATH)
            if isinstance(data, dict):
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
        return dict(DEFAULT_CONFIG)

    def _load_state_from_disk(self, today: str) -> dict:
        if not QUOTA_STATE_PATH.exists():
            return {}
        try:
            data = json_read(QUOTA_STATE_PATH)
            if not isinstance(data, dict):
                return {}
            if data.get("date") != today:
                return {}
            if not isinstance(data.get("keywords", {}), dict):
                return {}
            if not isinstance(data.get("entities", {}), dict):
                return {}
            if not isinstance(data.get("global_sources", {}), dict):
                data["global_sources"] = {}
            data["global_count"] = int(data.get("global_count", 0))
            return data
        except Exception:
            return {}

    def _build_state_from_48h(self, today: str) -> dict:
        """Construit l'état quota depuis les articles du jour présents dans 48-heures.json."""
        state = {
            "date": today,
            "global_count": 0,
            "keywords": {},
            "entities": {},
            "global_sources": {},
        }
        if not WUDD_48H_PATH.exists():
            return state
        try:
            articles = json_read(WUDD_48H_PATH)
        except Exception:
            return state
        if not isinstance(articles, list):
            return state

        for article in articles:
            if not isinstance(article, dict):
                continue
            article_dt = parse_article_date(article.get("Date de publication", ""))
            if article_dt is None or article_dt.date().isoformat() != today:
                continue
            keyword = article.get("mot_cle") if isinstance(article.get("mot_cle"), str) else ""
            source = article.get("Sources") if isinstance(article.get("Sources"), str) else ""
            entities = article.get("entities") if isinstance(article.get("entities"), dict) else None
            self._apply_article_to_state(keyword or "_sans_mot_cle_", _domain(source), entities, state)
        return state

    def _apply_article_to_state(
        self,
        keyword: str,
        src_key: str,
        entities: dict | None = None,
        state: dict | None = None,
    ) -> None:
        """Applique un article à l'état quota cible."""
        target = state if state is not None else self._state
        kw_data = target["keywords"].setdefault(keyword, {"total": 0, "sources": {}})
        kw_data["total"] += 1
        kw_data["sources"][src_key] = kw_data["sources"].get(src_key, 0) + 1
        target["global_count"] += 1

        global_sources = target.setdefault("global_sources", {})
        global_sources[src_key] = global_sources.get(src_key, 0) + 1

        if not entities:
            return
        ignored = self._ignored_entity_types
        entity_counts = target.setdefault("entities", {})
        for etype, etype_list in entities.items():
            if etype.upper() in ignored:
                continue
            if isinstance(etype_list, list):
                for name in etype_list:
                    entity_counts[name] = entity_counts.get(name, 0) + 1


# ── Singleton ─────────────────────────────────────────────────────────────────
_quota_manager: QuotaManager | None = None


def get_quota_manager() -> QuotaManager:
    """Retourne l'instance singleton du QuotaManager."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager()
    return _quota_manager
