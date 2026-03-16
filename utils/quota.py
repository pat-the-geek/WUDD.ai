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
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUOTA_CONFIG_PATH = PROJECT_ROOT / "config" / "quota.json"
QUOTA_STATE_PATH  = PROJECT_ROOT / "data"   / "quota_state.json"

# ── Valeurs par défaut ────────────────────────────────────────────────────────
DEFAULT_CONFIG: dict = {
    "enabled": True,
    "global_daily_limit": 150,
    "per_keyword_daily_limit": 30,
    "per_source_daily_limit": 5,
    "per_entity_daily_limit": 10,
    "adaptive_sorting": True,
    "summary_max_lines": 20,
}


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
        self._reload()
        # Reset au démarrage si la date de l'état ne correspond pas à aujourd'hui
        # (évite de conserver des compteurs d'un jour précédent si le process
        #  a tourné sans interruption à minuit sans que _maybe_reset_day soit appelé)
        self._startup_reset_if_stale()

    # ─── Chargement ──────────────────────────────────────────────────────────

    def _reload(self) -> None:
        """Charge la config et l'état courant, réinitialise l'état si nouveau jour."""
        # Config
        if QUOTA_CONFIG_PATH.exists():
            try:
                self._config = json.loads(QUOTA_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                self._config = dict(DEFAULT_CONFIG)
        else:
            self._config = dict(DEFAULT_CONFIG)

        # État
        today = str(date.today())
        loaded: dict = {}
        if QUOTA_STATE_PATH.exists():
            try:
                loaded = json.loads(QUOTA_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        if loaded.get("date") == today:
            self._state = loaded
        else:
            # Nouveau jour → remise à zéro
            self._state = {
                "date": today,
                "global_count": 0,
                "keywords": {},
                "entities": {},
            }
            self._persist()

    def _persist(self) -> None:
        """Écriture atomique de l'état dans data/quota_state.json."""
        QUOTA_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = QUOTA_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(QUOTA_STATE_PATH)

    # ─── API publique ─────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", True))

    @property
    def adaptive_sorting(self) -> bool:
        return bool(self._config.get("adaptive_sorting", True))

    def is_global_exhausted(self) -> bool:
        """True si le plafond global journalier est atteint."""
        if not self.enabled:
            return False
        limit = int(self._config.get("global_daily_limit", DEFAULT_CONFIG["global_daily_limit"]))
        return self._state["global_count"] >= limit

    def can_process(self, keyword: str, source: str) -> bool:
        """
        Vérifie si un article peut être traité selon les trois plafonds.
          keyword : mot-clé correspondant
          source  : nom ou URL de la source (ex. "Le Monde", "https://lemonde.fr/...")
        """
        if not self.enabled:
            return True
        with self._lock:
            self._maybe_reset_day()
            # Plafond global
            if self.is_global_exhausted():
                return False
            # Plafond par mot-clé
            kw_limit = int(self._config.get("per_keyword_daily_limit", DEFAULT_CONFIG["per_keyword_daily_limit"]))
            kw_data = self._state["keywords"].get(keyword, {"total": 0, "sources": {}})
            if kw_data["total"] >= kw_limit:
                return False
            # Plafond par source (pour ce mot-clé)
            src_key = _domain(source)
            src_limit = int(self._config.get("per_source_daily_limit", DEFAULT_CONFIG["per_source_daily_limit"]))
            if kw_data["sources"].get(src_key, 0) >= src_limit:
                return False
            return True

    def can_process_entities(self, entities: dict) -> tuple[bool, str]:
        """
        Vérifie si un article peut être importé selon le plafond par entité.
        Retourne (True, '') si autorisé, ou (False, nom_entite) si une entité
        a atteint son quota journalier.
        Si quota désactivé, aucune entité détectée ou limite <= 0, retourne toujours (True, '').
        """
        if not self.enabled:
            return True, ""
        limit = int(self._config.get("per_entity_daily_limit", DEFAULT_CONFIG["per_entity_daily_limit"]))
        if limit <= 0:
            return True, ""
        with self._lock:
            self._maybe_reset_day()
            entity_counts = self._state.get("entities", {})
            for etype_list in entities.values():
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
            kw_data = self._state["keywords"].setdefault(
                keyword, {"total": 0, "sources": {}}
            )
            kw_data["total"] += 1
            kw_data["sources"][src_key] = kw_data["sources"].get(src_key, 0) + 1
            self._state["global_count"] += 1
            if entities:
                entity_counts = self._state.setdefault("entities", {})
                for etype_list in entities.values():
                    if isinstance(etype_list, list):
                        for name in etype_list:
                            entity_counts[name] = entity_counts.get(name, 0) + 1
            self._persist()

    def sort_by_priority(self, keywords: list[str]) -> list[str]:
        """
        Trie les mots-clés du moins consommé au plus consommé (tri adaptatif).
        Si adaptive_sorting est désactivé, retourne l'ordre d'origine.
        """
        if not self.enabled or not self.adaptive_sorting:
            return keywords
        kw_limit = int(self._config.get("per_keyword_daily_limit", DEFAULT_CONFIG["per_keyword_daily_limit"]))

        def _ratio(kw: str) -> float:
            total = self._state["keywords"].get(kw, {}).get("total", 0)
            return total / kw_limit if kw_limit > 0 else 0.0

        return sorted(keywords, key=_ratio)

    def get_stats(self) -> dict:
        """
        Retourne les statistiques de consommation du jour.
        Relit toujours le fichier depuis le disque pour rester synchronisé
        avec les modifications externes (rebuild_quota, autre processus…).
        Utilisé par l'API Flask pour l'interface Quota.
        """
        with self._lock:
            self._reload()  # resync depuis disque à chaque appel stats
        kw_limit    = int(self._config.get("per_keyword_daily_limit", DEFAULT_CONFIG["per_keyword_daily_limit"]))
        global_limit = int(self._config.get("global_daily_limit", DEFAULT_CONFIG["global_daily_limit"]))
        src_limit   = int(self._config.get("per_source_daily_limit", DEFAULT_CONFIG["per_source_daily_limit"]))

        keywords_stats = {}
        for kw, data in self._state.get("keywords", {}).items():
            keywords_stats[kw] = {
                "total": data["total"],
                "limit": kw_limit,
                "pct": round(data["total"] / kw_limit * 100) if kw_limit > 0 else 0,
                "sources": {
                    src: {"count": cnt, "limit": src_limit, "saturated": cnt >= src_limit}
                    for src, cnt in data.get("sources", {}).items()
                },
            }

        entity_limit = int(self._config.get("per_entity_daily_limit", DEFAULT_CONFIG["per_entity_daily_limit"]))
        entity_counts = self._state.get("entities", {})
        top_entities = sorted(entity_counts.items(), key=lambda x: -x[1])[:20]
        entities_stats = {
            name: {
                "count": cnt,
                "limit": entity_limit,
                "pct": round(cnt / entity_limit * 100) if entity_limit > 0 else 0,
                "saturated": cnt >= entity_limit,
            }
            for name, cnt in top_entities
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
        }

    def reset_day(self) -> None:
        """Réinitialise manuellement tous les compteurs du jour."""
        with self._lock:
            self._state = {
                "date": str(date.today()),
                "global_count": 0,
                "keywords": {},
                "entities": {},
            }
            self._persist()

    def save_config(self, new_config: dict) -> None:
        """Sauvegarde une nouvelle configuration (depuis l'UI)."""
        allowed_keys = {
            "enabled", "global_daily_limit", "per_keyword_daily_limit",
            "per_source_daily_limit", "per_entity_daily_limit", "adaptive_sorting",
            "summary_max_lines",
        }
        config = {k: v for k, v in new_config.items() if k in allowed_keys}
        # Validation des entiers
        for int_key in ("global_daily_limit", "per_keyword_daily_limit", "per_source_daily_limit",
                        "per_entity_daily_limit", "summary_max_lines"):
            if int_key in config:
                config[int_key] = max(1, int(config[int_key]))
        QUOTA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUOTA_CONFIG_PATH.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with self._lock:
            self._config = config

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
                self._state = {"date": today, "global_count": 0, "keywords": {}, "entities": {}}
                self._persist()

    def _maybe_reset_day(self) -> None:
        """Réinitialise l'état si on est passé à un nouveau jour."""
        today = str(date.today())
        if self._state.get("date") != today:
            self._state = {"date": today, "global_count": 0, "keywords": {}, "entities": {}}
            self._persist()


# ── Singleton ─────────────────────────────────────────────────────────────────
_quota_manager: QuotaManager | None = None


def get_quota_manager() -> QuotaManager:
    """Retourne l'instance singleton du QuotaManager."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager()
    return _quota_manager
