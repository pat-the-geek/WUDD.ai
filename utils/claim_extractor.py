"""Extraction de claims factuels depuis un résumé d'article.

Un claim est une affirmation factuelle atomique et vérifiable :
  "OpenAI a levé 6,6 milliards de dollars" → {type: CHIFFRE, sujet: OpenAI, valeur: 6.6B}

Le fournisseur IA (EurIA ou Claude) est sélectionné via AI_PROVIDER dans .env.
"""

import json
import re
from typing import Optional

from .api_client import get_ai_client
from .logging import default_logger

CLAIM_TYPES = ("CHIFFRE", "DATE", "FAIT_BINAIRE", "ATTRIBUTION", "AUTRE")

_PROMPT_CLAIMS = """Tu es un extracteur de faits journalistiques.
Extrait UNIQUEMENT les affirmations factuelles vérifiables du texte ci-dessous.
Retourne un tableau JSON strict, sans explication, sans markdown.

Format attendu :
[
  {{
    "claim": "affirmation courte et précise (max 120 caractères)",
    "type": "CHIFFRE|DATE|FAIT_BINAIRE|ATTRIBUTION|AUTRE",
    "sujet": "entité principale concernée",
    "valeur": "la valeur chiffrée, la date ou le fait",
    "confiance": 0.0
  }}
]

Règles :
- CHIFFRE : montants, effectifs, pourcentages, volumes
- DATE : dates précises ou délais datés
- FAIT_BINAIRE : décision binaire (adopté/rejeté, autorisé/interdit, confirmé/démenti)
- ATTRIBUTION : action ou responsabilité attribuée à une entité nommée
- confiance : 0.0–1.0 (certitude que c'est factuel et vérifiable)
- Ignorer les opinions, analyses et prévisions vagues
- Retourner [] si aucun claim factuel détecté

Texte à analyser :
{resume}"""


def extract_claims(resume: str, source: str = "") -> list[dict]:
    """Extrait les claims factuels d'un résumé via l'API IA configurée.

    Args:
        resume: Texte du résumé article
        source: Nom de la source (pour les logs)

    Returns:
        Liste de dicts {claim, type, sujet, valeur, confiance}
        ou [] en cas d'échec ou résumé trop court
    """
    if not resume or len(resume.strip()) < 50:
        return []

    client = get_ai_client()
    prompt = _PROMPT_CLAIMS.format(resume=resume.strip()[:3000])

    try:
        raw = client.ask(prompt, max_attempts=2, timeout=45, max_tokens=600)
        if not raw:
            return []

        # Extraire le tableau JSON de la réponse
        json_match = re.search(r'\[[\s\S]*\]', raw)
        if not json_match:
            return []

        claims = json.loads(json_match.group(0))
        if not isinstance(claims, list):
            return []

        valid = []
        for c in claims:
            if not isinstance(c, dict):
                continue
            if not c.get("claim") or not c.get("type"):
                continue
            if c["type"] not in CLAIM_TYPES:
                c["type"] = "AUTRE"
            c.setdefault("sujet", "")
            c.setdefault("valeur", "")
            c.setdefault("confiance", 0.5)
            valid.append(c)

        return valid

    except (json.JSONDecodeError, Exception) as e:
        default_logger.warning(f"[claim_extractor] Erreur extraction ({source}): {e}")
        return []
