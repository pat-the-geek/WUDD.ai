# OBSIDIAN.md — Intégration WUDD.ai × Obsidian

Ce document décrit la configuration requise pour exploiter pleinement les notes générées par WUDD.ai dans un vault Obsidian, notamment les propriétés YAML, la cartographie via Map View, et les requêtes Dataview.

---

## Export automatisé vers le vault (`export_obsidian.py`)

Le script `scripts/export_obsidian.py` exporte articles, entités, rapports et synthèses dans la structure `Veille/` du vault. Les notes incluent frontmatter YAML, liens internes `[[entité]]`, graphes Mermaid et géolocalisation.

```bash
# Exporter les 7 derniers jours
python3 scripts/export_obsidian.py --days 7

# Simulation sans écriture
python3 scripts/export_obsidian.py --dry-run --days 7

# Flux spécifique, forcer la réécriture
python3 scripts/export_obsidian.py --flux Intelligence-artificielle --force
```

Structure générée :
```
Veille/
├── articles/     # YYYY-MM-DD_source_slug-titre.md
├── entités/      # Notes entités ≥ 5 mentions (Mermaid co-occ + pie + timeline)
├── rapports/     # Copie des rapports existants
└── synthèses/
    ├── _INDEX.md
    └── <flux>.md
```

L'export peut aussi être lancé depuis l'interface web **Export & Diffusion → onglet Obsidian**.

**Cron Docker** : tous les jours à 8h30 — `30 8 * * * root cd /app && python3 scripts/export_obsidian.py --days 7`

---

## Table des matières

1. [Prérequis](#prérequis)
2. [Plugins recommandés](#plugins-recommandés)
3. [Structure du vault](#structure-du-vault)
4. [Format du frontmatter YAML](#format-du-frontmatter-yaml)
5. [Configuration Map View](#configuration-map-view)
6. [Configuration Dataview](#configuration-dataview)
7. [Requêtes Dataview exemples](#requêtes-dataview-exemples)
8. [Workflow d'export](#workflow-dexport)
9. [Dépannage](#dépannage)

---

## Prérequis

| Élément | Version minimale |
|---|---|
| Obsidian | 1.4.0+ |
| Plugin **Dataview** | 0.5.56+ |
| Plugin **Map View** | 4.0.0+ (optionnel, pour la cartographie) |
| Plugin **Templater** | 2.0+ (optionnel, pour les templates) |

### Variables d'environnement

Dans le fichier `.env` à la racine du projet WUDD.ai, définir le chemin vers le vault :

```env
OBSIDIAN_DIR=/Users/vous/Obsidian/MonVault/WUDD-ai
```

Ce répertoire doit exister et être accessible depuis le conteneur Docker.
Il est monté automatiquement via `docker-compose.yml`.

---

## Plugins recommandés

### Indispensables

- **Dataview** — requêtes dynamiques sur les propriétés YAML
  - Installer via : Paramètres → Modules complémentaires → Parcourir → "Dataview"
  - Activer "JavaScript Queries" dans les paramètres Dataview

- **Properties** (natif Obsidian 1.4+) — panneau de propriétés intégré, aucune installation requise

### Fortement recommandés

- **Map View** — affichage cartographique des notes avec `location`
  - Utilise le champ `location: [lat, lon]` du frontmatter
  - Configurer le provider de tuiles (OpenStreetMap par défaut)

- **Tag Wrangler** — gestion avancée des tags (fusion, renommage)

- **Obsidian Query Language (OQL)** — alternative à Dataview pour les débutants

---

## Structure du vault

```
OBSIDIAN_DIR/
├── WUDD-ai/                    ← répertoire d'export WUDD.ai
│   ├── articles/               ← notes d'articles (export depuis ArticleFullReportDialog)
│   │   ├── 2026-03-16_le-monde_titre-article.md
│   │   └── ...
│   ├── rapports/               ← rapports d'entités (export depuis EntityFullReportDialog)
│   │   ├── rapport_ORG_OpenAI_2026-03-16.md
│   │   └── ...
│   └── _templates/             ← templates Templater (optionnel)
│       └── article-wudd.md
```

> **Note :** le sous-répertoire (`articles/` vs `rapports/`) est déterminé côté serveur
> selon le `target` de l'export. Voir `viewer/routes/export.py`.

---

## Format du frontmatter YAML

### Note d'article (ArticleFullReportDialog)

```yaml
---
title: "Titre de l'article ou nom de la source"
date: 2026-03-16
date_publication: "16/03/2026"
source: "Le Monde"
url: "https://www.lemonde.fr/..."
version: "1.0"
location: [48.8566, 2.3522]          # GPE principale (si résolue via Wikipedia)
sentiment: "positif"
score_sentiment: 4
ton_editorial: "factuel"
score_ton: 5
score_source: 85
temps_lecture: "2 min 30 s"
tags:
  - "Le-Monde"
  - "OpenAI"
  - "Sam-Altman"
  - "France"
personnes:
  - "Sam Altman"
  - "Elon Musk"
organisations:
  - "OpenAI"
  - "Microsoft"
lieux:
  - "France"
  - "Paris"
entites_geo:
  - name: "France"
    location: [46.2276, 2.2137]
  - name: "Paris"
    location: [48.8566, 2.3522]
type: Rapport-WUDD-ai
statut: generated
---
```

### Note de rapport d'entité (EntityFullReportDialog)

```yaml
---
title: "Rapport — ORG : OpenAI"
date: 2026-03-16
version: "1.0"
entity_type: "ORG"
location: [37.3382, -121.8863]        # uniquement pour GPE/LOC
tags:
  - "OpenAI"
  - "Microsoft"
  - "Sam-Altman"
  - "ChatGPT"
type: Rapport-WUDD-ai
statut: generated
---
```

### Règles de nommage des tags

Les tags sont normalisés pour être compatibles avec Obsidian :
- Accents supprimés (`é` → `e`, `ç` → `c`, etc.)
- Espaces remplacés par des tirets (`Sam Altman` → `Sam-Altman`)
- Caractères spéciaux (`:`, `.`, `,`, `?`, `!`, `"`, `'`, etc.) remplacés par des tirets
- Tirets consécutifs fusionnés
- Tirets en début/fin supprimés
- Longueur maximale : 50 caractères

---

## Configuration Map View

Map View lit le champ `location: [lat, lon]` du frontmatter pour positionner les notes sur une carte.

### Installation

1. Paramètres → Modules complémentaires → Parcourir → **"Map View"**
2. Activer le plugin

### Configuration recommandée

Dans les paramètres de Map View :

```json
{
  "defaultMapCenter": { "lat": 46.8, "lng": 8.2 },
  "defaultZoom": 4,
  "mapSource": "openstreetmap",
  "markerIcons": {
    "default": {
      "prefix": "fa",
      "icon": "circle"
    }
  },
  "queryForDefaultView": "type: Rapport-WUDD-ai"
}
```

### Afficher uniquement les notes WUDD.ai sur la carte

Dans la barre de recherche de Map View :

```
type: Rapport-WUDD-ai
```

ou pour les articles d'une source spécifique :

```
source: "Le Monde"
```

### Utilisation des entités géographiques multiples

Les articles peuvent contenir plusieurs GPE/LOC via le champ `entites_geo`. Map View ne lit que le champ `location` de premier niveau (GPE principale). Pour afficher toutes les entités géographiques d'un article, utilisez Dataview (voir ci-dessous).

---

## Configuration Dataview

Activer les options suivantes dans Paramètres → Dataview :

| Option | Valeur recommandée |
|---|---|
| Enable JavaScript Queries | ✅ Activé |
| Enable Inline Queries | ✅ Activé |
| Automatic View Refreshing | ✅ Activé |
| Refresh Interval | 5000 ms |
| Date Format | `YYYY-MM-DD` |

---

## Requêtes Dataview exemples

### 1. Tous les articles WUDD.ai triés par date

````markdown
```dataview
TABLE date, source, sentiment, score_source, temps_lecture
FROM "WUDD-ai"
WHERE type = "Rapport-WUDD-ai"
SORT date DESC
```
````

### 2. Articles positifs à haute crédibilité (score_source ≥ 70)

````markdown
```dataview
TABLE date, source, titre, score_source, score_sentiment
FROM "WUDD-ai"
WHERE type = "Rapport-WUDD-ai"
  AND sentiment = "positif"
  AND score_source >= 70
SORT score_source DESC
LIMIT 20
```
````

### 3. Articles mentionnant une entité spécifique (ex. OpenAI)

````markdown
```dataview
TABLE date, source, url
FROM "WUDD-ai"
WHERE contains(organisations, "OpenAI")
SORT date DESC
```
````

### 4. Carte des articles avec géolocalisation (liste)

````markdown
```dataview
TABLE date, source, location
FROM "WUDD-ai"
WHERE type = "Rapport-WUDD-ai" AND location
SORT date DESC
```
````

### 5. Distribution des sentiments (comptage)

````markdown
```dataviewjs
const pages = dv.pages('"WUDD-ai"').where(p => p.type === "Rapport-WUDD-ai")
const counts = {}
for (const p of pages) {
  const s = p.sentiment ?? "inconnu"
  counts[s] = (counts[s] ?? 0) + 1
}
dv.list(Object.entries(counts).map(([s, n]) => `**${s}** : ${n} articles`))
```
````

### 6. Top 10 sources par nombre d'articles

````markdown
```dataviewjs
const pages = dv.pages('"WUDD-ai"').where(p => p.type === "Rapport-WUDD-ai")
const counts = {}
for (const p of pages) {
  const s = p.source ?? "Inconnu"
  counts[s] = (counts[s] ?? 0) + 1
}
const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10)
dv.table(["Source", "Nb articles"], sorted)
```
````

### 7. Articles récents par entité personnelle

````markdown
```dataview
TABLE date, source, file.link AS Note
FROM "WUDD-ai"
WHERE contains(personnes, "Sam Altman")
SORT date DESC
LIMIT 10
```
````

### 8. Articles géolocalisés en France

````markdown
```dataview
TABLE date, source, location
FROM "WUDD-ai"
WHERE contains(lieux, "France") AND location
SORT date DESC
```
````

### 9. Score moyen par source (JavaScript)

````markdown
```dataviewjs
const pages = dv.pages('"WUDD-ai"')
  .where(p => p.type === "Rapport-WUDD-ai" && p.score_source != null)
const bySource = {}
for (const p of pages) {
  if (!bySource[p.source]) bySource[p.source] = []
  bySource[p.source].push(p.score_source)
}
const result = Object.entries(bySource)
  .map(([src, scores]) => [src, (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1), scores.length])
  .sort((a, b) => b[1] - a[1])
  .slice(0, 15)
dv.table(["Source", "Score moyen", "Nb articles"], result)
```
````

### 10. Synthèse hebdomadaire (7 derniers jours)

````markdown
```dataviewjs
const since = dv.date("today") - dv.duration("7 days")
const pages = dv.pages('"WUDD-ai"')
  .where(p => p.type === "Rapport-WUDD-ai" && p.date >= since)
  .sort(p => p.date, "desc")
dv.paragraph(`**${pages.length} articles** importés cette semaine`)
dv.table(["Date", "Source", "Sentiment", "Titre"],
  pages.map(p => [p.date, p.source, p.sentiment ?? "—", p.file.link]))
```
````

---

## Workflow d'export

### Depuis l'interface WUDD.ai

1. Ouvrir un article ou un rapport d'entité dans le viewer
2. Cliquer sur **"Export Obsidian"** (icône livre violet)
3. Le fichier est créé dans `OBSIDIAN_DIR/` avec le nommage `YYYY-MM-DD_source_slug-titre.md`
4. Obsidian détecte automatiquement le nouveau fichier (synchronisation temps réel)

### Déduplication

Le serveur vérifie le MD5 du résumé avant d'écrire le fichier.
Si une note avec le même contenu existe déjà, le fichier n'est **pas** réécrit.
Une réponse `{ ok: true, deduplicated: true }` est retournée et un tooltip l'indique dans l'interface.

### Nommage des fichiers

| Type | Format | Exemple |
|---|---|---|
| Article | `YYYY-MM-DD_source_slug-titre.md` | `2026-03-16_le-monde_openai-lance-gpt5.md` |
| Rapport entité | `rapport_TYPE_entite_YYYY-MM-DD.md` | `rapport_ORG_OpenAI_2026-03-16.md` |

- Le slug source est limité à 15 caractères
- Le slug titre est limité à 40 caractères
- Les accents et caractères spéciaux sont supprimés du nom de fichier

---

## Dépannage

### Les notes n'apparaissent pas dans Map View

- Vérifier que le champ `location` est présent dans le frontmatter (uniquement si des entités GPE/LOC ont été résolues via Wikipedia)
- Vérifier que Map View est configuré pour lire le bon répertoire
- Recharger le vault : `Ctrl+P` → "Reload app without saving"

### Les tags contiennent des tirets inattendus

C'est intentionnel : Obsidian n'accepte pas les espaces dans les tags.
`Sam Altman` devient `Sam-Altman`, `score: élevé` devient `score-eleve`.

### Dataview ne voit pas les nouvelles notes

- Vérifier que le "Automatic View Refreshing" est activé dans les paramètres Dataview
- Forcer un rechargement : clic droit sur le bloc Dataview → "Force Refresh"

### L'export échoue avec "OBSIDIAN_DIR non configuré"

- Vérifier que `OBSIDIAN_DIR` est défini dans `.env`
- Vérifier que le répertoire existe et est accessible en écriture
- En Docker : vérifier que le volume est correctement monté dans `docker-compose.yml`

### Les coordonnées GPS sont manquantes

Le géocodage s'appuie sur l'API Wikipedia (pas de clé requise).
Il peut échouer si :
- L'entité GPE/LOC n'a pas de page Wikipedia avec coordonnées
- Le réseau est indisponible au moment de l'export
- L'entité est trop générique (ex. "Gouvernement")

Dans ce cas, le champ `location` est simplement absent du frontmatter — la note s'exporte quand même normalement.
