# Rapport d'analyse technique — WUDD.ai
## Optimisations et nouvelles fonctionnalités proposées

*Généré le 17 mars 2026 — Claude Sonnet 4.6*

---

## Table des matières

1. [État des lieux — forces actuelles](#1-état-des-lieux--forces-actuelles)
2. [Optimisations techniques prioritaires](#2-optimisations-techniques-prioritaires)
3. [Nouvelles fonctionnalités recommandées](#3-nouvelles-fonctionnalités-recommandées)
4. [Tableau de priorisation](#4-tableau-de-priorisation)
5. [Axes à éviter ou différer](#5-axes-à-éviter-ou-différer)

---

## 1. État des lieux — forces actuelles

Le projet a atteint une maturité architecturale significative (v4.2). Les fondations sont solides :

- **Pipeline ETL complet** : collecte → déduplication → résumé IA → enrichissement NER/sentiment → indexation → rapport
- **Quotas adaptatifs à 4 niveaux** : global / par mot-clé / par source / par entité nommée
- **Index inversé** entity→articles avec normalisation de casse (v2)
- **Déduplication 3 signaux** : URL MD5 + résumé MD5 + Jaccard bigrammes
- **Double fournisseur IA** : EurIA (Qwen3) et Claude (Anthropic), sélectionnable via env var
- **Viewer Flask+React mobile-first** : 50+ endpoints, 30 composants, SSE streaming
- **Architecture sans base de données** : JSON files + indexes, portable et simple
- **Couverture de tests** : 50+ tests, 2 020 lignes, cibles `utils/` ≥ 80%

---

## 2. Optimisations techniques prioritaires

### 2.1 Persistance des données — migrer vers SQLite/DuckDB

**Problème actuel**
Le stockage JSON pur va devenir un goulot d'étranglement au-delà de ~50 000 articles. Chaque accès à `article_index.json` charge l'ensemble du fichier en mémoire. Les indexes (`entity_index.json`) grossissent de façon linéaire.

**Solution recommandée**
Introduire **DuckDB** comme couche d'accès analytique (compatible avec les fichiers JSON existants, pas de migration destructive) :

```python
# utils/db.py — nouvelle couche optionnelle
import duckdb

def query_articles(entity: str, days: int = 7) -> list[dict]:
    conn = duckdb.connect()
    return conn.execute("""
        SELECT * FROM read_json_auto('data/articles/**/*.json')
        WHERE list_contains(
            json_extract_string(entities, '$.PERSON'), ?
        )
        AND date_diff('day', "Date de publication", today()) <= ?
    """, [entity, days]).fetchall()
```

DuckDB lit les JSON natifs sans migration, permet du SQL analytique, et reste sans serveur. L'index actuel peut coexister pendant la transition.

**Impact** : requêtes 10-100× plus rapides sur les gros corpus, agrégations temporelles instantanées.

---

### 2.2 Index entity — passage à un modèle événementiel

**Problème actuel**
L'index entity est reconstruit toutes les 24h (staleness check au démarrage Flask). Si un article est ajouté à 15h, il n'est indexé qu'à J+1. Les scripts `entity_timeline.py` et `cross_flux_analysis.py` tournent toutes les 5 minutes mais lisent un index potentiellement vieux.

**Solution recommandée**
Ajouter un hook post-écriture dans `rolling_window.py` et les scripts d'enrichissement :

```python
# utils/rolling_window.py — à la fin de update_rolling_window()
from utils.entity_index import get_entity_index

def update_rolling_window(new_articles, output_path, hours=48, source_dir=None):
    # ... logique existante ...

    # Mise à jour incrémentale de l'index immédiatement
    index = get_entity_index()
    index.update_incremental(new_articles, str(output_path))
```

L'index passerait de 24h à quelques secondes de latence, sans reconstruction complète coûteuse.

---

### 2.3 Gestion des erreurs — enrichir le circuit breaker

**Problème actuel**
Le circuit breaker actuel (seuil 5 échecs, grace 300s) est binaire : ouvert ou fermé. Il ne distingue pas les erreurs temporaires (timeout) des erreurs permanentes (quota dépassé, clé API invalide).

**Solution recommandée**
Ajouter des états différenciés et des backoffs spécifiques par type d'erreur :

```python
class CircuitBreaker:
    # Statuts distincts
    CLOSED = "closed"
    OPEN_TIMEOUT = "open_timeout"      # 300s grace
    OPEN_QUOTA = "open_quota"          # grâce jusqu'à minuit
    OPEN_AUTH = "open_auth"            # bloqué, alerte admin requise

    def record_failure(self, error: Exception):
        if isinstance(error, QuotaExceededError):
            self.state = self.OPEN_QUOTA
            self.grace_until = midnight_today()
        elif isinstance(error, AuthenticationError):
            self.state = self.OPEN_AUTH
            self._notify_admin()  # webhook Ntfy/Discord
        else:
            # comportement existant
            ...
```

---

### 2.4 Parallélisme — remplacer ThreadPoolExecutor par asyncio pour les I/O

**Problème actuel**
`utils/parallel.py` utilise `ThreadPoolExecutor` (5 workers). Les threads Python sont limités par le GIL pour du code CPU-bound mais acceptables pour de l'I/O. Cependant, la gestion des erreurs est fragmentée et le monitoring des workers absent.

**Solution recommandée**
Pour les enrichissements (enrich_entities, enrich_sentiment), utiliser `asyncio` + `aiohttp` qui gère mieux les centaines de petites requêtes HTTP :

```python
# utils/async_enricher.py
import asyncio
import aiohttp

async def enrich_batch(articles: list[dict], semaphore_limit: int = 10):
    semaphore = asyncio.Semaphore(semaphore_limit)
    async with aiohttp.ClientSession() as session:
        tasks = [enrich_one(article, session, semaphore) for article in articles]
        return await asyncio.gather(*tasks, return_exceptions=True)
```

Gain attendu : 3-5× sur les scripts d'enrichissement nocturnes.

---

### 2.5 Déduplication — améliorer le seuil Jaccard adaptatif

**Problème actuel**
Le seuil Jaccard bigrammes est fixé à 0.80 pour tous les types d'articles. Ce seuil unique génère des faux positifs sur les articles courts (brèves de 50 mots) et des faux négatifs sur les articles longs reformulés.

**Solution recommandée**
Seuil adaptatif selon la longueur du résumé :

```python
def _adaptive_threshold(text: str) -> float:
    words = len(text.split())
    if words < 80:
        return 0.70   # textes courts : seuil plus bas
    elif words < 200:
        return 0.80   # seuil actuel
    else:
        return 0.85   # textes longs : exiger plus de similarité
```

---

### 2.6 Monitoring cron — améliorer check_cron_health.py

**Problème actuel**
`check_cron_health.py` s'exécute toutes les 10 minutes mais son mode d'alerte n'est pas documenté. Il est difficile de savoir si un job cron a silencieusement échoué.

**Solution recommandée**
Ajouter un fichier `data/cron_health.json` avec horodatage par job, et exposer un endpoint `/api/health/cron` dans le viewer :

```json
{
  "flux_watcher": {
    "last_run": "2026-03-17T14:35:00Z",
    "last_success": "2026-03-17T14:35:00Z",
    "articles_added_last_run": 3,
    "consecutive_failures": 0
  },
  "enrich_entities": {
    "last_run": "2026-03-17T02:00:00Z",
    "articles_enriched_today": 47,
    "consecutive_failures": 0
  }
}
```

Un badge "santé du pipeline" serait visible dans la sidebar du viewer.

---

### 2.7 Cache API — TTL différencié par type de contenu

**Problème actuel**
`utils/cache.py` applique un TTL uniforme de 24h à toutes les réponses API. Un résumé d'article n'a pas la même durée de vie qu'une réponse NER.

**Solution recommandée**
TTL configurables par type de requête :

```python
CACHE_TTL = {
    "summary": 86400,      # 24h — stable
    "entities": 604800,    # 7 jours — très stable
    "sentiment": 604800,   # 7 jours — très stable
    "synthesis": 3600,     # 1h — peut évoluer avec de nouveaux articles
    "geocode": 2592000,    # 30 jours — quasi-permanent
}
```

---

### 2.8 API Client — support du mode batch natif Claude

**Problème actuel**
`utils/api_client.py` appelle Claude en mode synchrone article par article. L'API Anthropic propose un **Batch API** (jusqu'à 10 000 requêtes simultanées) avec 50% de réduction de coût.

**Solution recommandée**
Implémenter `ClaudeClient.generate_batch()` dans `api_client.py` pour les scripts nocturnes (`enrich_entities.py`, `enrich_sentiment.py`) :

```python
class ClaudeClient:
    def generate_batch(self, prompts: list[str], model: str = None) -> list[str]:
        """Utilise l'API Batch Anthropic pour les enrichissements nocturnes."""
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)

        requests = [
            {"custom_id": str(i), "params": {"model": model or self.batch_model,
             "max_tokens": 1024, "messages": [{"role": "user", "content": p}]}}
            for i, p in enumerate(prompts)
        ]
        batch = client.messages.batches.create(requests=requests)
        # polling + retour des résultats
        ...
```

Économies estimées : 30-50% sur les coûts Claude pour les enrichissements batch.

---

## 3. Nouvelles fonctionnalités recommandées

### 3.1 Recherche sémantique par embeddings (PRIORITÉ HAUTE)

**Contexte**
La recherche actuelle est lexicale (regex + entités exactes). En veille informationnelle, la recherche par sens ("articles sur la régulation de l'IA en Europe" sans ces mots-clés exacts) est une fonctionnalité centrale.

**Proposition**
Ajouter un module `utils/embeddings.py` utilisant l'API Claude (embeddings) ou un modèle local léger (sentence-transformers `paraphrase-multilingual-MiniLM`) :

```python
# utils/embeddings.py
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')  # 420MB, local

def embed_articles(articles: list[dict]) -> np.ndarray:
    texts = [a.get("Résumé", "") for a in articles]
    return model.encode(texts, batch_size=32)

def semantic_search(query: str, articles: list[dict], top_k: int = 10):
    q_emb = model.encode([query])
    a_embs = embed_articles(articles)
    scores = cosine_similarity(q_emb, a_embs)[0]
    return sorted(zip(scores, articles), reverse=True)[:top_k]
```

**Intégration UI** : onglet "Recherche sémantique" dans `SearchOverlay.jsx` avec un toggle lexical/sémantique.

**Index** : stocker les embeddings dans `data/embeddings_index.npy` (1 vecteur × 384 dims × float32 = ~1.5KB/article, soit ~150MB pour 100 000 articles).

---

### 3.2 Détection de contradictions entre sources (PRIORITÉ HAUTE)

**Contexte**
En veille, détecter quand deux sources affirment des faits opposés sur le même événement est une fonctionnalité à haute valeur (journalisme de données, fact-checking).

**Proposition**
Un script `scripts/detect_contradictions.py` basé sur les entités partagées + analyse sentiment contradictoire :

```python
# Logique : deux articles parlant des mêmes entités (ORG+GPE ou PERSON+ORG)
# avec des sentiments opposés (positif vs négatif, score_sentiment ≥ 3 écart)
# ET publiés dans la même fenêtre de 48h

def find_contradictions(articles: list[dict]) -> list[dict]:
    contradictions = []
    for a1, a2 in combinations(articles, 2):
        shared = shared_entities(a1, a2)
        if len(shared) >= 2 and sentiment_gap(a1, a2) >= 3:
            contradictions.append({
                "article_1": a1["URL"],
                "article_2": a2["URL"],
                "shared_entities": shared,
                "sentiment_gap": sentiment_gap(a1, a2),
                "sources": [a1["Sources"], a2["Sources"]]
            })
    return contradictions
```

**Output** : `data/contradictions.json`, endpoint `/api/contradictions`, badge dans le viewer.

---

### 3.3 Suivi narratif des événements (PRIORITÉ HAUTE)

**Contexte**
Actuellement, les articles sont analysés individuellement. Un système de veille professionnel doit pouvoir suivre l'**évolution d'un événement dans le temps** : comment une histoire se développe, quels acteurs apparaissent ou disparaissent.

**Proposition**
Un module `utils/narrative_tracker.py` qui regroupe les articles par événement :

```python
class NarrativeTracker:
    """
    Identifie et suit les "fils narratifs" — groupes d'articles
    couvrant le même événement sur une fenêtre glissante.

    Méthode : clustering par entités partagées + fenêtre temporelle.
    Résultat : data/narratives.json avec évolution chronologique.
    """

    def detect_narratives(self, articles: list[dict], window_days: int = 14) -> list[dict]:
        # 1. Grouper par entités communes (≥ 2 entités partagées)
        # 2. Filtrer par fenêtre temporelle
        # 3. Trier chronologiquement pour reconstituer l'arc narratif
        # 4. Générer un résumé de progression via AI
        ...
```

**UI** : composant `NarrativeTimeline.jsx` — vue linéaire d'un événement avec les articles dans l'ordre chronologique, entités clés, évolution du ton éditorial.

---

### 3.4 Analyse de la diversité des sources (PRIORITÉ MOYENNE)

**Contexte**
En veille stratégique, il est important de savoir si l'information collectée sur un sujet provient d'une seule chambre d'écho ou de sources variées (géographie, ligne éditoriale, langue).

**Proposition**
Un endpoint et un composant de visualisation de la diversité :

```python
# utils/source_diversity.py

def compute_diversity_score(articles: list[dict]) -> dict:
    sources = [a["Sources"] for a in articles]
    return {
        "nb_sources_uniques": len(set(sources)),
        "concentration_herfindahl": herfindahl_index(sources),  # 0=diversifié, 1=monopole
        "score_global": diversity_score(sources),
        "repartition_geographique": geo_breakdown(sources),
        "repartition_editoriale": editorial_breakdown(sources),  # via sources_credibility.json
        "couverture_opinion_vs_factuel": tone_breakdown(articles)
    }
```

**UI** : gauge de diversité dans `SourceBiasPanel.jsx`, alerte si score Herfindahl > 0.5 (concentration forte).

---

### 3.5 Résumés progressifs (incremental summarization)

**Contexte**
Pour un topic suivi sur plusieurs semaines, générer un nouveau résumé complet chaque jour est coûteux en tokens. La technique d'**incremental summarization** consiste à conserver un "résumé courant" et à le mettre à jour avec les nouvelles informations uniquement.

**Proposition**
Un fichier `data/topic_summaries/<topic>.json` mis à jour quotidiennement :

```json
{
  "topic": "Régulation IA en Europe",
  "last_updated": "2026-03-17",
  "summary_running": "Résumé consolidé des 30 derniers jours...",
  "new_facts_today": ["Adoption du règlement X", "Déclaration de Y"],
  "articles_count": 127
}
```

L'IA est appelée uniquement avec : résumé existant + nouveaux articles du jour → mise à jour différentielle. Économise 80-90% des tokens sur les topics à forte volumétrie.

---

### 3.6 Export Obsidian avec liens bidirectionnels (PRIORITÉ MOYENNE)

**Contexte**
Le projet possède déjà une intégration Obsidian (d'après les commits récents). L'amélioration logique est de générer des **liens `[[wikilinks]]` bidirectionnels** entre notes — une fonctionnalité centrale d'Obsidian pour la gestion des connaissances.

**Proposition**
Enrichir `scripts/articles_rss_to_markdown.py` pour générer des liens croisés :

```markdown
---
title: "OpenAI annonce GPT-5"
date: 2026-03-17
entities:
  - "[[OpenAI]]"
  - "[[Sam Altman]]"
  - "[[GPT-5]]"
tags: [IA, LLM, OpenAI]
---

[[Sam Altman]], PDG d'[[OpenAI]], a annoncé aujourd'hui...

## Articles liés
- [[2026-03-15 — Microsoft intègre GPT-4]]  (entités communes: OpenAI, LLM)
- [[2026-03-10 — Régulation IA en Europe]] (entités communes: IA, OpenAI)
```

Chaque entité NER devient une note Obsidian liée. Un graphe de connaissances se construit naturellement.

---

### 3.7 Alertes de silence (absence detection)

**Contexte**
En veille, l'absence soudaine d'articles sur un topic habituellement actif est aussi significative que leur présence. Ex : une source qui cesse de publier, un sujet qui disparaît de l'agenda médiatique.

**Proposition**
Ajouter dans `trend_detector.py` la détection de silences :

```python
def detect_silence(entity: str, articles: list[dict], baseline_days: int = 7) -> dict | None:
    recent_24h = count_mentions(entity, articles, hours=24)
    baseline_avg = avg_daily_mentions(entity, articles, days=baseline_days)

    if baseline_avg >= 3 and recent_24h == 0:
        return {
            "type": "silence",
            "entity": entity,
            "baseline_avg": baseline_avg,
            "hours_since_last_mention": hours_since_last_mention(entity, articles),
            "severity": "élevé" if baseline_avg >= 10 else "modéré"
        }
```

**Output** : les alertes de type `silence` dans `data/alertes.json`, visualisation distincte dans `AlertsPanel.jsx`.

---

### 3.8 Profil de veille personnalisé (watchlist intelligente)

**Contexte**
Le composant `EntityWatchPanel.jsx` existe mais est statique (liste d'entités à surveiller). Une watchlist intelligente calculerait un score de pertinence personnalisé en fonction des interactions de l'utilisateur.

**Proposition**
Un fichier `data/user_profile.json` qui enregistre les signaux implicites :

```json
{
  "interactions": {
    "PERSON:Sam Altman": {"views": 15, "reports_generated": 3, "last_viewed": "2026-03-17"},
    "ORG:Mistral AI": {"views": 8, "reports_generated": 1}
  },
  "preferred_topics": ["IA", "LLM", "Régulation"],
  "preferred_sources": ["Le Monde", "Wired", "MIT Tech Review"]
}
```

Le score de l'article serait ajusté par `scoring.py` avec un multiplicateur de pertinence personnelle (0.8–1.5×), remontant les articles sur les topics d'intérêt.

---

### 3.9 Pipeline de fact-checking assisté

**Contexte**
Pour les articles avec des affirmations chiffrées ou des citations, un pipeline de vérification basique peut signaler les statistiques inhabituelles ou les citations non sourcées.

**Proposition**
Un script `scripts/flag_claims.py` qui extrait et marque les affirmations à vérifier :

```python
CLAIM_PATTERNS = [
    r'\d+[\s]?%',           # pourcentages
    r'\d+[\s]?(milliards|millions)',  # montants
    r'"[^"]{20,}"',         # citations directes
    r'selon\s+[A-Z][a-z]+', # attribution floue
]

def extract_claims(article: dict) -> list[dict]:
    claims = []
    for pattern in CLAIM_PATTERNS:
        matches = re.findall(pattern, article["Résumé"])
        for m in matches:
            claims.append({"claim": m, "source": article["Sources"], "url": article["URL"]})
    return claims
```

**Output** : champ `claims` dans les articles, badge "À vérifier" dans l'interface.

---

### 3.10 API REST publique documentée (OpenAPI/Swagger)

**Contexte**
Le viewer Flask possède 50+ endpoints mais sans documentation formelle. Une API documentée permettrait des intégrations externes (Make/Zapier, scripts tiers, apps mobiles natives).

**Proposition**
Ajouter `flask-openapi3` ou `flask-restx` :

```python
# viewer/app.py
from flask_restx import Api, Resource

api = Api(app, version='4.2', title='WUDD.ai API',
          description='API de veille informationnelle',
          doc='/api/docs')

@api.route('/api/articles/top')
class TopArticles(Resource):
    @api.doc(params={'flux': 'Nom du flux (optionnel)', 'days': 'Fenêtre temporelle en jours'})
    def get(self):
        """Retourne les top 10 articles par score de pertinence."""
        ...
```

Documentation interactive accessible sur `http://localhost:5050/api/docs`.

---

### 3.11 Intégration RSS sortant (Atom personnalisé par topic)

**Contexte**
L'export Atom existe (`utils/exporters/atom_feed.py`) mais génère un seul feed par flux. Un feed Atom **filtré par entité ou par topic** permettrait de s'abonner à des veilles très ciblées depuis n'importe quel lecteur RSS.

**Proposition**
Endpoint dynamique : `/api/export/atom?entity=OpenAI&type=ORG&days=7`

```python
@app.route('/api/export/atom')
def atom_by_entity():
    entity = request.args.get('entity')
    entity_type = request.args.get('type', 'ORG')
    days = int(request.args.get('days', 7))

    articles = entity_index.get_recent_articles(entity, entity_type, days)
    return generate_atom_feed(articles, title=f"WUDD.ai — {entity}")
```

---

### 3.12 Détection automatique de nouvelles sources (source discovery)

**Contexte**
Aujourd'hui les sources RSS sont ajoutées manuellement. En veille professionnelle, la découverte automatique de nouvelles sources pertinentes est un avantage compétitif majeur.

**Proposition**
Un script `scripts/discover_sources.py` qui analyse les URLs citées dans les résumés :

```python
def discover_new_sources(articles: list[dict], known_domains: set[str]) -> list[str]:
    """
    Extrait les domaines cités dans les résumés mais absents de l'OPML.
    Filtre par fréquence (≥ 3 citations) et disponibilité RSS (/feed, /rss, /atom).
    """
    cited_domains = Counter(extract_domains_from_summaries(articles))
    candidates = [
        domain for domain, count in cited_domains.items()
        if count >= 3 and domain not in known_domains
    ]
    return [d for d in candidates if has_rss_feed(d)]
```

**UI** : onglet "Sources suggérées" dans `SettingsPanel.jsx` avec bouton d'ajout en un clic.

---

### 3.13 Scoring de fraîcheur des sources

**Contexte**
Certaines sources RSS publient irrégulièrement ou tombent en hibernation. Une source qui n'a pas publié depuis 30 jours devrait être signalée dans les paramètres.

**Proposition**
Ajouter dans `utils/source_credibility.py` un score de fraîcheur dynamique :

```python
def freshness_score(source: str, articles: list[dict]) -> dict:
    source_articles = [a for a in articles if a["Sources"] == source]
    if not source_articles:
        return {"score": 0, "status": "inactif", "last_article": None}

    dates = [parse_article_date(a) for a in source_articles]
    last_pub = max(dates)
    days_since = (datetime.now() - last_pub).days

    return {
        "score": max(0, 100 - days_since * 2),
        "status": "actif" if days_since < 7 else "lent" if days_since < 30 else "inactif",
        "articles_30j": sum(1 for d in dates if (datetime.now() - d).days <= 30)
    }
```

---

### 3.14 Génération de synthèses comparatives multi-sources

**Contexte**
Pour un événement couvert par plusieurs sources, générer automatiquement une synthèse qui **compare les angles de traitement** ("Le Monde insiste sur X, Libération sur Y, Les Échos sur Z").

**Proposition**
Un endpoint `/api/synthesize/comparative` et un prompt spécialisé dans `docs/PROMPTS.md` :

```
Tu es un analyste de presse. Voici {N} articles de sources différentes sur le même événement.
Compare leur angle de traitement :
1. Quels faits sont mentionnés par toutes les sources ?
2. Quels faits sont spécifiques à une seule source ?
3. Quelles divergences d'interprétation observes-tu ?
4. Quelle source semble la plus complète ?
Réponds en français, de façon synthétique et factuelle.
```

**UI** : bouton "Analyse comparative" dans `EntityArticlePanel.jsx` quand ≥ 3 articles partagent une entité commune.

---

## 4. Tableau de priorisation

| # | Fonctionnalité | Impact | Complexité | Priorité |
|---|---|---|---|---|
| 2.1 | Migration DuckDB | Performance majeure | Moyenne | **P1** |
| 2.2 | Index événementiel | Latence données | Faible | **P1** |
| 3.1 | Recherche sémantique | UX majeure | Haute | **P1** |
| 3.7 | Alertes de silence | Valeur veille | Faible | **P1** |
| 2.8 | Batch API Claude | Coût API | Moyenne | **P1** |
| 3.2 | Détection contradictions | Valeur éditoriale | Moyenne | **P2** |
| 3.3 | Suivi narratif | Valeur veille | Haute | **P2** |
| 3.5 | Résumés progressifs | Coût API | Moyenne | **P2** |
| 3.6 | Export Obsidian wiklinks | Intégration PKM | Faible | **P2** |
| 2.6 | Monitoring cron enrichi | Opérationnel | Faible | **P2** |
| 3.10 | API OpenAPI/Swagger | Intégration | Faible | **P3** |
| 3.11 | Atom par entité | Export | Faible | **P3** |
| 3.12 | Source discovery | Automatisation | Moyenne | **P3** |
| 3.4 | Diversité sources | Analyse | Moyenne | **P3** |
| 3.8 | Profil personnalisé | UX | Haute | **P3** |
| 3.9 | Flag claims | Editorial | Moyenne | **P4** |
| 3.13 | Score fraîcheur sources | Monitoring | Faible | **P4** |
| 3.14 | Synthèse comparative | AI | Faible | **P4** |
| 2.3 | Circuit breaker enrichi | Résilience | Faible | **P4** |
| 2.5 | Jaccard adaptatif | Qualité | Très faible | **P4** |

**Légende** : P1 = implémenter dès maintenant / P2 = prochain sprint / P3 = backlog / P4 = si ressources disponibles

---

## 5. Axes à éviter ou différer

### 5.1 Base de données relationnelle (PostgreSQL, MySQL)
Le passage à une vraie SGBDR serait disproportionné pour un usage mono-utilisateur. DuckDB couvre 95% des besoins analytiques sans la complexité opérationnelle d'un serveur de base de données.

### 5.2 Topic modeling par ML (LDA, BERTopic)
Ces modèles nécessitent des dépendances lourdes (scikit-learn, transformers ~1-4GB) et un corpus suffisant (>1000 articles). L'approche actuelle basée sur les entités NER + `thematiques_societales.json` est plus légère et contrôlable.

### 5.3 Interface multi-utilisateurs avec authentification
L'outil est conçu pour un usage personnel (veilleur unique). Ajouter une gestion d'utilisateurs introduirait une complexité architecturale significative sans valeur immédiate.

### 5.4 Modèles de langage locaux (Ollama, llama.cpp)
Sauf contrainte de souveraineté des données, les APIs EurIA (données hébergées en Suisse) et Claude offrent un meilleur rapport qualité/complexité que l'autohébergement de LLMs.

---

*Rapport généré par Claude Sonnet 4.6 sur la base d'une analyse complète du codebase WUDD.ai v4.2 (37 scripts, 23 modules utils, 50+ endpoints Flask, 30 composants React, 2 020 lignes de tests).*
