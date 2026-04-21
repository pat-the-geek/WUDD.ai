# 21/04/2026 — Audit dépendances et réalignement des runtimes (v2.8.5)

## Maintenance — Dépendances, frameworks et build Docker

### `requirements.txt`

- Rehausse des versions minimales Python pour refléter l'état courant recommandé du projet
- Mises à jour des minima pour `requests`, `beautifulsoup4`, `python-dotenv`, `urllib3`
- Rehausse des dépendances optionnelles déjà exploitées par le code : `duckdb`, `aiohttp`, `anthropic`, `python-whois`
- Mise à jour de l'outillage de tests : `pytest`, `pytest-cov`

### `viewer/requirements.txt`

- Mise à jour des minima pour `flask` et `openpyxl`

### `Dockerfile`

- Build frontend Docker : `node:20-slim` → `node:24-slim`
- Runtime Python Docker : `python:3.10-slim` → `python:3.14-slim`

### `docs/RAPPORT_DEPENDANCES_FRAMEWORKS_2026-04-21.md` — lot majeur frontend

- Nouveau rapport versionné sur les librairies et frameworks du projet
- Inventaire des versions déclarées, versions locales observées et dernières versions disponibles
- Plan d'upgrade par lots avec distinction entre lot sûr et migrations frontend majeures

### `viewer/package.json` / `viewer/package-lock.json`

- Mise à jour des dépendances frontend mineures sans changement de major : `mermaid`, `react-markdown`, `remark-gfm`, `vite`, `@vitejs/plugin-react`, `tailwindcss`, `postcss`, `autoprefixer`
- Lockfile régénéré sous Node 24
- Build frontend validé sous Node 24

### `viewer/src/App.jsx` / `viewer/src/components/FileViewer.jsx` / `viewer/src/components/ArticleListViewer.jsx` / `viewer/src/utils/mermaidLoader.js`

- Lazy-loading consolidé sur les panneaux et dialogues les plus lourds
- Préchargement opportuniste sur intention utilisateur pour la recherche, les réglages, les entités, le top, le chatbot et les rapports d'article
- Lissage des fetchs auxiliaires du viewer au démarrage pour laisser la liste de fichiers charger en priorité
- Chargement Mermaid mutualisé et à la demande, avec préchauffage ciblé seulement pour les contenus Markdown qui en ont besoin

### `viewer/package.json` / `viewer/package-lock.json` — migration React 19

- `react` et `react-dom` relevés vers `19.2.5`
- `react-leaflet` relevé vers `5.0.0` pour lever le blocage de peer dependency React 18

### `viewer/package.json` / `viewer/package-lock.json` — migration Vite 8

- `vite` relevé vers `8.0.9`
- `@vitejs/plugin-react` relevé vers `6.0.1`
- build production validé sous Node 24 sans changement de configuration Vite

### `viewer/package.json` / `viewer/package-lock.json` / `viewer/vite.config.js` / `viewer/src/index.css` / `viewer/tailwind.config.js` — migration Tailwind 4

- `tailwindcss` relevé vers `4.2.3`
- ajout du plugin `@tailwindcss/vite` `4.2.3`
- suppression de l'ancienne chaîne `postcss` / `autoprefixer` et suppression de `viewer/postcss.config.js`
- migration de la feuille d'entrée Tailwind vers `@import "tailwindcss"` avec chargement de la config JS via `@config`
- transposition de l'ancienne `safelist` NER vers des directives `@source inline(...)` dans `viewer/src/index.css`
- ajout d'une couche de compatibilité CSS minimale pour préserver les comportements de bordures, placeholders, boutons et `ring`
- lockfile régénéré et build production validé sous Node 24

### `viewer/package.json` / `viewer/package-lock.json` — modernisation Markdown et icônes

- `react-markdown` relevé vers `10.1.0`
- `lucide-react` relevé vers `1.8.0`
- remplacement local de l'icône de marque `Youtube` supprimée en 1.x par `PlayCircle` dans les panneaux vidéo liés
- lockfile régénéré et build production revalidé sous Node 24

### `docs/RAPPORT_DEPENDANCES_FRAMEWORKS_2026-04-21.md`

- Ajout des contraintes techniques vérifiées pour le futur lot majeur frontend
- Mise à jour du statut après validation complète de Tailwind 4 sous Node 24

### Validation

- Suite de tests locale : `1104 passed, 1 skipped`
- Suite de tests dans l'image Docker avec env minimale : `1104 passed, 1 skipped`
- Audit npm frontend après correction du lockfile : `0` vulnérabilité

### Sécurité frontend

- Correction des 2 vulnérabilités npm restantes sans changement de major déclaré
- Mise à jour transitive du lockfile : `dompurify` `3.3.1` → `3.4.0`, `picomatch` `2.3.1` → `2.3.2`, `picomatch` `4.0.3` → `4.0.4`

# 14/04/2026 — Garde-fous anti-caractères chinois dans les résumés IA (v2.8.4)

## Amélioration — Qualité linguistique des résumés (français strict)

### `utils/api_client.py`

- Ajout d'un contrôle **en amont** dans les prompts de résumé : consigne explicite
  `français uniquement` et `aucun caractère chinois (hanzi)`
- Ajout d'un contrôle **en aval** sur le texte généré : détection des caractères
  CJK Han via regex unicode
- Si des caractères chinois sont détectés, relance automatique de l'IA avec un
  prompt de correction strict (jusqu'à 2 régénérations)
- Le mécanisme est appliqué aux 3 chemins de génération :
  `generate_summary`, `generate_summary_with_sentiment` et variantes
  `EurIA`, `Claude`, `Ollama`
- Harmonisation du nettoyage des préfixes `# Résumé` via helper centralisé

### `tests/test_api_client_pure.py`

- Nouveaux tests unitaires pour :
  - détection des caractères chinois
  - contraintes de prompt français
  - relance automatique quand un résumé contient du chinois

# 12/04/2026 — Script de renommage des rapports Obsidian (v2.8.3)

## Ajout — Maintenance du vault Obsidian

### `scripts/rename_obsidian_reports.py`

- Nouveau script CLI pour verifier les rapports WUDD.ai du vault Obsidian
- Detecte les fichiers Markdown de rapports d'articles dont le nom ne commence pas par `YYYY-MM-DD`
- Retrouve l'article source via l'URL du frontmatter dans `data/articles-from-rss/*.json`
- Recupere le nom cible depuis `rapports[].fichier`
- Integre un mode `--dry-run`, une limite `--limit` et une commande de renommage configurable via `--rename-command`

---

# 10/04/2026 — Déduplication sémantique dans le contexte Terminal IA (v2.8.2)

## Amélioration — Terminal IA / chatbot

Lors de la lecture de fichiers JSON d'articles, le contexte injecté dans le Terminal IA
est désormais **dédupliqué sémantiquement** avant d'être envoyé à l'IA.

### `viewer/routes/export.py` — `_format_articles_for_context()`

- **Passe 1 — URL exacte** : les doublons stricts (même URL) sont éliminés
- **Passe 2 — Similarité Jaccard** : les articles dont les résumés sont quasi-identiques
  (seuil ≥ 0.80 sur bigrammes de mots normalisés) sont exclus du contexte
- Utilise les fonctions `_normalize`, `_tokenize`, `_bigrams` de `utils/deduplication.py`
- Le message d'en-tête du contexte indique désormais le nombre de doublons supprimés :
  `X article(s) au total — Y uniques (Z doublon(s) sémantique(s) supprimé(s)) — N inclus`

---

# 09/04/2026 — Correction routage Ollama : get_config() obligatoire avant lecture AI_PROVIDER_* (v2.8.1)

## Bug fix — Ollama ignoré dans le contexte cron Docker

### Problème identifié
Dans le contexte cron Docker (env minimal), `get_summary_client()` et `get_ner_client()`
lisaient `os.environ.get("AI_PROVIDER_SUMMARY")` / `os.environ.get("AI_PROVIDER_NER")`
**avant** que `load_dotenv()` soit appelé. Ces variables étaient vides → bascule
silencieuse vers EurIA, consommant ~961 000 tokens cloud/jour inutilement.

### Fix — `utils/api_client.py`
- Ajout de `get_config()` en tête de `get_summary_client()` et `get_ner_client()`
  pour garantir le chargement du `.env` avant toute lecture de variable d'env

### Correction infrastructure macOS — Ollama inaccessible depuis Docker
- `OLLAMA_HOST` pointait vers `host.docker.internal` (IPv6 seulement) alors
  qu'Ollama n'écoutait que sur `127.0.0.1` (IPv4 loopback)
- Nouveau LaunchAgent `~/Library/LaunchAgents/com.wudd.ollama.plist` :
  remplace `homebrew.mxcl.ollama` avec `OLLAMA_HOST=0.0.0.0` baked dans le plist
  (`KeepAlive=true`, `RunAtLoad=true`) — persiste aux reboots et aux `brew upgrade`
- Suppression de l'ancien `homebrew.mxcl.ollama.plist` géré par Homebrew

### Résultat mesuré
| Fenêtre | EurIA | Ollama | Total |
|---|---|---|---|
| Avant fix (00h–17h55) | 961 062 tokens | 26 083 tokens | 987 145 |
| Après fix (18h00+) | 0 tokens | 100 % | — |

---

# 08/04/2026 — Résumés d'articles via Ollama local (v2.8.0)

## Option B — Ollama local pour les résumés d'articles

Décharge la génération des résumés d'articles sur Ollama local (`qwen2.5:7b`)
en complément de l'Option A (NER/sentiment). Économie estimée : ~789 000 tokens/jour
supplémentaires selon le flux d'articles.

### `utils/api_client.py` — `get_summary_client()`

- Nouvelle factory `get_summary_client()` : lit `AI_PROVIDER_SUMMARY` ; si `ollama` et
  serveur joignable → `FallbackClient(OllamaClient, EurIAClient)` ; sinon cloud seul
- `FallbackClient.generate_summary_with_sentiment()` : `fallback_on_none=True` — bascule
  automatiquement sur EurIA si Ollama retourne `None`
- `OllamaClient.generate_summary_with_sentiment()` : override dédié avec `max_tokens=800`
  et `timeout=90` pour gérer les articles longs

### 5 scripts mis à jour

Tous utilisent désormais `get_summary_client()` au lieu de `get_ai_client()` :
`flux_watcher.py`, `get-keyword-from-rss.py`, `web_watcher.py`,
`repair_failed_summaries.py`, `Get_data_from_JSONFile_AskSummary_v2.py`

### `scripts/generate_ai_consumption_report.py`

- Tracking de la consommation Ollama dans les logs (`[Ollama] Usage`)
- Regex `USAGE_LINE_OLLAMA`, compteurs par service, agrégation dans `_provider_totals()`

### `tests/test_api_client_pure.py`

5 nouveaux tests `TestGetSummaryClient` (total : 97 tests) :
- Routage Ollama disponible → `FallbackClient(OllamaClient)`
- Fallback cloud si Ollama injoignable
- `AI_PROVIDER_SUMMARY` vide → client cloud
- `generate_summary_with_sentiment` → `None` déclenche fallback cloud
- `generate_summary` → `None` sans fallback (comportement normal)

### `.env.example`

```env
# IA Locale — Ollama (Option B : résumés d'articles)
AI_PROVIDER_SUMMARY=ollama  # ~789K tokens/j économisés
```

---

# 07/04/2026 — Inférence NER/sentiment locale via Ollama (v2.7.0)

## Option A — Ollama local pour NER et sentiment batch

Ajout d'un troisième provider IA dédié aux tâches structurées batch (NER et
sentiment), exploitant les GPU/NPU locaux (Metal/Neural Engine sur Apple Silicon)
sans consommer de tokens API cloud.

### `utils/api_client.py` — `OllamaClient` + `get_ner_client()`

- Nouveau classe `OllamaClient(EurIAClient)` : endpoint `http://{OLLAMA_HOST}:11434/v1/chat/completions`, sans credentials    
  - Tous les appels sont tracés dans les logs avec le préfixe `[Ollama/<modèle>]`
  - `OllamaClient._ollama_host()` lit la variable `OLLAMA_HOST` (défaut `localhost`, mettre `host.docker.internal` dans Docker sur macOS)
  - `OllamaClient.is_available()` et `OllamaClient.list_models()` — sondes sans authentification
- Nouvelle fonction `get_ner_client()` : retourne `OllamaClient` si `AI_PROVIDER_NER=ollama` et serveur joignable, sinon bascule transparente sur le client cloud principal — aucune modification requise dans les scripts appelants
- `get_ai_client()` étendu : branche `AI_PROVIDER=ollama` (utilisation directe d'Ollama comme provider principal)

### `utils/config.py` — Validation étendue

- `AI_PROVIDER=ollama` désormais accepté sans erreur de validation (aucun credentials requis)
- Message d'erreur mis à jour : `Valeurs acceptées: 'euria', 'claude', 'ollama'`

### `scripts/enrich_entities.py` + `scripts/enrich_sentiment.py`

- Import de `get_ner_client` ajouté
- Appel `get_ai_client()` remplacé par `get_ner_client()` — routage automatique selon `AI_PROVIDER_NER`

### `docker-compose.yml`

- Variable d'environnement `OLLAMA_HOST=host.docker.internal` injectée automatiquement — le conteneur Docker peut joindre Ollama sur l'hôte macOS sans configuration supplémentaire

### `.env.example`

Nouvelles variables documentées :

```env
# IA Locale — Ollama (Option A : NER + sentiment batch uniquement)
AI_PROVIDER_NER=ollama
OLLAMA_MODEL=qwen2.5:7b
```

### `viewer/routes/settings.py`

- `POST /api/ai-check` : supporte désormais `"provider": "ollama"`
- `GET /api/ollama/status` : retourne `{ available, models, active_model, ner_provider }`
- `GET /api/ollama/models` : retourne la liste des modèles installés localement

### `viewer/src/components/SettingsPanel.jsx`

- Panneau **Réglages → Config IA** étendu avec une section « NER · Sentiment batch »
  - Pill de statut live (vert/orange selon disponibilité du serveur)
  - Bascule Cloud ↔ Ollama avec mémorisation dans `.env`
  - Chips de sélection du modèle Ollama (depuis `GET /api/ollama/models`)
  - Instructions de démarrage `brew services start ollama` affichées si hors ligne
- Bouton *Check* adapté : appelle `loadOllamaStatus()` pour le groupe Ollama

### Tests — `tests/test_api_client_pure.py`

20 nouveaux tests unitaires (sans requête réseau) :
- `TestOllamaClient` (12) : `_ollama_host`, `_default_url`, `__init__`, `is_available`, `list_models`
- `TestGetAiClientOllama` (2) : branche `AI_PROVIDER=ollama` de `get_ai_client()`
- `TestGetNerClient` (6) : routage NER selon `AI_PROVIDER_NER`, fallback si hors ligne, modèle custom

**Économies estimées :** ~165 000 tokens/jour (21% de la consommation totale) en déchargeant le NER batch sur Ollama `qwen2.5:7b` (4.7 GB, ~35–45 tok/s sur M4, 6 GB RAM unifiée).

---

# 25/03/2026 — Détection des silences + refactoring web_watcher (v2.6.0)

## `scripts/trend_detector.py` — Détection des silences (optimisation 3.7)

Ajout de la fonction `detect_silences()` : détecte les entités habituellement
actives (moy. ≥ 3 mentions/j sur 7j) qui disparaissent brusquement de l'agenda
médiatique (0 mention sur les dernières 24h).

**Nouvelle fonction :**

```
detect_silences(counts_24h, counts_7j, min_baseline_avg=3.0, top_n=10, rules=None)
```

Retourne une liste d'alertes avec `"type": "silence"` contenant :
- `entity_type`, `entity_value`, `count_24h` (= 0), `count_7j`
- `baseline_avg_per_day` : fréquence de référence (mentions/j sur 7j)
- `niveau` : `"élevé"` si avg ≥ 10/j, `"modéré"` sinon

**Intégration dans `main()` :**
- Nouveau flag `--no-silence` pour désactiver la détection
- Nouveau flag `--silence-threshold AVG` pour ajuster le seuil
- Les alertes de tendance et de silence sont combinées dans `data/alertes.json`

**Mise à jour `config/alert_rules.json` :**
- Nouveau paramètre `"silence_baseline_avg": 3.0` dans la section `global`

## `viewer/routes/analytics.py` — Support alertes de silence

- `GET /api/alerts` : nouveau paramètre `?type=silence|tendance` pour filtrer
- `POST /api/alerts/run` : nouveaux paramètres `no_silence` et `silence_threshold`

## `viewer/src/components/AlertsPanel.jsx` — Affichage des silences

- Nouveau badge compteur pour les alertes de silence (icône 🔇, fond gris)
- Rendu distinct pour les silences : fond ardoise, icône `VolumeX`, détail `baseline_avg_per_day`
- Nouveau filtre "Type" : Tendances ↑ / Silences 🔇 / Tous
- Filtre "Filtre" renommé "Niveau" pour plus de clarté

## `scripts/web_watcher.py` — Refactoring `_process_source()` (item 8)

Extraction de la logique de persistance dans une fonction dédiée :

```
_save_and_index_articles(out_path, existing_articles, new_for_48h)
```

Responsabilités : tri par date, écriture atomique, mise à jour `article_index` +
`entity_index`, mise à jour `48-heures.json` via `rolling_window`. `_process_source()`
est réduite de 100 à 50 lignes et délègue clairement à cette nouvelle fonction.

## Tests

- `tests/test_new_features.py::TestDetectSilences` — 10 nouveaux tests
  couvrant détection, niveaux, tri, top_n, filtrage par type, champs requis

---

# 25/03/2026 — Documentation complète des nouvelles fonctionnalités (v2.4)

## `scripts/USAGE.md` — Refonte complète

Le guide de référence CLI a été entièrement réécrit pour couvrir les **46 scripts** du projet (contre 15 précédemment). Chaque script est maintenant documenté avec son rôle, ses arguments CLI, des exemples d'utilisation, son entrée cron et ses sorties.

Scripts nouvellement documentés :

| Script | Rôle |
|---|---|
| `web_watcher.py` | Surveillance sources web via sitemap |
| `enrich_sentiment.py` | Enrichissement sentiment et ton éditorial |
| `enrich_images.py` | Enrichissement images (og:image / twitter:image) |
| `detect_contradictions.py` | Détection de contradictions entre sources |
| `generate_morning_digest.py` | Morning Digest quotidien |
| `generate_briefing.py` | Briefing exécutif hebdomadaire |
| `generate_reading_notes.py` | Notes de lecture par tag |
| `generate_keyword_reports.py` | Rapports Markdown par mot-clé |
| `generate_data_quality_report.py` | Rapport qualité des données |
| `generate_ai_consumption_report.py` | Rapport consommation API IA |
| `cluster_articles.py` | Clustering thématique (UI) |
| `import_obsidian_reports.py` | Sync rapports Obsidian |
| `backup_data.py` | Sauvegarde incrémentale |
| `archive_quota_state.py` | Archivage quotidien des quotas |
| `optimize_quota.py` | Optimisation hebdomadaire des quotas |
| `optimize_scoring_weights.py` | Optimisation des poids de scoring |
| `calibrate_alerts.py` | Auto-calibration des seuils d'alerte |
| `update_source_performance.py` | Scores empiriques des sources |
| `update_quality_scores.py` | Scores de qualité des articles |
| `precompute_entity_stats.py` | Pré-calcul stats entités |
| `keyword_drift_detector.py` | Détection dérive mots-clés |
| `rebuild_48h.py` | Reconstruction 48-heures.json |
| `fix_article_dates.py` | Migration normalisation dates |
| `normalize_entity_index.py` | Migration index entités v1→v2 |
| `migrate_build_indexes.py` | Migration construction des index |

## `docs/ARCHITECTURE.md` — Nouveaux modules `utils/`

Documentation des modules `utils/` créés dans les versions v2.3–v2.4 :

| Module | Rôle |
|---|---|
| `utils/rolling_window.py` | Fenêtre glissante 48h (`48-heures.json`) |
| `utils/article_merger.py` | Recherche et fusion d'articles similaires |
| `utils/async_enricher.py` | Enrichissement NER/sentiment asynchrone (aiohttp) |
| `utils/engagement_tracker.py` | Signaux d'engagement implicites (auto-apprentissage) |
| `utils/quality_monitor.py` | Score de qualité des articles (0–100) |
| `utils/quota_optimizer.py` | Optimisation automatique des quotas |
| `utils/scoring_optimizer.py` | Optimisation automatique des poids de scoring |
| `utils/source_performance.py` | Score empirique des sources (métriques réelles) |
| `utils/alert_calibrator.py` | Auto-calibration des seuils d'alerte |
| `utils/contradiction_feedback.py` | Feedback sur les contradictions détectées |
| `utils/source_registry.py` | Registre centralisé des sources surveillées |

---

# 20/03/2026 — Visualisations custom React dans le rapport cross-flux (sans Mermaid)

## `scripts/cross_flux_analysis.py` — Remplacement des blocs Mermaid

Les deux blocs Mermaid du rapport cross-flux ont été remplacés par des composants React personnalisés, plus fiables et entièrement contrôlables.

**Fonctions supprimées :**
- `_sanitize_mindmap_text()` — nettoyage pour Mermaid mindmap (obsolète)
- `_build_mermaid_mindmap_keywords()` — génération du mindmap Mermaid (obsolète)
- `_build_mermaid_top_flux()` — génération du xychart Mermaid (obsolète)

**Nouvelles fonctions :**

| Fonction | Description |
|---|---|
| `_normalize_keyword_stem(kw)` | Normalise un mot-clé vers le stem du fichier RSS correspondant (`strip().lower().replace(' ', '-')`) |
| `_build_keyword_graph_block(project_root, active_stems)` | Génère un bloc `keyword-graph` (JSON) ne contenant que les mots-clés ayant au moins un article dans la période analysée |
| `_build_flux_chart_block(flux_article_counts, flux_letter_map, top_n=15)` | Génère un bloc `flux-chart` (JSON) avec, pour chaque flux, son `name`, son `count` et sa `letter` issue de l'attribution alphabétique |

**Fonctions inchangées :**
- `_assign_flux_letters(sorted_flux_names)` — attribue A, B, C… aux flux triés alphabétiquement ; utilisé à la fois pour la liste textuelle et pour le champ `letter` du graphique

## `viewer/src/components/KeywordForceGraph.jsx` — Nouveau composant

Graphe force-directed des mots-clés WUDD.ai (remplace le mindmap Mermaid dans le rapport et dans le panneau Paramètres).

- **Props :** `{ keywords }` — tableau de `{ keyword, or, and }`
- **Interactions :** zoom/pan, slider "Liens" (facteur 0.4–3.5×), bouton "Sous-termes" (affiche/masque les termes OR/AND)
- **Couleurs :** racine violet, mots-clés bleu, termes OR teal, termes AND orange
- **Algorithme :** 280 itérations force-directed, zéro dépendance externe (SVG + React pur)

## `viewer/src/components/FluxBarChart.jsx` — Nouveau composant

Graphique à barres horizontales pour les statistiques par flux RSS (remplace le xychart Mermaid).

- **Props :** `{ items }` — tableau de `{ name, count, letter }`
- Affiche la **lettre alphabétique** assignée par Python (`flux_letter_map`) en couleur correspondant à la barre
- Tronque les noms à 22 caractères, retire le préfixe `rss:`
- Palette 10 couleurs (indigo/bleu/teal/orange), cycle automatique
- SVG pur React, zéro dépendance

## `viewer/src/components/MarkdownViewer.jsx` — Nouveaux blocs personnalisés

Deux nouveaux types de blocs de code interprétés par le rendu Markdown :

| Type de bloc | Composant rendu |
|---|---|
| ` ```keyword-graph ` | `<KeywordForceGraph keywords={JSON.parse(children)} />` dans un conteneur 600 px de hauteur |
| ` ```flux-chart ` | `<FluxBarChart items={JSON.parse(children)} />` |

Correction de `makeResponsiveSvg()` : remplacement de `height:auto` (invisible dans WebKit) par `aspect-ratio` calculé depuis le `viewBox` de l'SVG inline.

## `viewer/src/components/EntityFullReportDialog.jsx`

Même correction `makeResponsiveSvg()` (aspect-ratio) appliquée dans le `useEffect` du `MermaidBlock`.
Thème Mermaid changé de `neutral` → `default`.

## `viewer/src/components/SettingsPanel.jsx`

Le mindmap Mermaid du panneau Paramètres (onglet Mots-clés) est remplacé par `KeywordForceGraph` dans une modal plein-écran (`fixed inset-0 z-[9999]`). Tout le code Mermaid résiduel supprimé.

## `viewer/src/components/EntityGraph.jsx`

Les boutons +/– d'espacement des liens sont remplacés par un slider `<input type="range" min="0.4" max="3.5" step="0.05">` labellisé "Liens".

---

# 17/03/2026 — Couche analytique DuckDB + script d'import d'articles

## `utils/db.py` — Nouvelle couche analytique DuckDB (Optimisation 2.1)

Lecture SQL directe des fichiers JSON sans migration de données (`read_json_auto()`).
DuckDB est une dépendance optionnelle — si indisponible, le code bascule sur Python classique.

Méthodes disponibles via `get_db()` (singleton thread-safe) :

| Méthode | Description |
|---|---|
| `query_articles_by_entity(entity, days)` | Articles mentionnant une entité (18 types NER) |
| `article_stats_by_source(days)` | Statistiques par source : volume, sentiment moyen |
| `article_stats_by_day(days)` | Volume quotidien |
| `sentiment_distribution(days)` | Distribution positif/neutre/négatif avec % |
| `source_bias_stats()` | Agrège sentiment + ton éditorial par source |
| `top_sources_by_credibility()` | Sources triées par `score_source` moyen |
| `reading_time_stats(days)` | Moyenne et médiane du temps de lecture |
| `entity_json_from_file(path)` | Lecture directe d'un fichier pour `generate_48h_report.py` |

## `scripts/import_articles.py` — Nouveau script d'import

Injecte des articles depuis un fichier JSON externe dans la structure WUDD.ai.

Fonctionnalités :
- Validation des champs obligatoires (`Date de publication`, `Sources`, `URL`, `Résumé`)
- Déduplication contre les articles existants du flux cible (via `Deduplicator`)
- Destinations : `data/articles/<flux>/` ou `data/articles-from-rss/<keyword>.json`
- Mise à jour automatique de `article_index` et `entity_index` après import
- Sauvegarde atomique (`.tmp` → rename)

Options CLI : `--file`, `--flux`, `--keyword`, `--rss`, `--dry-run`, `--force`, `--validate-only`

## Accélération DuckDB dans les scripts existants

- **`scripts/generate_48h_report.py`** : `compute_top_entities()` utilise DuckDB pour lire le fichier 48h directement si disponible (évite `json.load` Python sur les grands fichiers)
- **`viewer/routes/analytics.py`** : endpoint `/api/sources/bias` utilise `db.source_bias_stats()` comme chemin rapide (bascule rglob si indisponible)
- **`scripts/trend_detector.py`** : mise à jour des seuils et règles d'alertes

## Mise à jour documentation

- `docs/ARCHITECTURE.md` v4.3 : ajout `utils/db.py` dans le diagramme utils, section dédiée `import_articles.py` + `utils/db.py`
- `README.md` : arborescence + section utilisation `import_articles.py`

---

# 07/03/2026 — Quota par entité nommée (`per_entity_daily_limit`)

## Nouveau plafond : entités nommées (`utils/quota.py`)

- `DEFAULT_CONFIG` : ajout de `per_entity_daily_limit` (défaut : `10`, max UI : `20`)
- `can_process_entities(entities)` : vérifie si un article peut être ajouté selon le plafond par entité ; retourne `(True, '')` ou `(False, nom_entité)` si une entité est saturée
- `record_article(kw, source, entities=None)` : paramètre optionnel `entities` — incrémente le compteur de chaque entité nommée présente dans l'article
- `get_stats()` : inclut désormais un champ `entities` avec le Top 20 des entités les plus présentes du jour
- `save_config()` : accepte et valide `per_entity_daily_limit`
- **Fix reset** : les trois méthodes de réinitialisation (`_reload`, `_maybe_reset_day`, `reset_day`) incluent maintenant explicitement `"entities": {}` pour garantir une remise à zéro complète à minuit

## Intégration dans les scripts

- `scripts/get-keyword-from-rss.py` : après `generate_entities()` et avant la création de l'article, appel `quota.can_process_entities(entities)` ; `record_article()` reçoit `entities` en paramètre ; log de démarrage étendu avec le plafond entité
- `scripts/flux_watcher.py` : même logique — vérification entité + passage `entities` à `record_article()`

## Onglet Quota du Viewer

- `config/quota.json` : champ `per_entity_daily_limit = 10`
- `viewer/app.py` : validation du nouveau champ entier dans `api_save_quota_config()`
- `viewer/src/components/SettingsPanel.jsx` :
  - Nouveau slider **Par entité** (curseur amber, plage 1–20) dans les plafonds journaliers
  - Nouvelle section **Entités nommées** dans la consommation du jour : Top 20 avec barres de progression et badge "Saturée" ; affichée en permanence avec état vide explicite (*"Aucune entité enregistrée aujourd'hui."*)

---

# 07/03/2026 · Chaînage entity_timeline + cross_flux + enrich_reading_time après flux_watcher

## Priorités 1 à 10 — 10 nouvelles fonctions de veille informationnelle

| # | Fonction | Fichiers |
|---|---|---|
| 1 | Déduplication 3 signaux | `utils/deduplication.py`, `get-keyword-from-rss.py` |
| 2 | Règles d'alertes configurables | `config/alert_rules.json`, `scripts/trend_detector.py` |
| 3 | Suivi temporel des entités (Timeline) | `scripts/entity_timeline.py`, endpoint Flask |
| 4 | Score de crédibilité des sources | `utils/source_credibility.py`, `config/sources_credibility.json` |
| 5 | Résumé exécutif automatisé | `scripts/generate_briefing.py`, endpoint Flask |
| 6 | Estimation du temps de lecture | `utils/reading_time.py`, `scripts/enrich_reading_time.py` |
| 7 | Analyse croisée des flux | `scripts/cross_flux_analysis.py`, endpoint Flask |
| 8 | Scoring pondéré par crédibilité | `utils/scoring.py` (multiplicateur source) |
| 9 | API 5 nouveaux endpoints Flask | `viewer/app.py` |
| 10 | Tests unitaires (50 tests) | `tests/test_new_features.py` |

## Interface mobile — toolbars bottom sheet

- **TopArticlesPanel** (`viewer/src/components/TopArticlesPanel.jsx`) : rang centré style podium (🥇🥈🥉 + cercles numérotés), toolbar transparente fixée en bas sur mobile (`bg-white/80 backdrop-blur-xl`), bouton `✕` toujours à droite
- **AlertsPanel** (`viewer/src/components/AlertsPanel.jsx`) : toolbar mobile en bas, contrôles masqués (`hidden md:flex`), fermeture à droite
- **SourceBiasPanel** (`viewer/src/components/SourceBiasPanel.jsx`) : même pattern que AlertsPanel
- **ScriptConsolePanel** (`viewer/src/components/ScriptConsolePanel.jsx`) : bottom sheet sur mobile (`items-end md:items-center`, `rounded-t-2xl`), safe-area-inset-bottom, bouton `✕` mobile dans le footer
- **App.jsx** : bouton **Biais éditoriaux** (icône `Eye`) ajouté dans la navigation bottom mobile entre Alertes et Dashboard

## Déduplication avancée (`utils/deduplication.py`)

- Classe `Deduplicator` — 3 signaux combinés : URL MD5 + résumé MD5 (200 chars) + Jaccard bigrammes (seuil configurable ≥ 0.80)
- `deduplicate()` et `deduplicate_incremental()` — statistiques `{total, unique, removed}`
- Intégré dans `scripts/get-keyword-from-rss.py` (seuil 0.85)

## Alertes configurables (`config/alert_rules.json` + `scripts/trend_detector.py`)

- `config/alert_rules.json` : seuils par type d'entité (PERSON, ORG, GPE, EVENT…), 3 niveaux (modéré/élevé/critique), filtres, webhooks Discord/Slack/Ntfy configurables
- `trend_detector.py` entièrement refactorisé : chargement dynamique des règles, `--threshold`, `--top`, `--dry-run`, `--no-notify`
- 3 nouvelles tâches cron : `trend_detector.py` (07h00), `entity_timeline.py` (07h30), `enrich_reading_time.py` (04h30 dim), `cross_flux_analysis.py` (05h30 lun)

---



## Analyse et priorisation

Après analyse de l'état de l'art en veille informationnelle, 10 nouvelles fonctions
ont été conçues et implémentées, triées par priorité décroissante :

| # | Fonction | Priorité | Fichiers créés / modifiés |
|---|----------|----------|--------------------------|
| 1 | Déduplication de contenu | 🔴 Critique | `utils/deduplication.py` + `get-keyword-from-rss.py` |
| 2 | Règles d'alertes configurables | 🔴 Critique | `config/alert_rules.json` + `trend_detector.py` |
| 3 | Suivi temporel des entités | 🟠 Élevé | `scripts/entity_timeline.py` + endpoint Flask |
| 4 | Score de crédibilité des sources | 🟠 Élevé | `utils/source_credibility.py` + `config/sources_credibility.json` |
| 5 | Résumé exécutif automatisé | 🟠 Élevé | `scripts/generate_briefing.py` + endpoint Flask |
| 6 | Estimation du temps de lecture | 🟡 Moyen | `utils/reading_time.py` + `scripts/enrich_reading_time.py` |
| 7 | Analyse croisée des flux | 🟡 Moyen | `scripts/cross_flux_analysis.py` + endpoint Flask |
| 8 | Scoring pondéré par crédibilité | 🟡 Moyen | `utils/scoring.py` (multiplicateur source) |
| 9 | API endpoints nouvelles fonctions | 🟡 Moyen | `viewer/app.py` (5 nouveaux endpoints) |
| 10 | Tests unitaires (50 tests) | 🟢 Bas | `tests/test_new_features.py` |

---

## Priorité 1 — `utils/deduplication.py` : Déduplication de contenu

- Nouveau module avec `Deduplicator` (classe) et fonctions utilitaires :
  - `compute_title_similarity(t1, t2)` : similarité Jaccard sur bigrammes de mots normalisés (insensible accents/casse)
  - `compute_resume_fingerprint(text)` : empreinte MD5 des 200 premiers caractères normalisés
  - `compute_url_fingerprint(url)` : empreinte MD5 de l'URL normalisée
  - `deduplicate(articles)` : déduplication en place, stats (`total/unique/removed`)
  - `deduplicate_incremental(new, existing)` : filtre les nouveaux articles vs existants
- **3 signaux combinés** : URL exacte + empreinte résumé MD5 + similarité titre Jaccard ≥ 0.80
- Intégration dans `get-keyword-from-rss.py` : remplacement de la déduplication par URL seule par la déduplication avancée (titre + URL + résumé)

## Priorité 2 — `config/alert_rules.json` : Règles d'alertes configurables

- Nouveau fichier de configuration pour `trend_detector.py` :
  - Seuils globaux (`threshold_ratio`, `top_n`, `min_mentions_24h`)
  - Seuils **par type d'entité** (ex: GPE seuil 2.5, EVENT seuil 1.5)
  - Types d'entités à activer/désactiver individuellement
  - Filtres (entités exclues, longueur min/max)
  - Configuration des notifications (Discord/Slack/Ntfy) avec niveaux
- `trend_detector.py` entièrement refactorisé :
  - Chargement dynamique de `alert_rules.json` (CLI surcharge la config)
  - Seuils par type d'entité respectés dans `detect_trends()`
  - Niveaux d'alerte (modéré/élevé/critique) configurables avec émojis
  - Notifications webhook optionnelles pour niveaux sélectionnés
  - `--no-notify` pour désactiver les notifications à la demande

## Priorité 3 — `scripts/entity_timeline.py` : Suivi temporel des entités

- Nouveau script qui construit la série chronologique des mentions d'entités :
  - Scanne tous les articles de `data/articles/` et `data/articles-from-rss/`
  - Produit `data/entity_timeline.json` : dates, top entités, séries complètes
  - Options : `--days`, `--top`, `--entity`, `--type`, `--dry-run`
- Endpoint Flask `GET /api/entities/timeline` avec cache 1h

## Priorité 4 — `utils/source_credibility.py` : Score de crédibilité

- `CredibilityEngine` : évalue 41 sources francophones et anglophones :
  - Scores 0–100, biais éditorial, type de média, pays, niveau de fact-checking
  - Correspondance exacte + partielle (insensible aux suffixes : "Le Monde diplomatique" → Le Monde)
  - `get_score()`, `get_multiplier()` (0.60–1.20), `get_metadata()`, `rate_articles()`
- `config/sources_credibility.json` : base de données initiale de 41 sources
- Endpoint Flask `GET /api/sources/credibility`

## Priorité 5 — `scripts/generate_briefing.py` : Résumé exécutif

- Génère un briefing Markdown quotidien (`--period daily`) ou hebdomadaire (`--period weekly`) :
  - Top entités + alertes actives + articles les mieux scorés + statistiques de sentiment
  - Synthèse narrative via EurIA (désactivable avec `--no-ai`)
  - Frontmatter YAML + sections structurées
  - Sortie : `rapports/markdown/_BRIEFING_/briefing_YYYY-MM-DD_{period}.md`
- Endpoint Flask `POST /api/briefing/generate`

## Priorité 6 — `utils/reading_time.py` : Temps de lecture estimé

- `estimate_reading_time(text, wpm=230)` : estimation basée sur 230 mots/min (adulte francophone, INSERM)
- `count_words(text)` : nettoyage URLs, HTML, Markdown avant comptage
- `enrich_reading_time(articles)` : enrichissement en masse avec `overwrite=False` par défaut
- `scripts/enrich_reading_time.py` : script CLI avec `--flux`, `--keyword`, `--dry-run`, `--force`
- Champs ajoutés : `temps_lecture_minutes` (float) et `temps_lecture_label` (str)

## Priorité 7 — `scripts/cross_flux_analysis.py` : Analyse croisée

- Détecte les entités présentes dans ≥ N flux distincts (`--min-flux 2`)
- Produit `data/cross_flux_report.json` et `rapports/markdown/_CROSSFLUX_/cross_flux_YYYY-MM-DD.md`
- Rapport avec tableau de convergence et détail par entité
- Endpoint Flask `GET /api/cross-flux`

## Priorité 8 — `utils/scoring.py` : Multiplicateur de crédibilité

- `ScoringEngine` charge maintenant `CredibilityEngine` de façon optionnelle
- Le score final de chaque article est multiplié par le score de crédibilité de sa source
  (ex: Reuters → ×1.18, source inconnue → ×0.90, source faible → ×0.72)
- Rétrocompatible : si `sources_credibility.json` est absent, comportement identique à avant

## Priorité 9 — `viewer/app.py` : 5 nouveaux endpoints API

| Route | Description |
|---|---|
| `GET /api/entities/timeline` | Série chronologique des entités |
| `GET /api/sources/credibility` | Score de crédibilité d'une source ou liste complète |
| `GET /api/alerts/rules` | Lire les règles d'alertes |
| `POST /api/alerts/rules` | Sauvegarder les règles d'alertes |
| `POST /api/briefing/generate` | Générer un briefing exécutif |
| `GET /api/cross-flux` | Analyse croisée des flux |

## Priorité 10 — `tests/test_new_features.py` : 50 tests unitaires

- Couverture : `utils/deduplication.py`, `utils/source_credibility.py`, `utils/reading_time.py`, `scripts/trend_detector.py`
- 100% de réussite

---



## `utils/quota.py` — resync disque automatique

- `get_stats()` relit maintenant `data/quota_state.json` depuis le disque à chaque appel
- Permet la synchronisation immédiate après une mise à jour externe (script `rebuild_quota.py`, autre processus cron…) sans redémarrage de Flask
- L'onglet **Quota** dans les Réglages reflète toujours la consommation réelle

## Header — suppression de « / Explorateur »

- `viewer/src/App.jsx` : le texte `/ Explorateur` à côté du logo WUDD.ai a été supprimé pour épurer le header

---

# 06/03/2026 — Système de quota adaptatif & fix sys.path Flask

## Quota adaptatif (`utils/quota.py`)

- Nouveau module `utils/quota.py` : `QuotaManager` singleton thread-safe qui régule les imports journaliers selon trois plafonds cumulatifs :
  - **Global** : nombre total d'articles/jour (défaut 150)
  - **Par mot-clé** : max articles/mot-clé/jour (défaut 30) — évite 200 articles "Trump" en une journée
  - **Par source × mot-clé** : max articles d'un même site pour un mot-clé donné (défaut 5) — garantit la diversité des sources
- **Tri adaptatif** : à chaque article traité, les mots-clés sont classés par ratio de consommation croissant → les moins alimentés sont traités en priorité, le budget inutilisé est redistribué automatiquement
- **Auto-reset à minuit** : détection de changement de date, remise à zéro des compteurs sans intervention
- **Écriture atomique** : état persisté dans `data/quota_state.json` via fichier `.tmp` (pas de corruption)
- Configuration dans `config/quota.json` : modifiable à chaud via l'UI

## Intégration dans les scripts d'import

- `scripts/get-keyword-from-rss.py` : appel `quota.can_process(kw, source)` avant tout appel EurIA + `quota.record_article()` après ajout + arrêt immédiat si `is_global_exhausted()`
- `scripts/flux_watcher.py` : même logique + tri adaptatif des mots-clés avant chaque article
- Les articles déjà indexés (doublons) ne consomment pas de quota

## Onglet "Quota" dans Réglages

- Nouveau 5ème onglet **Quota** dans `SettingsPanel.jsx` :
  - Toggle activer/désactiver la régulation
  - 3 sliders : plafond global (10–500), par mot-clé (1–100), par source (1–20)
  - Toggle tri adaptatif avec description
  - **Visualisation temps réel** : barres de progression colorées (vert → orange → rouge) par mot-clé, badges sources saturées, indicateur "Plafond atteint"
  - Bouton "Réinitialiser" (avec confirmation) pour remise à zéro manuelle

## 4 endpoints Flask

| Route | Description |
|---|---|
| `GET /api/quota/config` | Lire la configuration |
| `POST /api/quota/config` | Sauvegarder la configuration |
| `GET /api/quota/stats` | Statistiques de consommation du jour |
| `POST /api/quota/reset` | Réinitialiser les compteurs |

## Fix sys.path Flask en production Docker

- `viewer/app.py` : ajout de `sys.path.insert(0, PROJECT_ROOT)` juste après la définition de `PROJECT_ROOT`
- Sans ce fix, les imports `utils.*` échouaient avec `ModuleNotFoundError` quand Flask était lancé via `python3 /app/viewer/app.py` (le répertoire courant `/app/viewer` était ajouté à sys.path au lieu de `/app`)
- Ce correctif profite aussi aux routes existantes `utils.scoring`, `utils.exporters.*`

---

# 06/03/2026 — Sentiment, Export & Diffusion, robustesse explorateur

## Analyse de sentiment (`enrich_sentiment.py`)

- Nouveau script `scripts/enrich_sentiment.py` : enrichit chaque article avec 4 champs IA :
  - `sentiment` : `positif` / `neutre` / `négatif`
  - `score_sentiment` : 1–5 (1 = très négatif, 5 = très positif)
  - `ton_editorial` : `factuel` / `alarmiste` / `promotionnel` / `critique` / `analytique`
  - `score_ton` : 1–5 (1 = très biaisé, 5 = très factuel)
- Mode Round-Robin sur `data/articles-from-rss/` (37 fichiers, 1 fichier/jour) avec état persistant
- Sauvegarde incrémentale tous les 50 enrichissements (`SAVE_EVERY = 50`) pour éviter les pertes sur timeout
- Options CLI : `--flux`, `--keyword`, `--dry-run`, `--delay`, `--force`

## Affichage sentiment dans l'explorateur

- Nouveau composant `SentimentBadge` dans `ArticleListViewer.jsx`
- Badges colorés affichés dans la **vue grille** et la **vue timeline** pour les articles enrichis :
  - Sentiment : pastille verte/grise/rouge + label + score (ex. `Positif 4/5`)
  - Ton éditorial : badge neutre + label + score (ex. `Factuel 5/5`)
- Les articles non enrichis ne sont pas affectés (champs absents → badges masqués)

## Export & Diffusion (nouveau panel)

- Nouveau composant `ExportPanel.jsx` avec 3 onglets accessibles via le bouton **Export** (icône Share) dans le header :
  - **Atom XML** : sélection source (tout / flux / mot-clé), curseur max_entries (5–200), URL copiable, téléchargement ou aperçu
  - **Newsletter HTML** : fenêtre temporelle (24h/48h/72h/7 jours), titre personnalisable, aperçu, téléchargement HTML, envoi SMTP
  - **Webhook** : test Discord / Slack / Ntfy / Toutes, résultat inline, tableau des variables `.env`
- Routes backend déjà présentes (`/api/export/atom`, `/api/export/newsletter`, `/api/export/webhook-test`) — panel en expose l'interface

## Robustesse explorateur — fichiers markdown aléatoirement absents

- **Backend** (`viewer/app.py`) : double scan avec 200 ms d'intervalle + union par chemin pour compenser les listings incomplets de virtiofs (Docker Desktop / macOS)
- **Frontend** (`App.jsx`) : protection étendue — conserve les fichiers markdown présents dans l'état précédent mais absents de la nouvelle réponse (virtiofs, listing partiel transitoire)

---

# 06/03/2026 — Améliorations UX viewer

## Réglages — Tri alphabétique des mots-clés

- Onglet **Mots-clés** du panneau Réglages : la liste est maintenant triée par ordre alphabétique (insensible à la casse, locale française) au chargement
- Facilite la lecture et la navigation dans les listes longues de mots-clés
- Fichier modifié : `viewer/src/components/SettingsPanel.jsx` (fonction `KeywordsTab`)

---

# 04/03/2026 — Rapport quotidien Top 10 entités (48h)

## Nouveau script `generate_48h_report.py`

- Génère chaque soir à 23h00 un rapport de veille analytique depuis `data/articles-from-rss/_WUDD.AI_/48-heures.json`
- Pré-calcule les **Top 10 entités nommées** (PERSON, ORG, GPE, PRODUCT, EVENT) avant l'appel API pour garantir un comptage exact
- Sélectionne les 5 articles les plus récents par entité (~50 articles) pour respecter les limites de contexte de l'API EurIA
- Structure du rapport : frontmatter YAML · 10 sections entité (Contexte / Actualité 48h / Analyse) · Corrélations inter-entités · Constatations générales · Tableau de références
- Images intégrées au format Markdown `![](URL)` (une par section entité, sans doublon)
- Nettoyage automatique des blocs de code parasites que le LLM peut générer autour du frontmatter
- Sortie : `rapports/markdown/_WUDD.AI_/rapport_48h.md` — fichier unique remplacé chaque jour
- Mode test : `--dry-run` (affiche Top 10 + prompt sans appel API)
- Cron ajouté dans `archives/crontab` : `0 23 * * *`
- Documentation : `scripts/USAGE.md` §8, `CLAUDE.md` (tables Key Scripts et Scheduled cron jobs)

# 28/02/2026 — Dashboard entités, export article, correction API

## Viewer — Détail entités avec export

- Nouveau composant `EntityArticlePanel` : cliquer sur une entité dans le Dashboard Entités ouvre la liste des articles la mentionnant
- Bouton **Générer un rapport** : télécharge un rapport Markdown (`rapport_<TYPE>_<valeur>_YYYY-MM-DD.md`) dans le dossier Téléchargements
- Bouton **Exporter JSON** : télécharge les articles filtrés (`entites_<TYPE>_<valeur>_YYYY-MM-DD.json`) dans le dossier Téléchargements
- Nouveau endpoint Flask `GET /api/entities/articles?type=PRODUCT&value=ChatGPT`
- 2 nouvelles captures d'écran dans `docs/Screen-captures/` : `WWUD.ai-Viewer-entities.png`, `WWUD.ai-Viewer-entity-detail.png`

## Correction bug API (résumés en erreur)

- Fix critique : `if e.response` → `if e.response is not None` dans `utils/api_client.py` et `utils/http_utils.py` — `bool(requests.Response)` retourne `False` pour tout code HTTP ≥ 400, masquant le code d'erreur réel
- `ask()` lève désormais `RuntimeError` au lieu de retourner une chaîne d'erreur silencieusement sauvegardée en JSON
- Ajout de la troncature à 15 000 caractères dans `generate_summary()` pour respecter la limite documentée de l'API
- Nouveau script `scripts/repair_failed_summaries.py` : détecte et régénère les résumés en erreur (220 articles réparés le 28/02/2026)
- README mis à jour : section §5 Viewer (captures entités), §4 (script réparation, format JSON complet avec `entities` et `Images`)

# 26/02/2026 — Viewer web (Flask + React)

- Ajout du Viewer WUDD.ai : interface locale de navigation/lecture/édition des fichiers JSON et Markdown
- Backend Flask (`viewer/app.py`) : API REST, navigation fichiers, recherche plein texte, gestion flux et planification
- Frontend React 18 + Vite + Tailwind : `JsonViewer`, `MarkdownViewer`, `SearchOverlay`, `SettingsPanel`, `SchedulerPanel`, `Sidebar`
- Démarrage dev : `bash viewer/start.sh` — production : port 5050 via `entrypoint.sh` Docker
- 7 captures d'écran ajoutées dans `docs/Screen-captures/`
- Documentation mise à jour : README (section 5), CLAUDE.md, ARCHITECTURE.md (ADR-007), STRUCTURE.md, DOCS_INDEX.md
- Fix Docker : `viewer/package-lock.json` versionné pour `npm ci`

# 21/02/2026 - Vérification conformité orchestrations

- Toutes les tâches planifiées (scheduler, extraction par mot-clé, monitoring, test cron) sont orchestrées exclusivement dans Docker (cron du conteneur analyse-actualites).
- Aucune tâche cron n’est programmée sur l’hôte.
### Ajout du script get-keyword-from-rss.py (20/02/2026)

- Nouveau script : `get-keyword-from-rss.py` (extraction quotidienne par mot-clé depuis tous les flux RSS)
- Génère un fichier JSON par mot-clé dans `data/articles-from-rss/`, sans doublon
- Résumé IA et images principales extraites
- Intégration au scheduler via cron (1h00 chaque jour)
- Documentation mise à jour (README.md, USAGE.md, ARCHITECTURE.md)

# Changements apportés - Restructuration du 23 janvier 2026

## 🎯 Objectif
Réorganisation complète du projet AnalyseActualités pour améliorer la maintenabilité, l'évolutivité et la clarté de la structure, avec implémentation de chemins absolus automatiques.

## ✅ Actions réalisées

### Version 2.0 - Chemins absolus (23/01/2026 - après-midi)

#### Problème résolu
Scripts v1.0 (chemins relatifs) causaient des erreurs `FileNotFoundError` quand exécutés depuis un autre répertoire ou via raccourcis macOS.

#### Solution implémentée
Détection automatique du répertoire du projet via `__file__` :
```python
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_ARTICLES_DIR = os.path.join(PROJECT_ROOT, "data", "articles")
# ...
```

#### Fichiers modifiés
- ✅ `scripts/Get_data_from_JSONFile_AskSummary.py` : Chemins absolus + création auto dossiers
- ✅ `.github/copilot-instructions.md` : Mise à jour complète (v2.0)
- ✅ `STRUCTURE.md` : Documentation chemins absolus
- ✅ `README.md` : Clarification utilisation v2.0
- ✅ `ARCHITECTURE.md` : Documentation technique complète (NOUVEAU)

#### Nouveaux fichiers
- ✅ `ARCHITECTURE.md` - Documentation architecturale complète (diagrammes, flux, ADRs)

#### Bénéfices
- ✅ Scripts fonctionnent depuis n'importe quel répertoire
- ✅ Compatible raccourcis macOS
- ✅ Compatible automatisation (cron, GitHub Actions)
- ✅ Création automatique des dossiers manquants

### Version 1.0 - Restructuration initiale (23/01/2026 - matin)

### 1. Création de la structure de dossiers
- ✅ `scripts/` - Scripts Python exécutables
- ✅ `config/` - Fichiers de configuration
- ✅ `data/articles/` - Articles JSON générés
- ✅ `data/raw/` - Données brutes (texte, HTML)
- ✅ `rapports/markdown/` - Rapports Markdown
- ✅ `rapports/pdf/` - Rapports PDF
- ✅ Renommage : `Anciennes versions/` → `archives/`

### 2. Migration des fichiers

#### Scripts (→ `scripts/`)
- `Get_data_from_JSONFile_AskSummary.py`
- `Get_htmlText_From_JSONFile.py`
- `articles_json_to_markdown.py`

#### Configuration (→ `config/`)
- `sites_actualite.json` (133 sources)
- `categories_actualite.json` (215 catégories)
- `prompt-rapport.txt`

#### Données (→ `data/articles/`)
- `articles_generated_2025-12-01_2025-12-28.json`
- `articles_generated_2026-01-01_2026-01-18.json`

#### Rapports (→ `rapports/`)
- `rapport_complet_ia_gouvernement.md` → `rapports/markdown/`
- `rapport_sommaire_articles_generated_2025-12-01_2025-12-28.md` → `rapports/markdown/`
- `rapport_sommaire_articles_generated_2026-01-01_2026-01-18.md` → `rapports/markdown/`
- `rapport_sommaire_articles_generated_2025-12-01_2025-12-28.pdf` → `rapports/pdf/`

### 3. Mise à jour des scripts

#### `Get_htmlText_From_JSONFile.py`
**Avant** :
```python
output_file = 'all_articles.txt'
```
**Après** :
```python
output_file = '../data/raw/all_articles.txt'
```

#### `Get_data_from_JSONFile_AskSummary.py`
**Avant** :
```python
file_output = f"articles_generated_{date_debut}_{date_fin}.json"
report_file = f"rapport_sommaire_{file_output.replace('.json', '.md')}"
```
**Après** :
```python
file_output = f"../data/articles/articles_generated_{date_debut}_{date_fin}.json"
base_filename = os.path.basename(file_output)
report_file = f"../rapports/markdown/rapport_sommaire_{base_filename.replace('.json', '.md')}"
```

### 4. Nouveaux fichiers créés

#### Documentation
- ✅ `README.md` - Documentation principale (5866 octets)
- ✅ `STRUCTURE.md` - Documentation de la structure du projet
- ✅ `scripts/USAGE.md` - Guide d'utilisation des scripts

#### Configuration projet
- ✅ `.gitignore` - Fichiers à ignorer (Python + macOS + projet)
- ✅ `requirements.txt` - Dépendances Python
  ```
  requests>=2.31.0
  beautifulsoup4>=4.12.0
  python-dotenv>=1.0.0
  ```

#### Historique
- ✅ `CHANGELOG.md` - Ce fichier

## 📊 Comparaison avant/après

### Avant (structure plate)
```
AnalyseActualités/
├── Get_data_from_JSONFile_AskSummary.py
├── Get_htmlText_From_JSONFile.py
├── articles_json_to_markdown.py
├── sites_actualite.json
├── categories_actualite.json
├── articles_generated_*.json (×2)
├── rapport_*.md (×3)
├── rapport_*.pdf (×1)
└── Anciennes versions/
```
**Problèmes** :
- Tous les fichiers mélangés à la racine
- Difficile de distinguer scripts, config, données, rapports
- Pas de documentation centralisée

### Après (structure organisée)
```
AnalyseActualités/
├── scripts/          # Scripts exécutables
├── config/           # Configuration
├── data/            # Données (articles, raw)
├── rapports/        # Rapports (md, pdf)
├── archives/        # Anciennes versions
├── tests/           # Tests (vide)
├── .github/         # Config GitHub
├── README.md        # Documentation
├── STRUCTURE.md     # Structure détaillée
├── CHANGELOG.md     # Historique
├── .gitignore       # Exclusions Git
└── requirements.txt # Dépendances
```
**Avantages** :
- ✅ Séparation claire des responsabilités
- ✅ Chemins prévisibles et standardisés
- ✅ Documentation complète
- ✅ Facile à versionner avec Git
- ✅ Prêt pour collaboration

## 🔧 Compatibilité et rétrocompatibilité

### ⚠️ Breaking changes
Les scripts doivent maintenant être exécutés depuis le dossier `scripts/` :
```bash
# ❌ Ancien (ne fonctionne plus)
python3 Get_data_from_JSONFile_AskSummary.py

# ✅ Nouveau
cd scripts/
python3 Get_data_from_JSONFile_AskSummary.py
```

### 🔄 Migration pour les utilisateurs

Si vous avez des scripts personnalisés qui référencent les anciens chemins :

1. **Mettre à jour les chemins absolus** :
   ```python
   # Avant
   with open('sites_actualite.json', 'r') as f:
   
   # Après
   with open('../config/sites_actualite.json', 'r') as f:
   ```

2. **Mettre à jour les commandes** :
   ```bash
   # Ajouter 'cd scripts/' avant l'exécution
   cd scripts/
   python3 votre_script.py
   ```

## 📈 Bénéfices mesurables

1. **Organisation** : 100% des fichiers dans des dossiers logiques
2. **Documentation** : 3 nouveaux fichiers de documentation
3. **Maintenabilité** : Chemins relatifs cohérents
4. **Versioning** : `.gitignore` complet pour Git
5. **Onboarding** : Guide d'utilisation pour nouveaux contributeurs

## 🚀 Prochaines étapes recommandées

1. **Tests** : Créer des tests unitaires dans `/tests/`
2. **CI/CD** : Configurer GitHub Actions pour tests automatiques
3. **Docker** : Créer un Dockerfile pour faciliter le déploiement
4. **Documentation API** : Documenter les fonctions avec Sphinx
5. **Versioning** : Initialiser un dépôt Git si pas déjà fait

## 🐛 Problèmes connus

Aucun problème connu après la restructuration. Les dépendances sont installées et les imports fonctionnent correctement.

## 📝 Checklist de vérification

- ✅ Tous les dossiers créés
- ✅ Tous les fichiers déplacés
- ✅ Scripts mis à jour avec nouveaux chemins
- ✅ Documentation créée (README, STRUCTURE, USAGE)
- ✅ .gitignore créé
- ✅ requirements.txt créé
- ✅ Dépendances Python vérifiées
- ✅ Imports des scripts testés

## 🔒 Sauvegardes

Tous les fichiers originaux ont été préservés dans le dossier `archives/` avant toute modification.

## 📧 Support

Pour toute question sur cette restructuration :
- **Auteur** : Patrick Ostertag
- **Email** : patrick.ostertag@gmail.com
- **Date** : 23 janvier 2026

---

*Restructuration effectuée avec succès - Projet AnalyseActualités v2.0*
