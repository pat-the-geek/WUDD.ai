### 6. get-keyword-from-rss.py

**Description** : Extraction quotidienne des articles contenant un mot-clé (défini dans `config/keyword-to-search.json`) depuis tous les flux RSS de WUDD.opml.
Pour chaque mot-clé, génère un fichier JSON dans `data/articles-from-rss/` (sans doublon), avec résumé IA et images principales.

La **déduplication avancée** (`utils/deduplication.py`) est appliquée automatiquement en cascade selon trois signaux complémentaires :

| Signal | Cas détectés | Coût |
|---|---|---|
| **URL normalisée (MD5)** — sans fragment, sans trailing slash | Même article, paramètres tracking différents | O(1) — filtre de première passe |
| **Empreinte MD5 du résumé** — 200 premiers caractères | Dépêches AFP/Reuters reprises par N sites (URL différentes, même texte source) | O(1) |
| **Jaccard bigrammes des titres** — stopwords filtrés, seuil ≥ 0.85 | Titres reformulés, variantes de temps ou ponctuation | O(n) — appliqué en dernier |

Ces trois signaux couvrent ~95 % des doublons réels d'un corpus RSS multilingue. Voir `utils/deduplication.py` pour la configuration du seuil.

**Filtrage avancé (OR / AND)**

Chaque entrée de `keyword-to-search.json` supporte deux collections optionnelles :

| Champ | Comportement |
|---|---|
| `or` | Si le mot-clé principal est absent du titre, sélectionne l'article si **au moins un** mot de la liste est présent |
| `and` | Après une présélection (mot-clé ou `or`), exige qu'**au moins un** mot de la liste soit présent dans le titre |

Exemples :
```json
{ "keyword": "David Bowie", "or": ["Ziggy Stardust", "Thin White Duke"] }
{ "keyword": "UBS", "and": ["banque", "bank"] }
{ "keyword": "Intelligence artificielle", "or": ["AI", "IA"] }
```

> La correspondance des mots `or`/`and` utilise des frontières de mot (`\b` regex) pour éviter les faux positifs.

**Utilisation** :
```bash
python3 get-keyword-from-rss.py
```

**Automatisation (cron)** :
```
0 1 * * * root cd /app && python3 scripts/get-keyword-from-rss.py 2>&1 | tee -a /app/rapports/cron_get_keyword.log
```

**Sortie** :
- `../data/articles-from-rss/<mot-clé>.json`

### 7. repair_failed_summaries.py

**Description** : Détecte et régénère les résumés d'articles contenant un message d'erreur (ex. `"Désolé, je n'ai pas pu obtenir de réponse…"`). Utile après une indisponibilité temporaire de l'API.

**Arguments** :

| Argument | Description | Défaut |
| --- | --- | --- |
| `--dir PATH` | Répertoire à scanner | `data/articles-from-rss/` |
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--delay SECS` | Délai entre chaque appel API (secondes) | 1 |

**Utilisation** :

```bash
# Réparer tous les fichiers dans data/articles-from-rss/
python3 scripts/repair_failed_summaries.py

# Cibler un répertoire spécifique
python3 scripts/repair_failed_summaries.py --dir data/articles/Intelligence-artificielle

# Simulation sans appel API
python3 scripts/repair_failed_summaries.py --dry-run
```

**Sortie** : Sauvegarde atomique des fichiers JSON modifiés (écriture via `.tmp` puis remplacement).

---

### 8. repair_failed_enrichments.py

**Description** : Détecte et réessaie l'enrichissement (NER et/ou sentiment) des articles dont le champ `enrichissement_statut` vaut `echec_api` ou `echec_parse`. Met également à jour l'`entity_index` après chaque réparation NER réussie. Utile après une indisponibilité temporaire de l'API (EurIA ou Claude).

**Arguments** :

| Argument | Description | Défaut |
| --- | --- | --- |
| `--type entities\|sentiment\|all` | Type d'enrichissement à réparer | `all` |
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--delay SECS` | Délai entre chaque appel API (secondes) | 1.0 |

**Utilisation** :

```bash
# Réparer NER et sentiment pour tous les fichiers
python3 scripts/repair_failed_enrichments.py

# NER uniquement
python3 scripts/repair_failed_enrichments.py --type entities

# Sentiment uniquement
python3 scripts/repair_failed_enrichments.py --type sentiment

# Simulation sans appel API
python3 scripts/repair_failed_enrichments.py --dry-run
```

**Automatisation (cron)** — planifiable après `enrich_entities.py` (ex. 03:30) pour traiter les échecs de la nuit.

**Sortie** : Sauvegarde atomique des fichiers JSON modifiés + mise à jour de l'`entity_index`.

**Description** : Génère chaque soir un rapport de veille analytique basé sur les **Top 10 entités nommées** des 48 dernières heures. Lit `data/articles-from-rss/_WUDD.AI_/48-heures.json` (produit par `get-keyword-from-rss.py`), pré-calcule les entités les plus citées (personnes, organisations, pays, produits, événements), sélectionne les 5 articles les plus récents par entité, et génère un rapport structuré via l'API IA (EurIA ou Claude).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Affiche le prompt et le Top 10 entités sans appeler l'API | désactivé |

**Utilisation** :

```bash
# Génération réelle du rapport
python3 scripts/generate_48h_report.py

# Simulation — affiche le Top 10 et le prompt (sans appel API)
python3 scripts/generate_48h_report.py --dry-run
```

**Automatisation (cron)** — exécuté chaque jour à 23h00, après la dernière collecte RSS :
```
0 23 * * * root cd /app && python3 scripts/generate_48h_report.py 2>&1 | tee -a /app/rapports/cron_48h_report.log
```

**Sortie** :
- `rapports/markdown/_WUDD.AI_/rapport_48h.md` — fichier unique, écrasé chaque jour

**Structure du rapport généré** :
1. Frontmatter YAML (titre, date, période, nombre d'articles analysés)
2. **10 sections entité** : Contexte · Actualité des 48h (sources citées inline) · Analyse stratégique · Image `![](URL)`
3. **Corrélations inter-entités** : liens significatifs entre les Top 10
4. **Constatations générales** : dynamiques, ruptures, signaux faibles
5. **Tableau de références** : tous les articles cités (date, source, URL)

**Prérequis** : `data/articles-from-rss/_WUDD.AI_/48-heures.json` doit exister (généré par `get-keyword-from-rss.py`). Pour un rapport enrichi, les articles doivent avoir été traités par `enrich_entities.py`.

---

### 9. flux_watcher.py

**Description** : Surveillance round-robin des flux RSS listés dans `data/WUDD.opml`. Appelé toutes les **5 minutes** par cron, il traite un seul flux à la fois (rotation circulaire) : pour chaque article récent (≤ 7 jours) dont le titre correspond à un mot-clé de `config/keyword-to-search.json`, il génère un résumé IA + entités NER + image principale et l'ajoute sans doublon dans `data/articles-from-rss/<keyword>.json`. Met également à jour `data/articles-from-rss/_WUDD.AI_/48-heures.json` de façon incrémentale. L'état du round-robin est conservé dans `data/flux_watcher_state.json`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Affiche le flux sélectionné sans traitement IA ni écriture | désactivé |

**Utilisation** :
```bash
# Exécution normale (traitement IA)
python3 scripts/flux_watcher.py

# Simulation — affiche le prochain flux sans appel API
python3 scripts/flux_watcher.py --dry-run
```

**Automatisation (cron)** — toutes les 5 minutes, enchaîné avec les scripts de calcul local :
```
*/5 * * * * root cd /app && { python3 scripts/flux_watcher.py 2>&1 | tee -a /app/rapports/cron_flux_watcher.log; python3 scripts/entity_timeline.py >> /app/rapports/cron_flux_watcher.log 2>&1; python3 scripts/cross_flux_analysis.py >> /app/rapports/cron_flux_watcher.log 2>&1; python3 scripts/enrich_reading_time.py >> /app/rapports/cron_flux_watcher.log 2>&1; }
```

> `entity_timeline.py`, `cross_flux_analysis.py` et `enrich_reading_time.py` s'exécutent systématiquement après chaque passage du watcher (calculs 100 % locaux, < 1 s). Le Dashboard du Viewer dispose ainsi de données fraîches toutes les 5 minutes.

**Sorties** :
- `data/articles-from-rss/<keyword>.json` — mis à jour incrementalement
- `data/articles-from-rss/_WUDD.AI_/48-heures.json` — fenêtre glissante 48h
- `data/flux_watcher_state.json` — état du round-robin

---

### 10. articles_rss_to_markdown.py

**Description** : Convertit les fichiers JSON de `data/articles-from-rss/` en rapports Markdown annotés (entités nommées en ligne). Génère un fichier Markdown par mot-clé dans `rapports/markdown/keyword/<mot-clé>/`. Destiné à être exécuté le dernier jour du mois après la collecte.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--keyword MOT` | Traiter uniquement ce mot-clé | tous les mots-clés |

**Utilisation** :
```bash
# Convertir tous les fichiers RSS en Markdown
python3 scripts/articles_rss_to_markdown.py

# Un mot-clé spécifique uniquement
python3 scripts/articles_rss_to_markdown.py --keyword anthropic
```

**Automatisation (cron)** — dernier jour du mois à 5h30 :
```
30 5 28-31 * * root [ "$(date -d tomorrow +%d)" = "01" ] && cd /app && python3 scripts/articles_rss_to_markdown.py 2>&1 | tee -a /app/rapports/cron_rss_markdown.log
```

**Sortie** :
- `rapports/markdown/keyword/<keyword>/<keyword>_YYYY-MM-DD.md`

---

### 11. trend_detector.py

**Description** : Détecte les entités nommées en forte progression en comparant leurs mentions sur les **24 dernières heures** avec leur moyenne sur les **7 derniers jours**. Génère `data/alertes.json` consommé par le panneau **Tendances & alertes** du Viewer. Les seuils et types surveillés sont configurables dans `config/alert_rules.json`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--top N` | Nombre d'alertes à conserver | 20 (config) |
| `--threshold RATIO` | Seuil global de ratio 24h/7j | 2.0 (config) |
| `--dry-run` | Calcule les tendances sans écrire `alertes.json` | désactivé |
| `--no-notify` | Désactive les notifications webhook | désactivé |

**Utilisation** :
```bash
# Exécution normale — génère data/alertes.json
python3 scripts/trend_detector.py

# Simulation sans écriture
python3 scripts/trend_detector.py --dry-run

# Top 15 avec seuil rehaussé, sans notifications
python3 scripts/trend_detector.py --top 15 --threshold 3.0 --no-notify
```

**Automatisation (cron)** — chaque matin à 7h00 :
```
0 7 * * * root cd /app && python3 scripts/trend_detector.py 2>&1 | tee -a /app/rapports/cron_trends.log
```

**Configuration** : `config/alert_rules.json` — seuils par type d'entité, niveaux (modéré / élevé / critique), configuration webhooks Discord / Slack / Ntfy.

**Sortie** :
- `data/alertes.json` — liste des alertes avec ratio, niveau et entités concernées

---

### 12. enrich_reading_time.py

**Description** : Calcule et ajoute le **temps de lecture estimé** (en minutes) à chaque article de `data/articles/` et `data/articles-from-rss/`. Basé sur 230 mots/minute (référence INSERM, adulte francophone). Traitement 100 % local, aucun appel EurIA ni Claude. Champs ajoutés : `temps_lecture_minutes` (float) et `temps_lecture_label` (chaîne lisible, ex. `"3 min"`).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Traiter uniquement ce flux | tous |
| `--keyword MOT` | Traiter uniquement ce mot-clé | tous |
| `--dry-run` | Simulation sans écriture | désactivé |
| `--force` | Réenrichir les articles déjà enrichis | désactivé |

**Utilisation** :
```bash
# Enrichir tous les articles
python3 scripts/enrich_reading_time.py

# Un flux spécifique
python3 scripts/enrich_reading_time.py --flux Intelligence-artificielle

# Simulation
python3 scripts/enrich_reading_time.py --dry-run
```

**Automatisation (cron)** — enchaîné après `flux_watcher.py` toutes les 5 minutes (voir §9). Ne possède plus d'entrée cron dédiée.

**Sortie** : Sauvegarde atomique des fichiers JSON modifiés.

---

### 13. entity_timeline.py

**Description** : Construit la **série chronologique** des mentions d'entités nommées en scannant tous les articles de `data/articles/` et `data/articles-from-rss/`. Produit `data/entity_timeline.json` utilisé par le composant **Timeline des entités** dans le Dashboard du Viewer (sparklines SVG).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--days N` | Fenêtre temporelle en jours | 30 |
| `--top N` | Nombre d'entités à inclure | 50 |
| `--entity NOM` | Filtrer sur une entité précise | toutes |
| `--type TYPE` | Filtrer par type NER (PERSON, ORG, GPE…) | tous |
| `--dry-run` | Affiche le résultat sans écrire le fichier | désactivé |

**Utilisation** :
```bash
# Générer la timeline complète (30j, top 50 entités)
python3 scripts/entity_timeline.py

# Fenêtre 7 jours, top 20
python3 scripts/entity_timeline.py --days 7 --top 20

# Une entité spécifique
python3 scripts/entity_timeline.py --entity "OpenAI" --type ORG
```

**Automatisation (cron)** — enchaîné après `flux_watcher.py` toutes les 5 minutes (voir §9). Ne possède plus d'entrée cron dédiée.

**Sortie** :
- `data/entity_timeline.json` — séries temporelles par entité, exposées via `GET /api/entities/timeline`

---

### 14. cross_flux_analysis.py

**Description** : Détecte les **entités transversales** présentes dans plusieurs flux distincts. Identifie les sujets qui dépassent un seul fil de veille et créent des convergences thématiques. Génère un rapport JSON et un rapport Markdown structuré incluant deux visualisations interactives rendues par le Viewer.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--min-flux N` | Nombre minimum de flux distincts pour inclure une entité | 2 |
| `--top N` | Nombre d'entités à inclure | 20 |
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
# Analyse complète (entités dans ≥ 2 flux)
python3 scripts/cross_flux_analysis.py

# Entités présentes dans ≥ 3 flux
python3 scripts/cross_flux_analysis.py --min-flux 3

# Simulation
python3 scripts/cross_flux_analysis.py --dry-run
```

**Automatisation (cron)** — enchaîné après `flux_watcher.py` toutes les 5 minutes (voir §9). Ne possède plus d'entrée cron dédiée.

**Visualisations dans le rapport Markdown** :

Le rapport utilise deux blocs de code personnalisés interprétés par `MarkdownViewer.jsx` :

| Bloc | Composant | Description |
|---|---|---|
| ` ```keyword-graph ` | `KeywordForceGraph` | Graphe force-directed des mots-clés RSS — **filtré** aux seuls mots-clés ayant au moins 1 article sur la période |
| ` ```flux-chart ` | `FluxBarChart` | Barres horizontales des top flux par volume — chaque barre porte une **lettre alphabétique** correspondant à la liste textuelle du rapport |

La lettre de chaque flux est assignée par `_assign_flux_letters()` (ordre alphabétique A, B, C…) et transmise via le champ `letter` du JSON.

**Fonctions internes clés** :

| Fonction | Rôle |
|---|---|
| `_normalize_keyword_stem(kw)` | Normalise un mot-clé vers le stem du fichier RSS (`strip().lower().replace(' ', '-')`) |
| `_build_keyword_graph_block(project_root, active_stems)` | Génère le bloc `keyword-graph` en ne gardant que les stems présents dans `data/articles-from-rss/` avec `v > 0` |
| `_build_flux_chart_block(flux_article_counts, flux_letter_map, top_n=15)` | Génère le bloc `flux-chart` avec `{name, count, letter}` par item |
| `_assign_flux_letters(sorted_flux_names)` | Attribue A–Z puis AA, AB… aux flux triés alphabétiquement |

**Sortie** :
- `data/cross_flux_report.json` — entités transversales avec comptages par flux
- `rapports/markdown/_CROSSFLUX_/cross_flux_YYYY-MM-DD.md` — rapport Markdown avec tableau de convergence, graphe mots-clés et graphique flux

---

### 15. benchmark_indexes.py

**Description** : Mesure les gains de performance des index WUDD.ai en comparant les opérations clés **avant** (scan `rglob`) et **après** (lecture de l'index) :

1. `ScoringEngine.get_top_articles()` vs `get_top_articles_from_index()`
2. `EntityIndex.load_articles()` vs scan rglob complet
3. `compute_top_entities()` O(n) vs simulation O(n²)
4. État du cache de synthèse IA (`SynthesisCache.stats()`)

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--iterations N` | Nombre de répétitions par benchmark (meilleur temps retenu) | 3 |

**Utilisation** :

```bash
# Benchmark par défaut (3 itérations)
python3 scripts/benchmark_indexes.py

# 5 itérations pour plus de précision
python3 scripts/benchmark_indexes.py --iterations 5
```

**Prérequis** : Les index doivent être construits. Lancer d'abord :
```bash
python3 scripts/migrate_build_indexes.py
```

**Sortie** : Rapport console avec temps avant/après et facteur d'accélération (ex. `×12 plus rapide`) pour chaque opération.

## Générer le rapport Markdown d'un flux

```bash
python3 scripts/articles_json_to_markdown.py data/articles/Economie-numerique/articles_generated_2026-02-01_2026-02-17.json
```

## Lancer le scheduler sur tous les flux

```bash
python3 scripts/scheduler_articles.py
```

## Ajouter un nouveau flux

Ajouter une entrée dans `config/flux_json_sources.json` avec le titre et l'URL du flux.
# Guide d'utilisation des scripts

Ce guide explique comment utiliser les différents scripts du projet AnalyseActualités.

## 🚀 Lancement rapide

Tous les scripts doivent être exécutés **depuis le dossier `scripts/`** pour que les chemins relatifs fonctionnent correctement.

```bash
cd scripts/
```

---

## 📝 Scripts disponibles

### 1. Get_data_from_JSONFile_AskSummary.py

**Description** : Script principal qui collecte des articles depuis un flux JSON, génère des résumés via l'API IA (EurIA ou Claude), et crée un rapport Markdown.

**Utilisation** :
```bash
python3 Get_data_from_JSONFile_AskSummary.py [date_debut] [date_fin]
```

**Exemples** :
```bash
# Avec dates spécifiques
python3 Get_data_from_JSONFile_AskSummary.py 2026-01-01 2026-01-31

# Sans dates (demande interactive)
python3 Get_data_from_JSONFile_AskSummary.py
```

**Prérequis** :
- Fichier `.env` configuré avec `REEDER_JSON_URL`, `URL`, et `bearer`
- Connexion internet active

**Sorties** :
- `../data/articles/articles_generated_<date_debut>_<date_fin>.json`
- `../rapports/markdown/rapport_sommaire_articles_generated_<date_debut>_<date_fin>.md`

---

### 2. Get_htmlText_From_JSONFile.py

**Description** : Extrait le contenu texte brut de tous les articles d'un flux JSON.

**Utilisation** :
```bash
python3 Get_htmlText_From_JSONFile.py
```

**Fonctionnement** :
1. Une fenêtre s'ouvre pour sélectionner un fichier JSON (flux d'articles)
2. Le script récupère le HTML de chaque URL
3. Extrait le texte avec BeautifulSoup
4. Génère un fichier consolidé

**Sortie** :
- `../data/raw/all_articles.txt`

---

### 3. articles_json_to_markdown.py

**Description** : Convertit un fichier JSON d'articles en rapport Markdown formaté.

**Utilisation** :
```bash
python3 articles_json_to_markdown.py
```

**Fonctionnement** :
1. Sélectionnez un fichier JSON d'articles (depuis `../data/articles/`)
2. Choisissez le nom et l'emplacement du fichier Markdown de sortie
3. Le script génère un rapport avec dates, sources, URLs et résumés

**Format d'entrée attendu** :
```json
[
  {
    "Date de publication": "2026-01-23T10:00:00Z",
    "Sources": "Nom de la source",
    "URL": "https://...",
    "Résumé": "Texte du résumé..."
  }
]
```

---

## ⚙️ Configuration requise

### Fichier .env (racine du projet)

```env
# API Infomaniak EurIA
URL=https://api.infomaniak.com/euria/v1/chat/completions
bearer=VOTRE_TOKEN_API_ICI

# URL du flux JSON à traiter
REEDER_JSON_URL=https://votre-flux.com/feed.json

# Paramètres optionnels
max_attempts=5
default_error_message=Aucune information disponible
```

### Dépendances Python

Installez les dépendances depuis la racine du projet :
```bash
cd ..
pip install -r requirements.txt
cd scripts/
```

### 4. enrich_entities.py

**Description** : Enrichit les fichiers JSON d'articles existants avec les **entités nommées (NER)** extraites via l'API IA (EurIA ou Claude). Parcourt `data/articles/` (flux) et `data/articles-from-rss/` (mots-clés) et ajoute le champ `entities` à chaque article qui dispose d'un `Résumé`.

**Utilisation** :
```bash
# Tout traiter (flux + rss)
python3 scripts/enrich_entities.py

# Un flux spécifique uniquement
python3 scripts/enrich_entities.py --flux Intelligence-artificielle

# Un mot-clé spécifique uniquement
python3 scripts/enrich_entities.py --keyword anthropic

# Simulation (aucun appel API, aucune écriture)
python3 scripts/enrich_entities.py --dry-run

# Réduire la cadence (délai entre appels, défaut 1.0 s)
python3 scripts/enrich_entities.py --delay 2.0

# Ré-enrichir même les articles déjà traités
python3 scripts/enrich_entities.py --force
```

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Restreindre au sous-dossier `data/articles/<NOM>/` | tous les flux |
| `--keyword MOT` | Restreindre au fichier `data/articles-from-rss/<MOT>.json` | tous les mots-clés |
| `--dry-run` | Mode simulation : aucun appel API, aucune sauvegarde | désactivé |
| `--delay SEC` | Pause en secondes entre chaque appel API | 1.0 |
| `--force` | Re-traiter les articles ayant déjà le champ `entities` | désactivé |

**Catégories NER extraites** (18 types) :

| Type | Contenu |
|---|---|
| `PERSON` | Personnes physiques nommées |
| `ORG` | Organisations, entreprises, institutions |
| `GPE` | Pays, villes, régions géopolitiques |
| `LOC` | Lieux géographiques non géopolitiques |
| `PRODUCT` | Produits, services, technologies |
| `EVENT` | Événements nommés (conférences, crises…) |
| `NORP` | Nationalités, groupes politiques/religieux |
| `FAC` | Bâtiments, monuments nommés |
| `WORK_OF_ART` | Titres d'œuvres (livres, films, rapports…) |
| `LAW` | Lois, règlements nommés |
| `DATE` / `TIME` | Dates et heures explicites |
| `MONEY` / `PERCENT` | Montants et pourcentages |
| `QUANTITY` / `CARDINAL` / `ORDINAL` | Mesures et nombres |

**Format ajouté dans chaque article** :
```json
"entities": {
  "PERSON": ["Emmanuel Macron", "Sam Altman"],
  "ORG": ["OpenAI", "Infomaniak"],
  "GPE": ["France", "États-Unis"],
  "PRODUCT": ["ChatGPT", "Qwen3"]
}
```

**Comportement** :
- Sauvegarde atomique (écriture dans `.tmp` puis remplacement) pour éviter la corruption
- Les articles sans champ `Résumé` sont ignorés
- Les articles ayant déjà `entities` sont ignorés (sauf avec `--force`)
- Rapport de stats en fin d'exécution : total / enrichis / déjà présents / erreurs / ignorés

**Prérequis** :
- Fichiers JSON dans `data/articles/` ou `data/articles-from-rss/`
- Fichier `.env` avec `URL` et `bearer` configurés

---

### 5. analyse_thematiques.py

**Description** : Analyse les thématiques sociétales présentes dans tous les articles collectés et génère un rapport statistique détaillé.

**Utilisation** :
```bash
python3 analyse_thematiques.py
```

**Prérequis** :
- Fichiers JSON dans `../data/articles/`
- Fichier `../config/thematiques_societales.json` (créé automatiquement si absent)

**Sorties** :
- Rapport console avec statistiques par thématique
- 12 thématiques analysées : IA & Technologie, Économie, Santé, Politique, etc.
- Pourcentages d'occurrence et exemples d'articles par thème

**Exemple de sortie** :
```
═══════════════════════════════════════════════════════════════════════
                    ANALYSE DES THÉMATIQUES SOCIÉTALES
═══════════════════════════════════════════════════════════════════════

📊 Corpus analysé: 72 articles valides
📅 Période: Décembre 2025 - Janvier 2026

1. INTELLIGENCE ARTIFICIELLE & TECHNOLOGIE (100.0%)
   Mentions: 72
   Exemples d'articles (3):
   [1] Numerama - En 2025, ChatGPT perd du terrain...
```

---

## � Système de quota adaptatif

> **Module :** `utils/quota.py` | **Config :** `config/quota.json` | **État :** `data/quota_state.json`

Le système de quota régule automatiquement le nombre d'articles importés par jour via l'API IA (EurIA ou Claude). Il applique quatre plafonds indépendants et trie les mots-clés de façon adaptative pour garantir la diversité des sources.

### Paramètres (`config/quota.json`)

```json
{
  "enabled": true,
  "global_daily_limit": 150,
  "per_keyword_daily_limit": 30,
  "per_source_daily_limit": 5,
  "per_entity_daily_limit": 10,
  "adaptive_sorting": true
}
```

| Paramètre | Description | Défaut |
|---|---|---|
| `enabled` | Active / désactive complètement le système | `true` |
| `global_daily_limit` | Plafond journalier global (tous mots-clés confondus) | `150` |
| `per_keyword_daily_limit` | Max articles par mot-clé par jour | `30` |
| `per_source_daily_limit` | Max articles d'un même site pour un mot-clé donné | `5` |
| `per_entity_daily_limit` | Max articles contenant une même entité nommée par jour (max 20 via UI) | `10` |
| `adaptive_sorting` | Trie les mots-clés par ratio consommation/plafond croissant | `true` |

### Fonctionnement

1. **Avant chaque import** : `quota.can_process(keyword, source)` vérifie les 3 plafonds (global, mot-clé, source).
2. **Après détection NER, avant création** : `quota.can_process_entities(entities)` vérifie le plafond par entité — retourne `(True, '')` ou `(False, nom_entité)`. Un article est rejeté si l'une de ses entités est saturée.
3. **Après ajout** : `quota.record_article(keyword, source, entities)` incrémente tous les compteurs (y compris par entité).
4. **Tri adaptatif** : `quota.sort_by_priority(keywords)` ordonne les mots-clés par ratio consommation/plafond (croissant) — les sujets les moins traités passent en premier.
5. **Reset automatique** : Les compteurs (global, mots-clés, entités) se réinitialisent à minuit chaque jour (reset lazy au premier appel après minuit).

### Intégration dans les scripts

| Script | Comportement |
|---|---|
| `get-keyword-from-rss.py` | Stoppe le traitement dès que le quota global est atteint ; saute les sources saturées |
| `flux_watcher.py` | Sortie immédiate en début de run si quota global épuisé |

### Interface graphique (Viewer)

L'onglet **Quota** dans les Réglages du Viewer permet de :
- Activer/désactiver le système
- Ajuster les quatre plafonds via des curseurs (global, par mot-clé, par source, par entité — max 20)
- Activer/désactiver le tri adaptatif
- Visualiser la consommation en temps réel (barres de progression par mot-clé)
- Identifier les sources saturées (badges en rouge)
- Consulter le **Top 20 des entités nommées** du jour avec indication de saturation
- Remettre à zéro les compteurs manuellement

---

## �📂 Structure des chemins

Les scripts utilisent des chemins relatifs depuis le dossier `scripts/` :

```
scripts/
├── script.py           # Script en cours d'exécution
│
├── ../config/          # Configuration
│   ├── sites_actualite.json
│   ├── categories_actualite.json
│   ├── prompt-rapport.txt
│   └── thematiques_societales.json  # Thématiques + mots-clés
│
├── ../data/            # Données générées
│   ├── articles/       # JSON des articles
│   └── raw/            # Données brutes (txt)
│
└── ../rapports/        # Rapports générés
    ├── markdown/       # Rapports .md
    └── pdf/            # Rapports PDF
```

---

## 🔧 Dépannage

### Erreur : "No module named 'requests'"
```bash
pip install requests beautifulsoup4 python-dotenv
```

### Erreur : "FileNotFoundError: ../data/articles/..."
Assurez-vous d'exécuter les scripts **depuis le dossier scripts/** :
```bash
cd scripts/
python3 nom_du_script.py
```

### Interface graphique ne s'affiche pas
Les scripts utilisent `tkinter` qui nécessite un environnement graphique. Sur serveur headless, adaptez le code pour passer les chemins en arguments.

### Erreur API EurIA / Claude
Vérifiez :
- Le token `bearer` (EurIA) ou `CLAUDE_API_KEY` (Claude) dans le fichier `.env`
- La variable `AI_PROVIDER` (`euria` ou `claude`) dans `.env`
- La validité de l'URL de l'API
- Votre connexion internet

---

## 📊 Workflow typique

1. **Collecte et analyse** (génère articles JSON + rapport)
   ```bash
   python3 Get_data_from_JSONFile_AskSummary.py 2026-01-01 2026-01-31
   ```

2. **Enrichissement avec entités nommées (NER)** (optionnel)
   ```bash
   python3 scripts/enrich_entities.py
   # Ou pour un flux spécifique :
   python3 scripts/enrich_entities.py --flux Intelligence-artificielle
   ```

3. **Analyse des thématiques sociétales**
   ```bash
   python3 analyse_thematiques.py
   ```

4. **Conversion en Markdown personnalisé** (optionnel)
   ```bash
   python3 articles_json_to_markdown.py
   # Sélectionner : ../data/articles/articles_generated_2026-01-01_2026-01-31.json
   ```

5. **Extraction texte brut** (pour analyse manuelle)
   ```bash
   python3 Get_htmlText_From_JSONFile.py
   # Sélectionner un flux JSON source
   ```

---

## 📧 Support

Pour toute question : patrick.ostertag@gmail.com
