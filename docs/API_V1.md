# API REST publique `/api/v1`

API stable et versionnée pour les agents IA, scripts d'intégration et le serveur MCP. Découplée de l'UI viewer — les contrats restent stables même si l'UI évolue.

## Authentification

L'API est protégée par un bearer token statique défini dans `.env` :

```bash
WUDD_API_TOKEN=<une-valeur-aléatoire>
```

Si la variable est **absente ou vide**, l'API est ouverte (réservé au dev local).

Toutes les requêtes mutantes (POST, PATCH, DELETE) et lectures doivent inclure :

```
Authorization: Bearer <token>
```

Génération recommandée :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Sources RSS — `/api/v1/sources`

Les sources sont stockées dans `data/WUDD.opml`. Chaque source a un `id` stable dérivé de son URL (SHA-1 tronqué à 12 caractères).

### Modèle JSON

```json
{
  "id": "a3f1c20e9b4d",
  "url": "https://lemonde.fr/rss/une.xml",
  "nom": "Le Monde",
  "html_url": "https://lemonde.fr",
  "tags": ["presse", "généraliste"],
  "actif": true,
  "bypass_quota": false
}
```

### `GET /api/v1/sources`

Liste les sources. Par défaut, exclut les sources désactivées.

| Query | Description |
|---|---|
| `include_inactive=1` | inclut les sources désactivées |
| `tag=<tag>` | filtre par tag exact (insensible à la casse) |

Réponse : `{ "items": [...], "total": N }`.

### `POST /api/v1/sources`

Ajoute une source. Body :

```json
{
  "url": "https://example.com/feed.xml",
  "nom": "Optionnel — résolu automatiquement si absent",
  "tags": ["optionnel"],
  "actif": true,
  "bypass_quota": false,
  "html_url": "https://example.com"
}
```

- `url` est obligatoire (doit commencer par `http://` ou `https://`)
- Si `nom` n'est pas fourni, le titre du flux RSS est récupéré via une requête HTTP (fallback : domaine)
- Retourne `201` + objet créé, `409` si l'URL existe déjà

### `PATCH /api/v1/sources/<id>`

Met à jour un sous-ensemble des champs. Tous optionnels :

```json
{ "nom": "...", "tags": [...], "actif": true, "bypass_quota": false, "html_url": "..." }
```

### `DELETE /api/v1/sources/<id>`

- Par défaut : **soft delete** — la source passe `actif=false`, elle reste dans l'OPML
- `?hard=1` : suppression définitive de l'entrée OPML

## Mots-clés thématiques — `/api/v1/keywords`

Stockés dans `config/keyword-to-search.json`. Un mot-clé est une expression de surveillance qui peut être plus riche qu'une simple détection NER (synonymes, contexte obligatoire, seuil d'alerte).

### Modèle JSON

```json
{
  "id": "5e2f8a91cb04",
  "expression": "gouvernance des modèles",
  "tags": ["IA", "régulation"],
  "seuil_alerte": 3,
  "ou": ["AI governance", "model governance"],
  "et": ["IA", "modèle"]
}
```

- `ou` : synonymes / variantes — un seul terme suffit pour matcher
- `et` : termes obligatoires de contexte — tous doivent être présents dans le titre
- `seuil_alerte` : nombre d'occurrences avant déclenchement d'une alerte (optionnel)

### `GET /api/v1/keywords`

Liste les mots-clés. Query `tag=<tag>` filtre par tag exact.

### `POST /api/v1/keywords`

```json
{
  "expression": "transformation digitale",
  "tags": ["métier"],
  "seuil_alerte": 5,
  "ou": ["transition digitale", "digital transformation"],
  "et": ["entreprise"]
}
```

- `expression` est obligatoire
- Retourne `201` + objet créé, `409` si l'expression existe déjà

### `PATCH /api/v1/keywords/<id>`

Met à jour un sous-ensemble. Tous les champs sont optionnels.

### `DELETE /api/v1/keywords/<id>`

Supprime le mot-clé.

### `GET /api/v1/keywords/<id>/articles`

Retourne les articles matchant l'expression depuis `data/articles-from-rss/<expression>.json`. Query `days=N` restreint à la fenêtre des N derniers jours (basé sur `Date de publication`).

Réponse : `{ "expression": "...", "items": [...], "total": N }`.

## Exemples

```bash
TOKEN="$(grep WUDD_API_TOKEN .env | cut -d= -f2)"

# Lister les sources actives
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5050/api/v1/sources

# Ajouter une nouvelle source RSS
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://bakom.admin.ch/rss","tags":["institutionnel","CH"]}' \
  http://localhost:5050/api/v1/sources

# Désactiver une source
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/sources/a3f1c20e9b4d

# Ajouter un mot-clé
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"expression":"souveraineté numérique","tags":["politique"],"seuil_alerte":3}' \
  http://localhost:5050/api/v1/keywords
```

## Accès via MCP

Les sept tools suivants sont enregistrés dans le serveur MCP (`mcp_server/tool_registry.py`) et appellent automatiquement `/api/v1` :

- `list_sources`, `add_source`, `update_source`, `toggle_source`, `delete_source`
- `list_keywords`, `add_keyword`, `update_keyword`, `delete_keyword`, `get_keyword_articles`

Le serveur MCP transmet automatiquement le `WUDD_API_TOKEN` au ViewerClient si la variable est définie dans `.env`.
