# Rapport de session — Prérequis backend veille be.CLEAR → WUDD.ai

**Date :** 2026-05-17
**Réf. spec :** `spec-veille-beclear-wuddai-v1.2.md`
**Périmètre :** correction bug `watch_entity`, endpoint articles/entité/date, `wudd_article_id` stable
**Validation :** données réelles WUDD.ai (aucun mock), watchlist sauvegardée/restaurée

---

## Diagnostic initial (étape 0)

### Architecture réelle constatée

- Stockage **fichiers JSON uniquement**, pas de base de données. La watchlist
  est `data/watched_entities.json`, écrite par `_save_watched()` via
  **remplacement atomique synchrone** (`tmp.write` → `os.replace`).
- Le viewer Flask tourne sous **Gunicorn multi-workers** en production
  (`entrypoint.sh` : `WUDD_GUNICORN_WORKERS=2`, `--threads 4`).
- Serveur MCP `wudd-ai` séparé (`mcp_server/`, FastMCP) consommant l'API HTTP
  du viewer via `ViewerClient`.

### Endpoints articles existants

| Endpoint | Filtre entité | Filtre date | Champ ID article |
|---|---|---|---|
| `GET /api/entities/articles` | oui (`type`+`value`, index NER) | **non** | aucun (URL implicite) |
| `GET /api/search/entity` | oui (recherche partielle) | non | aucun (URL implicite) |
| `GET /api/entity-context` | oui (contexte entité) | non | aucun (URL implicite) |
| `GET /api/entities/cooccurrences` | oui (cooccurrences) | non | n/a (pas d'articles bruts) |
| `GET /api/watched-entities/{entity_name}/articles` *(créé)* | **oui** (index NER) | **oui** (`date`) | **`id` / `wudd_article_id`** |

**Conclusion 0b :** aucun endpoint existant ne combinait filtre entité **et**
filtre date, et aucun n'exposait d'identifiant d'article stable → les deux
livrables bloquants étaient bien manquants.

### Identifiant article actuel

- **Champ :** aucun. Recherche exhaustive (`id`, `article_id`,
  `wudd_article_id`) dans `utils/ scripts/ viewer/ mcp_server/` : aucun champ
  d'identifiant dans le JSON article. Champs réels : `Date de publication`,
  `Sources`, `URL`, `Résumé`, `Images`, `entities`, `sentiment`…
- **Identité de facto :** l'**URL**. C'est la clé de déduplication
  (`utils.deduplication.compute_url_fingerprint` = MD5 de l'URL normalisée),
  la clé de `ArticleIndex.get_by_url`, et la clé de jointure des rapports.
- **Format :** ni UUID, ni entier auto-incrémenté. Seul handle stable =
  empreinte MD5 de l'URL normalisée.
- **Stabilité garantie :** **à corriger** (aucun ID exposé) → traité étape 3.

---

## Corrections réalisées

### Bug `watch_entity` read-after-write

- **Cause racine (corrigée du diagnostic de la spec) :** ce **n'est pas** une
  écriture asynchrone — `_save_watched()` est synchrone et atomique. La cause
  réelle est le **cache de lecture par processus** `_watched_cache` (TTL 60 s)
  combiné au **multi-worker Gunicorn** : un `POST` traité par le worker A
  n'invalide que le cache du worker A ; un `GET` ultérieur routé vers le
  worker B sert une liste périmée jusqu'à 60 s. S'ajoute une course de
  repopulation intra-processus (un `GET` lent réécrit un résultat périmé
  après l'invalidation du `POST`). Le retour `~16 ms` puis `action: updated`
  au 2ᵉ POST confirme que l'écriture **était** committée — seul le **chemin de
  lecture** était périmé.
- **Approche choisie : B — read-your-writes garanti.** Le cache est désormais
  clé-té sur l'**empreinte filesystem** du fichier
  (`mtime_ns` + taille + `inode`), partagée par tous les workers via le
  système de fichiers commun. `os.replace` crée un nouvel inode → toute
  écriture par n'importe quel worker rend le cache des autres workers
  immédiatement invalide, sans IPC. Immunise aussi contre la course de
  repopulation (le résultat périmé est tagué avec l'ancien stamp et n'est
  jamais servi). Latence préservée (cache toujours actif tant que le fichier
  n'a pas changé).
- **Fichier(s) modifié(s) :** `viewer/routes/entities.py`
  (`_watched_file_stamp()` + handler `GET /api/watched-entities` ;
  invalidations `POST`/`DELETE` conservées, désormais redondantes mais sûres).
  Le filet de sécurité MCP `_confirm_watch_persisted` (re-lectures) est
  conservé tel quel (« ne pas casser l'existant »).
- **Test de validation (séquence immédiate, 0 délai, données réelles) :**
  ✅ **passé** — `POST` → `GET` contient l'entité → `POST` `action:"updated"`
  (idempotent) → `DELETE` → `GET` ne la contient plus.
- **Test régression multi-worker :** ✅ **passé** — cache périmé ré-injecté
  pour simuler un autre worker ; après écriture concurrente, le `GET` ignore
  le cache périmé (stamp fichier changé) et renvoie l'état frais.

### Nouvel endpoint

- **URL :** `GET /api/watched-entities/{entity_name}/articles`
- **Paramètres :** `entity_name` (path, URL-encodé) ; `date`
  (query, `YYYY-MM-DD`, **défaut J-1 UTC**, filtre sur **date de
  publication**) ; `type` (query, opt., type NER pour désambiguïser ;
  défaut : tous types) ; `limit` (défaut 50, borné [1,500]) ; `offset`
  (défaut 0).
- **Logique :** réutilise le mécanisme NER existant
  (`resolve_entity_matches` + `load_match_refs`, identique à
  `/api/entities/articles` et `watch_entity`) — pas de full-text. Filtre
  strict sur la **date de publication** de l'article (revalidée après
  chargement, pas la date d'indexation). Tri `score_pertinence` puis date
  décroissants ; pagination après tri.
- **Réponse :** `{entity, date, total, articles:[{id, wudd_article_id,
  titre, resume, source, url, date_publication, entites,
  score_pertinence}]}`. `score_pertinence` = score `ScoringEngine`
  normalisé 0–1.
- **Comportements aux limites :** ✅ entité inconnue → `total:0, articles:[]`
  (pas 404) ; entité hors watchlist → renvoyée (lecture seule) ; date sans
  article → `total:0` ; date future → **400** explicite ; date mal formée →
  **400**.
- **Fichier créé/modifié :** `viewer/routes/entities.py` (route +
  `api_watched_entity_articles`), `utils/openapi.py` (doc OpenAPI auto +
  méta-params).
- **Outil MCP ajouté : oui** — `get_watched_entity_articles`
  (`mcp_server/tools/watched_entities.py` + `tool_registry.py`).
  ⚠️ Le nom suggéré par la spec, `get_entity_articles`, est **déjà pris**
  par un tool existant ciblant un autre endpoint (`/api/entities/articles`,
  sans filtre date). Pour ne rien casser, le nouvel outil est exposé sous
  `get_watched_entity_articles` (décision documentée dans le code).
- **Test avec entité réelle :** ✅ `GET
  /api/watched-entities/Anthropic/articles?date=2026-03-06&type=ORG&limit=5`
  → `total: 26`, exemple :

  ```json
  {
    "id": "wudd-2026-03-06-d0acb42c0552",
    "wudd_article_id": "wudd-2026-03-06-d0acb42c0552",
    "titre": "...",
    "resume": "...",
    "source": "Le Temps",
    "url": "https://...",
    "date_publication": "2026-03-06T00:00:00Z",
    "entites": { "ORG": ["Anthropic", ...], "PERSON": [...] },
    "score_pertinence": 0.731
  }
  ```

### `wudd_article_id`

- **Statut avant :** n'existait pas (aucun champ ID dans le JSON article).
- **Format final :** `wudd-{YYYY-MM-DD}-{md5(url_normalisée)[:12]}`
  (ex. `wudd-2026-03-06-d0acb42c0552`). Repli déterministe
  `wudd-{date}-nourl-{md5(Sources|Résumé)[:12]}` si URL absente ;
  segment date `0000-00-00` si date non parsable.
- **Implémentation :** `utils/article_id.py` →
  `compute_wudd_article_id(article)`. **Dérivé, jamais persisté** : réutilise
  `compute_url_fingerprint()` du moteur de dédup (alignement sur la clé
  d'identité déjà utilisée partout) + date de publication via
  `parse_article_date`.
- **Aucune migration de données nécessaire** (calcul à la volée ; fichiers
  `data/` inchangés).
- **Test stabilité :** ✅ **passé** — ré-indexation simulée (résumé + entités
  + titre régénérés, URL et date constantes) → ID **identique**. Unicité
  vérifiée sur lots réels (aucune collision).

---

## Anomalies rencontrées

- **Test préexistant cassé (hors périmètre) :**
  `tests/test_viewer_app.py::...::test_watched_entities_post_canonicalizes_entity`
  échoue (`mentions_7d == 1` attendu, obtenu `0`). Vérifié : **échoue à
  l'identique sur `main` sans mes modifications** (`git stash`) → anomalie
  préexistante, **non introduite** par cette session. Les 199 autres tests
  des suites `test_viewer_app / test_new_features / test_indexes` passent.
- **`fastmcp` non installé dans le venv local** → `tests/test_mcp_tools.py`
  non collectable hors Docker (limite d'environnement, pas une régression).
  Les modules MCP modifiés compilent (`py_compile`) ; le module outil
  `watched_entities.py` n'importe pas `fastmcp` et a été validé indirectement
  via l'endpoint HTTP réel.
- Bugs connus du rapport 2026-05-09 : le read-after-write est corrigé ;
  `cooccurrences total_count: 0` sur types structurels (mineur) **non traité**
  (hors périmètre de cette session).

---

## Points à transmettre au prompt Claude Workflow

- **URL exacte endpoint articles :**
  `GET /api/watched-entities/{entity_name}/articles`
  (`entity_name` URL-encodé dans le chemin).
- **Format `wudd_article_id` :** `wudd-{YYYY-MM-DD}-{hash12}` où `hash12` =
  12 premiers hex du MD5 de l'URL normalisée ; **stable** (invariant en
  ré-indexation/régénération), exposé dans `id` **et** `wudd_article_id`.
- **Paramètre date :** nom = `date`, format = `YYYY-MM-DD`, **défaut = J-1
  (hier, UTC)**, filtre sur la **date de publication**. Date future ou mal
  formée → HTTP 400.
- **Champ entités dans la réponse JSON :** `entites` (dict NER OntoNotes,
  ex. `{"ORG": [...], "PERSON": [...], "GPE": [...], "LAW": [...]}`).
- **Désambiguïsation :** paramètre optionnel `type` (`ORG`, `PERSON`,
  `GPE`, …) ; absent → recherche tous types confondus.
- **Pagination :** `limit` (défaut 50, max 500), `offset` (défaut 0) ;
  `total` = nombre total avant pagination.
- **Outil MCP :** `get_watched_entity_articles` (et **non**
  `get_entity_articles`, déjà utilisé pour un autre endpoint).
- **Entité absente de l'index NER :** réponse `200` avec
  `{entity, date, total: 0, articles: []}` (jamais `404`) — prévoir ce cas
  côté pipeline.
