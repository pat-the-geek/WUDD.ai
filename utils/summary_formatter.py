"""utils/summary_formatter.py — Reformatage Markdown léger des résumés d'articles.

Transforme un résumé d'article en texte brut en Markdown léger (chapitres `###`,
**gras** et *italique* parcimonieux) pour un affichage enrichi dans le viewer et
les notifications de veille — SANS inventer de faits.

Réutilisé par :
  - scripts/enrich_summary_format.py  (champ `Résumé_md` des articles)
  - scripts/watch_entity_articles.py  (notifications Discord)

Le reformatage passe par `get_summary_client()` : Ollama local privilégié
(AI_PROVIDER_SUMMARY=ollama) pour économiser des tokens cloud, fallback
EurIA/Claude automatique. En cas d'échec, retourne une chaîne vide : l'appelant
conserve alors le résumé brut.
"""

import re

from utils.logging import default_logger

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

__all__ = ["format_summary_markdown", "degrade_overbold"]


def degrade_overbold(text: str) -> str:
    """Garde-fou contre le sur-gras des petits modèles (ex. qwen2.5:7b).

    Pour chaque ligne hors titre : si une part trop importante du texte est en
    **gras** (≥ 60 % des caractères) ou si la ligne entière est gras, on retire
    les marqueurs ** de cette ligne. Préserve les titres `### …` intacts.
    """
    out_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        bold_chars = sum(len(m.group(1)) for m in _BOLD_RE.finditer(line))
        plain_len = len(_BOLD_RE.sub(r"\1", line).strip())
        whole_line_bold = bool(re.fullmatch(r"\*\*.+\*\*", stripped, re.DOTALL))
        if whole_line_bold or (plain_len and bold_chars / plain_len >= 0.6):
            line = _BOLD_RE.sub(r"\1", line)
        out_lines.append(line)
    return "\n".join(out_lines)


def _build_prompt(resume: str, entity_label: str | None, max_chars: int) -> str:
    """Construit le prompt de reformatage Markdown.

    Si `entity_label` est fourni, la première mention de cette entité est mise en
    gras (cas notification de veille) ; sinon on met en gras seulement quelques
    chiffres/noms réellement clés (cas résumé d'article générique).
    """
    if entity_label:
        bold_rule = (
            "Le texte des paragraphes reste en clair (non gras). Utilise le **gras** "
            f"avec PARCIMONIE : mets en gras UNIQUEMENT la première mention de l'entité "
            f"« {entity_label} » et au plus 2 ou 3 chiffres réellement clés."
        )
    else:
        bold_rule = (
            "Le texte des paragraphes reste en clair (non gras). Utilise le **gras** "
            "avec PARCIMONIE : au plus 2 ou 3 chiffres, dates ou noms réellement clés. "
        )
    return (
        "Reformate le résumé d'article ci-dessous en Markdown, EN FRANÇAIS, pour un "
        "affichage de lecture agréable. Règles STRICTES :\n"
        "- N'invente AUCUN fait : utilise uniquement les informations du résumé, "
        "sans rien ajouter ni retirer du fond.\n"
        "- Structure en chapitres avec des titres de niveau 3 (### Titre).\n"
        "- Commence par « ### En bref » suivi d'une phrase d'accroche (texte normal, NON gras).\n"
        "- Ajoute 1 à 3 chapitres supplémentaires SEULEMENT si le contenu le justifie "
        "(ex. ### Contexte, ### Enjeux, ### Détails). Si le résumé est court, garde "
        "uniquement « En bref ».\n"
        f"- {bold_rule} N'écris JAMAIS une phrase ou une ligne entière en gras. "
        "*Italique* possible pour une nuance ponctuelle. N'utilise PAS de soulignement.\n"
        "- Réponds UNIQUEMENT avec le Markdown, sans préambule ni commentaire. "
        f"Maximum ~{max_chars} caractères.\n\n"
        f"Résumé :\n{resume}"
    )


def format_summary_markdown(
    resume: str,
    entity_label: str | None = None,
    max_chars: int = 1500,
    timeout: int = 45,
) -> str:
    """Reformate un résumé en Markdown léger (chapitres + gras/italique parcimonieux).

    Args:
        resume       : résumé d'article en texte brut.
        entity_label : si fourni, met en gras la 1re mention de cette entité.
        max_chars    : taille cible indicative du Markdown produit.
        timeout      : timeout de l'appel IA (s).

    Returns:
        Markdown formaté, ou chaîne vide en cas d'échec (l'appelant conserve le brut).
    """
    resume = (resume or "").strip()
    if not resume:
        return ""
    prompt = _build_prompt(resume, entity_label, max_chars)
    try:
        from utils.api_client import get_summary_client
        out = get_summary_client().ask(prompt, timeout=timeout, max_tokens=700)
    except Exception as exc:
        default_logger.warning(f"Reformatage Markdown indisponible ({exc}) — résumé brut conservé.")
        return ""
    if not out or out.strip().lower().startswith("erreur"):
        default_logger.warning("Reformatage Markdown en échec — résumé brut conservé.")
        return ""
    return degrade_overbold(out.strip())
