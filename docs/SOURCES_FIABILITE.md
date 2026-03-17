# Fiabilité et biais éditoriaux des sources

> Documentation fonctionnelle · Version 1.0 · Mars 2026

---

## Table des matières

1. [Vue d'ensemble du système d'évaluation](#1-vue-densemble-du-système-dévaluation)
2. [Score de crédibilité statique](#2-score-de-crédibilité-statique)
3. [Score composite dynamique (v2)](#3-score-composite-dynamique-v2)
4. [Critère 1 — Triangulation inter-sources](#4-critère-1--triangulation-inter-sources)
5. [Critère 2 — Âge et stabilité du domaine](#5-critère-2--âge-et-stabilité-du-domaine)
6. [Critère 3 — Transparence éditoriale](#6-critère-3--transparence-éditoriale)
7. [Critère 4 — Régularité de publication](#7-critère-4--régularité-de-publication)
8. [Critère 5 — Référencement MBFC](#8-critère-5--référencement-mbfc)
9. [Multiplicateur de scoring et impact sur le classement](#9-multiplicateur-de-scoring-et-impact-sur-le-classement)
10. [Biais éditorial et ton éditorial](#10-biais-éditorial-et-ton-éditorial)
11. [Champs JSON des articles](#11-champs-json-des-articles)
12. [Panneau Biais éditoriaux — interface](#12-panneau-biais-éditoriaux--interface)
13. [Limites et précautions d'interprétation](#13-limites-et-précautions-dinterprétation)

---

## 1. Vue d'ensemble du système d'évaluation

WUDD.ai distingue deux dimensions complémentaires dans l'analyse des sources :

**La crédibilité de la source** mesure la fiabilité structurelle du média : son histoire, ses pratiques éditoriales, sa transparence, son indépendance. Elle s'applique une fois par source, indépendamment du contenu des articles.

**Le biais éditorial** mesure la coloration thématique et affective du traitement de l'information : est-ce que ce média couvre ce sujet de façon factuelle ou alarmiste ? positive ou négative ? Ce critère s'applique article par article, à partir de l'analyse sémantique du résumé.

Ces deux dimensions sont **indépendantes mais complémentaires**. Un média très crédible peut avoir un biais éditorial marqué sur un sujet précis. Un média peu crédible peut occasionnellement publier un article factuel et équilibré.

```
Article
  │
  ├─► Crédibilité source ──► multiplicateur (0.60–1.20) ──► score_pertinence
  │         │
  │   ┌─────┴──────────────────────────────────────────────────┐
  │   │  score statique (0–100)                                  │
  │   │  + âge domaine + transparence + MBFC                    │
  │   │    → score composite (0–100) [v2]                       │
  │   └──────────────────────────────────────────────────────────┘
  │
  ├─► Triangulation inter-sources ──► bonus score_pertinence (+0 à +10)
  ├─► Régularité de publication   ──► malus score_pertinence (0 à -10)
  │
  └─► Analyse sémantique ──► sentiment + ton_editorial ──► biais éditorial
```

---

## 2. Score de crédibilité statique

### Définition

Le score statique (champ `score` dans `config/sources_credibility.json`) est un entier entre **0 et 100** qui reflète la fiabilité éditoriale structurelle d'un média, évaluée selon les critères de référence du journalisme international (IFCN, RSF, MBFC).

### Référentiel d'évaluation

| Tranche | Valeur | Signification |
|---|---|---|
| **90–100** | Très élevée | Agences de presse internationales (Reuters, AFP, AP), grands quotidiens de référence, médias publics à charte stricte |
| **80–89** | Élevée | Presse nationale sérieuse, fact-checking actif, ligne éditoriale transparente |
| **70–79** | Bonne | Médias régionaux, presse gratuite de qualité, médias spécialisés sans fact-checking systématique |
| **50–69** | Moyenne / variable | Chaînes d'info en continu, médias à coloration politique marquée, sources dont la rigueur varie |
| **0–49** | Faible | Sources à vérifier systématiquement — non utilisées en production dans WUDD.ai |

### Exemples de scores

| Source | Score | Justification |
|---|---|---|
| Reuters | 97 | Agence de presse mondiale, charte stricte, fact-checking intégré |
| AFP | 96 | Idem, référence francophone |
| Le Monde | 92 | Quotidien de référence, service Décodex, fact-checking actif |
| Les Échos | 90 | Presse économique sérieuse, indépendance rédactionnelle |
| BBC | 90 | Média public, charte éditoriale stricte, couverture internationale |
| Le Figaro | 88 | Presse nationale, rigueur reconnue, biais centre-droite déclaré |
| franceinfo | 87 | Média public, équipe fact-checking dédiée |
| France Inter | 84 | Radio publique, couverture sérieuse, biais centre-gauche déclaré |
| Médiapart | 80 | Investigations reconnues, modèle économique indépendant |
| BFM TV | 68 | Sensationnalisme fréquent, pression du temps réel |
| CNews | 55 | Ligne éditoriale marquée droite, fact-checking limité |

### Sources inconnues

Toute source absente de `sources_credibility.json` reçoit un **score par défaut de 50** (valeur neutre). Elle contribue au scoring sans bonus ni malus particulier. L'opérateur peut à tout moment enrichir la base en ajoutant une entrée dans le fichier de configuration.

### Métadonnées associées

Chaque entrée de `sources_credibility.json` contient les champs suivants :

| Champ | Type | Valeurs possibles |
|---|---|---|
| `score` | int | 0–100 |
| `biais` | string | `"centre"`, `"centre-gauche"`, `"centre-droite"`, `"gauche"`, `"droite"`, `"inconnu"` |
| `type` | string | `"agence de presse"`, `"presse écrite"`, `"presse hebdomadaire"`, `"presse économique"`, `"presse numérique"`, `"presse technologique"`, `"presse régionale"`, `"presse gratuite"`, `"média public"`, `"radio"`, `"radio publique"`, `"chaîne info en continu"`, `"chaîne info internationale"` |
| `pays` | string | `"France"`, `"Royaume-Uni"`, `"États-Unis"`, `"Suisse"`, `"Belgique"`, `"Canada"`, `"Allemagne"`, `"Qatar"`, … |
| `fiabilite` | string | `"très élevée"`, `"élevée"`, `"bonne"`, `"moyenne"`, `"variable"` |
| `fact_checking` | bool | `true` / `false` |

---

## 3. Score composite dynamique (v2)

### Objectif

Le score statique est entièrement manuel et ne se met à jour qu'à la main. Le score composite v2 combine le score statique avec **3 signaux automatisés** calculés périodiquement par le script `scripts/enrich_source_credibility.py`.

### Formule

```
score_composite = score_statique    × 0.60
               + score_age_domaine  × 0.15
               + score_transparence × 0.10
               + score_mbfc         × 0.15
```

Le score composite reste dans la plage 0–100. Il remplace le score statique dans le calcul du multiplicateur de scoring à partir de la v2.

### Tolérance au manque de données (fallback)

Si une source n'a pas encore été enrichie (champs `domain_age_years`, `transparence`, `mbfc_rating` absents), `get_composite_score()` retourne le score statique pur sans pénalité. La pondération s'applique progressivement au fur et à mesure des enrichissements :

| Champs disponibles | Calcul appliqué |
|---|---|
| Aucun champ v2 | `score_statique` (100%) |
| `domain_age_years` seulement | `score × 0.75 + age × 0.25` |
| `domain_age_years` + `transparence` | `score × 0.75 + age × 0.15 + transp × 0.10` |
| Tous les champs v2 | Formule complète (voir ci-dessus) |

### Nouveaux champs JSON dans `sources_credibility.json`

| Champ | Type | Exemple | Ajouté par |
|---|---|---|---|
| `domain_age_years` | float | `28.4` | `enrich_source_credibility.py` |
| `transparence` | int | `3` | `enrich_source_credibility.py` |
| `mbfc_rating` | string | `"HIGH"` | `enrich_source_credibility.py` |
| `enrich_date` | string | `"2026-03-16"` | `enrich_source_credibility.py` |

---

## 4. Critère 1 — Triangulation inter-sources

### Principe

Un événement couvert indépendamment par plusieurs médias à crédibilité élevée est plus fiable qu'un article isolé. Ce critère calcule, pour chaque article, le nombre de sources distinctes (score ≥ 75) qui traitent du même sujet dans les 48 dernières heures.

### Calcul

```
similarité(A, B) = Jaccard(bigrammes(résumé A), bigrammes(résumé B))

si similarité ≥ 0.35 : les deux articles couvrent le même événement

triangulation_score(article) = nombre de sources distinctes
                                 (score ≥ 75) ayant un article
                                 similaire dans ±48h
```

La similarité de Jaccard sur bigrammes est le même algorithme utilisé par `utils/deduplication.py` (avec un seuil plus bas : 0.35 vs 0.80, pour détecter la proximité thématique sans exiger la duplication stricte).

### Impact sur le score_pertinence

| Triangulation | Bonus |
|---|---|
| ≥ 4 sources | +10 pts |
| 3 sources | +7 pts |
| 2 sources | +4 pts |
| 1 source (l'article lui-même) | 0 |

### Limites

Ce critère favorise mécaniquement les événements couverts par de nombreux médias (actualité chaude), et peut sous-valoriser des enquêtes exclusives publiées par une seule source fiable. Il ne mesure pas la qualité de la couverture, seulement sa diffusion.

---

## 5. Critère 2 — Âge et stabilité du domaine

### Principe

Les sites de désinformation, fermes à clics et médias opportunistes sont le plus souvent créés récemment. Les recherches de NewsGuard et du Stanford Internet Observatory montrent qu'une écrasante majorité des sites diffusant de la mésinformation ont moins de 3 ans d'existence au moment de leur activité maximale.

### Source externe utilisée

**WHOIS** — protocole internet standard qui interroge les registres de noms de domaine (IANA, ICANN, registrars nationaux comme AFNIC pour `.fr`, Nominet pour `.co.uk`, etc.). La requête est effectuée via la bibliothèque Python **`python-whois`** (`pip install python-whois`). WHOIS est public, gratuit, sans clé API, mais soumis à des limites de débit selon les registrars.

**Domaine testé :** extrait automatiquement depuis le champ `url` de l'article (ex : `https://www.lemonde.fr/article/…` → `lemonde.fr`).

**User-Agent :** `Mozilla/5.0 (compatible; WUDD.ai/2.3; +https://github.com/wudd-ai)`

### Calcul

```python
import whois
from datetime import datetime, timezone

w = whois.whois(domain)          # requête WHOIS via python-whois
creation = w.creation_date       # date de création du domaine
if isinstance(creation, list):
    creation = creation[0]       # certains registrars retournent une liste

age_years = (datetime.now(timezone.utc) - creation).days / 365.25
```

Si WHOIS échoue (registrar muet, délai dépassé, domaine privé), le critère est ignoré sans pénalité : la formule de score composite s'adapte automatiquement aux champs disponibles (voir §3).

### Conversion en score (0–100)

| Âge du domaine | score_age_domaine |
|---|---|
| ≥ 20 ans | 100 |
| 10–19 ans | 85 |
| 5–9 ans | 70 |
| 3–4 ans | 50 |
| 2–3 ans | 30 |
| 1–2 ans | 15 |
| < 1 an | 0 |

### Fréquence de mise à jour

Ce critère est calculé une fois par source lors de son premier ajout, puis recalculé annuellement (1er du mois, 04:30, via cron). Le champ `enrich_date` permet de détecter les entrées obsolètes.

---

## 6. Critère 3 — Transparence éditoriale

### Principe

Une source fiable identifie qui la publie, comment la contacter, et selon quelles règles éditoriales. L'absence de mentions légales ou de page "À propos" est un signal d'alerte reconnu par l'IFCN (*International Fact-Checking Network*) dans ses critères de certification des fact-checkeurs.

### Source externe utilisée

**HTTP direct** — le système effectue des requêtes HTTP sur le site lui-même, sans intermédiaire. Il utilise la bibliothèque Python **`requests`** avec un User-Agent identifié (`WUDD.ai/2.3`). Aucune clé API ni service tiers requis.

**Méthode :** `HEAD` en première intention (plus rapide, ne télécharge pas le corps), puis fallback `GET` si le serveur répond `405 Method Not Allowed`. Timeout : **8 secondes** par requête. Une réponse HTTP `200 OK` sur l'URL finale (après redirections) valide la présence de la page.

### Méthode de vérification

Le système teste plusieurs chemins canoniques par catégorie (une seule réponse 200 suffit pour valider la catégorie) :

| Catégorie | Chemins testés | Points | Justification |
|---|---|---|---|
| Mentions légales | `/mentions-legales`, `/mentions_legales`, `/legal`, `/mentions-légales` | 1 | Obligations légales françaises (LCEN) |
| À propos | `/about`, `/qui-sommes-nous`, `/a-propos`, `/apropos`, `/about-us` | 1 | Identité du média |
| CGU | `/cgu`, `/conditions`, `/conditions-generales`, `/terms` | 1 | Cadre contractuel clair |
| Contact | `/contact`, `/redaction`, `/nous-contacter`, `/contactez-nous` | 1 | Joignabilité de la rédaction |

### Conversion en score (0–100)

| Points obtenus | score_transparence | Interprétation |
|---|---|---|
| 4 | 100 | Transparence complète |
| 3 | 75 | Bonne transparence |
| 2 | 50 | Transparence partielle |
| 1 | 25 | Transparence minimale |
| 0 | 0 | Opacité totale — signal d'alerte |

### Limites

Ce critère ne vérifie que la **présence** des pages, pas leur contenu. Un site peut afficher une page de mentions légales vide ou fictive. Il s'agit d'un signal parmi d'autres, à croiser avec les autres critères.

---

## 7. Critère 4 — Régularité de publication

### Principe

Une source qui publie de façon erratique — longues périodes de silence suivies de pics d'activité massive — présente un comportement atypique pouvant signaler un site de contenu automatisé, une campagne coordonnée ou un média opportuniste. Les sources journalistiques légitimes maintiennent généralement un rythme de publication stable.

### Calcul

À partir des articles collectés dans `data/` sur les **30 derniers jours**, pour chaque source :

```
intervalles = liste des durées (en heures) entre publications successives
écart_type  = std(intervalles)

score_regularite = max(0, 100 − écart_type / 2)
```

Un écart-type de 0 h (publication parfaitement régulière) donne 100. Un écart-type de 200 h donne 0.

### Impact sur le score_pertinence

| Irrégularité (écart-type) | Effet |
|---|---|
| < 24 h | 0 (neutre) |
| 24–72 h | −3 pts |
| 72–120 h | −6 pts |
| > 120 h | −10 pts |

### Conditions d'activation

Ce critère ne s'applique que si la source dispose d'au moins **10 articles** dans les 30 derniers jours dans la base locale. En dessous de ce seuil, l'effet est neutre (0 pts).

### Note importante

Ce critère mesure la régularité de la **collecte** dans WUDD.ai, pas nécessairement la régularité réelle du média. Une source bien connue mais peu couverte par les flux configurés peut sembler irrégulière sans l'être réellement.

---

## 8. Critère 5 — Référencement MBFC

### Présentation de MBFC

**Media Bias / Fact Check** ([mediabiasfactcheck.com](https://mediabiasfactcheck.com)) est la base de données publique de référence pour l'évaluation des médias, créée en 2015 par Dave Van Zandt. Elle classe chaque source selon deux axes : le biais politique et le niveau factuel. Plus de 5 000 sources mondiales y sont référencées.

Pour WUDD.ai, seul le **niveau factuel** (« Factual Reporting ») est utilisé dans le score composite.

### Source externe utilisée

**Scraping HTTP de mediabiasfactcheck.com** — MBFC ne propose pas d'API publique. Le système interroge directement le moteur de recherche interne du site :

```
GET https://mediabiasfactcheck.com/?s={nom_source_encodé}
```

Exemple : pour « Le Monde » → `https://mediabiasfactcheck.com/?s=Le+Monde`

Le HTML de la page de résultats est ensuite analysé par expression régulière pour extraire le rating factuel dans le bloc de texte entourant la première occurrence du nom de la source.

**Pattern de détection (par ordre de priorité) :**

| Pattern regex | Rating retenu |
|---|---|
| `VERY\s+HIGH` | `"VERY HIGH"` |
| `HIGH\s+FACTUAL` | `"HIGH"` |
| `\bHIGH\b` | `"HIGH"` |
| `MOSTLY\s+FACTUAL` | `"MOSTLY FACTUAL"` |
| `\bMIXED\b` | `"MIXED"` |
| `VERY\s+LOW` | `"VERY LOW"` |
| `\bLOW\b` | `"LOW"` |

Si le nom de la source n'apparaît pas dans les résultats, ou si aucun pattern ne correspond dans les 200 caractères avant / 500 après la première occurrence, `mbfc_rating` est mis à `null`.

**User-Agent :** `Mozilla/5.0 (compatible; WUDD.ai/2.3; +https://github.com/wudd-ai)` — Timeout : 8 secondes.

> **Note :** Le scraping de MBFC est réalisé de façon respectueuse (1 requête par source, délai de 2 secondes entre requêtes, uniquement lors des enrichissements planifiés). WUDD.ai n'archive pas le contenu de MBFC et ne l'utilise que pour un seul champ (`mbfc_rating`).

### Niveaux factuels MBFC et conversion

| Rating MBFC | Signification | score_mbfc |
|---|---|---|
| `VERY HIGH` | Fiabilité factuelle très haute — jamais pris en faute sur des faits | 100 |
| `HIGH` | Fiabilité factuelle haute — erreurs rares et corrigées | 85 |
| `MOSTLY FACTUAL` | Généralement fiable — quelques imprécisions | 65 |
| `MIXED` | Fiabilité variable — mélange de faits et d'opinions mal distingués | 40 |
| `LOW` | Faible fiabilité — nombreuses inexactitudes | 15 |
| `VERY LOW` | Sources pseudo-scientifiques, complotistes ou délibérément trompeuses | 0 |
| Non répertorié | Source absente de la base MBFC | 50 (neutre) |

### Champ JSON dans `sources_credibility.json`

| Champ | Type | Valeurs possibles |
|---|---|---|
| `mbfc_rating` | string | `"VERY HIGH"`, `"HIGH"`, `"MOSTLY FACTUAL"`, `"MIXED"`, `"LOW"`, `"VERY LOW"`, `null` |

---

## 9. Multiplicateur de scoring et impact sur le classement

### Rôle du multiplicateur

Le multiplicateur de crédibilité s'applique **en dernier** dans le calcul de `score_pertinence`, après la somme pondérée des composantes (fraîcheur, entités, mots-clés, complétude). Il amplifie ou atténue le score calculé selon la crédibilité de la source.

### Formule du multiplicateur

```
multiplicateur = 0.60 + (score_composite / 100) × (1.20 − 0.60)
              = 0.60 + score_composite × 0.006

score_pertinence_final = score_brut × multiplicateur
                       + bonus_triangulation − malus_irregularite
```

### Tableau de correspondance

| Score composite | Multiplicateur | Effet sur le classement |
|---|---|---|
| 100 | 1.20 | +20% — forte remontée dans les tops articles |
| 90 | 1.14 | +14% |
| 80 | 1.08 | +8% |
| 50 (source inconnue) | 0.90 | −10% — légère pénalité |
| 30 | 0.78 | −22% — pénalité significative |
| 0 | 0.60 | −40% — forte pénalité |

### Score final de pertinence — exemples

Pour un article avec score brut = 75 :

| Source | Score composite | Multiplicateur | Triangulation | Score final |
|---|---|---|---|---|
| Reuters | 97 | 1.18 | +7 (3 sources) | **min(100, 75×1.18+7) = 95.5** |
| Le Monde | 92 | 1.15 | +4 (2 sources) | **min(100, 75×1.15+4) = 90.3** |
| Source inconnue | 50 | 0.90 | 0 | **67.5** |
| BFM TV | 68 | 1.01 | 0 | **75.8** |
| CNews | 55 | 0.93 | 0 | **69.8** |

---

## 10. Biais éditorial et ton éditorial

### Distinction conceptuelle

Le **biais éditorial** désigne la tendance systématique d'un média à traiter certains sujets de manière orientée. Il est déclaratif dans WUDD.ai (champ `biais` dans `sources_credibility.json`).

Le **ton éditorial** est mesuré article par article par le modèle IA lors de l'enrichissement sentiment (`scripts/enrich_sentiment.py`).

### Champs de sentiment et de ton (par article)

| Champ | Type | Valeurs possibles | Description |
|---|---|---|---|
| `sentiment` | string | `"positif"`, `"neutre"`, `"négatif"` | Tonalité émotionnelle globale du résumé |
| `score_sentiment` | int | 1–5 | Intensité : 1 = très négatif, 3 = neutre, 5 = très positif |
| `ton_editorial` | string | `"factuel"`, `"alarmiste"`, `"promotionnel"`, `"critique"`, `"analytique"` | Nature du traitement éditorial |
| `score_ton` | int | 1–5 | Factualité : 5 = très factuel, 1 = très biaisé/sensationnaliste |

### Valeurs détaillées : `sentiment`

| Valeur | Description |
|---|---|
| `"positif"` | Résumé à connotation favorable — annonce positive, progrès, résolution de crise |
| `"neutre"` | Résumé factuel sans coloration affective marquée |
| `"négatif"` | Résumé à connotation défavorable — catastrophe, échec, conflit, polémique |

### Valeurs détaillées : `score_sentiment`

| Valeur | Signification |
|---|---|
| 5 | Très positif — enthousiasme, célébration, optimisme fort |
| 4 | Positif — satisfaction, bonne nouvelle, progrès |
| 3 | Neutre — information factuelle sans affect |
| 2 | Négatif — inquiétude, critique, déception |
| 1 | Très négatif — alarme, catastrophisme, polémique forte |

### Valeurs détaillées : `ton_editorial`

| Valeur | Description | Signal d'alerte ? |
|---|---|---|
| `"factuel"` | Présentation sobre des faits, sources citées, absence de jugement | Non |
| `"analytique"` | Explication des causes et conséquences, mise en perspective | Non |
| `"critique"` | Remise en question, positionnement éditorial assumé | Selon contexte |
| `"promotionnel"` | Valorisation d'un produit, d'une institution ou d'une position | Oui |
| `"alarmiste"` | Exagération du danger ou de l'urgence, vocabulaire catastrophiste | Oui |

### Valeurs détaillées : `score_ton`

| Valeur | Signification |
|---|---|
| 5 | Très factuel — journalisme de référence, neutralité stricte |
| 4 | Factuel — quelques formulations engagées mais information solide |
| 3 | Mitigé — mélange de faits et d'opinions |
| 2 | Biaisé — opinion prédomine sur les faits |
| 1 | Très biaisé / sensationnaliste — information secondaire |

### Lecture combinée

Le panneau **Biais éditoriaux** agrège ces données par source pour révéler des tendances :

- Une source avec **score_ton moyen < 2.5** et **taux négatif > 60%** présente un profil alarmiste systématique.
- Une source avec **score_ton moyen > 4** et **sentiment majoritairement neutre** correspond au profil d'une agence de presse.
- Un écart important entre le `biais` déclaré et le ton mesuré mérite une investigation manuelle.

---

## 11. Champs JSON des articles

Récapitulatif de tous les champs liés à la fiabilité et au biais dans le format article WUDD.ai :

| Champ | Ajouté par | Présence | Valeurs |
|---|---|---|---|
| `score_source` | `utils/source_credibility.py` via scripts de collecte | Optionnel | 0–100 (score composite si enrichi, statique sinon) |
| `sentiment` | `scripts/enrich_sentiment.py` | Optionnel | `"positif"`, `"neutre"`, `"négatif"` |
| `score_sentiment` | `scripts/enrich_sentiment.py` | Optionnel | 1–5 |
| `ton_editorial` | `scripts/enrich_sentiment.py` | Optionnel | `"factuel"`, `"analytique"`, `"critique"`, `"promotionnel"`, `"alarmiste"` |
| `score_ton` | `scripts/enrich_sentiment.py` | Optionnel | 1–5 |
| `score_pertinence` | `utils/scoring.py` | Calculé à la demande | 0–100 |

---

## 12. Panneau Biais éditoriaux — interface

Le panneau **Biais éditoriaux** (`SourceBiasPanel`) est accessible depuis la barre de navigation de l'interface WUDD.ai. Il agrège les données de toutes les sources présentes dans les fichiers JSON du répertoire `data/`.

### Colonnes du tableau

| Colonne | Source de donnée | Notes |
|---|---|---|
| **Source** | Champ `Sources` des articles | |
| **Articles** | Comptage des articles collectés | |
| **Score fiabilité** | `score_composite` (ou statique si non enrichi) | Badge coloré 0–100 |
| **Âge domaine** | `domain_age_years` | Alerte si < 2 ans |
| **Transparence** | `transparence` | Icônes ●●●● (0–4) |
| **MBFC** | `mbfc_rating` | Badge coloré |
| **Sentiment** | Distribution positive/neutre/négative | Barre tricolore proportionnelle |
| **Ton dominant** | `ton_editorial` le plus fréquent | Badge coloré par type |
| **Score ton** | Moyenne de `score_ton` | /5 — vert ≥ 4, rouge ≤ 2 |

### Options de tri

| Option | Critère de tri |
|---|---|
| Volume d'articles | `article_count` descendant |
| Score fiabilité ↓ | `score_composite` descendant |
| Ton le + factuel | `avg_score_ton` descendant |
| Ton le + biaisé | `avg_score_ton` ascendant |
| Taux négatif ↓ | Ratio `négatif / article_count` |

---

## 13. Limites et précautions d'interprétation

### Ce que le système mesure

- La **crédibilité structurelle** d'un média (son histoire, ses pratiques, sa transparence).
- La **coloration éditoriale** d'un article spécifique (son ton, son sentiment).
- La **confirmation croisée** d'un événement par plusieurs sources indépendantes.

### Ce que le système ne mesure pas

- La **vérité factuelle** d'un article. Un article d'une source très crédible peut contenir une erreur.
- Le **contexte géopolitique** du biais. Certains médias ont des biais liés à leur financement d'État.
- La **qualité de la traduction** pour les sources non francophones.
- **L'intention de tromper** : un ton alarmiste peut être justifié par un événement réellement grave.

### Précautions d'utilisation

> Le score composite et le multiplicateur de scoring sont des **outils de priorisation**, pas des jugements définitifs. Ils orientent l'attention de l'utilisateur sans substituer son jugement éditorial.

La base `sources_credibility.json` doit être régulièrement revue par l'opérateur, notamment pour les nouvelles sources détectées automatiquement qui reçoivent par défaut un score de 50.

---

*Document généré pour WUDD.ai v2.3 — Patrick Ostertag — Mars 2026*
