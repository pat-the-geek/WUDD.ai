# SQLite — Plan de migration pour >50 000 articles

**Version :** 1.0 — Juin 2026  
**Statut :** Évaluation et planification (implémentation conditionnelle au seuil)

---

## Contexte

WUDD.ai utilise actuellement un stockage **fichier JSON par collection** (flux ou mot-clé) avec deux indexes légers (`article_index.json`, `entity_index.json`). Cette architecture convient jusqu'à ~50 000 articles.

Au-delà de ce seuil, plusieurs opérations deviennent goulots :

| Opération | Fichier actuel | Complexité | Impact à 50k+ |
|---|---|---|---|
| Rebuild `article_index` | `rglob("*.json")` + parse | O(n × taille) | 30-60 s |
| Recherche plein texte | Scan linéaire des JSON | O(n × longueur) | 10-20 s |
| Top articles (scoring) | Scan `article_index.json` complet | O(n) | 2-5 s |
| Recherche d'entités | Scan `entity_index.json` | O(n) | 1-3 s |
| Déduplication Jaccard | Comparaison pairwise | O(n²) au pire | Prohibitif |

---

## Seuil de déclenchement

Activer la migration SQLite quand **l'une des conditions suivantes est vraie** :

```python
# utils/db_threshold.py — détection automatique du seuil
SQLITE_THRESHOLD_ARTICLES = 50_000
SQLITE_THRESHOLD_INDEX_BUILD_S = 30.0   # Rebuild index > 30 secondes
SQLITE_THRESHOLD_SEARCH_S = 5.0         # Recherche plein texte > 5 secondes
```

Le script `scripts/benchmark_indexes.py` mesure ces durées. Lancer périodiquement :

```bash
python3 scripts/benchmark_indexes.py --iterations 3
```

---

## Architecture cible avec SQLite

### Structure de la base

```sql
-- Une seule base : data/wudd.db
-- Toutes les tables coexistent avec le stockage JSON existant (migration progressive)

CREATE TABLE articles (
    id          INTEGER PRIMARY KEY,
    url         TEXT UNIQUE NOT NULL,
    source      TEXT,
    flux        TEXT,
    keyword     TEXT,
    date_pub    TEXT,            -- ISO 8601 : YYYY-MM-DDTHH:MM:SSZ
    summary     TEXT,
    sentiment   TEXT,
    score_sent  INTEGER,
    ton_ed      TEXT,
    score_ton   INTEGER,
    rt_min      REAL,
    score_src   INTEGER,
    has_entities INTEGER DEFAULT 0,
    has_images  INTEGER DEFAULT 0,
    file_path   TEXT,
    file_idx    INTEGER,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE entities (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,   -- PERSON, ORG, GPE, PRODUCT…
    value       TEXT NOT NULL,
    value_lc    TEXT NOT NULL     -- value.lower() pour recherche insensible à la casse
);

CREATE TABLE images (
    id          INTEGER PRIMARY KEY,
    article_id  INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER
);

-- Indexes pour les requêtes fréquentes
CREATE INDEX idx_articles_source   ON articles(source);
CREATE INDEX idx_articles_flux     ON articles(flux);
CREATE INDEX idx_articles_date     ON articles(date_pub);
CREATE INDEX idx_articles_sentiment ON articles(sentiment);
CREATE INDEX idx_entities_value_lc ON entities(value_lc);
CREATE INDEX idx_entities_type     ON entities(type);

-- Full-text search sur résumés (SQLite FTS5)
CREATE VIRTUAL TABLE articles_fts USING fts5(
    url UNINDEXED,
    summary,
    source,
    content=articles,
    content_rowid=id
);
```

### Requêtes remplaçant les opérations actuelles

| Opération actuelle | Requête SQLite équivalente |
|---|---|
| Top articles (scoring) | `SELECT * FROM articles ORDER BY score_src DESC LIMIT 20` |
| Entités par fréquence | `SELECT value, COUNT(*) c FROM entities GROUP BY value_lc ORDER BY c DESC LIMIT 50` |
| Articles d'une entité | `SELECT a.* FROM articles a JOIN entities e ON e.article_id=a.id WHERE e.value_lc=?` |
| Recherche plein texte | `SELECT * FROM articles_fts WHERE summary MATCH ?` |
| Déduplication URL | `SELECT id FROM articles WHERE url=?` |

---

## Stratégie de migration

### Phase 1 — Mode hybride (recommandée pour démarrer)

Maintenir les JSON comme source de vérité, SQLite comme **index secondaire accéléré**.

```
data/
├── articles/         ← JSON (source de vérité inchangée)
├── article_index.json ← Garder pour compatibilité descendante
└── wudd.db           ← Nouveau : SQLite pour requêtes rapides
```

Avantages :
- Pas de rupture : tous les scripts existants fonctionnent sans modification
- Migration progressive : peupler SQLite depuis les JSON existants
- Rollback simple : supprimer `wudd.db`, retomber sur les JSON

### Phase 2 — SQLite comme source de vérité (optionnel, futur)

Ne migrer vers ce mode que si les JSON deviennent un problème (corruption, vitesse d'écriture, taille disque).

---

## Plan d'implémentation

### Étape 1 : `utils/db.py` — Couche d'accès SQLite

```python
# utils/db.py (à créer quand le seuil est atteint)
from pathlib import Path
import sqlite3
from contextlib import contextmanager

DB_PATH = None  # Initialisé par get_db()

def get_db(project_root: Path) -> Path:
    global DB_PATH
    if DB_PATH is None:
        DB_PATH = project_root / "data" / "wudd.db"
    return DB_PATH

@contextmanager
def db_connection(project_root: Path):
    conn = sqlite3.connect(get_db(project_root))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # Lectures concurrentes
    conn.execute("PRAGMA synchronous=NORMAL") # Perf vs durabilité
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

### Étape 2 : `scripts/migrate_to_sqlite.py` — Migration initiale

```bash
python3 scripts/migrate_to_sqlite.py --dry-run   # Simulation
python3 scripts/migrate_to_sqlite.py             # Migration réelle
```

Durée estimée : ~2 min pour 50 000 articles (single-threaded, bottleneck = I/O JSON).

### Étape 3 : Adapter `utils/article_index.py`

Ajouter un mode `backend="sqlite"` en plus du mode JSON actuel :

```python
# utils/article_index.py (modification)
def get_article_index(project_root, *, backend="auto"):
    """backend='auto' → SQLite si wudd.db existe, sinon JSON."""
    ...
```

### Étape 4 : Adapter `utils/entity_index.py`

Même logique : mode `backend="auto"` avec fallback JSON.

### Étape 5 : Intégrer dans les scripts d'enrichissement

Appeler `db.upsert_article()` après chaque enrichissement NER/sentiment pour maintenir SQLite synchronisé avec les JSON.

---

## Estimation de performances cibles

| Opération | JSON actuel (50k) | SQLite cible (50k) | SQLite cible (200k) |
|---|---|---|---|
| Rebuild index complet | 30-60 s | < 1 s (lecture seule) | < 3 s |
| Top 20 articles | 2-5 s | < 50 ms | < 100 ms |
| Recherche entité | 1-3 s | < 10 ms | < 20 ms |
| Full-text search | 10-20 s | < 200 ms (FTS5) | < 500 ms |
| Déduplication URL | 100-500 ms | < 1 ms | < 1 ms |

---

## Taille SQLite estimée

| Corpus | Taille JSON (gzip) | Taille SQLite | Taille SQLite + FTS5 |
|---|---|---|---|
| 10 000 articles | ~50 MB | ~30 MB | ~45 MB |
| 50 000 articles | ~250 MB | ~150 MB | ~225 MB |
| 200 000 articles | ~1 GB | ~600 MB | ~900 MB |

---

## Décision de déclenchement

Lancer `scripts/benchmark_indexes.py` lorsque le corpus dépasse **20 000 articles** pour avoir des mesures précoces. Déclencher la migration si le rebuild dépasse 30 secondes **ou** si le nombre d'articles franchit 50 000.

```bash
# Vérifier le nombre d'articles actuel
python3 -c "
from pathlib import Path
import json
root = Path('.')
n = sum(
    len(json.loads(f.read_text())
    if isinstance(json.loads(f.read_text()), list)
    else [])
    for f in root.glob('data/**/*.json')
    if 'articles_generated' in f.name or f.parent.name == 'articles-from-rss'
)
print(f'Articles totaux estimés : {n}')
"
```

---

## Références

- [SQLite WAL Mode](https://sqlite.org/wal.html) — Mode journal recommandé pour lectures concurrentes
- [SQLite FTS5](https://sqlite.org/fts5.html) — Recherche full-text intégrée
- [DuckDB vs SQLite](https://duckdb.org/why_duckdb.html) — DuckDB reste préférable pour les requêtes analytiques complexes (déjà utilisé via `utils/db.py`)
- `docs/ARCHITECTURE.md` — Architecture complète WUDD.ai
- `scripts/benchmark_indexes.py` — Outil de mesure des performances actuelles
