"""utils/rolling_window.py — Fenêtre glissante d'articles (48-heures.json).

Utilitaire partagé entre get-keyword-from-rss.py, web_watcher.py et
flux_watcher.py pour maintenir un fichier JSON agrégé des articles
des dernières N heures.

Usage :
    from utils.rolling_window import update_rolling_window

    # Mode incrémental : ajouter des articles à une fenêtre existante
    update_rolling_window(new_articles, output_path, hours=48)

    # Mode reconstruction : reconstruire depuis tous les JSON d'un répertoire
    update_rolling_window([], output_path, hours=48, source_dir=OUTPUT_DIR)

    # Avec mise à jour immédiate de l'index entités (optimisation 2.2)
    update_rolling_window(new_articles, output_path, update_entity_index=True)
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .date_utils import parse_article_date, utc_now_naive
from .logging import default_logger
from .rss_file_naming import canonical_stem, is_numbered_copy

_lock = threading.Lock()


def update_rolling_window(
    new_articles: list[dict],
    output_path: Path,
    hours: int = 48,
    source_dir: Optional[Path] = None,
    update_entity_index: bool = False,
) -> int:
    """Met à jour la fenêtre glissante d'articles et écrit le résultat de façon atomique.

    Deux modes :

    - **Incrémental** (source_dir absent) : charge la fenêtre existante,
      y ajoute new_articles, élimine les entrées hors fenêtre et sauvegarde.
      Idéal pour web_watcher.py qui ajoute 1 à 5 articles par run.

    - **Reconstruction** (source_dir fourni) : relit tous les *.json du
      répertoire source (hors output_path), collecte les articles dans la
      fenêtre et reconstruit le fichier depuis zéro.
      Idéal pour get-keyword-from-rss.py qui traite de nombreux fichiers.

    Args:
        new_articles        : nouveaux articles à intégrer (vide si mode reconstruction)
        output_path         : chemin du fichier de sortie (ex. 48-heures.json)
        hours               : fenêtre temporelle en heures (défaut : 48)
        source_dir          : répertoire source pour le mode reconstruction
        update_entity_index : si True, met à jour entity_index.json immédiatement
                              après l'écriture (optimisation 2.2 — index événementiel).
                              Défaut : False pour compatibilité ascendante.

    Returns:
        Nombre d'articles dans la fenêtre après mise à jour.
    """
    cutoff = utc_now_naive() - timedelta(hours=hours)

    with _lock:
        # ── Mode reconstruction depuis source_dir ─────────────────────────
        if source_dir is not None and source_dir.exists():
            # Charger les champs utilisateur (rapports, etc.) depuis le fichier
            # de sortie existant afin de les préserver lors de la reconstruction.
            # Les fichiers sources (mots-clés) ne contiennent pas ces métadonnées
            # lorsqu'elles ont été saisies directement dans la vue agrégée.
            _preserved_fields: dict[str, dict] = {}
            if output_path.exists():
                try:
                    _existing_out = json.loads(output_path.read_text(encoding="utf-8"))
                    if isinstance(_existing_out, list):
                        for _art in _existing_out:
                            _url = _art.get("URL", "")
                            if not _url:
                                continue
                            _fields: dict = {}
                            if isinstance(_art.get("rapports"), list) and _art["rapports"]:
                                _fields["rapports"] = _art["rapports"]
                            if _fields:
                                _preserved_fields[_url] = _fields
                except Exception:
                    pass

            seen_urls: set[str] = set()
            collected: list[dict] = []

            # Sélection d'un seul fichier par stem canonique pour ignorer les
            # copies accidentelles du type "keyword 2.json".
            selected_files: dict[str, Path] = {}
            for json_file in sorted(source_dir.glob("*.json")):
                if json_file.resolve() == output_path.resolve():
                    continue
                if "cache" in json_file.parts:
                    continue
                stem_key = canonical_stem(json_file.stem)
                current = selected_files.get(stem_key)
                if current is None:
                    selected_files[stem_key] = json_file
                    continue
                # Préférer le nom canonique (non numéroté) quand présent.
                if is_numbered_copy(current) and not is_numbered_copy(json_file):
                    selected_files[stem_key] = json_file

            for json_file in selected_files.values():
                try:
                    articles = json.loads(json_file.read_text(encoding="utf-8"))
                    if not isinstance(articles, list):
                        continue
                except Exception:
                    continue
                for article in articles:
                    url = article.get("URL", "")
                    if not url or url in seen_urls:
                        continue
                    dt = parse_article_date(article.get("Date de publication", ""))
                    if dt is None or dt < cutoff:
                        continue
                    seen_urls.add(url)
                    # Réinjecter les champs utilisateur préservés (ex. rapports)
                    # si le fichier source ne les contient pas encore.
                    preserved = _preserved_fields.get(url)
                    if preserved:
                        extra = {field: value for field, value in preserved.items()
                                 if field not in article}
                        if extra:
                            article = {**article, **extra}
                    collected.append(article)

        # ── Mode incrémental ───────────────────────────────────────────────
        else:
            existing: list[dict] = []
            if output_path.exists():
                try:
                    existing = json.loads(output_path.read_text(encoding="utf-8"))
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
            existing_urls = {a.get("URL", "") for a in existing if a.get("URL")}
            to_add = [a for a in new_articles if a.get("URL", "") not in existing_urls]
            all_articles = existing + to_add
            seen_urls = set()
            collected = []
            for article in all_articles:
                url = article.get("URL", "")
                if url and url in seen_urls:
                    continue
                dt = parse_article_date(article.get("Date de publication", ""))
                if dt is None or dt < cutoff:
                    continue
                if url:
                    seen_urls.add(url)
                collected.append(article)

        # Tri par date décroissante
        def _sort_key(a: dict) -> datetime:
            dt = parse_article_date(a.get("Date de publication", ""))
            return dt if dt else datetime.min

        collected.sort(key=_sort_key, reverse=True)

        # Écriture atomique
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(collected, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            tmp.replace(output_path)
        except OSError as e:
            default_logger.error(f"rolling_window : erreur écriture {output_path} — {e}")
            try:
                tmp.unlink()
            except OSError:
                pass

        # ── Mise à jour immédiate de l'index entités (optimisation 2.2) ──────
        if update_entity_index and collected:
            try:
                from .entity_index import get_entity_index
                eidx = get_entity_index(output_path.parent.parent.parent)  # project_root
                added = eidx.update(collected, str(output_path))
                default_logger.debug(
                    f"rolling_window : index entités mis à jour (+{added} refs) pour {output_path.name}"
                )
            except Exception as e:
                # Non bloquant : l'index sera reconstruit à la prochaine passe quotidienne
                default_logger.warning(f"rolling_window : mise à jour entity_index échouée — {e}")

        return len(collected)
