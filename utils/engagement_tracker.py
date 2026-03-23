"""
utils/engagement_tracker.py — Traçage des signaux d'engagement implicites

Enregistre les actions utilisateur dans le viewer comme signaux d'intérêt
sans demander de notation explicite. Ces signaux alimentent :
  - utils/scoring_optimizer.py   (ajustement des poids de scoring)
  - utils/source_performance.py  (score empirique des sources)
  - utils/quota_optimizer.py     (réallocation du budget quotidien)

Signaux et poids :
  article_opened      +1.0   article ouvert/lu
  article_full_report +2.0   rapport complet généré
  entity_synthesis    +1.5   synthèse d'entité demandée
  article_exported    +2.5   exporté JSON ou Markdown
  article_merged      +1.0   fusion acceptée
  article_deleted     -2.0   supprimé (signal négatif)
  alert_dismissed     -1.0   alerte ignorée

État persistant : data/engagement_state.json
Singleton via get_engagement_tracker()
"""

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _PROJECT_ROOT / "data" / "engagement_state.json"

# Poids associés à chaque type de signal
SIGNAL_WEIGHTS: dict[str, float] = {
    "article_opened":      1.0,
    "article_full_report": 2.0,
    "entity_synthesis":    1.5,
    "article_exported":    2.5,
    "article_merged":      1.0,
    "article_deleted":    -2.0,
    "alert_dismissed":    -1.0,
}

# Fenêtre de rétention des signaux (en jours)
_RETENTION_DAYS = 90


class EngagementTracker:
    """Collecte et agrège les signaux d'engagement utilisateur.

    Structure de l'état :
    {
      "version": 1,
      "updated_at": "2026-03-23T10:00:00Z",
      "articles": {
        "<url_md5>": {
          "url": "https://...",
          "source": "Le Monde",
          "keyword": "intelligence-artificielle",
          "score": 3.5,
          "signals": {"article_opened": 1, "article_full_report": 1},
          "last_seen": "2026-03-23"
        }
      },
      "sources": {"Le Monde": 12.5, "BFM TV": -1.0},
      "keywords": {"intelligence-artificielle": 8.0, "geopolitique": 2.5},
      "entities": {"Emmanuel Macron": 4.5, "OpenAI": 3.0},
      "alerts": {"dismissed": ["GPE:France", "PERSON:Jean Dupont"]},
      "daily_activity": {"2026-03-23": {"signals": 12, "articles": 5}}
    }
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = self._load()

    # ── Persistance ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if _STATE_PATH.exists():
            try:
                return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "version": 1,
            "updated_at": "",
            "articles": {},
            "sources": {},
            "keywords": {},
            "entities": {},
            "alerts": {"dismissed": []},
            "daily_activity": {},
        }

    def _persist(self) -> None:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_STATE_PATH)

    # ── API publique ──────────────────────────────────────────────────────────

    def record(
        self,
        signal_type: str,
        url: Optional[str] = None,
        source: Optional[str] = None,
        keyword: Optional[str] = None,
        entities: Optional[list[str]] = None,
        alert_entity: Optional[str] = None,
    ) -> None:
        """Enregistre un signal d'engagement.

        Args:
            signal_type   : type de signal (cf. SIGNAL_WEIGHTS)
            url           : URL de l'article concerné (optionnel)
            source        : nom de la source (optionnel)
            keyword       : mot-clé associé à l'article (optionnel)
            entities      : liste d'entités présentes dans l'article (optionnel)
            alert_entity  : entité de l'alerte ignorée (pour alert_dismissed)
        """
        if signal_type not in SIGNAL_WEIGHTS:
            return
        weight = SIGNAL_WEIGHTS[signal_type]
        today = str(date.today())

        with self._lock:
            # Activité journalière
            day = self._state.setdefault("daily_activity", {}).setdefault(
                today, {"signals": 0, "articles": 0}
            )
            day["signals"] += 1
            if url:
                day["articles"] += 1

            # Score article
            if url:
                url_key = _md5_key(url)
                art = self._state["articles"].setdefault(url_key, {
                    "url": url, "source": source or "", "keyword": keyword or "",
                    "score": 0.0, "signals": {}, "last_seen": today,
                })
                art["score"] = round(art["score"] + weight, 2)
                art["signals"][signal_type] = art["signals"].get(signal_type, 0) + 1
                art["last_seen"] = today
                if source:
                    art["source"] = source
                if keyword:
                    art["keyword"] = keyword

            # Score source
            if source:
                sources = self._state.setdefault("sources", {})
                sources[source] = round(sources.get(source, 0.0) + weight, 2)

            # Score keyword
            if keyword:
                kws = self._state.setdefault("keywords", {})
                kws[keyword] = round(kws.get(keyword, 0.0) + weight, 2)

            # Score entités
            if entities:
                ents = self._state.setdefault("entities", {})
                for ent in entities:
                    ents[ent] = round(ents.get(ent, 0.0) + weight, 2)

            # Alertes ignorées
            if signal_type == "alert_dismissed" and alert_entity:
                dismissed = self._state.setdefault("alerts", {}).setdefault("dismissed", [])
                if alert_entity not in dismissed:
                    dismissed.append(alert_entity)

            self._persist()

    def get_article_score(self, url: str) -> float:
        """Retourne le score d'engagement cumulé pour une URL."""
        with self._lock:
            return self._state["articles"].get(_md5_key(url), {}).get("score", 0.0)

    def get_source_scores(self) -> dict[str, float]:
        """Retourne les scores d'engagement agrégés par source."""
        with self._lock:
            return dict(self._state.get("sources", {}))

    def get_keyword_scores(self) -> dict[str, float]:
        """Retourne les scores d'engagement agrégés par mot-clé."""
        with self._lock:
            return dict(self._state.get("keywords", {}))

    def get_entity_scores(self) -> dict[str, float]:
        """Retourne les scores d'engagement agrégés par entité."""
        with self._lock:
            return dict(self._state.get("entities", {}))

    def get_dismissed_alerts(self) -> list[str]:
        """Retourne la liste des entités dont les alertes ont été ignorées."""
        with self._lock:
            return list(self._state.get("alerts", {}).get("dismissed", []))

    def get_stats(self) -> dict:
        """Retourne un résumé des statistiques d'engagement."""
        with self._lock:
            articles = self._state.get("articles", {})
            sources = self._state.get("sources", {})
            keywords = self._state.get("keywords", {})
            entities = self._state.get("entities", {})
            daily = self._state.get("daily_activity", {})

            top_articles = sorted(
                [{"url": v["url"], "source": v["source"], "score": v["score"]}
                 for v in articles.values()],
                key=lambda x: -x["score"]
            )[:10]

            top_sources = sorted(
                [{"source": k, "score": v} for k, v in sources.items()],
                key=lambda x: -x["score"]
            )[:10]

            top_keywords = sorted(
                [{"keyword": k, "score": v} for k, v in keywords.items()],
                key=lambda x: -x["score"]
            )[:10]

            recent_days = sorted(daily.keys())[-7:]

            return {
                "total_articles_tracked": len(articles),
                "total_sources": len(sources),
                "total_keywords": len(keywords),
                "total_entities": len(entities),
                "top_articles": top_articles,
                "top_sources": top_sources,
                "top_keywords": top_keywords,
                "dismissed_alerts": len(self._state.get("alerts", {}).get("dismissed", [])),
                "daily_activity": {d: daily[d] for d in recent_days},
                "updated_at": self._state.get("updated_at", ""),
            }

    def purge_old_entries(self) -> int:
        """Supprime les entrées articles antérieures à _RETENTION_DAYS jours."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)).date()
        removed = 0
        with self._lock:
            articles = self._state.get("articles", {})
            to_delete = [
                k for k, v in articles.items()
                if v.get("last_seen", "9999-12-31") < str(cutoff)
            ]
            for k in to_delete:
                del articles[k]
                removed += 1
            if removed:
                self._persist()
        return removed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _md5_key(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracker_instance: Optional[EngagementTracker] = None
_tracker_lock = threading.Lock()


def get_engagement_tracker() -> EngagementTracker:
    """Retourne l'instance singleton de l'EngagementTracker."""
    global _tracker_instance
    if _tracker_instance is None:
        with _tracker_lock:
            if _tracker_instance is None:
                _tracker_instance = EngagementTracker()
    return _tracker_instance
