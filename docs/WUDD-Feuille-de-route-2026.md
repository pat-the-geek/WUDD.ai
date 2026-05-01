---
title: WUDD.ai — Feuille de route complète
date: 2026-04-29
version: 2.9.0
tags:
  - wudd
  - roadmap
  - technique
  - obsidian
  - veille
type: roadmap
statut: en cours
---

# WUDD.ai — Feuille de route complète
**Rapport de synthèse — 29 avril 2026 — v2.9.0**

> Mise à jour de statut du 29/04/2026 : plusieurs items techniques de l'axe 1
> sont déjà implémentés dans le code courant. Les cases ci-dessous reflètent
> désormais l'état réel vérifié.

> Addendum P1 (soir) : alignement documentaire finalisé sur les livraisons
> v2.8.12 à v2.8.14 (quota, entités, runtime Docker viewer/worker).

> Addendum P2 : **AXE 3 terminé à 100%** — 8 items restants implémentés :
> `[[wikilinks]]` entités, Nominatim fallback, `entités_geo`, notes GPE/LOC,
> frontmatter rapports, statut scheduler, template vault `samples/`.

---

## Légende des efforts

| Effort | Durée |
|---|---|
| **XS** | < 2h |
| **S** | ½ journée |
| **M** | 1 journée |
| **L** | 2–3 jours |
| **XL** | 1 semaine+ |

---

## AXE 1 — Améliorations techniques

### 1.1 Architecture backend — Critique

- [x] **`[L]`** Découper `viewer/app.py` (4 822 lignes) en blueprints Flask
	- `routes/files.py` — `/api/files`, `/api/content`, `/api/search`, `/api/download`
	- `routes/entities.py` — `/api/entities/*`, `/api/search/entity`, `/api/entity-context`, `/api/watched-entities`, `/api/annotations`
	- `routes/analytics.py` — `/api/alerts`, `/api/articles/top`, `/api/sources/*`, `/api/cross-flux`, `/api/analytics/*`, `/api/briefing`
	- `routes/export.py` — `/api/export/*`, `/api/chat/*`
	- `routes/quota.py` — `/api/quota/*`
	- `routes/settings.py` — `/api/keywords`, `/api/rss-feeds`, `/api/web-sources`, `/api/flux-sources`, `/api/env`, `/api/ai-providers`
	- `routes/scheduler.py` — `/api/scheduler`, `/api/scripts/*`
	- `viewer/state.py` — état global partagé (`_rss_job`, `_bias_cache`)
	- `viewer/helpers.py` — fonctions partagées (`safe_path()`, `collect_files()`, `_call_ai_blocking()`)
- [x] **`[S]`** Ajouter un **circuit breaker** dans `utils/api_client.py`
	- États OPEN / HALF-OPEN / CLOSED
	- Fenêtre de grâce 5 minutes après N échecs consécutifs
	- Log explicite à chaque transition d'état
- [x] **`[XS]`** Corriger les **collisions de cache entre providers IA** (`utils/cache.py`)
	- Inclure le nom du provider (`AI_PROVIDER`) dans la clé MD5
- [x] **`[XS]`** Remplacer le **reset paresseux des quotas** par un job cron explicite
	- Job `1 0 * * *` présent dans `archives/crontab` (installé via `entrypoint.sh`)
	- `utils/quota.py` : `reset_day()` publique + `_startup_reset_if_stale()` au démarrage si date ≠ aujourd'hui

### 1.1 bis Checkpoint P1 — Vérification factuelle (29/04 soir)

- [x] **`[XS]`** Aligner la documentation de référence avec l'implémentation réelle
	- `docs/ameliorations/AMELIORATIONS.md` mis à jour
	- `docs/RAPPORT_TECHNIQUE_PERFORMANCES_2026-04-29.md` actualisé (addendum post-correctifs)
- [x] **`[S]`** Optimiser la latence d'ouverture du panneau entité
	- route `/api/entities/articles` bornée en mode compact
	- fallback disque complet désactivé en mode UI compact
- [x] **`[S]`** Réduire la latence de l'onglet quotas
	- `utils/quota.py` optimisé (sync mtime/TTL, payload borné)
	- `/api/quota/stats` compact utilisé côté frontend
- [x] **`[XS]`** Valider le runtime Docker après correctifs
	- services `analyse-actualites-viewer` et `analyse-actualites-worker` démarrés
	- endpoint `/api/runtime-info` opérationnel

Preuves de traçabilité :

- `CHANGELOG.md` : v2.8.12, v2.8.13, v2.8.14
- `viewer/routes/entities.py`, `viewer/routes/quota.py`, `utils/quota.py`
- `viewer/src/components/EntityArticlePanel.jsx`, `viewer/src/components/SettingsPanel.jsx`

### 1.2 Qualité du code — Moyen terme

- [x] **`[S]`** Créer `utils/file_io.py` — wrapper centralisé `json_read()` / `json_read_safe()` / `json_write()` / `json_write_compact()` avec `ensure_ascii=False` et écriture atomique systématiques
	- Migré dans `utils/quota.py`, `utils/rolling_window.py`, `utils/synthesis_cache.py`, `utils/alert_calibrator.py`
	- 1114 tests passés sans régression
- [x] **`[S]`** Créer `utils/entity_utils.py` — abstraire la boucle `for etype, evals in entities.items()` (dupliquée dans 4+ scripts)
- [x] **`[S]`** Valider les fichiers de configuration au démarrage via `jsonschema` dans `utils/config.py` (`quota.json`, `alert_rules.json`, `flux_json_sources.json`, `keyword-to-search.json`)
	- Schémas définis en tête de `utils/config.py` : `_SCHEMA_QUOTA`, `_SCHEMA_ALERT_RULES`, `_SCHEMA_FLUX_SOURCES`, `_SCHEMA_KEYWORD_SEARCH`
	- Warnings non bloquants — un fichier invalide signalé sans empêcher le démarrage
	- `jsonschema` optionnel — ignoré silencieusement si non installé
- [x] **`[M]`** Ajouter des **React Error Boundaries** dans `App.jsx` — boundary `PanelErrorBoundary` appliquée à `EntityGraph` (KnowledgeGraph), `EntityDashboard`, `ChatbotPanel` avec fallback + actions Réessayer/Fermer
- [x] **`[M]`** Ajouter une **couche de cache frontend** (TTL 5 min) sur `EntityDashboard`, `TopArticlesPanel`, `SourceBiasPanel` — hook `useFetchCache` (`viewer/src/hooks/useFetchCache.js`), cache `Map` module-level partagé, TTL 5 min, invalidation via `reload()`
- [x] **`[S]`** Ajouter la **validation des requêtes POST Flask** sur les endpoints sensibles — helper partagé `require_json_body()` dans `viewer/helpers.py`, appliqué aux endpoints d’écriture sensibles (`/api/content`, `/api/article/refresh-resume`, `/api/articles/merge/*`, `/api/rss-feeds/save`, `/api/web-sources/*`, `/api/flux-sources`, `/api/env`, `/api/quota/config`, `/api/annotations`, `/api/watched-entities`)

### 1.3 Tests — Long terme

- [x] **`[L]`** Créer `tests/test_api_client.py` — fixtures mock, comportements d'erreur (429, 500, timeout)
- [x] **`[M]`** Créer `tests/test_cache.py` — TTL, éviction, collision de clés, provider différent
- [x] **`[M]`** Créer `tests/test_quota.py` — reset minuit, plafond par entité, adaptive sorting
- [x] **`[M]`** Créer `tests/test_http_utils.py` — retry, backoff, BeautifulSoup extraction
- [x] **`[XL]`** Créer `tests/test_viewer_app.py` — couverture des 62 endpoints Flask

### 1.4 Monitoring — Long terme

- [x] **`[L]`** Ajouter des métriques Prometheus sur les jobs cron et appels API — `utils/metrics.py` + endpoint `/metrics` + `tests/test_metrics.py` (42 tests)
- [x] **`[M]`** Documenter l'API Flask (OpenAPI/Swagger via flask-restx) — `utils/openapi.py` + endpoints `/api/openapi.json` et `/api/docs` (Swagger UI CDN) + `tests/test_openapi.py` (31 tests)
- [x] **`[M]`** Envisager SQLite au-delà de 50 000 articles pour les rebuilds d'index — Plan de migration documenté dans `docs/SQLITE_MIGRATION.md` (seuil 50k, architecture cible, estimation perf)

---

## AXE 2 — Nouvelles fonctionnalités veille

### 2.1 Entités surveillées — Critique

> Actuellement : liste de favoris avec compteur statique, totalement déconnectée du reste du pipeline.

- [x] **`[M]`** **Connecter `watched_entities.json` à `trend_detector.py`** — les entités surveillées déclenchent automatiquement une alerte si leur ratio dépasse `watched_threshold_ratio` (défaut 1.0, configurable dans `alert_rules.json`)
	- Nouvelles fonctions `_load_watched_entities()` et `detect_watched_alerts()` dans `trend_detector.py`
	- Flag `"watched": True` injecté sur chaque alerte (entités déjà en tendance marquées sans doublon)
	- Entités surveillées non tendance ajoutées en tête de liste pour visibilité garantie
	- Seuil dédié configurable : `config/alert_rules.json > global > watched_threshold_ratio`
- [x] **`[M]`** **Prioriser les entités surveillées dans `generate_briefing.py`** — section "Veille prioritaire" systématique dans le briefing (`data/watched_entities.json` chargé, mentions sur la période calculées, niveau/ratio des alertes injectés si disponibles)
- [x] **`[S]`** **Notifications push** quand une entité surveillée franchit un seuil — intégré dans `scripts/trend_detector.py` via `_send_notifications()` (fusion alertes par niveau + entités `watched=True` avec `ratio >= watched_threshold_ratio`, envoi via `utils/exporters/webhook.py`)
- [x] **`[S]`** **Mettre en cache le comptage des mentions** — endpoint `/api/watched-entities` optimisé via `EntityIndex.get_refs()` (lecture `data/entity_index.json` + cutoff 24h/7j + arrêt anticipé), suppression du scan `rglob` des JSON à chaque ouverture
- [ ] **`[M]`** **Historique de mentions** — courbe temporelle depuis `entity_timeline.json` visible dans `EntityWatchPanel`
- [ ] **`[S]`** **Rapport hebdomadaire automatique** des entités surveillées — sauvegardé dans `rapports/markdown/_WUDD.AI_/`

### 2.2 Recherche et découverte

- [ ] **`[XL]`** **Recherche sémantique par embeddings vectoriels**
	- Générer des embeddings via l'API IA pour chaque résumé d'article
	- Stocker dans un index vectoriel embarqué (`lancedb` — sans serveur)
	- Bascule "recherche exacte / recherche sémantique" dans `SearchOverlay.jsx`
- [ ] **`[L]`** **Digest personnalisé par profil d'intérêt**
	- `config/user_profiles.json` : entités favorites, thématiques, sources préférées
	- Nouveau script `generate_personal_digest.py`
	- Onglet "Profil" dans `SettingsPanel.jsx`

### 2.3 Analyse éditoriale

- [ ] **`[L]`** **Comparaison de couverture par source**
	- Pour un même événement, afficher comment chaque source le traite (ton, angle, entités citées)
	- Nouveau composant `SourceCoverageCompare.jsx`
- [ ] **`[L]`** **Tableau de bord de veille concurrentielle**
	- Définir des "cibles" dans `SettingsPanel`
	- Rapport hebdomadaire : volume mentions, sentiment moyen, sources actives, articles notables
	- Extension de `EntityWatchPanel` + `generate_briefing.py`
- [ ] **`[M]`** **Alertes prédictives** dans `trend_detector.py`
	- Projection "seuil élevé dans ~2h" via régression linéaire sur 6 dernières valeurs horaires
	- Champ `prediction_seuil_dans_minutes` dans `alertes.json`

### 2.4 Productivité

- [ ] **`[M]`** **Annotations enrichies** — étendre à toutes les vues : `ArticleListViewer`, `EntityArticlePanel`, `MarkdownViewer`
	- Tags custom, notes libres, statut workflow (À traiter / En cours / Archivé / Important)
- [ ] **`[M]`** **Newsletter intelligente avec sélection automatique**
	- Mode "auto" dans `utils/exporters/newsletter.py`
	- `ScoringEngine` sélectionne les 5 meilleurs articles non encore envoyés
- [ ] **`[S]`** **Suivi de santé des sources** — script `check_source_health.py`
	- Sources sans nouvel article depuis 7 jours
	- Sources avec taux d'erreur > 30%
	- Résultat visible dans `SettingsPanel` onglet "Web sources"

### 2.5 Fonctionnalités avancées

- [ ] **`[XL]`** **Authentification multi-utilisateurs** (JWT)
- [ ] **`[XL]`** **Détection de propagation de narratifs** — quelle source a publié en premier, qui a repris
- [ ] **`[XL]`** **Analyse de réseaux d'influence** — clusters via algorithme Louvain, hubs et ponts

---

## AXE 3 — Export Obsidian

### 3.1 Infrastructure de base

- [x] **`[S]`** Ajouter `OBSIDIAN_DIR` / `OBSIDIAN_VAULT_NAME` dans `.env.example` et `utils/config.py` avec validation
- [x] **`[S]`** Monter le vault comme volume dans `docker-compose.yml`
- [x] **`[XS]`** Créer la structure de dossiers : `Veille/articles/`, `Veille/entités/`, `Veille/rapports/`, `Veille/synthèses/`
- [x] **`[S]`** Créer `scripts/export_obsidian.py` — CLI avec argparse (`--flux`, `--keyword`, `--days`, `--dry-run`, `--force`, `--no-entities`, `--no-synthesis`)

### 3.2 Notes articles

- [x] **`[M]`** Générateur de **frontmatter YAML complet** depuis le JSON article
	- `title`, `date`, `source`, `url`, `flux`
	- `sentiment`, `score_sentiment`, `ton_editorial`, `score_ton`
	- `score_source`, `temps_lecture`, `tags`, `entités`
- [x] **`[S]`** Nommage des fichiers : `YYYY-MM-DD_source_slug-titre.md` (slug 40 caractères max)
- [x] **`[S]`** Corps de la note : Résumé, Entités avec liens `[[internes]]` par type, section Source avec crédibilité
- [x] **`[S]`** Insertion des images : `![](https://url-image)` depuis le champ `Images` existant
- [x] **`[S]`** Déduplication à l'export — MD5 résumé implémenté dans `export_obsidian.py`

### 3.3 Notes d'entités avec diagrammes Mermaid

- [x] **`[M]`** Note par entité significative (≥ 5 mentions) dans `Veille/entités/` avec frontmatter complet
- [x] **`[M]`** **Diagramme de co-occurrences** `graph TD` depuis `entity_index.json` — implémenté (Top relations)

```mermaid
graph TD
    OpenAI --- Anthropic
    OpenAI --- Sam_Altman["Sam Altman"]
    OpenAI --- GPT_5["GPT-5"]
    OpenAI --- États_Unis["États-Unis"]
```

- [x] **`[M]`** **Timeline de couverture** `timeline` depuis `entity_timeline.json` — implémenté

```mermaid
timeline
    title Couverture — OpenAI (mars 2026)
    01 mars : Le Monde · GPT-5 annoncé
    05 mars : RTS · Régulation européenne votée
    08 mars : Libération · Anthropic lève 2 milliards
```

- [x] **`[S]`** **Pie chart ton éditorial** `pie` depuis les articles enrichis filtrés sur l'entité (sentiments répartition)

```mermaid
pie title Ton éditorial — Sources IA (30 derniers jours)
    "Factuel" : 42
    "Analytique" : 28
    "Alarmiste" : 18
    "Critique" : 12
```

- [x] **`[S]`** Liste des 10 articles les plus récents en liens `[[internes]]` en fin de note

### 3.4 Géolocalisation (Map View)

- [x] **`[S]`** Identifier la GPE principale par article (première entité GPE/LOC disponible)
- [x] **`[M]`** Résolution coordonnées GPS via `data/geocode_cache.json` puis Nominatim si absent
- [x] **`[S]`** Injecter `location: [lat, lon]` dans le frontmatter (coordonnée de la GPE principale)
- [x] **`[S]`** Injecter `entités_geo` — liste GPE/LOC avec coordonnées résolues

```yaml
entités_geo:
  - name: Bruxelles
    location: [50.8503, 4.3517]
  - name: France
    location: [46.2276, 2.2137]
```

- [x] **`[S]`** Note géographique par entité GPE/LOC avec coordonnée GPS et backlinks articles

### 3.5 Notes de synthèse

- [x] **`[S]`** Copier les rapports Markdown existants dans `Veille/rapports/` avec frontmatter ajouté
- [x] **`[S]`** Note de synthèse par flux (`Veille/synthèses/<flux>.md`) : statistiques, top entités liées, liens vers derniers rapports
- [x] **`[M]`** Note index globale (`Veille/synthèses/_INDEX.md`) : tableau de bord tous flux, top 20 entités cross-flux, alertes actives — "home page" de la veille dans Obsidian

### 3.6 Intégration dans le Viewer

- [x] **`[S]`** Endpoint Flask `POST /api/export/obsidian` — paramètres : `flux`, `keyword`, `days`, `force`, `dry_run`, `no_entities`, `no_synthesis`
- [x] **`[M]`** Onglet **Obsidian** dans `ExportPanel.jsx`
	- Statut vault (chemin + accessible/inaccessible)
	- Sélecteur source, slider période, checkboxes options (géo, Mermaid, rapports)
	- Bouton "Exporter" avec streaming SSE du nombre de notes créées
- [x] **`[S]`** Bouton "Ouvrir dans Obsidian" via protocole `obsidian://open?vault=...`
- [x] **`[XS]`** Badge d'avertissement si `OBSIDIAN_DIR` non configuré

### 3.7 Automatisation

- [x] **`[S]`** Ajouter `export_obsidian.py` au crontab Docker — quotidien à 08:30 après les enrichissements
- [x] **`[XS]`** Exposer le statut du dernier export dans `/api/scheduler`

### 3.8 Documentation

- [x] **`[M]`** Créer `docs/OBSIDIAN.md` : prérequis, configuration, structure vault, format frontmatter, configuration Map View, requêtes Dataview exemples
- [x] **`[XS]`** Template de vault vide pré-configuré dans `samples/obsidian-vault-template/`

---

## AXE 4 — Copies d'écran

> Remplacer intégralement les 19 captures existantes dans `docs/Screen-captures/`

- [ ] **`[XS]`** Supprimer les 19 anciennes captures dans `docs/Screen-captures/`
- [ ] **`[XS]`** **Capture 1** — Interface principale : sidebar + liste articles JSON avec badges sentiment
- [ ] **`[XS]`** **Capture 2** — Recherche full-text ⌘K : overlay avec résultats multi-flux surlignés
- [ ] **`[XS]`** **Capture 3** — Rapport Markdown : rapport rendu avec image, sections et tableau sources
- [ ] **`[XS]`** **Capture 4** — Dashboard entités vue Liste : compteurs + sections colorées par type NER
- [ ] **`[XS]`** **Capture 5** — Graphe de co-occurrences : réseau force-layout d'une entité clé
- [ ] **`[XS]`** **Capture 6** — Top Articles podium : 3 cartes avec 🥇🥈🥉, badges sentiment/ton/lecture
- [ ] **`[XS]`** **Capture 7** — Tendances & Alertes : liste rouge/orange/jaune avec ratios
- [ ] **`[XS]`** **Capture 8** — Terminal IA : conversation en cours avec réponse Markdown streamée
- [ ] **`[XS]`** **Capture 9** — Biais éditoriaux : tableau avec barres tricolores et badges ton
- [ ] **`[XS]`** **Capture 10** — Réglages Planification : tableau cron jobs avec statuts actifs
- [ ] **`[XS]`** Mettre à jour les références aux captures dans `README.md` et `docs/ARCHITECTURE.md`

---

## Tableau de bord des priorités

### Immédiat — cette semaine

| Tâche | Axe | Effort |
|---|---|---|
| Fix cache provider IA | Tech | XS |
| Reset quota cron 00:01 | Tech | XS |
| Brancher entités surveillées sur alertes | Fonc. | M |
| Cache mentions dans EntityWatchPanel | Fonc. | S |
| Refaire les 10 copies d'écran | Comm. | ~1j |

### Court terme — 2 à 4 semaines

| Tâche | Axe | Effort |
|---|---|---|
| Split Flask blueprints | Tech | L |
| Circuit breaker API | Tech | S |
| Validation config JSON + file_io.py | Tech | S+S |
| React Error Boundaries + cache frontend | Tech | M+M |
| Export Obsidian — livrable minimal (phases 3.1 à 3.2) | Obsidian | L |
| Annotations enrichies toutes vues | Fonc. | M |
| Newsletter auto | Fonc. | M |
| Suivi santé sources | Fonc. | S |

### Moyen terme — 1 à 2 mois

| Tâche | Axe | Effort |
|---|---|---|
| Export Obsidian complet sans géo (phases 3.3 à 3.5) | Obsidian | L |
| Géolocalisation Map View (phase 3.4) | Obsidian | L |
| Tests api_client, cache, quota, Flask | Tech | XL |
| Alertes prédictives | Fonc. | M |
| Digest personnalisé | Fonc. | L |
| Comparaison couverture sources | Fonc. | L |

### Long terme — 3 à 6 mois

| Tâche | Axe | Effort |
|---|---|---|
| Recherche sémantique embeddings | Fonc. | XL |
| Veille concurrentielle | Fonc. | L |
| Authentification multi-utilisateurs | Tech | XL |
| Détection propagation narratifs | Fonc. | XL |
| Métriques Prometheus + OpenAPI | Tech | L |

---

## Estimation globale

| Axe | Effort total estimé |
|---|---|
| Améliorations techniques | ~15 jours |
| Nouvelles fonctionnalités veille | ~25 jours |
| Export Obsidian complet | ~7 jours |
| Copies d'écran | ~1 jour |
| **Total** | **~48 jours** |
