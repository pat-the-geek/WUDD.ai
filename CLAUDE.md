# CLAUDE.md — AI Assistant Guide for WUDD.ai / AnalyseActualités

This file provides essential context for AI assistants working in this codebase.

## Project Overview

**WUDD.ai** (also called *Analyse Actualités*) is a French-language intelligent news monitoring platform. It fetches articles from JSON feeds accessible via HTTP URL, summarizes them with an AI API (Infomaniak EurIA / Qwen3), and produces structured JSON outputs and Markdown reports.

- **Language:** All configuration keys, prompts, log messages, and output are in **French**
- **Version:** 2.3.0 (déduplication, crédibilité sources, timeline entités, backup)
- **License:** MIT — Patrick Ostertag
- **Python:** 3.10+

---

## Repository Structure

```
WUDD.ai/
├── scripts/            # Executable Python scripts (entry points)
├── viewer/             # Local web UI — Flask backend + React frontend
├── utils/              # Shared utility modules (importable package)
├── config/             # JSON configuration files and logging config
├── tests/              # Pytest test suite
├── docs/               # Architecture, security, deployment documentation
├── samples/            # Example outputs (JSON, Markdown, PDF)
├── archives/           # Historical versions, crontab, old requirements.txt
├── .env.example        # Environment variable template (copy to .env)
├── Dockerfile          # Container image definition
├── docker-compose.yml  # Docker Compose orchestration
├── entrypoint.sh       # Docker container startup script
├── README.md           # Main user-facing documentation
└── CHANGELOG.md        # Version history
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| AI API | **EurIA** (Infomaniak / Qwen3, défaut) **ou Claude** (Anthropic) — sélectionnable via `AI_PROVIDER` dans `.env` |
| HTTP | `requests` + `urllib3` (retry/backoff) |
| HTML parsing | `beautifulsoup4` |
| Config / secrets | `python-dotenv` |
| Testing | `pytest`, `pytest-cov` |
| Containerization | Docker + Docker Compose |
| Scheduling | `cron` inside Docker container |
| Data storage | File-based JSON (source de vérité) + **DuckDB** ≥ 0.10.0 (couche analytique en mémoire — requêtes SQL sur JSON natifs via `read_json_auto()`, optionnel) |

---

## Environment Setup

### 1. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in real values
```

Required variables:

| Variable | Description |
|---|---|
| `URL` | EurIA API endpoint (Infomaniak) |
| `bearer` | Bearer token for EurIA API |
| `REEDER_JSON_URL` | Source JSON feed URL (accessible via HTTP) |
| `MAX_RETRIES` | Max API retry attempts (default: 3) |
| `TIMEOUT_RESUME` | Timeout for summary generation in seconds (default: 60) |
| `TIMEOUT_RAPPORT` | Timeout for report generation in seconds (default: 300) |
| `BACKUP_L1` | Absolute path for primary backup destination (incremental copy of `data/`) |
| `BACKUP_L2` | Absolute path for secondary backup destination (optional — copy of `BACKUP_L1`) |

**Never commit `.env` to git.** It is listed in `.gitignore`.

### 2. Install dependencies

```bash
pip install -r viewer/requirements.txt
```

Dependencies: `requests`, `beautifulsoup4`, `python-dotenv`, `pytest`, `pytest-cov`

---

## Running the Application

### Manual execution (CLI)

All scripts use `__file__`-based path resolution and can be run from **any directory**:

```bash
# Generate article summaries for a flux and date range
python3 scripts/Get_data_from_JSONFile_AskSummary_v2.py \
  --flux "Intelligence-artificielle" \
  --date_debut 2026-02-01 \
  --date_fin 2026-02-28

# Run the multi-flux scheduler (processes all configured fluxes)
python3 scripts/scheduler_articles.py

# Enrich existing articles with named entities (NER) — all sources
python3 scripts/enrich_entities.py

# Enrich a specific flux only
python3 scripts/enrich_entities.py --flux Intelligence-artificielle

# Dry-run (no API call, no save)
python3 scripts/enrich_entities.py --dry-run

# Convert an articles JSON file to Markdown report
python3 scripts/articles_json_to_markdown.py data/articles/MyFlux/articles_generated_2026-02-01_2026-02-28.json

# Extract keywords from RSS feeds (daily task)
python3 scripts/get-keyword-from-rss.py

# Analyse thematic distribution across articles
python3 scripts/analyse_thematiques.py
```

### Via Docker (production)

```bash
# Build and start the container (runs cron jobs automatically)
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

The Docker container installs `archives/crontab` at startup and runs `cron -f` in the foreground.

### Scheduled cron jobs (inside Docker)

**Continuous / frequent jobs**

| Schedule | Script | Purpose |
|---|---|---|
| Every 5 min | `flux_watcher.py` + `entity_timeline.py` + `cross_flux_analysis.py` + `enrich_reading_time.py` | Round-robin RSS watcher — incremental 48h update, entity timeline & cross-flux analysis |
| Every 10 min | `check_cron_health.py` | Health monitoring |
| Every 2h (all day) | `web_watcher.py` | Surveillance sources web sans RSS via sitemap.xml — max 5 articles/source/run |
| Every 2h 06:00–22:00 (9×/day) | `get-keyword-from-rss.py` | Extract articles by keyword from RSS |

**Nightly pipeline (sequential enrichment)**

| Time | Script | Purpose |
|---|---|---|
| 01:00 daily | `backup_data.py` | Incremental backup: `data/` → `BACKUP_L1` → `BACKUP_L2` |
| 02:00 daily | `enrich_entities.py` | Round-robin NER enrichment — adds `entities` field to articles that don't have it yet |
| 02:30 daily | `enrich_images.py` | Fetch `og:image`/`twitter:image` for articles without images (HTTP only, no AI) |
| 03:00 daily | `enrich_sentiment.py` | Round-robin sentiment enrichment — adds `sentiment`, `score_sentiment`, `ton_editorial`, `score_ton` |
| 04:00 Sunday | `repair_failed_summaries.py` | Weekly maintenance — re-generates summaries containing API error messages |

**Morning reports (post-collection)**

| Time | Script | Purpose |
|---|---|---|
| 06:00 Monday | `scheduler_articles.py` | Weekly multi-flux article collection |
| 06:30 Monday | `generate_briefing.py --period weekly` | Weekly executive briefing (top entities + scored articles + trends, EurIA narrative) |
| 07:00 daily | `trend_detector.py` | Trend detection — generates `data/alertes.json` |
| 07:30 daily | `generate_morning_digest.py --ai` | Daily morning digest (top stories + active alerts, AI synthesis) |
| 08:00 daily | `generate_reading_notes.py` | Daily reading notes by tag — saved to `rapports/markdown/_WUDD.AI_/` |
| 23:00 daily | `generate_48h_report.py` | Daily Top 10 entities report (48h window, after last RSS pass at 22:00) |

**Monthly pipeline (last day of month)**

| Time | Script | Purpose |
|---|---|---|
| 05:00 | `radar_wudd.py` | Monthly thematic radar report |
| 05:30 | `articles_rss_to_markdown.py` | Convert RSS articles to annotated Markdown (with inline NER) |
| 06:00 | `generate_keyword_reports.py` | Generate one Markdown report per RSS keyword for the current month |

---

## Key Scripts

| Script | Purpose | Key arguments |
|---|---|---|
| `Get_data_from_JSONFile_AskSummary_v2.py` | Core: fetch → summarize → save JSON | `--flux`, `--date_debut`, `--date_fin` |
| `scheduler_articles.py` | Orchestrate all fluxes with adaptive scheduling | (none; reads `config/flux_json_sources.json`) |
| `flux_watcher.py` | Round-robin RSS watcher — fetches one feed per run, updates `48-heures.json` incrementally | `--dry-run` |
| `get-keyword-from-rss.py` | Keyword extraction from OPML RSS (every 2h, 06:00–22:00) | (none; reads `config/keyword-to-search.json`) |
| `articles_json_to_markdown.py` | JSON articles → Markdown report | positional path to JSON file |
| `articles_rss_to_markdown.py` | Convert RSS keyword JSON articles → annotated Markdown (with inline NER) | `--keyword` |
| `analyse_thematiques.py` | Thematic classification statistics | (none; reads `data/articles/`) |
| `enrich_entities.py` | Enrich existing articles with named entities (NER) | `--flux`, `--keyword`, `--dry-run`, `--delay`, `--force` |
| `enrich_sentiment.py` | Round-robin sentiment enrichment — adds `sentiment`, `score_sentiment`, `ton_editorial`, `score_ton` | `--flux`, `--keyword`, `--dry-run`, `--delay`, `--force` |
| `trend_detector.py` | Detect trending entities and generate `data/alertes.json` | `--dry-run` |
| `repair_failed_summaries.py` | Re-generate summaries that contain error messages | `--dir`, `--dry-run`, `--delay` |
| `repair_failed_enrichments.py` | Re-run NER/sentiment enrichment for articles with `enrichissement_statut=echec_api` | `--type entities\|sentiment\|all`, `--dry-run`, `--delay` |
| `benchmark_indexes.py` | Benchmark index performance vs rglob scans (scoring, entity search, compute_top_entities) | `--iterations N` |
| `check_cron_health.py` | Cron health probe | (none) |
| `generate_keyword_reports.py` | Monthly Markdown report per RSS keyword (current month) | (none) |
| `generate_48h_report.py` | Daily Top 10 named-entity report from last 48h articles | `--dry-run` |
| `generate_morning_digest.py` | Daily morning digest: top stories + active alerts + AI synthesis | `--ai`, `--dry-run` |
| `generate_reading_notes.py` | Daily reading notes by tag — `rapports/markdown/_WUDD.AI_/` | (none) |
| `generate_briefing.py` | Executive briefing: top entities + scored articles + trends narrative | `--period daily\|weekly`, `--dry-run`, `--no-ai` |
| `cluster_articles.py` | Thematic clustering of articles (entity-based, no ML deps) — on-demand via UI | `--days`, `--min-size`, `--output`, `--dry-run` |
| `radar_wudd.py` | Monthly thematic radar — generates end-of-month statistics | (none) |
| `Get_htmlText_From_JSONFile.py` | Extract raw HTML text from articles | (none; interactive file picker) |
| `backup_data.py` | Incremental backup of `data/` to `BACKUP_L1` and optionally `BACKUP_L2` | `--dry-run` |
| `enrich_images.py` | Add `Images` field to articles without images — fetches HTML and extracts `og:image`/`twitter:image` | `--flux`, `--keyword`, `--dry-run`, `--delay`, `--force` |
| `web_watcher.py` | Watch web sources without RSS via sitemap.xml — fetches pages, generates AI summaries, saves to `data/articles-from-rss/` | `--dry-run`, `--source` |

---

## Utils Package (`utils/`)

All utility modules are importable as `from utils.X import Y`. They are the correct place to add shared logic.

| Module | Purpose |
|---|---|
| `utils/config.py` | Singleton `Config` class — loads `.env`, validates vars, provides typed paths |
| `utils/api_client.py` | Dual-provider AI client (EurIA or Claude) with retry/backoff logic — `generate_summary()`, `generate_entities()` (NER), `generate_sentiment()`, `generate_report()`. Provider selected via `AI_PROVIDER` env var. |
| `utils/http_utils.py` | HTTP session with `urllib3` retry adapter |
| `utils/date_utils.py` | Multi-format date parsing and validation |
| `utils/logging.py` | Centralized timestamped logging (`print_console()`) |
| `utils/cache.py` | File-based TTL cache (24h default, MD5 keys) |
| `utils/parallel.py` | `ThreadPoolExecutor` wrapper for I/O-bound parallelism |
| `utils/scoring.py` | `ScoringEngine` — ranks articles by relevance score for Top articles and newsletter |
| `utils/quota.py` | `QuotaManager` — adaptive daily quota regulation: global cap, per-keyword cap, per-source-per-keyword cap, **per-entity-named cap**, adaptive keyword sorting by consumption ratio. Singleton via `get_quota_manager()`. State in `data/quota_state.json`, config in `config/quota.json`. |
| `utils/deduplication.py` | `Deduplicator` — detects near-duplicate articles using 3 signals: URL MD5 + résumé MD5 + Jaccard bigrammes (threshold 0.80). Methods: `deduplicate()`, `deduplicate_incremental()`, `is_duplicate()` |
| `utils/source_credibility.py` | `CredibilityEngine` — source credibility score (0–100) from `config/sources_credibility.json`; influences article ranking via `scoring.py` multiplier. Methods: `get_score()`, `get_multiplier()`, `rate_articles()` |
| `utils/reading_time.py` | Reading time estimation at 230 wpm (francophone average). Returns `temps_lecture_minutes` (float) and `temps_lecture_label` (str). Functions: `estimate_reading_time()`, `enrich_reading_time()` |
| `utils/rolling_window.py` | Shared rolling-window helper — maintains `48-heures.json` incrementally or by full rebuild from source dir. Used by `flux_watcher.py`, `get-keyword-from-rss.py` and `web_watcher.py`. Function: `update_rolling_window(new_articles, output_path, hours, source_dir)` |
| `utils/exporters/atom_feed.py` | Atom XML feed generation (`generate_atom_feed()`, `generate_atom_from_flux()`) |
| `utils/exporters/newsletter.py` | Newsletter HTML generation + SMTP send (`generate_newsletter_html()`, `send_newsletter()`) |
| `utils/exporters/webhook.py` | Webhook notifications — Discord, Slack, Ntfy (`send_discord()`, `send_slack()`, `send_ntfy()`) |

## Viewer (`viewer/`)

Local web interface for browsing, reading and editing generated JSON/Markdown files.

- **Backend:** Flask (`viewer/app.py`) — REST API for file listing, content read/write, file deletion, search, scheduler status, flux/keyword config, NER stats, entity geocoding/images, AI synthesis streaming, script execution streaming
- **Frontend:** React 18 + Vite + Tailwind CSS — compiled to `viewer/dist/` for production
- **Responsive:** Fully mobile/tablet-ready — hamburger sidebar drawer, bottom navigation bar (mobile), iPhone safe-area support (`viewport-fit=cover`, `env(safe-area-inset-top/bottom)`), dynamic `theme-color` meta tag
- **Port:** 5050 (Flask / Docker) / 5173 (Vite dev server)
- **Start (dev):** `bash viewer/start.sh` (from project root)
- **In Docker:** started automatically by `entrypoint.sh` on port 5050

| Component | Role |
|---|---|
| `JsonViewer.jsx` | Syntax-highlighted JSON with inline edit/save |
| `MarkdownViewer.jsx` | Rendered Markdown with image support |
| `SearchOverlay.jsx` | Full-text search across all files (⌘K) |
| `SettingsPanel.jsx` | Flux management, cron scheduling, thematic config; RSS tab: manage `data/WUDD.opml` feeds (check availability, add via URL paste with title resolution, delete, save); Keywords tab: displays keywords sorted alphabetically (fr locale); Quota tab: configure and monitor daily import quotas (4 sliders incl. per-entity, Top 20 named entities section) |
| `Sidebar.jsx` | File navigation by flux and type |
| `FileViewer.jsx` | File content viewer; "Supprimer" button with confirmation dialog (restricted to data/ and rapports/) |
| `ScriptConsolePanel.jsx` | Modal console to launch `get-keyword-from-rss.py` in the background; real-time SSE log streaming; auto-refreshes the file list on success |
| `EntityDashboard.jsx` | Aggregate NER stats cross-files; clicking an entity opens EntityArticlePanel |
| `EntityArticlePanel.jsx` | Draggable/resizable floating window: articles filtered by entity, co-occurrence graph, AI synthesis tab (streaming SSE, cached per entity), "Générer un rapport" and "Exporter JSON" |
| `AlertsPanel.jsx` | Alert management panel — configurable thresholds, bottom sheet on mobile |
| `ArticleListViewer.jsx` | Article list with filtering and sorting |
| `ChatbotPanel.jsx` | Chat interface for AI interactions |
| `ClusterView.jsx` | Thematic article clustering visualization |
| `ComparePanel.jsx` | Article comparison interface |
| `EntityCalendar.jsx` | Calendar view of entity mentions over time |
| `EntityGallery.jsx` | Gallery view of entity-related images |
| `EntityGraph.jsx` | Network graph visualization of entity co-occurrences |
| `EntityHighlighter.jsx` | Inline text highlighting for detected entities |
| `EntityPanel.jsx` | Generic entity detail panel |
| `EntitySearchModal.jsx` | Modal for entity search |
| `EntityTimeline.jsx` | Temporal timeline visualization of entity mentions |
| `EntityWatchPanel.jsx` | Watch list management for tracked entities |
| `EntityWorldMap.jsx` | Leaflet map visualization of geographic entities (GPE/LOC) |
| `ExportPanel.jsx` | Data export interface |
| `SchedulerPanel.jsx` | Cron job scheduling interface |
| `SourceBiasPanel.jsx` | Source credibility and editorial bias visualization |
| `TopArticlesPanel.jsx` | Top articles ranking — podium style (🥇🥈🥉 + numbered circles), mobile bottom sheet |
| `TTSButton.jsx` | Text-to-speech button for article content |

### Using Config

```python
from utils.config import get_config

config = get_config()  # Singleton; reads .env once
config.setup_directories()  # Creates data/ and rapports/ dirs if needed

headers = config.get_api_headers()  # {"Authorization": "Bearer ...", ...}
articles_dir = config.data_articles_dir  # Path object
```

Config raises `ValueError` at startup if `URL` or `bearer` are missing.

---

## Configuration Files (`config/`)

| File | Purpose |
|---|---|
| `flux_json_sources.json` | Array of flux definitions (title, URL, cron schedule, timeout) |
| `quota.json` | Daily quota configuration: `enabled`, `global_daily_limit`, `per_keyword_daily_limit`, `per_source_daily_limit`, `per_entity_daily_limit` (default 10, max 20), `adaptive_sorting` |
| `sites_actualite.json` | 133+ RSS news sources registry |
| `categories_actualite.json` | 214 article categories for classification |
| `thematiques_societales.json` | 12-theme classification (IA, economy, health, geopolitics, …) |
| `alert_rules.json` | Alert rule configuration — thresholds per entity type (modéré/élevé/critique), webhook targets |
| `sources_credibility.json` | Source credibility scores (0–100) for known media outlets — used by `utils/source_credibility.py` |
| `web_sources.json` | Web source definitions for `web_watcher.py` (sitemap URL, url_pattern, keyword, max_per_run) |
| `keyword-to-search.json` | Keywords and their RSS feed targets for `get-keyword-from-rss.py` |
| `logging.conf` | Python logging configuration |

### Adding a new flux

Edit `config/flux_json_sources.json` and add an entry with `title` and `url` (plus optional `cron` and `timeout`). The scheduler picks it up automatically on the next run.

---

## Data Architecture

**File-based storage only — no database.**

```
data/
├── articles/
│   └── <flux-name>/           # One directory per flux (isolated)
│       ├── articles_generated_<date_debut>_<date_fin>.json
│       └── cache/             # API response cache (TTL 24h, MD5 keys)
├── articles-from-rss/
│   └── <keyword>.json         # Keyword-extracted + web_watcher articles
├── raw/
│   └── all_articles.txt       # Raw extracted HTML text
├── alertes.json               # Generated by trend_detector.py
├── entity_timeline.json       # Generated by entity_timeline.py
├── quota_state.json           # Quota counters (auto-reset at midnight)
└── web_watcher_state.json     # Processed URL tracking for web_watcher.py

rapports/
├── markdown/
│   └── <flux-name>/           # One directory per flux
│       └── rapport_*.md
└── pdf/
    └── <flux-name>/
```

### Article JSON format

```json
[
  {
    "Date de publication": "23/01/2025",
    "Sources": "Le Monde",
    "URL": "https://...",
    "Résumé": "20-line AI-generated summary in French",
    "Images": [
      {"URL": "https://...", "Width": 1200}
    ],
    "entities": {
      "PERSON": ["Emmanuel Macron"],
      "ORG": ["OpenAI", "Infomaniak"],
      "GPE": ["France", "Paris"],
      "PRODUCT": ["ChatGPT"]
    },
    "sentiment": "positif",
    "score_sentiment": 4,
    "ton_editorial": "factuel",
    "score_ton": 5,
    "temps_lecture_minutes": 2.5,
    "temps_lecture_label": "2 min 30 s",
    "score_source": 85
  }
]
```

Images are filtered to width > 500px (up to 3 per article). The `Images` field is also added retroactively by `enrich_images.py` for articles that lack it.

The `entities` field is optional — added by `enrich_entities.py` or `get-keyword-from-rss.py`. It uses 18 NER category types (PERSON, ORG, GPE, LOC, PRODUCT, EVENT, DATE, MONEY, etc.). Absent from older articles until enriched.

The `sentiment` / `score_sentiment` / `ton_editorial` / `score_ton` fields are optional — added by `enrich_sentiment.py` (Round-Robin, 1 file/day on `articles-from-rss/`). Absent from older articles until enriched.

The `temps_lecture_minutes` / `temps_lecture_label` fields are optional — added by `enrich_reading_time.py` using `utils/reading_time.py` (230 wpm).

The `score_source` field is optional — added by `utils/source_credibility.py` based on `config/sources_credibility.json`; influences article ranking.

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Single file
pytest tests/test_date_utils.py -v

# With coverage report
pytest --cov=utils tests/

# HTML coverage report
pytest --cov=utils --cov-report=html tests/
```

Test files:
- `tests/test_date_utils.py` — Date parsing edge cases (184 lines)
- `tests/test_multi_flux.py` — Multi-flux cache isolation (49 lines)
- `tests/test_new_features.py` — Deduplication, source credibility, reading time (50 tests)

Coverage targets: `utils/` ≥ 80%, `scripts/` ≥ 60%, critical functions 100%.

---

## Architecture Patterns

1. **Multi-flux partitioning** — Each flux is fully isolated: separate `data/`, `rapports/`, and `cache/` subdirectories.

2. **Absolute path resolution** — Scripts use `Path(__file__).parent` to locate project root. Never rely on the working directory.

3. **Retry with exponential backoff** — `utils/api_client.py` uses urllib3 `Retry` with a 2.0x backoff factor (default 3 retries). Mirror this pattern for any new external calls.

4. **Singleton config** — Always use `get_config()` from `utils/config.py`. Do not instantiate `Config()` directly or read `.env` manually in scripts.

5. **File-based caching** — `utils/cache.py` caches API responses by MD5-hashed key with a configurable TTL. Use it for all expensive external calls.

6. **ThreadPoolExecutor parallelism** — `utils/parallel.py` wraps `ThreadPoolExecutor` for parallel article processing. Default `max_workers=5`.

7. **Headless-first** — Everything runs via CLI and Docker cron. Scripts using `tkinter` (interactive file picker) are legacy patterns; prefer CLI arguments.

8. **Adaptive quota regulation** — `utils/quota.py` enforces four daily ceilings (global, per-keyword, per-source-per-keyword, per-named-entity). Flow: call `quota.can_process(kw, source)` before the EurIA API call, then `quota.can_process_entities(entities)` after NER extraction and before saving the article, then `quota.record_article(kw, source, entities)` to update all counters. Keywords are sorted by consumption ratio so the least-consumed topics are prioritised. The state (including entity counts) auto-resets at midnight (lazy reset on first call after midnight).

9. **3-signal deduplication** — `utils/deduplication.py` detects near-duplicate articles across sources using URL MD5 (exact duplicates), résumé MD5 (same text, different source), and Jaccard similarity on word bigrams (≥ 0.80 threshold for near-duplicates). Always call `dedup.is_duplicate(article, existing)` before appending a new article to a JSON file.

10. **Credibility-weighted scoring** — `utils/source_credibility.py` loads `config/sources_credibility.json` and provides a multiplier (0.0–1.0) per source. `utils/scoring.py` applies this multiplier to relevance scores so that highly-credible sources rank higher. Add new sources to `sources_credibility.json` rather than hardcoding scores in scripts.

---

## Key Conventions

- **French everywhere** — All configuration keys (`"Date de publication"`, `"Résumé"`, `"Sources"`), log messages, and report text are in French. Do not introduce English keys in JSON data structures.
- **No GUI dependencies in production paths** — `tkinter` is only used in older standalone scripts. New scripts must accept paths as CLI arguments.
- **Import from `utils`** — Shared logic belongs in `utils/`. Do not duplicate HTTP, retry, cache, or date logic in individual scripts.
- **JSON output first** — The pipeline output is always JSON first, then optionally converted to Markdown/PDF.
- **No hardcoded paths** — Always resolve paths relative to `config.project_root` or `__file__`.
- **`.env` is never committed** — Secrets live only in `.env` (gitignored). Reference `.env.example` for the list of required variables.
- **Never modify `.env` or any environment parameter without explicit user approval** — The `.env` file contains credentials and API configuration specific to this project. Always ask before reading values from other projects' `.env` files, copying credentials, or changing any environment variable (URL, bearer, timeouts, etc.).

---

## Claude Report Integration

When analyzing article JSON files with Claude directly (outside the pipeline), use the instructions in `docs/instructions-for-claude-report.md`:

- Group articles by thematic using `config/thematiques_societales.json`
- Use the `"Résumé"` field instead of fetching original URLs for fast reports
- Insert images as HTTP image links when present
- Output using the template in `docs/instructions-for-claude-report.md` (frontmatter + TOC + body + reference table)
- Final output format: Markdown compatible with **iA Writer**

---

## Docs Reference

| File | Content |
|---|---|
| `docs/ARCHITECTURE.md` | Full technical architecture (v3.0, Feb 2026) with Mermaid diagrams |
| `docs/DEPLOY.md` | Deployment procedures |
| `docs/EXTERNAL_SERVICES.md` | External service dependencies (EurIA, JSON feeds via HTTP, RSS, Wikipedia, Wikidata, OSM) |
| `docs/ENTITIES.md` | NER semantic analysis — Dashboard Liste / Carte / Galerie, pipeline, caches |
| `docs/security/SECURITY.md` | Security considerations |
| `docs/security/SECURITY_AUDIT.md` | Security audit report |
| `docs/PROMPTS.md` | EurIA prompt templates |
| `scripts/USAGE.md` | Detailed per-script CLI usage guide |
| `tests/README.md` | Testing guide |
