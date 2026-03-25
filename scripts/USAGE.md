# Guide d'utilisation des scripts — WUDD.ai

Ce guide décrit tous les scripts disponibles dans `scripts/`, leur rôle, leurs arguments CLI et leur comportement en production.

> **Prérequis** : fichier `.env` à la racine du projet configuré avec `URL`, `bearer` et `REEDER_JSON_URL`. Voir `.env.example` pour la liste complète.
> Les scripts peuvent être lancés **depuis n'importe quel répertoire** — ils utilisent des chemins absolus calculés à partir de `__file__`.

---

## 📋 Index des scripts

| # | Script | Rôle | Cron |
|---|--------|------|------|
| 1 | [`Get_data_from_JSONFile_AskSummary_v2.py`](#1-get_data_from_jsonfile_asksummary_v2py) | Script ETL principal | Manuel / schedulé |
| 2 | [`scheduler_articles.py`](#2-scheduler_articlespy) | Orchestration multi-flux | Lundi 06h00 |
| 3 | [`flux_watcher.py`](#3-flux_watcherpy) | Surveillance RSS round-robin | Toutes les 5 min |
| 4 | [`get-keyword-from-rss.py`](#4-get-keyword-from-rsspy) | Extraction RSS par mot-clé | Toutes les 2h |
| 5 | [`web_watcher.py`](#5-web_watcherpy) | Surveillance sources web sans RSS | Toutes les 2h |
| 6 | [`enrich_entities.py`](#6-enrich_entitiespy) | Enrichissement NER post-hoc | Nuit 02h00 |
| 7 | [`enrich_sentiment.py`](#7-enrich_sentimentpy) | Enrichissement sentiment | Nuit 03h00 |
| 8 | [`enrich_images.py`](#8-enrich_imagespy) | Enrichissement images (og:image) | Nuit 02h30 |
| 9 | [`enrich_reading_time.py`](#9-enrich_reading_timepy) | Calcul temps de lecture | Enchaîné flux_watcher |
| 10 | [`enrich_source_credibility.py`](#10-enrich_source_credibilitypy) | Crédibilité des sources | Hebdo dimanche |
| 11 | [`trend_detector.py`](#11-trend_detectorpy) | Détection de tendances | 07h00 quotidien |
| 12 | [`detect_contradictions.py`](#12-detect_contradictionspy) | Détection de contradictions | À la demande |
| 13 | [`generate_48h_report.py`](#13-generate_48h_reportpy) | Rapport Top 10 entités 48h | 23h00 quotidien |
| 14 | [`generate_morning_digest.py`](#14-generate_morning_digestpy) | Morning digest | 07h30 quotidien |
| 15 | [`generate_briefing.py`](#15-generate_briefingpy) | Briefing exécutif | Lundi 06h30 |
| 16 | [`generate_reading_notes.py`](#16-generate_reading_notespy) | Notes de lecture par tag | 08h00 quotidien |
| 17 | [`generate_keyword_reports.py`](#17-generate_keyword_reportspy) | Rapports par mot-clé | Mensuel |
| 18 | [`generate_data_quality_report.py`](#18-generate_data_quality_reportpy) | Rapport qualité données | À la demande |
| 19 | [`generate_ai_consumption_report.py`](#19-generate_ai_consumption_reportpy) | Rapport consommation IA | À la demande |
| 20 | [`radar_wudd.py`](#20-radar_wuddpy) | Radar thématique mensuel | Mensuel 05h00 |
| 21 | [`cross_flux_analysis.py`](#21-cross_flux_analysispy) | Analyse croisée multi-flux | Enchaîné flux_watcher |
| 22 | [`entity_timeline.py`](#22-entity_timelinepy) | Série temporelle des entités | Enchaîné flux_watcher |
| 23 | [`cluster_articles.py`](#23-cluster_articlespy) | Clustering thématique | À la demande (UI) |
| 24 | [`analyse_thematiques.py`](#24-analyse_thematiquespy) | Analyse thématique sociétale | À la demande |
| 25 | [`repair_failed_summaries.py`](#25-repair_failed_summariespy) | Réparation résumés en erreur | Dimanche 04h00 |
| 26 | [`repair_failed_enrichments.py`](#26-repair_failed_enrichmentspy) | Réparation enrichissements en erreur | 03h30 quotidien |
| 27 | [`import_articles.py`](#27-import_articlespy) | Import d'articles externes | À la demande |
| 28 | [`import_obsidian_reports.py`](#28-import_obsidian_reportspy) | Sync rapports Obsidian | À la demande |
| 29 | [`backup_data.py`](#29-backup_datapy) | Sauvegarde incrémentale | 01h00 quotidien |
| 30 | [`archive_quota_state.py`](#30-archive_quota_statepy) | Archivage état quotas | 00h05 quotidien |
| 31 | [`optimize_quota.py`](#31-optimize_quotapy) | Optimisation des quotas | Lundi 05h45 |
| 32 | [`optimize_scoring_weights.py`](#32-optimize_scoring_weightspy) | Optimisation poids de scoring | Lundi 05h30 |
| 33 | [`calibrate_alerts.py`](#33-calibrate_alertspy) | Auto-calibration seuils d'alerte | Quotidien |
| 34 | [`update_source_performance.py`](#34-update_source_performancepy) | Scores empiriques des sources | Mensuel |
| 35 | [`update_quality_scores.py`](#35-update_quality_scorespy) | Scores de qualité articles | Hebdomadaire |
| 36 | [`precompute_entity_stats.py`](#36-precompute_entity_statspy) | Pré-calcul stats entités | Enchaîné flux_watcher |
| 37 | [`benchmark_indexes.py`](#37-benchmark_indexespy) | Benchmark des index | Développement |
| 38 | [`articles_json_to_markdown.py`](#38-articles_json_to_markdownpy) | JSON → Markdown (flux) | À la demande |
| 39 | [`articles_rss_to_markdown.py`](#39-articles_rss_to_markdownpy) | JSON → Markdown (RSS) | Mensuel 05h30 |
| 40 | [`keyword_drift_detector.py`](#40-keyword_drift_detectorpy) | Dérive des mots-clés | À la demande |
| 41 | [`check_cron_health.py`](#41-check_cron_healthpy) | Monitoring des jobs cron | Toutes les 10 min |
| 42 | [`migrate_build_indexes.py`](#42-migrate_build_indexespy) | Migration : construction des index | Migration unique |
| 43 | [`normalize_entity_index.py`](#43-normalize_entity_indexpy) | Migration : normalisation index | Migration unique |
| 44 | [`rebuild_48h.py`](#44-rebuild_48hpy) | Reconstruction 48-heures.json | À la demande |
| 45 | [`fix_article_dates.py`](#45-fix_article_datespy) | Migration : normalisation des dates | Migration unique |
| 46 | [`Get_htmlText_From_JSONFile.py`](#46-get_htmltext_from_jsonfilepy) | Extraction texte brut (GUI) | À la demande |

---

## 📝 Référence détaillée

### 1. Get_data_from_JSONFile_AskSummary_v2.py

**Description** : Script ETL principal — récupère les articles d'un flux JSON distant, génère un résumé IA (EurIA ou Claude), extrait les entités NER et les images principales, sauvegarde le tout dans `data/articles/<flux>/` et génère un rapport Markdown.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Nom du flux (sous-dossier dans `data/articles/`) | Obligatoire |
| `--date_debut` | Date de début au format `YYYY-MM-DD` | 1er du mois courant |
| `--date_fin` | Date de fin au format `YYYY-MM-DD` | Aujourd'hui |

**Utilisation** :
```bash
# Flux avec plage de dates explicite
python3 scripts/Get_data_from_JSONFile_AskSummary_v2.py --flux Intelligence-artificielle --date_debut 2026-02-01 --date_fin 2026-02-28

# Dates par défaut (1er du mois → aujourd'hui)
python3 scripts/Get_data_from_JSONFile_AskSummary_v2.py --flux Economie-numerique
```

**Prérequis** : `.env` avec `REEDER_JSON_URL`, `URL`, `bearer`. Le flux doit être configuré dans `config/flux_json_sources.json`.

**Sorties** :
- `data/articles/<flux>/articles_generated_<date_debut>_<date_fin>.json`
- `rapports/markdown/<flux>/rapport_sommaire_articles_generated_<date_debut>_<date_fin>.md`

---

### 2. scheduler_articles.py

**Description** : Orchestrateur multi-flux. Lit `config/flux_json_sources.json` et exécute `Get_data_from_JSONFile_AskSummary_v2.py` sur chaque flux configuré, avec gestion adaptative de la fréquence.

**Utilisation** :
```bash
python3 scripts/scheduler_articles.py
```

**Automatisation (cron)** :
```
0 6 * * 1 root cd /app && python3 scripts/scheduler_articles.py 2>&1 | tee -a /app/rapports/cron_scheduler.log
```

---

### 3. flux_watcher.py

**Description** : Surveillance round-robin des flux RSS de `data/WUDD.opml`. Traite **un seul flux par exécution** (rotation circulaire). Pour chaque article récent (≤ 7 jours) dont le titre correspond à un mot-clé de `config/keyword-to-search.json`, génère un résumé IA + NER + image et l'ajoute sans doublon dans `data/articles-from-rss/<keyword>.json`. Met à jour `48-heures.json` de façon incrémentale.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Affiche le flux sélectionné sans traitement IA ni écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/flux_watcher.py
python3 scripts/flux_watcher.py --dry-run
```

**Automatisation (cron)** — toutes les 5 minutes, enchaîné avec les calculs locaux :
```
*/5 * * * * root cd /app && { python3 scripts/flux_watcher.py 2>&1 | tee -a /app/rapports/cron_flux_watcher.log; python3 scripts/entity_timeline.py >> /app/rapports/cron_flux_watcher.log 2>&1; python3 scripts/cross_flux_analysis.py >> /app/rapports/cron_flux_watcher.log 2>&1; python3 scripts/enrich_reading_time.py >> /app/rapports/cron_flux_watcher.log 2>&1; }
```

**Sorties** :
- `data/articles-from-rss/<keyword>.json` — mis à jour incrémentiellement
- `data/articles-from-rss/_WUDD.AI_/48-heures.json` — fenêtre glissante 48h
- `data/flux_watcher_state.json` — état du round-robin

---

### 4. get-keyword-from-rss.py

**Description** : Extraction quotidienne des articles contenant un mot-clé (défini dans `config/keyword-to-search.json`) depuis tous les flux RSS de `data/WUDD.opml`. Pour chaque mot-clé, génère un fichier JSON dans `data/articles-from-rss/` (sans doublon), avec résumé IA et images principales.

La **déduplication avancée** (`utils/deduplication.py`) est appliquée automatiquement en cascade selon trois signaux :

| Signal | Cas détectés | Coût |
|---|---|---|
| **URL normalisée (MD5)** | Même article, paramètres tracking différents | O(1) |
| **Empreinte MD5 du résumé** | Dépêches AFP/Reuters reprises par N sites | O(1) |
| **Jaccard bigrammes des titres** ≥ 0.85 | Titres reformulés, variantes | O(n) |

**Filtrage avancé (OR / AND)** via `keyword-to-search.json` :
```json
{ "keyword": "Intelligence artificielle", "or": ["AI", "IA"] }
{ "keyword": "UBS", "and": ["banque", "bank"] }
```

**Utilisation** :
```bash
python3 scripts/get-keyword-from-rss.py
```

**Automatisation (cron)** — toutes les 2h de 06h00 à 22h00 :
```
0 6,8,10,12,14,16,18,20,22 * * * root cd /app && python3 scripts/get-keyword-from-rss.py 2>&1 | tee -a /app/rapports/cron_get_keyword.log
```

**Sortie** : `data/articles-from-rss/<mot-clé>.json`

---

### 5. web_watcher.py

**Description** : Surveillance de sources web **sans flux RSS** via `sitemap.xml`. Pour chaque source définie dans `config/web_sources.json`, scanne le sitemap, extrait le texte HTML des nouvelles URLs (filtrées par `url_pattern`), génère un résumé IA et sauvegarde dans `data/articles-from-rss/`. Limite : max 5 articles par source par exécution.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--source NOM` | Traiter uniquement cette source | toutes |

**Utilisation** :
```bash
python3 scripts/web_watcher.py
python3 scripts/web_watcher.py --source "Tech Radar"
python3 scripts/web_watcher.py --dry-run
```

**Automatisation (cron)** — toutes les 2h :
```
0 */2 * * * root cd /app && python3 scripts/web_watcher.py 2>&1 | tee -a /app/rapports/cron_web_watcher.log
```

**Fichiers d'état** :
- `data/web_watcher_state.json` — URLs déjà traitées (déduplication inter-runs)

---

### 6. enrich_entities.py

**Description** : Enrichit les fichiers JSON d'articles existants avec les **entités nommées (NER)** extraites via l'API IA. Ajoute le champ `entities` (18 types : PERSON, ORG, GPE, LOC, PRODUCT, EVENT, etc.) à chaque article disposant d'un `Résumé`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Restreindre au sous-dossier `data/articles/<NOM>/` | tous |
| `--keyword MOT` | Restreindre au fichier `data/articles-from-rss/<MOT>.json` | tous |
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--delay SEC` | Pause entre chaque appel API (secondes) | 1.0 |
| `--force` | Re-traiter les articles ayant déjà le champ `entities` | désactivé |

**Utilisation** :
```bash
python3 scripts/enrich_entities.py
python3 scripts/enrich_entities.py --flux Intelligence-artificielle
python3 scripts/enrich_entities.py --keyword anthropic --delay 2.0
python3 scripts/enrich_entities.py --dry-run
python3 scripts/enrich_entities.py --force
```

**Automatisation (cron)** — nuit à 02h00, round-robin 1 fichier/jour :
```
0 2 * * * root cd /app && python3 scripts/enrich_entities.py 2>&1 | tee -a /app/rapports/cron_enrich.log
```

---

### 7. enrich_sentiment.py

**Description** : Enrichit les articles avec l'**analyse de sentiment** et le **ton éditorial** via l'API IA. Ajoute 4 champs : `sentiment` (positif/neutre/négatif), `score_sentiment` (1–5), `ton_editorial` (factuel/engagé/polémique…), `score_ton` (1–5). Mode round-robin : 1 fichier par exécution.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Restreindre à un flux | tous |
| `--keyword MOT` | Restreindre à un mot-clé | tous |
| `--all` | Forcer le traitement de tous les fichiers en une passe | désactivé |
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--force` | Ré-analyser les articles déjà enrichis | désactivé |
| `--delay SEC` | Pause entre appels API | 0.5 |
| `--status` | Affiche les statistiques sans traitement | désactivé |
| `--max-articles N` | Limiter le nombre d'articles à enrichir | 100 |

**Utilisation** :
```bash
python3 scripts/enrich_sentiment.py
python3 scripts/enrich_sentiment.py --keyword ia --force
python3 scripts/enrich_sentiment.py --status
python3 scripts/enrich_sentiment.py --dry-run
```

**Automatisation (cron)** — nuit à 03h00 :
```
0 3 * * * root cd /app && python3 scripts/enrich_sentiment.py 2>&1 | tee -a /app/rapports/cron_sentiment.log
```

---

### 8. enrich_images.py

**Description** : Ajoute le champ `Images` aux articles qui n'en ont pas, en récupérant les métadonnées `og:image` / `twitter:image` depuis le HTML de la page source. Aucun appel à l'API IA — traitement 100 % HTTP local.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Restreindre à un flux | tous |
| `--keyword MOT` | Restreindre à un mot-clé | tous |
| `--dry-run` | Simulation sans écriture | désactivé |
| `--delay SEC` | Pause entre requêtes HTTP | 0.5 |
| `--force` | Re-fetch les articles ayant déjà des images | désactivé |

**Utilisation** :
```bash
python3 scripts/enrich_images.py
python3 scripts/enrich_images.py --flux Economie-numerique --delay 1.0
python3 scripts/enrich_images.py --dry-run
```

**Automatisation (cron)** — nuit à 02h30 :
```
30 2 * * * root cd /app && python3 scripts/enrich_images.py 2>&1 | tee -a /app/rapports/cron_images.log
```

---

### 9. enrich_reading_time.py

**Description** : Calcule et ajoute le **temps de lecture estimé** à chaque article. Basé sur 230 mots/minute (référence francophone). Traitement 100 % local, sans appel IA. Champs ajoutés : `temps_lecture_minutes` (float) et `temps_lecture_label` (ex. `"3 min"`).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--flux NOM` | Restreindre à un flux | tous |
| `--keyword MOT` | Restreindre à un mot-clé | tous |
| `--dry-run` | Simulation sans écriture | désactivé |
| `--force` | Re-calculer même les articles déjà enrichis | désactivé |

**Utilisation** :
```bash
python3 scripts/enrich_reading_time.py
python3 scripts/enrich_reading_time.py --flux Intelligence-artificielle
python3 scripts/enrich_reading_time.py --dry-run
```

**Automatisation (cron)** — enchaîné après `flux_watcher.py` toutes les 5 minutes (calcul < 1 s).

---

### 10. enrich_source_credibility.py

**Description** : Enrichit automatiquement `config/sources_credibility.json` avec trois signaux : **âge du domaine** (WHOIS), **transparence éditoriale** (scraping HTTP), **rating MBFC**. Peut aussi synchroniser de nouvelles sources depuis l'OPML et `web_sources.json`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--sync` | Synchroniser d'abord les nouvelles sources depuis OPML/web_sources.json | désactivé |
| `--sync-only` | Synchronisation seule, sans appel HTTP externe | désactivé |
| `--force` | Ré-enrichir toutes les sources (y compris déjà enrichies) | désactivé |
| `--source NOM` | Enrichir uniquement cette source | toutes |
| `--delay SEC` | Pause entre requêtes HTTP | 2.0 |
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
# Synchroniser les nouvelles sources puis enrichir les manquantes
python3 scripts/enrich_source_credibility.py --sync

# Synchronisation seule (rapide — aucun appel HTTP externe)
python3 scripts/enrich_source_credibility.py --sync-only

# Enrichir toutes les sources (re-calcul complet)
python3 scripts/enrich_source_credibility.py --sync --force

# Une source spécifique
python3 scripts/enrich_source_credibility.py --source "Le Monde"

# Simulation sans écriture
python3 scripts/enrich_source_credibility.py --dry-run
```

**Automatisation (cron)** : synchronisation hebdomadaire (dimanche 03h30) + enrichissement mensuel (1er du mois 04h30).

---

### 11. trend_detector.py

**Description** : Détecte les entités nommées en forte progression en comparant les mentions des **24 dernières heures** à la moyenne des **7 derniers jours**. Génère `data/alertes.json` consommé par le panneau Tendances & alertes du Viewer. Envoie des notifications webhook si configuré.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--top N` | Nombre d'alertes à conserver | 20 (config) |
| `--threshold RATIO` | Seuil global de ratio 24h/7j | 2.0 (config) |
| `--dry-run` | Calcule les tendances sans écrire `alertes.json` | désactivé |
| `--no-notify` | Désactive les notifications webhook | désactivé |

**Utilisation** :
```bash
python3 scripts/trend_detector.py
python3 scripts/trend_detector.py --dry-run
python3 scripts/trend_detector.py --top 15 --threshold 3.0 --no-notify
```

**Automatisation (cron)** — chaque matin à 07h00 :
```
0 7 * * * root cd /app && python3 scripts/trend_detector.py 2>&1 | tee -a /app/rapports/cron_trends.log
```

**Sortie** : `data/alertes.json`

---

### 12. detect_contradictions.py

**Description** : Détecte les **contradictions factuelles** entre sources sur le même événement. Utilise deux passes : règles déterministes (chiffres, dates, antonymes) puis arbitrage LLM pour les cas ambigus. Peut analyser un article spécifique ou scanner tout le corpus.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--article URL` | URL de l'article de référence (mode viewer) | corpus complet |
| `--days N` | Fenêtre temporelle en jours | 2 |
| `--flux NOM` | Restreindre à un flux | tous |
| `--dry-run` | Analyse sans sauvegarde | désactivé |

**Utilisation** :
```bash
# Analyser un article spécifique (depuis le Viewer)
python3 scripts/detect_contradictions.py --article "https://example.com/article"

# Scanner le corpus des 7 derniers jours
python3 scripts/detect_contradictions.py --days 7

# Simulation
python3 scripts/detect_contradictions.py --dry-run
```

**Sortie** : `data/contradictions/<MD5>.json` par article analysé.

---

### 13. generate_48h_report.py

**Description** : Génère chaque soir un **rapport de veille analytique** basé sur les Top 10 entités nommées des 48 dernières heures. Lit `data/articles-from-rss/_WUDD.AI_/48-heures.json`, pré-calcule les entités les plus citées, sélectionne les 5 articles les plus récents par entité, et génère un rapport structuré via l'API IA.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Affiche le Top 10 et le prompt sans appeler l'API | désactivé |

**Utilisation** :
```bash
python3 scripts/generate_48h_report.py
python3 scripts/generate_48h_report.py --dry-run
```

**Automatisation (cron)** — chaque soir à 23h00 :
```
0 23 * * * root cd /app && python3 scripts/generate_48h_report.py 2>&1 | tee -a /app/rapports/cron_48h_report.log
```

**Sortie** : `rapports/markdown/_WUDD.AI_/rapport_48h.md` (fichier unique, écrasé chaque jour).

---

### 14. generate_morning_digest.py

**Description** : Génère le **Morning Digest** quotidien : top stories des dernières 24h, alertes actives, synthèse IA narrative. Utilise `article_index` pour le scoring et `data/alertes.json` pour les alertes.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--ai` | Génère une synthèse narrative via l'API IA | désactivé |
| `--dry-run` | Affiche le contenu sans sauvegarder | désactivé |
| `--period {24h,48h}` | Fenêtre temporelle | 24h |
| `--top N` | Nombre d'articles dans le digest | 10 |

**Utilisation** :
```bash
python3 scripts/generate_morning_digest.py --ai
python3 scripts/generate_morning_digest.py --dry-run
```

**Automatisation (cron)** — chaque matin à 07h30 :
```
30 7 * * * root cd /app && python3 scripts/generate_morning_digest.py --ai 2>&1 | tee -a /app/rapports/cron_digest.log
```

**Sortie** : `rapports/markdown/_WUDD.AI_/morning_digest_YYYY-MM-DD.md`

---

### 15. generate_briefing.py

**Description** : Génère un **briefing exécutif** synthétisant les entités les plus importantes, les articles les mieux scorés et les tendances émergentes. Disponible en mode daily (24h) et weekly (7j). La synthèse narrative finale est générée via l'API IA.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--period {daily,weekly}` | Période du briefing | `daily` |
| `--dry-run` | Affiche le briefing sans sauvegarder ni appeler l'API | désactivé |
| `--no-ai` | Génère le briefing sans synthèse IA | désactivé |

**Utilisation** :
```bash
python3 scripts/generate_briefing.py --period daily --no-ai
python3 scripts/generate_briefing.py --period weekly
python3 scripts/generate_briefing.py --dry-run
```

**Automatisation (cron)** — chaque lundi à 06h30 (hebdomadaire) :
```
30 6 * * 1 root cd /app && python3 scripts/generate_briefing.py --period weekly 2>&1 | tee -a /app/rapports/cron_briefing.log
```

**Sortie** : `rapports/markdown/_WUDD.AI_/briefing_<period>_YYYY-MM-DD.md`

---

### 16. generate_reading_notes.py

**Description** : Génère les **notes de lecture personnalisées** organisées par tag (mot-clé) à partir des articles enrichis. Format iA Writer-compatible, avec résumés, entités et images.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Affiche sans sauvegarder | désactivé |

**Utilisation** :
```bash
python3 scripts/generate_reading_notes.py
python3 scripts/generate_reading_notes.py --dry-run
```

**Automatisation (cron)** — chaque matin à 08h00 :
```
0 8 * * * root cd /app && python3 scripts/generate_reading_notes.py 2>&1 | tee -a /app/rapports/cron_reading_notes.log
```

**Sortie** : `rapports/markdown/_WUDD.AI_/notes_lecture_YYYY-MM-DD.md`

---

### 17. generate_keyword_reports.py

**Description** : Génère un **rapport Markdown par mot-clé** pour le mois courant. Pour chaque mot-clé actif dans `config/keyword-to-search.json`, produit une synthèse IA des articles collectés, avec entités, tendances et tableau de références.

**Utilisation** :
```bash
python3 scripts/generate_keyword_reports.py
```

**Automatisation (cron)** — dernier jour du mois à 06h00 :
```
0 6 28-31 * * root [ "$(date -d tomorrow +%d)" = "01" ] && cd /app && python3 scripts/generate_keyword_reports.py 2>&1 | tee -a /app/rapports/cron_kw_reports.log
```

**Sortie** : `rapports/markdown/keyword/<keyword>/<keyword>_YYYY-MM.md`

---

### 18. generate_data_quality_report.py

**Description** : Génère un **rapport Markdown de qualité des données** : champs manquants, résumés en erreur, score de qualité moyen par flux, sources problématiques.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dir {articles,rss,all}` | Sous-répertoire à analyser | `all` |
| `--dry-run` | Affiche le rapport sur stdout sans sauvegarder | désactivé |
| `--output CHEMIN` | Chemin de sortie du rapport Markdown | `rapports/markdown/_WUDD.AI_/` |

**Utilisation** :
```bash
python3 scripts/generate_data_quality_report.py
python3 scripts/generate_data_quality_report.py --dir articles --dry-run
python3 scripts/generate_data_quality_report.py --output /tmp/quality.md
```

---

### 19. generate_ai_consumption_report.py

**Description** : Génère un **rapport de consommation de l'API IA** : appels par script, tokens estimés, taux d'erreur, coût approximatif.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Affiche les 3000 premiers caractères sans sauvegarder | désactivé |

**Utilisation** :
```bash
python3 scripts/generate_ai_consumption_report.py
python3 scripts/generate_ai_consumption_report.py --dry-run
```

**Sortie** : `rapports/markdown/_WUDD.AI_/ai_consumption_YYYY-MM-DD.md`

---

### 20. radar_wudd.py

**Description** : Génère le **radar thématique mensuel** WUDD.ai — graphique SVG à bulles positionnant les thématiques sur deux axes (volume × sentiment). Produit un fichier HTML interactif filtrable par quadrant.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--data DIR` | Répertoire des JSON WUDD.ai | `data/` |
| `--output FICHIER` | Fichier HTML de sortie | `rapports/radar_wudd.html` |

**Utilisation** :
```bash
python3 scripts/radar_wudd.py
python3 scripts/radar_wudd.py --output /tmp/radar.html
```

**Automatisation (cron)** — dernier jour du mois à 05h00 :
```
0 5 28-31 * * root [ "$(date -d tomorrow +%d)" = "01" ] && cd /app && python3 scripts/radar_wudd.py 2>&1 | tee -a /app/rapports/cron_radar.log
```

**Sortie** : `rapports/radar_wudd.html`

---

### 21. cross_flux_analysis.py

**Description** : Détecte les **entités transversales** présentes dans plusieurs flux distincts. Génère un rapport Markdown avec deux visualisations interactives (`keyword-graph` et `flux-chart`) rendues par `MarkdownViewer.jsx`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--min-flux N` | Nombre minimum de flux pour inclure une entité | 2 |
| `--top N` | Nombre d'entités à inclure | 20 |
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/cross_flux_analysis.py
python3 scripts/cross_flux_analysis.py --min-flux 3 --top 30
python3 scripts/cross_flux_analysis.py --dry-run
```

**Automatisation (cron)** — enchaîné après `flux_watcher.py` toutes les 5 minutes.

**Sorties** :
- `data/cross_flux_report.json`
- `rapports/markdown/_CROSSFLUX_/cross_flux_YYYY-MM-DD.md`

---

### 22. entity_timeline.py

**Description** : Construit la **série chronologique** des mentions d'entités nommées en scannant l'ensemble du corpus. Produit `data/entity_timeline.json` utilisé par le composant Timeline du Dashboard Viewer.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--days N` | Fenêtre temporelle en jours | 30 |
| `--top N` | Nombre d'entités à inclure | 50 |
| `--entity NOM` | Filtrer sur une entité précise | toutes |
| `--type TYPE` | Filtrer par type NER (PERSON, ORG, GPE…) | tous |
| `--dry-run` | Affiche sans écrire le fichier | désactivé |

**Utilisation** :
```bash
python3 scripts/entity_timeline.py
python3 scripts/entity_timeline.py --days 7 --top 20
python3 scripts/entity_timeline.py --entity "OpenAI" --type ORG
```

**Automatisation (cron)** — enchaîné après `flux_watcher.py` toutes les 5 minutes.

**Sortie** : `data/entity_timeline.json`

---

### 23. cluster_articles.py

**Description** : Regroupe les articles en **clusters thématiques** basés sur le partage d'entités nommées (pas de dépendance ML). Utilisé à la demande depuis le Viewer (panneau ClusterView).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--days N` | Fenêtre temporelle en jours | 7 |
| `--min-size N` | Taille minimale d'un cluster | 2 |
| `--output FICHIER` | Fichier JSON de sortie | stdout |
| `--dry-run` | Affiche sans sauvegarder | désactivé |

**Utilisation** :
```bash
python3 scripts/cluster_articles.py --days 14
python3 scripts/cluster_articles.py --min-size 3 --output data/clusters.json
python3 scripts/cluster_articles.py --dry-run
```

**Sortie** : JSON avec liste de clusters `{ entities, articles, size }`.

---

### 24. analyse_thematiques.py

**Description** : Analyse les **thématiques sociétales** présentes dans tous les articles collectés et génère un rapport statistique détaillé (12 thèmes : IA, Économie, Santé, Politique…).

**Utilisation** :
```bash
python3 scripts/analyse_thematiques.py
```

**Prérequis** :
- Fichiers JSON dans `data/articles/`
- `config/thematiques_societales.json`

**Sortie** : Rapport console avec pourcentages et exemples par thème.

---

### 25. repair_failed_summaries.py

**Description** : Détecte et régénère les résumés d'articles contenant un **message d'erreur** (ex. `"Désolé, je n'ai pas pu obtenir de réponse…"`). Utile après une indisponibilité temporaire de l'API.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dir PATH` | Répertoire à scanner | `data/articles-from-rss/` |
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--delay SECS` | Délai entre chaque appel API (secondes) | 1 |

**Utilisation** :
```bash
python3 scripts/repair_failed_summaries.py
python3 scripts/repair_failed_summaries.py --dir data/articles/Intelligence-artificielle
python3 scripts/repair_failed_summaries.py --dry-run
```

**Automatisation (cron)** — chaque dimanche à 04h00 :
```
0 4 * * 0 root cd /app && python3 scripts/repair_failed_summaries.py 2>&1 | tee -a /app/rapports/cron_repair.log
```

---

### 26. repair_failed_enrichments.py

**Description** : Détecte et réessaie l'enrichissement (NER et/ou sentiment) des articles dont le champ `enrichissement_statut` vaut `echec_api` ou `echec_parse`. Met à jour `entity_index` après chaque réparation NER réussie.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--type entities\|sentiment\|all` | Type d'enrichissement à réparer | `all` |
| `--dry-run` | Simulation sans appel API ni écriture | désactivé |
| `--delay SECS` | Délai entre chaque appel API (secondes) | 1.0 |

**Utilisation** :
```bash
python3 scripts/repair_failed_enrichments.py
python3 scripts/repair_failed_enrichments.py --type entities
python3 scripts/repair_failed_enrichments.py --type sentiment
python3 scripts/repair_failed_enrichments.py --dry-run
```

---

### 27. import_articles.py

**Description** : Injecte des articles depuis un fichier JSON externe dans la structure de données WUDD.ai. Valide les champs obligatoires, déduplique, met à jour les index.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--file CHEMIN` | Fichier JSON source à importer | obligatoire |
| `--flux NOM` | Destination flux (`data/articles/<NOM>/`) | — |
| `--keyword MOT` | Destination mot-clé (`data/articles-from-rss/<MOT>.json`) | — |
| `--rss` | Écrire dans `data/articles-from-rss/` (avec `--keyword`) | désactivé |
| `--dry-run` | Simulation sans écriture | désactivé |
| `--force` | Importer même les doublons détectés | désactivé |
| `--validate-only` | Valider le fichier sans importer | désactivé |

**Utilisation** :
```bash
python3 scripts/import_articles.py --file export.json --flux Intelligence-artificielle
python3 scripts/import_articles.py --file export.json --keyword ia --rss
python3 scripts/import_articles.py --file export.json --validate-only
python3 scripts/import_articles.py --file export.json --flux Economie --dry-run
```

---

### 28. import_obsidian_reports.py

**Description** : Synchronise les **rapports WUDD.ai** générés dans Obsidian vers les fichiers JSON d'articles et `data/entity_reports_index.json`. Idempotent — peut être rejoué sans créer de doublons.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |
| `--force` | Réimporter les rapports déjà indexés | désactivé |

**Utilisation** :
```bash
python3 scripts/import_obsidian_reports.py
python3 scripts/import_obsidian_reports.py --dry-run
python3 scripts/import_obsidian_reports.py --force
```

**Prérequis** : Variable `OBSIDIAN_VAULT_PATH` dans `.env` (chemin absolu vers le vault Obsidian). Voir aussi `docs/OBSIDIAN.md`.

---

### 29. backup_data.py

**Description** : Sauvegarde incrémentale de `data/` vers `BACKUP_L1` puis optionnellement vers `BACKUP_L2` (variables `.env`). Copie uniquement les fichiers modifiés depuis le dernier backup (basé sur mtime).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation : affiche les actions sans les exécuter | désactivé |

**Utilisation** :
```bash
python3 scripts/backup_data.py
python3 scripts/backup_data.py --dry-run
```

**Automatisation (cron)** — chaque nuit à 01h00 :
```
0 1 * * * root cd /app && python3 scripts/backup_data.py 2>&1 | tee -a /app/rapports/cron_backup.log
```

**Prérequis** : Variables `BACKUP_L1` (et optionnellement `BACKUP_L2`) définies dans `.env`.

---

### 30. archive_quota_state.py

**Description** : Archive l'état des quotas du jour précédent (`data/quota_state.json`) dans `data/quota_history/YYYY-MM-DD.json`. Utilisé par `utils/quota_optimizer.py` pour analyser les tendances d'utilisation.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/archive_quota_state.py
```

**Automatisation (cron)** — chaque nuit à 00h05 :
```
5 0 * * * root cd /app && python3 scripts/archive_quota_state.py
```

---

### 31. optimize_quota.py

**Description** : Analyse l'historique des quotas dans `data/quota_history/` et **ajuste automatiquement** les limites dans `config/quota.json` : augmente les plafonds des mots-clés saturés, réduit ceux qui sont sous-utilisés.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/optimize_quota.py
python3 scripts/optimize_quota.py --dry-run
```

**Automatisation (cron)** — chaque lundi à 05h45 :
```
45 5 * * 1 root cd /app && python3 scripts/optimize_quota.py
```

---

### 32. optimize_scoring_weights.py

**Description** : Ajuste hebdomadairement les **poids de scoring** (`config/scoring_weights.json`) en comparant les scores prédits aux signaux d'engagement réels (`utils/engagement_tracker.py`). Utilise un gradient descent simplifié avec contrainte `sum(weights) == 1.0`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/optimize_scoring_weights.py
python3 scripts/optimize_scoring_weights.py --dry-run
```

**Automatisation (cron)** — chaque lundi à 05h30 :
```
30 5 * * 1 root cd /app && python3 scripts/optimize_scoring_weights.py
```

---

### 33. calibrate_alerts.py

**Description** : **Auto-calibration quotidienne** des seuils d'alerte dans `config/alert_rules.json`. Analyse si les alertes passées ont été suivies de nouveaux articles (signal de qualité) et ajuste les seuils pour réduire les faux positifs.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/calibrate_alerts.py
python3 scripts/calibrate_alerts.py --dry-run
```

**Automatisation (cron)** — quotidien après `trend_detector.py` (ex. 07h15).

---

### 34. update_source_performance.py

**Description** : Calcule mensuellement des **métriques empiriques** par source (taux de duplication, taux d'enrichissement, diversité des entités, engagement relatif) et met à jour `config/sources_credibility.json` avec un champ `empirical_score`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |
| `--stats-only` | Affiche les métriques sans mettre à jour | désactivé |

**Utilisation** :
```bash
python3 scripts/update_source_performance.py
python3 scripts/update_source_performance.py --stats-only
python3 scripts/update_source_performance.py --dry-run
```

---

### 35. update_quality_scores.py

**Description** : Recalcule les **scores de qualité** (0–100) de tous les articles dans `data/article_index.json`. Basé sur la présence de `Résumé`, `entities`, `sentiment`, `Images`, `temps_lecture` et `score_source`.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |
| `--stats-only` | Affiche les stats sans recalculer | désactivé |

**Utilisation** :
```bash
python3 scripts/update_quality_scores.py
python3 scripts/update_quality_scores.py --stats-only
```

---

### 36. precompute_entity_stats.py

**Description** : Pré-calcule `data/entity_stats.json` depuis `data/entity_index.json` — agrégation des statistiques par entité (volume, types, distribution temporelle). Utilisé par le Viewer pour les performances d'affichage.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Calcule sans écrire le fichier de sortie | désactivé |

**Utilisation** :
```bash
python3 scripts/precompute_entity_stats.py
python3 scripts/precompute_entity_stats.py --dry-run
```

**Automatisation** — enchaîné après `flux_watcher.py` si `entity_index` a été mis à jour.

---

### 37. benchmark_indexes.py

**Description** : Mesure les **gains de performance** des index WUDD.ai en comparant les opérations clés avant (scan `rglob`) et après (lecture de l'index).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--iterations N` | Nombre de répétitions par benchmark | 3 |

**Utilisation** :
```bash
python3 scripts/benchmark_indexes.py
python3 scripts/benchmark_indexes.py --iterations 5
```

**Prérequis** : Les index doivent être construits (`migrate_build_indexes.py`).

---

### 38. articles_json_to_markdown.py

**Description** : Convertit un fichier JSON d'articles de flux (`data/articles/<flux>/`) en rapport Markdown structuré. Accepte le chemin en argument CLI ou via dialogue GUI (`tkinter`).

**Utilisation** :
```bash
python3 scripts/articles_json_to_markdown.py data/articles/Economie-numerique/articles_generated_2026-02-01_2026-02-28.json

# Mode GUI (sélection interactive)
python3 scripts/articles_json_to_markdown.py
```

**Sortie** : `rapports/markdown/<flux>/rapport_sommaire_<nom_fichier>.md`

---

### 39. articles_rss_to_markdown.py

**Description** : Convertit les fichiers JSON de `data/articles-from-rss/` en rapports Markdown annotés avec les **entités nommées en ligne**. Génère un fichier par mot-clé.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--keyword MOT` | Traiter uniquement ce mot-clé | tous |

**Utilisation** :
```bash
python3 scripts/articles_rss_to_markdown.py
python3 scripts/articles_rss_to_markdown.py --keyword anthropic
```

**Automatisation (cron)** — dernier jour du mois à 05h30 :
```
30 5 28-31 * * root [ "$(date -d tomorrow +%d)" = "01" ] && cd /app && python3 scripts/articles_rss_to_markdown.py 2>&1 | tee -a /app/rapports/cron_rss_markdown.log
```

**Sortie** : `rapports/markdown/keyword/<keyword>/<keyword>_YYYY-MM-DD.md`

---

### 40. keyword_drift_detector.py

**Description** : Détecte la **dérive des mots-clés** (Axe 6 de l'auto-apprentissage) — identifie les mots-clés dont le volume d'articles a chuté significativement sur une période donnée, suggérant un changement de terminologie ou de couverture médiatique.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--days N` | Fenêtre d'analyse en jours | 30 |
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/keyword_drift_detector.py
python3 scripts/keyword_drift_detector.py --days 60 --dry-run
```

---

### 41. check_cron_health.py

**Description** : **Sonde de santé** des jobs cron WUDD.ai. Vérifie la date de dernière exécution de chaque script et alerte (console / email optionnel) si un job est en retard.

**Configuration** : Seuils d'alerte en minutes configurables directement dans le script (`MAX_DELAY_MINUTES` par job).

**Utilisation** :
```bash
python3 scripts/check_cron_health.py
```

**Automatisation (cron)** — toutes les 10 minutes :
```
*/10 * * * * root cd /app && python3 scripts/check_cron_health.py 2>&1 | tee -a /app/rapports/cron_health.log
```

---

### 42. migrate_build_indexes.py

**Description** : **Migration unique** — construit `data/article_index.json` et `data/entity_index.json` en scannant tout le corpus `data/`. À exécuter une seule fois lors de la mise à niveau vers la v2.3+.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/migrate_build_indexes.py
python3 scripts/migrate_build_indexes.py --dry-run
```

---

### 43. normalize_entity_index.py

**Description** : **Migration v1 → v2** — normalise les clés de `data/entity_index.json` en minuscules et ajoute le champ `caps` (forme d'affichage canonique).

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |
| `--backup` | Créer une copie de sauvegarde avant migration | désactivé |

**Utilisation** :
```bash
python3 scripts/normalize_entity_index.py --backup
python3 scripts/normalize_entity_index.py --dry-run
```

---

### 44. rebuild_48h.py

**Description** : Reconstruit `data/articles-from-rss/_WUDD.AI_/48-heures.json` en agrégeant **tous les articles des 48 dernières heures** depuis les fichiers sources. À utiliser si `48-heures.json` est corrompu ou manquant.

**Utilisation** :
```bash
python3 scripts/rebuild_48h.py
```

---

### 45. fix_article_dates.py

**Description** : **Migration unique** — normalise les dates au format RFC 2822 vers `DD/MM/YYYY` dans `data/articles-from-rss/`. À exécuter lors de la migration des anciens articles.

**Arguments** :

| Argument | Description | Défaut |
|---|---|---|
| `--dry-run` | Simulation sans écriture | désactivé |

**Utilisation** :
```bash
python3 scripts/fix_article_dates.py --dry-run
python3 scripts/fix_article_dates.py
```

---

### 46. Get_htmlText_From_JSONFile.py

**Description** : Extrait le **contenu texte brut** de tous les articles d'un flux JSON. Interface GUI (`tkinter`) pour sélectionner le fichier source. Usage : analyse manuelle, débogage.

**Utilisation** :
```bash
python3 scripts/Get_htmlText_From_JSONFile.py
# Une fenêtre s'ouvre pour sélectionner un fichier JSON flux
```

**Sortie** : `data/raw/all_articles.txt`

---

## ⚙️ Système de quota adaptatif

> **Module :** `utils/quota.py` | **Config :** `config/quota.json` | **État :** `data/quota_state.json`

Le système de quota régule le nombre d'articles importés par jour via l'API IA. Il applique quatre plafonds indépendants et trie les mots-clés adaptativement.

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
| `enabled` | Active / désactive le système | `true` |
| `global_daily_limit` | Plafond journalier global | `150` |
| `per_keyword_daily_limit` | Max articles par mot-clé par jour | `30` |
| `per_source_daily_limit` | Max articles d'un même site pour un mot-clé donné | `5` |
| `per_entity_daily_limit` | Max articles contenant une même entité nommée (max 20 via UI) | `10` |
| `adaptive_sorting` | Trie les mots-clés par ratio consommation/plafond croissant | `true` |

### Fonctionnement

1. `quota.can_process(keyword, source)` — vérifie les 3 plafonds avant import
2. `quota.can_process_entities(entities)` — vérifie le plafond par entité après NER
3. `quota.record_article(keyword, source, entities)` — incrémente tous les compteurs
4. `quota.sort_by_priority(keywords)` — priorise les sujets les moins traités
5. Reset automatique à minuit (reset lazy au premier appel après minuit)

---

## 🔧 Dépannage

### Erreur : "No module named 'requests'"
```bash
pip install -r viewer/requirements.txt
```

### Erreur API EurIA / Claude
Vérifiez :
- Le token `bearer` (EurIA) ou `CLAUDE_API_KEY` (Claude) dans `.env`
- La variable `AI_PROVIDER` (`euria` ou `claude`) dans `.env`
- La validité de l'URL de l'API et la connexion internet

### Index obsolètes ou manquants
```bash
python3 scripts/migrate_build_indexes.py
```

### `48-heures.json` corrompu
```bash
python3 scripts/rebuild_48h.py
```

---

## 📊 Workflow typique

### Collecte initiale d'un nouveau flux
```bash
python3 scripts/Get_data_from_JSONFile_AskSummary_v2.py --flux MonFlux --date_debut 2026-01-01 --date_fin 2026-01-31
python3 scripts/enrich_entities.py --flux MonFlux
python3 scripts/enrich_sentiment.py --flux MonFlux
python3 scripts/enrich_images.py --flux MonFlux
```

### Maintenance quotidienne (automatisée via cron)
1. 00h05 — `archive_quota_state.py`
2. 01h00 — `backup_data.py`
3. 02h00 — `enrich_entities.py` (round-robin)
4. 02h30 — `enrich_images.py`
5. 03h00 — `enrich_sentiment.py`
6. 07h00 — `trend_detector.py`
7. 07h30 — `generate_morning_digest.py --ai`
8. 08h00 — `generate_reading_notes.py`
9. 23h00 — `generate_48h_report.py`

### Maintenance hebdomadaire (lundi)
1. 05h30 — `optimize_scoring_weights.py`
2. 05h45 — `optimize_quota.py`
3. 06h00 — `scheduler_articles.py`
4. 06h30 — `generate_briefing.py --period weekly`

---

## 📧 Support

Pour toute question : patrick.ostertag@gmail.com
