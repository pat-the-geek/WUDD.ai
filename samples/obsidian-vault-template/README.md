# Template de vault Obsidian — WUDD.ai

Ce dossier contient une structure de départ pour un vault Obsidian compatible avec WUDD.ai.

## Structure

```
obsidian-vault-template/
└── Veille/
    ├── articles/        # Notes articles générées par export_obsidian.py
    ├── entités/         # Notes entités NER + notes géographiques (geo_*.md)
    ├── rapports/        # Rapports Markdown copiés depuis rapports/markdown/
    └── synthèses/
        └── _INDEX.md    # Index global — mis à jour à chaque export
```

## Installation

1. Copiez ce dossier dans votre vault Obsidian :
   ```bash
   cp -r samples/obsidian-vault-template/* /chemin/vers/votre/vault/
   ```
2. Configurez `OBSIDIAN_DIR` dans votre `.env` :
   ```env
   OBSIDIAN_DIR=/chemin/vers/votre/vault
   OBSIDIAN_VAULT_NAME=NomDuVault
   ```
3. Lancez l'export initial :
   ```bash
   python3 scripts/export_obsidian.py --days 30
   ```

## Plugins Obsidian recommandés

- **Dataview** — requêtes SQL sur les frontmatters YAML (filtrer par flux, sentiment, entité…)
- **Map View** — visualisation des champs `location: [lat, lon]` sur une carte
- **Templater** — templates dynamiques pour les nouvelles notes
- **Graph View** — exploration des liens `[[internes]]` entre articles et entités

## Exemples de requêtes Dataview

```dataview
TABLE date, source, sentiment, temps_lecture
FROM "Veille/articles"
WHERE flux = "Intelligence-artificielle"
SORT date DESC
LIMIT 20
```

```dataview
TABLE mentions, premiere_mention, derniere_mention
FROM "Veille/entités"
WHERE type = "entité"
SORT mentions DESC
LIMIT 15
```
