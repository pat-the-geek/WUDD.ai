"""utils/article_id.py — Identifiant d'article WUDD.ai stable et unique.

Contexte
--------
WUDD.ai ne stocke historiquement AUCUN champ `id` / `article_id` dans le JSON
article (champs réels : « Date de publication », « Sources », « URL »,
« Résumé », « Images », « entities », …). L'identité de facto d'un article
dans tout le pipeline est son **URL** : c'est la clé de déduplication
(`utils.deduplication.compute_url_fingerprint`), la clé de `ArticleIndex.get_by_url`
et la clé de jointure de tous les rapports.

Décision d'architecture (ne pas changer sans relecture)
-------------------------------------------------------
Le `wudd_article_id` est **dérivé de façon déterministe**, jamais stocké :

    wudd-{YYYY-MM-DD}-{md5(url_normalisée)[:12]}

* `{YYYY-MM-DD}` : date de PUBLICATION de l'article (champ
  « Date de publication »), normalisée. C'est une donnée source immuable
  (date d'édition par le média), pas la date d'indexation WUDD.ai.
* `{md5(url_normalisée)[:12]}` : empreinte de l'URL normalisée, réutilise
  exactement `compute_url_fingerprint()` du moteur de déduplication afin que
  l'ID soit aligné sur la clé d'identité déjà utilisée partout dans le code.

Conséquences :

* **Stabilité garantie** : à URL + date de publication constantes, l'ID est
  identique à chaque calcul, donc invariant en cas de ré-indexation, de mise à
  jour des entités ou de régénération du résumé (qui ne touchent ni l'URL ni la
  date de publication).
* **Aucune migration de données** : rien n'est écrit sur disque ; l'ID est
  calculé à la volée à chaque réponse JSON. Les fichiers `data/` existants
  restent inchangés.
* **Unicité** : l'URL normalisée est déjà la clé de dédup ; deux articles
  distincts ont des URL distinctes → empreintes distinctes. Le préfixe date
  ajoute lisibilité et tri chronologique sans rôle dans l'unicité.

Repli (articles dégradés)
-------------------------
* Date de publication absente / non parsable → segment date `0000-00-00`.
* URL absente → empreinte calculée sur « Sources » + « Résumé » (toujours
  déterministe), préfixée `nourl-` pour signaler le cas dégradé.
"""

from __future__ import annotations

import hashlib

from .date_utils import parse_article_date
from .deduplication import compute_url_fingerprint

_NO_DATE = "0000-00-00"


def _date_segment(article: dict) -> str:
    """Retourne le segment date `YYYY-MM-DD` issu de la date de publication."""
    raw = (
        article.get("Date de publication")
        or article.get("date_publication")
        or article.get("date")
        or ""
    )
    dt = parse_article_date(str(raw), date_only_policy="start")
    if dt is None:
        return _NO_DATE
    return dt.strftime("%Y-%m-%d")


def compute_wudd_article_id(article: dict) -> str:
    """Calcule le `wudd_article_id` déterministe et stable d'un article.

    Format : ``wudd-{YYYY-MM-DD}-{md5(url_normalisée)[:12]}``.

    L'identifiant est purement dérivé (jamais persisté) : il est donc stable
    par construction face à une ré-indexation ou une régénération du résumé,
    et ne nécessite aucune migration de données.

    Args:
        article : dict article au format interne WUDD.ai.

    Returns:
        Chaîne identifiant, ex. ``wudd-2026-05-16-3f9a1c0b7d2e``.
    """
    date_seg = _date_segment(article)
    url = str(article.get("URL") or article.get("url") or "").strip()

    if url:
        fingerprint = compute_url_fingerprint(url)[:12]
        return f"wudd-{date_seg}-{fingerprint}"

    # Repli déterministe si l'URL manque (rare, articles dégradés).
    fallback_basis = (
        str(article.get("Sources") or article.get("source") or "")
        + "|"
        + str(article.get("Résumé") or article.get("resume") or "")
    )
    fingerprint = hashlib.md5(fallback_basis.encode("utf-8")).hexdigest()[:12]
    return f"wudd-{date_seg}-nourl-{fingerprint}"
