"""Moteur de détection de contradictions entre claims d'articles.

Deux passes :
  1. Règles déterministes (chiffres, dates, faits binaires) — rapide, sans LLM
  2. Arbitrage LLM pour les cas ambigus (passe uniquement si passe 1 = None)

Le fournisseur IA (EurIA ou Claude) est sélectionné via AI_PROVIDER dans .env.
"""

import json
import re
from typing import Optional

from .api_client import get_ai_client
from .logging import default_logger

# ── Paires d'antonymes pour FAIT_BINAIRE ──────────────────────────────────────

_ANTONYMES: list[set] = [
    {"adopté", "rejeté"}, {"adoptée", "rejetée"},
    {"autorisé", "interdit"}, {"autorisée", "interdite"},
    {"approuvé", "refusé"}, {"approuvée", "refusée"},
    {"confirmé", "démenti"}, {"confirmée", "démentie"},
    {"annoncé", "annulé"}, {"annoncée", "annulée"},
    {"lancé", "abandonné"}, {"lancée", "abandonnée"},
    {"accepté", "refusé"}, {"acceptée", "refusée"},
    {"ouvert", "fermé"}, {"ouverte", "fermée"},
    {"validé", "invalidé"}, {"validée", "invalidée"},
    {"signé", "annulé"}, {"signée", "annulée"},
    {"croissance", "décroissance"}, {"hausse", "baisse"},
    {"augmentation", "diminution"}, {"progression", "régression"},
]


def _sont_antonymes(val_a: str, val_b: str) -> bool:
    a = val_a.lower().strip()
    b = val_b.lower().strip()
    for paire in _ANTONYMES:
        if a in paire and b in paire and a != b:
            return True
    return False


def _extract_number(text: str) -> Optional[float]:
    """Extrait le premier nombre d'une chaîne (gère milliards, millions, k)."""
    t = text.lower().replace(",", ".").replace("\u202f", "").replace(" ", "")
    m = re.search(r'([\d.]+)\s*(milliard|billion|md\b|b\b)', t)
    if m:
        return float(m.group(1)) * 1_000_000_000
    m = re.search(r'([\d.]+)\s*(million|m\b)', t)
    if m:
        return float(m.group(1)) * 1_000_000
    m = re.search(r'([\d.]+)\s*(millier|k\b)', t)
    if m:
        return float(m.group(1)) * 1_000
    m = re.search(r'[\d.]+', t)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _extract_year(text: str) -> Optional[int]:
    m = re.search(r'\b(20\d{2})\b', text)
    return int(m.group(1)) if m else None


# ── Passe 1 : règles déterministes ───────────────────────────────────────────

def compare_claims_deterministic(claim_a: dict, claim_b: dict) -> Optional[dict]:
    """Détecte une contradiction de manière déterministe, sans LLM.

    Returns:
        dict {type, description, score_confiance} ou None si pas de contradiction détectée
    """
    if claim_a.get("type") != claim_b.get("type"):
        return None

    ctype = claim_a["type"]
    val_a = str(claim_a.get("valeur", ""))
    val_b = str(claim_b.get("valeur", ""))

    if ctype == "CHIFFRE":
        num_a = _extract_number(val_a)
        num_b = _extract_number(val_b)
        if num_a and num_b and num_a > 0 and num_b > 0:
            diff = abs(num_a - num_b) / max(num_a, num_b)
            if diff > 0.15:
                return {
                    "type": "QUANTITATIVE",
                    "description": f"Montants divergents : {val_a} vs {val_b} (écart {diff:.0%})",
                    "score_confiance": round(min(0.60 + diff * 0.35, 0.95), 2),
                }

    elif ctype == "FAIT_BINAIRE":
        if _sont_antonymes(val_a, val_b):
            return {
                "type": "FACTUELLE_BINAIRE",
                "description": f"Affirmations opposées : « {val_a} » vs « {val_b} »",
                "score_confiance": 0.95,
            }

    elif ctype == "DATE":
        year_a = _extract_year(val_a)
        year_b = _extract_year(val_b)
        if year_a and year_b and year_a != year_b:
            return {
                "type": "TEMPORELLE",
                "description": f"Années incompatibles : {val_a} vs {val_b}",
                "score_confiance": 0.80,
            }

    return None


# ── Passe 2 : arbitrage LLM ───────────────────────────────────────────────────

_PROMPT_ARBITRAGE = """Tu es un expert en vérification de faits journalistiques.
Compare les deux passages ci-dessous et détermine s'il existe une contradiction factuelle réelle.
Réponds UNIQUEMENT en JSON valide, sans markdown.

Format :
{{
  "contradiction_detectee": true,
  "type": "FACTUELLE_BINAIRE|QUANTITATIVE|TEMPORELLE|ATTRIBUTION|NUANCE|AUCUNE",
  "description": "explication courte (max 100 caractères)",
  "source_probable": "A|B|INCONNUE",
  "justification": "raison du choix (max 100 caractères)",
  "score_confiance": 0.0
}}

SOURCE A — {source_a} (crédibilité {score_a}/100) :
Claim : {claim_a}
Contexte : {contexte_a}

SOURCE B — {source_b} (crédibilité {score_b}/100) :
Claim : {claim_b}
Contexte : {contexte_b}

Y a-t-il une contradiction factuelle ?"""


def arbitrate_with_llm(
    article_a: dict,
    article_b: dict,
    claim_a: dict,
    claim_b: dict,
) -> Optional[dict]:
    """Utilise le LLM configuré pour arbitrer un cas de contradiction ambigu.

    Returns:
        dict résultat ou None si pas de contradiction ou erreur
    """
    prompt = _PROMPT_ARBITRAGE.format(
        source_a=article_a.get("Sources", "Source A"),
        score_a=article_a.get("score_source", 50),
        claim_a=claim_a.get("claim", ""),
        contexte_a=article_a.get("Résumé", "")[:400],
        source_b=article_b.get("Sources", "Source B"),
        score_b=article_b.get("score_source", 50),
        claim_b=claim_b.get("claim", ""),
        contexte_b=article_b.get("Résumé", "")[:400],
    )

    client = get_ai_client()
    try:
        raw = client.ask(prompt, max_attempts=2, timeout=30, max_tokens=200)
        if not raw:
            return None
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            return None
        result = json.loads(json_match.group(0))
        if not result.get("contradiction_detectee"):
            return None
        if result.get("score_confiance", 0) < 0.40:
            return None
        return result
    except Exception as e:
        default_logger.warning(f"[contradiction_engine] Erreur arbitrage LLM: {e}")
        return None
