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
