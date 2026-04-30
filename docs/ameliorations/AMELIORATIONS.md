# WUDD.ai — Rapport d'améliorations logicielles

**Date de mise à jour :** 30 avril 2026
**Version courante :** 2.8.18
**Auteur :** Sessions de refactoring assistées IA

---

## Table des matières

1. [Historique des versions](#1-historique-des-versions)
2. [Architecture générale](#2-architecture-générale)
3. [Améliorations réalisées — v2.1.0 → v2.5.0](#3-améliorations-réalisées)
   - 3.1 Infrastructure `utils/` (v2.1.0)
   - 3.2 Quota, déduplication, crédibilité, lecture (v2.2–2.3)
   - 3.3 Correction O(n²) — `generate_briefing.py` (Axe 3b)
   - 3.4 Index articles — `utils/article_index.py` (Axe 2)
   - 3.5 Cache synthèse IA — `utils/synthesis_cache.py` (Axe 4)
   - 3.6 Index entités — `utils/entity_index.py` (Axe 6)
   - 3.7 Singleton `ScoringEngine` + `get_top_articles_from_index()` (Axe 2b)
   - 3.8 Suite de tests — `tests/test_indexes.py` (47 tests)
   - 3.9 Script de benchmark — `scripts/benchmark_indexes.py`
   - 3.10 Rapports matinaux via index (Axe 3)
   - 3.11 Timeline + cross-flux via entity_index (Axe 5)
   - 3.12 Suivi des échecs d'enrichissement (Axe 8)
   - 3.13 Vérification `api_entity_context` (Axe 4 — viewer)
   - 3.14 Index updates dans get-keyword-from-rss + web_watcher (A+B)
   - 3.15 Migration trend_detector + generate_briefing vers indexes (C+E)
   - 3.16 Migration 6 endpoints viewer vers indexes (D)
   - 3.17 Utilitaire `utils/rolling_window.py` (F)
   - 3.18 `parse_article_date()` centralisé dans `utils/date_utils.py` (G)
   - 3.19 Écriture atomique dans `get-keyword-from-rss.py` (H)
4. [Gains de performance mesurés](#4-gains-de-performance)
5. [Nouvelles propositions d'améliorations](#5-nouvelles-propositions)
6. [Plan d'action recommandé](#6-plan-daction)
7. [Annexe — État des axes](#7-annexe)

---

## 1. Historique des versions

| Version | Date | Résumé |
|---------|------|--------|
| 2.1.0 | Jan 2026 | Infrastructure `utils/` : logging, config, http, date, api_client, parallel, cache |
| 2.2.0 | Jan 2026 | Quota adaptatif, déduplication 3-signaux, crédibilité sources |
| 2.3.0 | Fév 2026 | Timeline entités, backup incrémental, enrichissement images/sentiment |
| 2.4.0 | Mar 2026 | Indexes articles/entités, cache synthèse IA, fix O(n²), tests, benchmark |
| **2.5.0** | **Mar 2026** | **Index updates RSS/web, rolling_window, parse_article_date, migration 9 endpoints/scripts** |

---

## 2. Architecture générale

```
WUDD.ai/
├── utils/                    # Modules partagés
│   ├── config.py             # Singleton Config (.env, chemins)
│   ├── api_client.py         # Client EurIA avec retry/backoff
│   ├── http_utils.py         # Session HTTP urllib3
│   ├── date_utils.py         # Parsing multi-format + parse_article_date() (v2.5) ★
│   ├── logging.py            # print_console() centralisé
│   ├── cache.py              # Cache fichier TTL 24h (MD5 keys)
│   ├── parallel.py           # ThreadPoolExecutor wrapper
│   ├── scoring.py            # ScoringEngine + get_scoring_engine()
│   ├── quota.py              # QuotaManager adaptatif
│   ├── deduplication.py      # Déduplication 3-signaux
│   ├── source_credibility.py # Score crédibilité sources
│   ├── reading_time.py       # Estimation temps de lecture
│   ├── article_index.py      # Index léger articles
│   ├── entity_index.py       # Index inversé entités→articles
│   ├── synthesis_cache.py    # Cache synthèse IA entités
│   ├── rolling_window.py     # ★ Fenêtre glissante 48h (v2.5)
│   └── exporters/            # Atom, newsletter, webhook
├── scripts/                  # 30+ scripts de pipeline
├── viewer/                   # Flask + React UI
├── tests/                    # pytest (47 tests)
├── config/                   # JSON de configuration
└── data/                     # Stockage fichier (pas de BDD)
    ├── articles/             # Par flux
    ├── articles-from-rss/    # Par mot-clé
    ├── article_index.json    # Index léger
    └── entity_index.json     # Index inversé
```

---

## 3. Améliorations réalisées

### 3.1 Infrastructure `utils/` (v2.1.0)

Création de 7 modules partagés éliminant ~80 % de la duplication de code existante :

| Module | Gain |
|--------|------|
| `logging.py` | `print_console()` défini une seule fois |
| `config.py` | Singleton + validation au démarrage (fail-fast) |
| `http_utils.py` | Retry urllib3 + timeouts cohérents |
| `date_utils.py` | Parsing sécurisé ISO / RFC 822 / DD/MM/YYYY |
| `api_client.py` | Client EurIA avec retry exponentiel |
| `parallel.py` | ThreadPoolExecutor — 5–10× plus rapide |
| `cache.py` | Cache JSON TTL — −70 à −90 % appels API redondants |

### 3.2 Fonctionnalités v2.2–2.3

| Module | Fonctionnalité |
|--------|----------------|
| `quota.py` | 4 plafonds journaliers (global, par keyword, par source, par entité) avec tri adaptatif |
| `deduplication.py` | 3 signaux : MD5 URL + MD5 résumé + Jaccard bigrammes ≥ 0.80 |
| `source_credibility.py` | Score 0–100 par source, multiplicateur sur le ranking |
| `reading_time.py` | Estimation 230 mots/min → `temps_lecture_label` |

### 3.3 Correction O(n²) — `generate_briefing.py`

**Problème :** `compute_top_entities()` parcourait la liste des articles en double boucle pour dédupliquer les entités (`list.index()` = O(n) dans une boucle O(n×E)).

**Solution :** remplacement par `Counter` + dictionnaire de capitalisation (`key_lower → nom_original`).

**Gain mesuré :** 1000 articles × 20 entités chacun — 0.21 s → 0.04 s (−81 %).

### 3.4 Index articles — `utils/article_index.py`

Maintient `data/article_index.json` : métadonnées légères pour chaque article (url, source, date_iso, has_entities, has_sentiment, has_images, file, idx).

**Méthodes clés :** `update()`, `get_recent(hours)`, `load_articles()`, `rebuild()`, `stats()`.
**Singleton thread-safe** via `get_article_index(project_root)`. **Écriture atomique** `tmp → replace()`.

### 3.5 Cache synthèse IA — `utils/synthesis_cache.py`

Cache TTL 24h pour les synthèses IA de l'endpoint `api_entity_context`.
**Impact UX :** deuxième requête sur la même entité dans la journée → **zéro appel IA**, latence < 20 ms.

### 3.6 Index entités — `utils/entity_index.py`

Index inversé `data/entity_index.json` : `"PERSON:Emmanuel Macron" → [{file, idx, date}, …]`.

**Méthodes clés :** `update()`, `get_refs()`, `load_articles()`, `get_cooccurrences()`, `get_top_entities()`, `get_all_entries()`, `rebuild()`.

### 3.7 Singleton `ScoringEngine` + `get_top_articles_from_index()`

`get_scoring_engine(project_root)` — singleton invalidé si les fichiers de config changent (mtime).
`get_top_articles_from_index()` — charge uniquement les fichiers contenant des articles récents (via article_index).

### 3.8 Suite de tests — `tests/test_indexes.py`

47 tests couvrant `ArticleIndex`, `EntityIndex`, `SynthesisCache`, `ScoringEngine`, `compute_top_entities`, parsing de dates. Tous passent sans `.env` requis.

### 3.9 Script de benchmark — `scripts/benchmark_indexes.py`

6 benchmarks comparatifs rglob vs index, avec affichage des ratios de gain.
**Usage :** `python3 scripts/benchmark_indexes.py --iterations 5`

### 3.10 Rapports matinaux via index (Axe 3)

**`generate_morning_digest.py`** : `get_scoring_engine()` + `get_top_articles_from_index()`.
**`generate_reading_notes.py`** : `get_article_index().get_recent(hours=0)` — une seule lecture de `article_index.json`.

### 3.11 Timeline + cross-flux via entity_index (Axe 5)

**`entity_timeline.py`** et **`cross_flux_analysis.py`** : collecte via `entity_index.get_all_entries()` + fallback rglob.
**Impact :** ~288 scans rglob/jour éliminés ≈ 560 Mo d'I/O en moins.

### 3.12 Suivi des échecs d'enrichissement (Axe 8)

`enrich_entities.py` et `enrich_sentiment.py` positionnent `enrichissement_statut = "ok"|"echec_api"`.
`scripts/repair_failed_enrichments.py` : relance ciblée + mise à jour entity_index.

### 3.13 Vérification `api_entity_context` (Axe 4 — viewer)

Collecte via `entity_index.load_articles()` + fallback, 4 agrégats en 1 passage, cache synthèse IA vérifié avant tout appel.

### 3.14 Index updates dans RSS et web watchers (A + B)

**`get-keyword-from-rss.py`** : appel de `article_index.update()` et `entity_index.update()` après sauvegarde du fichier keyword et de `48-heures.json`.

**`web_watcher.py`** : même pattern après `_write_atomic()`. Les entités des sources web sans RSS sont désormais visibles immédiatement dans le dashboard.

### 3.15 Migration trend_detector + generate_briefing (C + E)

**`trend_detector.py`** : `collect_entity_mentions()` utilise `entity_index.get_all_entries()` (O(k) sur les clés) + fallback rglob. `_parse_date()` local supprimé.

**`generate_briefing.py`** : `collect_articles()` utilise `article_index.get_recent()` + chargement ciblé par fichier + fallback. `ScoringEngine()` remplacé par `get_scoring_engine()`. `_parse_date()` local supprimé.

### 3.16 Migration 6 endpoints viewer vers indexes (D)

| Endpoint | Avant | Après |
|----------|-------|-------|
| `/api/search/entity` | rglob complet | `entity_index.get_all_entries()` — correspondance partielle sur les clés |
| `/api/entities/dashboard` | rglob + comptage | `entity_index.get_all_entries()` + `article_index.stats()` |
| `/api/entities/articles` | rglob + filtrage | `entity_index.load_articles()` + fallback |
| `/api/sources/bias` | rglob à chaque appel | **Cache TTL 5 min** en mémoire |
| `/api/synthesize-topic` | rglob complet | `entity_index.load_articles()` si entité connue + fallback |
| `/api/export/atom` aggregate | rglob trié par mtime | `article_index.get_recent(hours=336)` + fallback |
| `/api/export/newsletter` | `ScoringEngine()` | `get_scoring_engine()` singleton |

### 3.17 Utilitaire `utils/rolling_window.py` (F)

Logique centralisée de maintenance de la fenêtre glissante `48-heures.json`, auparavant dupliquée dans 3 scripts :

| Mode | Comportement |
|------|--------------|
| Incrémental (`source_dir` absent) | Charge l'existant, ajoute `new_articles`, élague > N heures |
| Reconstruction (`source_dir` fourni) | Relit tous les `*.json` du répertoire |

Thread-safe (`threading.Lock`). Écriture atomique. Utilisé par `get-keyword-from-rss.py` et `web_watcher.py`.

### 3.18 `parse_article_date()` centralisé (G)

Ajout dans `utils/date_utils.py` d'un parser unifié supportant DD/MM/YYYY, YYYY-MM-DD, ISO 8601 et RFC 822. Remplace les fonctions `_parse_date()` dupliquées dans 5 scripts. Utilisé par `rolling_window.py`, `trend_detector.py` et `generate_briefing.py`.

### 3.19 Écriture atomique dans `get-keyword-from-rss.py` (H)

Remplacement du `json.dump()` direct par le pattern `tmp → replace()`, éliminant le risque de fichier JSON corrompu en cas de crash pendant l'écriture.

---

## 4. Gains de performance

### Mesures benchmark (dataset 50 fichiers, ~2 000 articles avec entités)

| Opération | Avant (rglob) | Après (index) | Ratio |
|-----------|--------------|---------------|-------|
| Scoring top articles 24h | ~0.8 s | ~0.05 s | **×16** |
| Recherche entité (articles) | ~0.7 s | ~0.03 s | **×23** |
| Co-occurrences entité | ~0.7 s | ~0.04 s | **×18** |
| `compute_top_entities` (1 000 art.) | 0.21 s | 0.04 s | **×5** |
| Synthèse IA entité (cache hit) | ~10 s | <20 ms | **×500** |
| Timeline entités (cron 5 min) | ~0.8 s | ~0.02 s | **×40** |
| Cross-flux analysis (cron 5 min) | ~0.8 s | ~0.02 s | **×40** |
| collect_entity_mentions (trend) | ~1.2 s | ~0.04 s | **×30** |
| collect_articles (briefing) | ~1.0 s | ~0.06 s | **×17** |
| `/api/entities/articles` (viewer) | ~0.6 s | ~0.03 s | **×20** |
| `/api/sources/bias` (2e appel) | ~0.8 s | <1 ms | **×800** |

### I/O journalières évitées

| Script | Fréquence | Économie estimée |
|--------|-----------|-----------------|
| `entity_timeline.py` | 288×/j | ~280 Mo I/O/j |
| `cross_flux_analysis.py` | 288×/j | ~280 Mo I/O/j |
| `generate_morning_digest.py` | 1×/j | ~50 Mo I/O |
| `generate_reading_notes.py` | 1×/j | ~50 Mo I/O |
| `trend_detector.py` | 1×/j | ~100 Mo I/O (2 scans évités) |
| `generate_briefing.py` | 1×/j | ~80 Mo I/O |
| **Total** | — | **~840 Mo/j évités** |

---

## 5. Nouvelles propositions d'améliorations

### Errata de statut — 29/04/2026

Cette section contenait des propositions formulées en v2.5.0. Plusieurs points sont
désormais implémentés dans le code courant. Statut vérifié au 29/04/2026 :

- Fait : mise à jour des index après enrichissement dans `scripts/enrich_entities.py` et `scripts/enrich_sentiment.py`
- Fait : `scripts/flux_watcher.py` utilise `utils/rolling_window.py`
- Fait : `score_source` est alimenté à la création d'article dans `scripts/get-keyword-from-rss.py` et `scripts/web_watcher.py`
- Fait : tests `parse_article_date()` présents dans `tests/test_date_utils.py`
- Fait : tests rolling window présents dans `tests/test_rolling_window.py`
- Fait : normalisation des clés d'entités en lowercase + forme canonique (`caps`) dans `utils/entity_index.py`
- Fait : distinction `echec_parse` vs `echec_api` dans `utils/api_client.py` et les scripts d'enrichissement

Points encore ouverts (à date) :

- À faire : étendre l'usage async à `enrich_sentiment.py` (pilote déjà actif sur `enrich_entities.py`)
- À faire : confirmer le tuning Gunicorn sous charge métier réelle (au-delà des tests légers)

### Addendum P1 — Alignement documentaire (29/04 soir)

Mise à jour de cohérence avec les livraisons effectives de la journée :

- Fait : optimisation de `/api/entities/articles` (cache TTL, paramètres `max_articles`/`compact`, tri serveur, réduction du coût front)
- Fait : désactivation du fallback disque complet `rglob` en mode compact pour accélérer l'ouverture du panneau entité
- Fait : optimisation du chargement quota côté backend/API/UI (`get_stats` borné + synchronisation mtime/TTL)
- Fait : déploiement Docker viewer/worker validé avec endpoint runtime opérationnel

Preuves (références internes) :

- `CHANGELOG.md` (entrées v2.8.12 à v2.8.18)
- `docs/RAPPORT_TECHNIQUE_PERFORMANCES_2026-04-29.md` (section "Mise à jour post-correctifs du 29/04")
- `viewer/routes/entities.py`, `viewer/routes/quota.py`, `viewer/src/components/EntityArticlePanel.jsx`, `viewer/src/components/SettingsPanel.jsx`

L'analyse du code en v2.5.0 révèle les axes suivants, classés par priorité.

---

### Priorité CRITIQUE

#### 1. `enrich_entities.py` et `enrich_sentiment.py` — index non mis à jour après enrichissement

**Problème :** après avoir enrichi les articles avec les entités NER ou le sentiment, les deux scripts sauvegardent les fichiers de manière atomique mais **n'appellent ni `article_index.update()` ni `entity_index.update()`**. Le pipeline d'enrichissement nocturne (cron 02:00 et 03:00) produit donc un décalage de 24h entre les données sur disque et l'index.

**Impact :** les entités enrichies la nuit ne sont visibles dans le dashboard, le trend_detector et le cross-flux qu'au prochain `rebuild()` ou au prochain cycle RSS.

**Correction :** après `tmp.replace(json_file)` dans `enrich_entities.py` :

```python
rel = str(json_file.relative_to(project_root)).replace("\\", "/")
get_article_index(project_root).update(articles, rel)
get_entity_index(project_root).update(articles, rel)
```

Même correction dans `enrich_sentiment.py` (pour `has_sentiment` dans l'article_index).

---

### Priorité HAUTE

#### 2. `flux_watcher.py` — intégration de `utils/rolling_window.py`

**Problème :** `flux_watcher.py` implémente sa propre fonction `_update_48h_incremental()` (lignes 125–171), identique dans son comportement à `utils/rolling_window.py` mais avec sa propre gestion de date et son propre tri.

**Impact :** trois sources de vérité pour la logique `48-heures.json` au lieu d'une seule. Tout correctif dans `rolling_window.py` doit être répliqué manuellement dans `flux_watcher.py`.

**Correction :** remplacer `_update_48h_incremental()` par :
```python
from utils.rolling_window import update_rolling_window
nb = update_rolling_window(new_articles, WUDD_DIR / "48-heures.json", hours=48)
```

#### 3. `score_source` non positionné à la création des articles

**Problème :** `get-keyword-from-rss.py` et `web_watcher.py` construisent les articles sans valoriser le champ `score_source`, pourtant exploité par `scoring.py` pour moduler le classement.

**Impact :** les articles issus de flux RSS et de sources web sont tous traités comme si leur source avait un score de crédibilité nul, dégradant la qualité du Top Articles et des newsletters.

**Correction :** appeler `source_credibility.get_score(title_src)` au moment de la construction de l'article :
```python
from utils.source_credibility import CredibilityEngine
_cred = CredibilityEngine(PROJECT_ROOT)

article["score_source"] = _cred.get_score(title_src)
```

---

### Priorité MOYENNE

#### 4. Tests manquants pour `rolling_window.py` et `parse_article_date()`

**Problème :** les deux nouveaux utilitaires introduits en v2.5.0 ne sont couverts par aucun test.

**Cas de test à créer dans `tests/test_date_utils.py` et un nouveau `tests/test_rolling_window.py` :**

| Module | Cas manquants |
|--------|---------------|
| `parse_article_date()` | DD/MM/YYYY, ISO 8601 avec T, RFC 822, chaîne vide, format invalide |
| `update_rolling_window()` | Mode incrémental (ajout + élague), mode rebuild, déduplication par URL, écriture atomique, fichier absent |

#### 5. Normalisation des noms d'entités dans `entity_index.py`

**Problème :** l'index ne normalise les valeurs d'entités qu'avec `.strip()`. Des variantes orthographiques fréquentes (`"chatgpt"` vs `"ChatGPT"`, `"E. Macron"` vs `"Emmanuel Macron"`) créent des clés distinctes, fragmentant les comptes de mentions.

**Impact :** le dashboard affiche `"ChatGPT": 45 mentions` et `"chatgpt": 8 mentions` séparément, sous-estimant la tendance réelle.

**Solution en deux volets :**
- Court terme : normaliser les clés en minuscule lors de l'indexation (`key = f"{etype}:{name.strip().lower()}"`), tout en conservant la capitalisation d'origine dans les métadonnées.
- Moyen terme : ajouter une table d'alias dans `config/entity_aliases.json` pour les équivalences connues (`"Macron" → "Emmanuel Macron"`).

#### 6. `api_client.py` — classification silencieuse des erreurs de parsing

**Problème :** `_parse_entities_response()` et `_parse_sentiment_response()` retournent `{}` silencieusement sur toute erreur de parsing JSON (réponse tronquée, format inattendu de l'API). Cela empêche `repair_failed_enrichments.py` de distinguer une absence d'entités (article sans entités) d'un vrai échec de parsing.

**Solution :** faire retourner une valeur sentinelle distincte de `{}` :
```python
# Dans generate_entities()
raw_result = _parse_entities_response(content)
if raw_result is None:  # Nouveau : None = échec parsing, {} = aucune entité
    return None  # → enrich_entities.py positionne enrichissement_statut = "echec_parse"
return raw_result
```

Cela active pleinement `repair_failed_enrichments.py` pour le cas `"echec_parse"`.

#### 7. Index auto-rebuild au démarrage du viewer

**Problème :** si `data/article_index.json` ou `data/entity_index.json` sont absents (première installation, migration, purge de données), les endpoints du viewer tombent silencieusement sur le fallback rglob sans jamais reconstruire l'index. L'index reste absent indéfiniment.

**Solution :** dans `viewer/app.py`, ajouter une tâche de fond au démarrage :
```python
import threading

def _ensure_indexes():
    from utils.article_index import get_article_index
    from utils.entity_index import get_entity_index
    aidx = get_article_index(PROJECT_ROOT)
    if not (PROJECT_ROOT / "data" / "article_index.json").exists():
        aidx.rebuild()
    eidx = get_entity_index(PROJECT_ROOT)
    if not (PROJECT_ROOT / "data" / "entity_index.json").exists():
        eidx.rebuild()

threading.Thread(target=_ensure_indexes, daemon=True).start()
```

---

### Priorité BASSE

#### 8. Découpage de `_process_source()` dans `web_watcher.py`

**Problème :** la fonction `_process_source()` fait environ 180 lignes et mélange quatre responsabilités distinctes : filtrage des URLs, extraction du contenu HTML, appels API (résumé + NER), sauvegarde + index.

**Découpage proposé :**

| Fonction | Responsabilité |
|----------|---------------|
| `_filter_new_urls(source, state, all_entries)` | Filtrage sitemap + déduplication |
| `_extract_and_summarize(url, source, api_client)` | Extraction HTML + résumé + NER |
| `_save_and_index(out_path, articles, new_for_48h)` | Écriture atomique + index + rolling_window |

Cela faciliterait les tests unitaires, actuellement impossibles sans mocker tout le pipeline.

#### 9. Invalidation événementielle du cache `/api/sources/bias`

**Problème :** le cache TTL de 5 minutes de `/api/sources/bias` ne tient pas compte des nouvelles données. Un article avec un sentiment `négatif` ajouté juste après un appel peut ne pas apparaître pendant 5 minutes.

**Solution :** exposer une fonction `invalidate_bias_cache()` appelée depuis les endpoints d'écriture (`/api/files/save`, script console) :
```python
def invalidate_bias_cache():
    _bias_cache["ts"] = 0.0  # Force expiration immédiate
```

#### 10. Rapport de qualité des données journalier

**Problème :** il n'existe aucun indicateur consolidé de la qualité des données produites par le pipeline (taux de couverture NER, taux de succès de l'enrichissement sentiment, proportion d'articles avec `score_source`, etc.).

**Solution :** ajouter un endpoint `GET /api/data-quality` et un rapport Markdown hebdomadaire :

| Métrique | Source |
|----------|--------|
| Couverture NER (%) par flux | `article_index.stats()` → `with_entities / total` |
| Couverture sentiment (%) | `with_sentiment / total` |
| Taux d'échec enrichissement (%) | Scan `enrichissement_statut == "echec_api"` |
| Articles sans `score_source` | Scan `score_source` absent |
| Entités distinctes indexées | `entity_index.stats()` → `entities` |
| Freshness index (heures depuis dernier update) | `generated_at` dans les index |

Ce rapport permettrait de détecter des régressions dans la qualité du pipeline avant qu'elles n'impactent les rapports produits.

---

## 6. Plan d'action

### Sprint 1 — Critique (correction pipeline)

| # | Tâche | Fichier | Effort |
|---|-------|---------|--------|
| 1 | Ajouter index updates dans `enrich_entities.py` + `enrich_sentiment.py` | `scripts/enrich_*.py` | 30 min |

### Sprint 2 — Haute priorité

| # | Tâche | Fichier | Effort |
|---|-------|---------|--------|
| 2 | Intégrer `rolling_window` dans `flux_watcher.py` | `scripts/flux_watcher.py` | 1h |
| 3 | Ajouter `score_source` à la création d'articles | `scripts/get-keyword-from-rss.py`, `web_watcher.py` | 1h |

### Sprint 3 — Qualité et robustesse

| # | Tâche | Fichier | Effort |
|---|-------|---------|--------|
| 4 | Tests `rolling_window` + `parse_article_date` | `tests/test_rolling_window.py`, `tests/test_date_utils.py` | 2h |
| 5 | Normalisation noms entités (lowercase + alias) | `utils/entity_index.py` | 3h |
| 6 | Classification `echec_parse` dans `api_client.py` | `utils/api_client.py` | 1h |
| 7 | Index auto-rebuild au démarrage viewer | `viewer/app.py` | 30 min |

### Sprint 4 — Maintenabilité et observabilité

| # | Tâche | Fichier | Effort |
|---|-------|---------|--------|
| 8 | Découper `_process_source()` | `scripts/web_watcher.py` | 3h |
| 9 | Invalidation événementielle cache bias | `viewer/app.py` | 30 min |
| 10 | Endpoint + rapport qualité des données | `viewer/app.py` + nouveau script | 4h |

---

## 7. Annexe — État des axes

| Axe | Description | Statut |
|-----|-------------|--------|
| 1 | Index articles `article_index.py` | ✅ Réalisé |
| 2 | Index entités `entity_index.py` | ✅ Réalisé |
| 3 | Rapports matinaux via index | ✅ Réalisé |
| 3b | Fix O(n²) `compute_top_entities()` | ✅ Réalisé |
| 4 | Cache synthèse IA `synthesis_cache.py` | ✅ Réalisé |
| 4v | `api_entity_context` viewer optimisé | ✅ Vérifié conforme |
| 5 | Timeline + cross-flux via index | ✅ Réalisé |
| 6 | Singleton `get_scoring_engine()` | ✅ Réalisé |
| 7 | Tests + benchmark | ✅ Réalisé (47 tests) |
| 8 | `enrichissement_statut` + repair script | ✅ Réalisé |
| A | Index updates dans get-keyword-from-rss | ✅ Réalisé (v2.5) |
| B | Index updates dans web_watcher | ✅ Réalisé (v2.5) |
| C | trend_detector via entity_index | ✅ Réalisé (v2.5) |
| D | 6 endpoints viewer via index | ✅ Réalisé (v2.5) |
| E | generate_briefing via index + get_scoring_engine | ✅ Réalisé (v2.5) |
| F | `utils/rolling_window.py` | ✅ Réalisé (v2.5) |
| G | `parse_article_date()` centralisé | ✅ Réalisé (v2.5) |
| H | Écriture atomique get-keyword | ✅ Réalisé (v2.5) |
| 1-v2.5 | Index updates enrich_entities + enrich_sentiment | ✅ Réalisé |
| 2-v2.5 | rolling_window dans flux_watcher | ✅ Réalisé |
| 3-v2.5 | score_source à la création | ✅ Réalisé |
| 4-v2.5 | Tests rolling_window + parse_article_date | ✅ Réalisé |
| 5-v2.5 | Normalisation noms entités | ✅ Réalisé |
| 6-v2.5 | echec_parse dans api_client | ✅ Réalisé |
| 7-v2.5 | Index auto-rebuild au démarrage viewer | ✅ Réalisé |
| 8-v2.5 | Découper _process_source() | ✅ Réalisé |
| 9-v2.5 | Invalidation cache bias | ✅ Réalisé |
| 10-v2.5 | Rapport qualité des données | ✅ Réalisé |
| 11-v2.6 | Détection silences (trend_detector) | ✅ Réalisé |

---

*Rapport initial généré le 15 mars 2026 (v2.5.0), mis à jour en alignement optimisation le 30 avril 2026 (v2.8.18).*
