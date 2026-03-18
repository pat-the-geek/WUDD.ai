# Détection de contradictions entre sources — Fact-checking
## Rapport technique — WUDD.ai

**Date :** 17 mars 2026
**Version :** 1.0
**Auteur :** Analyse technique IA

---

## Table des matières

1. [Contexte et enjeux](#1-contexte-et-enjeux)
2. [Définitions et taxonomie des contradictions](#2-définitions-et-taxonomie-des-contradictions)
3. [Architecture proposée](#3-architecture-proposée)
4. [Pipeline de détection — étape par étape](#4-pipeline-de-détection--étape-par-étape)
5. [Intégration dans WUDD.ai](#5-intégration-dans-wuddai)
6. [Implémentation technique détaillée](#6-implémentation-technique-détaillée)
7. [Limites et précautions](#7-limites-et-précautions)
8. [Plan de développement](#8-plan-de-développement)

---

## 1. Contexte et enjeux

WUDD.ai agrège des articles provenant de **sources multiples** sur les mêmes événements. La plateforme dispose déjà de :
- Déduplication sur 3 signaux (URL, résumé MD5, Jaccard bigrammes)
- Crédibilité par source (`score_source`)
- Entités nommées (`entities`) et timeline
- Analyse croisée multi-flux (`cross_flux_analysis.py`)

Ce qui manque : **savoir si deux sources qui parlent du même événement disent des choses différentes**, voire contradictoires.

**Exemples concrets dans la veille IA/tech :**

| Événement | Source A | Source B | Contradiction |
|-----------|----------|----------|---------------|
| Levée de fonds startup | "100M€ levés" | "80M€ levés" | Chiffre |
| Licenciements | "1 200 emplois supprimés" | "800 postes concernés" | Volume |
| Décision réglementaire | "La loi a été adoptée" | "Le projet a été rejeté" | Fait binaire |
| Délai de déploiement | "Disponible en 2025" | "Prévu pour 2026" | Date |
| Attribution de responsabilité | "OpenAI est responsable" | "Les régulateurs sont en cause" | Causalité |

---

## 2. Définitions et taxonomie des contradictions

### 2.1 Types de contradictions

```
CONTRADICTION
├── FACTUELLE_BINAIRE     → opposé logique (adopté / rejeté, autorisé / interdit)
├── QUANTITATIVE          → chiffres divergents (100M vs 80M, 1200 vs 800 emplois)
├── TEMPORELLE            → dates différentes (2025 vs 2026)
├── ATTRIBUTION           → responsabilité ou action attribuée à des entités différentes
├── NUANCE               → une source affirme, l'autre minimise (sans contradiction dure)
└── OMISSION_SELECTIVE   → un fait important mentionné dans A, absent de B
```

### 2.2 Niveaux de confiance

```
NIVEAU_CONTRADICTION
├── CERTAINE   (score > 0.85) → contradiction logiquement détectable sans IA
├── PROBABLE   (0.60–0.85)    → détectée par LLM avec contexte
├── POSSIBLE   (0.40–0.60)    → nuance ou point de vue divergent
└── NOISE      (< 0.40)       → différence de style, pas de contradiction
```

---

## 3. Architecture proposée

```
Articles WUDD.ai (JSON)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 — Regroupement par événement                        │
│  event_clusterer.py                                          │
│  • Jaccard bigrammes sur "Résumé" (seuil 0.55 plus souple)  │
│  • Entités communes (≥ 2 entités ORG/PERSON/GPE partagées)  │
│  • Fenêtre temporelle (±3 jours)                             │
│  → Clusters d'articles sur le même événement                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 — Extraction de claims                              │
│  claim_extractor.py                                          │
│  • Appel EurIA/Claude avec prompt NER structuré              │
│  • Extrait : chiffres, dates, entités + prédicat             │
│  → Liste de "claims" par article                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 — Comparaison de claims                             │
│  contradiction_detector.py                                   │
│  • Règles déterministes (chiffres, dates, booléens)          │
│  • LLM comme arbitre pour les cas ambigus                    │
│  → Score de contradiction + type + extrait de preuve         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 4 — Fact-checking externe (optionnel)                 │
│  fact_checker.py                                             │
│  • Wikipedia / Wikidata (déjà utilisés pour géoloc)          │
│  • Sources primaires (communiqués officiels si dispo)        │
│  → Verdict : confirmé / infirmé / non vérifiable             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  ÉTAPE 5 — Stockage et affichage                             │
│  data/contradictions.json                                    │
│  viewer — ContradicitionPanel.jsx                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Pipeline de détection — étape par étape

### Étape 1 — Regroupement par événement (`event_clusterer.py`)

Le clustering d'articles sur le même événement est **le problème le plus difficile**. La déduplication existante utilise un seuil Jaccard de 0.70–0.85 pour exclure les doublons. Pour le clustering événementiel, on veut l'inverse : **regrouper des articles différents mais sur le même sujet**.

**Signaux combinés :**

```python
def same_event_score(article_a, article_b) -> float:
    # 1. Entités communes (NER déjà calculé)
    entities_a = set(flatten(article_a.get("entities", {}).values()))
    entities_b = set(flatten(article_b.get("entities", {}).values()))
    entity_overlap = len(entities_a & entities_b) / max(len(entities_a | entities_b), 1)
    # Bonus si ≥ 2 entités ORG ou PERSON en commun → événement très probable

    # 2. Similarité textuelle (Jaccard bigrammes, seuil bas 0.40–0.55)
    jaccard = compute_jaccard_bigrams(article_a["Résumé"], article_b["Résumé"])

    # 3. Fenêtre temporelle (±3 jours)
    date_diff = abs((date_a - date_b).days)
    date_score = max(0, 1 - date_diff / 3)

    # Score composite
    return 0.5 * entity_overlap + 0.35 * jaccard + 0.15 * date_score
```

**Seuil de clustering :** score ≥ 0.45 → même événement

### Étape 2 — Extraction de claims (`claim_extractor.py`)

Un **claim** est une affirmation factuelle atomique et vérifiable :

```
"OpenAI a levé 6,6 milliards de dollars en octobre 2024"
 ────────  ──────────────────────────────── ─────────────
  sujet          prédicat + valeur              date
```

**Prompt EurIA pour extraction de claims :**

```
Tu es un extracteur de faits journalistiques.
Extrait UNIQUEMENT les affirmations factuelles vérifiables du texte suivant.
Format JSON strict :

[
  {
    "claim": "affirmation courte et précise",
    "type": "CHIFFRE|DATE|FAIT_BINAIRE|ATTRIBUTION|AUTRE",
    "sujet": "entité principale concernée",
    "valeur": "la valeur chiffrée ou le fait",
    "confiance": 0.0-1.0
  }
]

Texte : {résumé}
```

**Exemple de sortie :**
```json
[
  {"claim": "OpenAI a levé 6,6 milliards de dollars", "type": "CHIFFRE",
   "sujet": "OpenAI", "valeur": "6,6 milliards de dollars", "confiance": 0.95},
  {"claim": "La valorisation est de 157 milliards", "type": "CHIFFRE",
   "sujet": "OpenAI", "valeur": "157 milliards de dollars", "confiance": 0.90}
]
```

### Étape 3 — Comparaison de claims

**3a. Règles déterministes (rapides, sans LLM) :**

```python
def compare_claims_deterministic(claim_a, claim_b) -> Optional[Contradiction]:
    # Même sujet, même type → comparer les valeurs
    if claim_a["sujet"] != claim_b["sujet"]:
        return None

    if claim_a["type"] == "CHIFFRE":
        val_a = extract_number(claim_a["valeur"])
        val_b = extract_number(claim_b["valeur"])
        if val_a and val_b:
            diff_ratio = abs(val_a - val_b) / max(val_a, val_b)
            if diff_ratio > 0.15:  # divergence > 15%
                return Contradiction(type="QUANTITATIVE", score=min(diff_ratio, 1.0), ...)

    if claim_a["type"] == "FAIT_BINAIRE":
        # Détection d'antonymes : adopté/rejeté, autorisé/interdit, etc.
        if sont_antonymes(claim_a["valeur"], claim_b["valeur"]):
            return Contradiction(type="FACTUELLE_BINAIRE", score=0.95, ...)

    if claim_a["type"] == "DATE":
        date_diff = abs((parse_date(claim_a["valeur"]) - parse_date(claim_b["valeur"])).days)
        if date_diff > 30:  # > 1 mois de différence
            return Contradiction(type="TEMPORELLE", score=min(date_diff/365, 1.0), ...)
```

**3b. LLM comme arbitre (pour les cas ambigus) :**

```
Deux sources parlent du même événement.

SOURCE A ({source_a}, crédibilité {score_a}/100) :
"{résumé_a}"

SOURCE B ({source_b}, crédibilité {score_b}/100) :
"{résumé_b}"

Y a-t-il une contradiction factuelle entre ces deux sources ?
Réponds en JSON :
{
  "contradiction_detectee": true/false,
  "type": "FACTUELLE_BINAIRE|QUANTITATIVE|TEMPORELLE|ATTRIBUTION|NUANCE|AUCUNE",
  "description": "explication courte de la contradiction",
  "extrait_a": "passage contradictoire dans A",
  "extrait_b": "passage contradictoire dans B",
  "source_probablement_correcte": "A|B|INCONNUE",
  "justification": "pourquoi (crédibilité, précision, cohérence interne)",
  "score_confiance": 0.0-1.0
}
```

### Étape 4 — Fact-checking externe

Sources disponibles dans WUDD.ai sans dépendance externe payante :

| Source | Ce qu'elle permet de vérifier | Déjà utilisée ? |
|--------|------------------------------|-----------------|
| **Wikipedia** | Dates clés, chiffres publics, biographies | Oui (géoloc entités) |
| **Wikidata** | Données structurées (fondation, CA, employés) | Oui (géoloc) |
| **OpenStreetMap** | Localisations géographiques | Oui (carte) |
| **Communiqués officiels** | Chiffres de levées de fonds (si URL connue) | Non |
| **EDGAR / AMF** | Données financières réglementées | Non |

**Stratégie pragmatique :** Wikipedia/Wikidata couvrent ~40% des claims vérifiables (entités bien connues). Pour les autres, le verdict est `"non_verifiable"` — ce qui est déjà informatif.

---

## 5. Intégration dans WUDD.ai

### Nouveaux fichiers

```
scripts/
├── detect_contradictions.py    # Pipeline principal
├── cluster_events.py           # Regroupement articles par événement
└── fact_checker.py             # Vérification externe Wikipedia/Wikidata

utils/
├── claim_extractor.py          # Extraction de claims via EurIA
└── contradiction_engine.py     # Moteur de comparaison (règles + LLM)

data/
└── contradictions.json         # Résultats stockés

viewer/src/components/
└── ContradictionPanel.jsx      # UI d'affichage
```

### Format de sortie `data/contradictions.json`

```json
[
  {
    "id": "contradiction_abc123",
    "detected_at": "2026-03-17T08:30:00",
    "event_cluster": ["url1", "url2", "url3"],
    "articles_en_conflit": [
      {
        "url": "https://lemonde.fr/...",
        "source": "Le Monde",
        "score_source": 90,
        "claim": "OpenAI a levé 6,6 milliards de dollars",
        "extrait": "...le géant américain a annoncé une levée de 6,6 milliards..."
      },
      {
        "url": "https://bfmtv.com/...",
        "source": "BFM TV",
        "score_source": 65,
        "claim": "OpenAI a levé 5 milliards de dollars",
        "extrait": "...une enveloppe de 5 milliards de dollars selon nos informations..."
      }
    ],
    "type_contradiction": "QUANTITATIVE",
    "description": "Montant de la levée de fonds divergent (6,6B vs 5B)",
    "score_confiance": 0.88,
    "source_probable": "Le Monde",
    "justification_source": "Score de crédibilité supérieur + chiffre plus précis (6,6B vs 5B arrondi)",
    "fact_check": {
      "statut": "confirme_source_a",
      "source_verification": "Wikidata Q12345",
      "valeur_referee": "6,6 milliards USD"
    },
    "flux": "Intelligence-artificielle",
    "entites_concernees": ["OpenAI", "Sam Altman"]
  }
]
```

### Endpoint Flask

```python
# GET /api/contradictions?days=7&flux=Intelligence-artificielle&type=QUANTITATIVE
# GET /api/contradictions/stats
# POST /api/contradictions/run  (lance la détection)
```

### Intégration DuckDB

DuckDB permettra de requêter rapidement les clusters d'événements sur une fenêtre temporelle :

```sql
-- Articles candidats au clustering (même entités, même fenêtre)
SELECT a1."Sources", a1."Résumé", a2."Sources", a2."Résumé"
FROM read_json_auto('data/articles/**/*.json') a1
JOIN read_json_auto('data/articles/**/*.json') a2
  ON a1."Date de publication" BETWEEN a2."Date de publication" - INTERVAL 3 DAY
                                   AND a2."Date de publication" + INTERVAL 3 DAY
WHERE a1."URL" != a2."URL"
  AND a1."Sources" != a2."Sources"
```

---

## 6. Implémentation technique détaillée

### Coût API estimé

| Étape | Fréquence | Tokens / appel | Coût EurIA |
|-------|-----------|----------------|------------|
| Extraction claims | 1×/article enrichi | ~500 in + 300 out | ~0.08 ct |
| Comparaison LLM | 1×/paire contradictoire | ~1200 in + 400 out | ~0.2 ct |
| Fact-check Wikipedia | 0 token (HTTP direct) | — | Gratuit |

Pour 100 articles/jour avec 20% de clusters → ~40 comparaisons LLM/jour → **< 0,10€/jour**.

### Optimisation : détection en deux passes

```
PASSE 1 — Règles déterministes (gratuit, < 1ms/paire)
  → Filtre 80% des paires sans contradiction
  → Résultats certains directement sauvegardés

PASSE 2 — LLM uniquement sur les 20% restants
  → Traite les cas ambigus
  → Arbitre entre nuance et contradiction réelle
```

### Scheduler recommandé

```cron
# Détection contradictions — après enrichissement NER de nuit
30 03 * * *  python3 scripts/detect_contradictions.py --days 2
```

Lancé après `enrich_entities.py` (02:00) pour disposer des entités nécessaires au clustering.

---

## 7. Limites et précautions

### Ce que le système **peut** faire
- Détecter des chiffres divergents entre deux résumés sur le même événement
- Identifier des affirmations binaires opposées (adopté / rejeté)
- Signaler des dates incompatibles
- Comparer la crédibilité des sources pour orienter vers la version probable

### Ce que le système **ne peut pas** faire
- Déterminer avec certitude laquelle des deux sources a raison
- Vérifier des claims sans source externe fiable disponible
- Comprendre le sarcasme, la citation au second degré, les contre-exemples intentionnels
- Distinguer une évolution d'information dans le temps d'une vraie contradiction

### Risques à mitiger

| Risque | Mitigation |
|--------|------------|
| Faux positifs (nuances présentées comme contradictions) | Seuil de confiance ≥ 0.70 pour affichage |
| Biais source (toujours favoriser la source avec le meilleur score) | Afficher les deux versions, ne jamais "effacer" une source |
| Coût API excessif si mal calibré | Passe déterministe en premier, LLM en dernier recours |
| Confusion temporelle (évolution vs contradiction) | Ordonner par date avant de comparer |

### Affichage responsable

La contradiction détectée doit **toujours afficher les deux sources** avec leur extrait, sans verdict définitif imposé à l'utilisateur. Le système propose une source probable avec justification — l'utilisateur reste juge.

---

## 8. Plan de développement

### Phase 1 — Fondations (1–2 semaines)
- [ ] `utils/claim_extractor.py` — prompt EurIA + parsing JSON
- [ ] `utils/contradiction_engine.py` — règles déterministes (chiffres, dates, binaires)
- [ ] Tests unitaires sur cas connus

### Phase 2 — Pipeline (1 semaine)
- [ ] `scripts/cluster_events.py` — regroupement par événement (entités + Jaccard)
- [ ] `scripts/detect_contradictions.py` — orchestration + écriture `contradictions.json`
- [ ] Intégration cron (03:30 daily)

### Phase 3 — LLM + Fact-check (1 semaine)
- [ ] Comparaison LLM pour les cas ambigus
- [ ] `scripts/fact_checker.py` — Wikipedia/Wikidata lookup
- [ ] Endpoint Flask `/api/contradictions`

### Phase 4 — Interface (1 semaine)
- [ ] `ContradictionPanel.jsx` — affichage côte-à-côte des sources en conflit
- [ ] Intégration dans `EntityArticlePanel.jsx` (badge contradiction sur entités)
- [ ] Alertes webhook si contradiction `CERTAINE` sur source de crédibilité ≥ 80

### Dépendances techniques
- Aucune nouvelle dépendance externe requise pour les phases 1–2
- Phase 3 : `wikipedia-api` (0.5 MB, déjà dans l'écosystème Python standard)
- Phase 4 : composant React pur, pas de lib supplémentaire

---

## Conclusion

La détection de contradictions est une fonctionnalité **haute valeur** pour WUDD.ai car elle transforme la veille informationnelle en **vérification de l'information**. Les briques sont déjà présentes dans le projet (NER, crédibilité source, similarité Jaccard, EurIA API) — il s'agit de les combiner dans un nouveau pipeline.

La complexité principale est le **regroupement par événement** (étape 1) : identifier que deux articles parlent du même fait sans être des doublons. Une fois ce clustering résolu, la détection de contradictions entre claims est relativement directe.

**Recommandation :** commencer par les contradictions **quantitatives** (chiffres divergents) — les plus fréquentes en veille tech/économique et les plus simples à détecter de manière déterministe, sans LLM.
