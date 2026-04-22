# Services externes — Dépendances et intégrations

> Document de référence · Version 1.2 · Mars 2026

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Infomaniak EurIA (LLM)](#2-infomaniak-euria-llm)
3. [Flux JSON — Source d'articles](#3-flux-json--source-darticles)
4. [Sources RSS / Sites d'actualité](#4-sources-rss--sites-dactualité)
5. [Wikimedia — Géocodage et galerie d'images](#5-wikimedia--géocodage-et-galerie-dimages)
6. [OpenStreetMap — Tuiles cartographiques](#6-openstreetmap--tuiles-cartographiques)
7. [Sites éditeurs — Extraction d'articles](#7-sites-éditeurs--extraction-darticles)
8. [Tableau récapitulatif](#8-tableau-récapitulatif)
9. [Variables d'environnement liées](#9-variables-denvironnement-liées)
10. [Flux de données global](#10-flux-de-données-global)
11. [Droits, licences et attributions](#11-droits-licences-et-attributions)

---

## 1. Vue d'ensemble

WUDD.ai s'appuie sur plusieurs services externes pour collecter, analyser et visualiser des articles d'actualité. Ces dépendances se répartissent en deux catégories :

- **Critiques** — la plateforme ne peut pas fonctionner sans elles (EurIA, flux JSON, flux RSS)
- **Optionnelles** — enrichissent l'expérience mais ont un mode dégradé acceptable (Wikimedia, OpenStreetMap)

Aucune base de données externe n'est utilisée : tout est stocké localement en JSON.

---

## 2. Infomaniak EurIA (LLM)

**Rôle : génération des résumés, NER, rapports** · Dépendance **critique**

| Attribut | Valeur |
| --- | --- |
| Fournisseur | Infomaniak (hébergeur suisse) |
| Modèle | Qwen/Qwen3.5-122B-A10B-FP8 (API OpenAI-compatible) |
| Endpoint | `https://api.infomaniak.com/2/ai/{PRODUCT_ID}/openai/v1/chat/completions` |
| Authentification | Bearer token (variable `bearer` dans `.env`) |
| Variable d'endpoint | `URL` dans `.env` |

### Utilisations

| Usage | Script / module | Timeout configuré |
| --- | --- | --- |
| Résumés d'articles (20 lignes FR) | `Get_data_from_JSONFile_AskSummary_v2.py`, `get-keyword-from-rss.py` | `TIMEOUT_RESUME` (60 s) |
| Entités nommées NER (18 types) | `enrich_entities.py`, `get-keyword-from-rss.py` | `TIMEOUT_RESUME` (60 s) |
| Rapports thématiques | `articles_json_to_markdown.py`, `scheduler_articles.py` | `TIMEOUT_RAPPORT` (300 s) |
| Analyse radar thématique | `radar_wudd.py` | `TIMEOUT_RAPPORT` (300 s) |
| Réparation de résumés échoués | `repair_failed_summaries.py` | `TIMEOUT_RESUME` (60 s) |

### Taxonomie NER — OntoNotes 5.0

L'extraction d'entités nommées suit la norme **OntoNotes 5.0**, développée par l'Université de Pennsylvanie, BBN Technologies et USC ISI, popularisée par **spaCy**. Les 18 types reconnus (`PERSON`, `ORG`, `GPE`, `LOC`, `PRODUCT`, `EVENT`, `DATE`, `MONEY`…) sont stables, documentés et interopérables avec l'écosystème NLP courant.

> L'extraction est réalisée par prompt soumis à Qwen/Qwen3.5-122B-A10B-FP8, pas par un pipeline NLP classique — le LLM applique la taxonomie OntoNotes et retourne directement le JSON structuré. Voir [docs/ENTITIES.md §3](ENTITIES.md#3-les-18-types-dentités-reconnus) pour la table complète des types.

### Client — `utils/api_client.py`

```python
# Fonctions exposées
generate_summary(text, flux)      # Résumé d'article
generate_entities(text)           # Extraction NER
generate_report(articles, flux)   # Rapport multi-articles
```

### Stratégie de résilience EurIA

- **Retry** : 3 tentatives max, backoff exponentiel ×2.0 (`urllib3.Retry`)
- **Codes retriés** : 429, 500, 502, 503, 504
- **Option** : `enable_web_search: true` activé (recherche web contextuelle lors de l'inférence)
- **Comportement en échec** : le résumé est marqué comme erreur, les articles suivants continuent

### Recommandations

- Surveiller le quota de tokens Infomaniak (tableau de bord infomaniak.com)
- En cas de migration vers un autre LLM : seul `utils/api_client.py` est à modifier (l'URL et le bearer changent dans `.env`)

---

## 3. Flux JSON — Source d'articles

**Rôle : source principale d'articles** · Dépendance **critique**

WUDD.ai consomme des flux d’actualités au format JSON accessibles par URL HTTP. Chaque flux est une collection d’articles sérialisée en JSON, exposable par n’importe quel service ou application compatible (agrégateur RSS, serveur personnalisé, script d’export, etc.).

| Attribut | Valeur |
| --- | --- |
| Format | JSON (tableau d’objets avec `url`, `date_published`, `authors`) |
| Endpoint | Toute URL HTTP retournant un JSON valide |
| Authentification | Aucune requise (l’URL peut intégrer un token) |
| Fréquence de consultation | Hebdomadaire (cron lundi 06:00) |
| Variable d’env. | `REEDER_JSON_URL` dans `.env` |

### Flux configurés (`config/flux_json_sources.json`)

| Flux | Thématique |
| --- | --- |
| Intelligence-artificielle | IA, tech |
| Suisse | Actualité suisse |
| Trump | Politique US |

### Ajouter un flux

1. Obtenir l’URL HTTP du flux JSON source
2. Ajouter une entrée dans `config/flux_json_sources.json` avec `title` et `url`
3. Le scheduler le traitera automatiquement au prochain lundi 06:00

### Comportement en cas d’indisponibilité du flux

Le script `Get_data_from_JSONFile_AskSummary_v2.py` lève une exception et s’arrête. Le flux concerné est ignoré lors du cycle suivant si la même URL échoue.

---

## 4. Sources RSS / Sites d'actualité

**Rôle : veille par mots-clés** · Dépendance **critique**

133 sources RSS enregistrées dans `config/sites_actualite.json`, consultées quotidiennement par `scripts/get-keyword-from-rss.py`.

### Catégories de sources

| Catégorie | Exemples |
| --- | --- |
| Presse tech | CNET, Les Numériques, Mashable, 01net |
| Blogs indépendants | Daring Fireball, Underscore_, Marco.org |
| Médias généralistes | RTS Première, France Culture, Futura Sciences |
| Réseaux sociaux | Mastodon (techhub.social, mastodon.social, mastodon.nl) |
| Vidéo | YouTube (France Culture, IGN France), Konbini |
| Reddit | r/MachineLearning, r/artificial, etc. |

### Mots-clés de surveillance (`config/keyword-to-search.json`)

Les mots-clés déclenchent la collecte dans les 133 sources. Un article est retenu si le mot-clé apparaît dans le titre ou la description RSS.

### Comportement en cas d'indisponibilité d'une source RSS

Une source RSS inaccessible est ignorée (timeout 10 s). Les autres sources continuent. Un avertissement est loggé.

---

## 5. Wikimedia — Géocodage et galerie d'images

**Rôle : coordonnées géographiques (carte) et images (galerie) des entités NER** · Dépendance **optionnelle**

Le viewer utilise quatre APIs de l'écosystème Wikimedia pour enrichir le Dashboard Entités :

| API | Usage | Vue concernée |
| --- | --- | --- |
| Wikipedia `coordinates` | Géocodage GPE/LOC | Vue Carte |
| Wikipedia `pageimages` | Portrait des entités PERSON | Vue Galerie |
| Wikidata `wbgetentities` (P154) | Logo officiel des ORG/PRODUCT | Vue Galerie |
| Wikimedia Commons `imageinfo` | Résolution URL des logos P154 | Vue Galerie |

Toutes les requêtes exigent un `User-Agent` valide — Wikipedia bloque les requêtes sans ce header (HTTP 403).

```python
# Dans viewer/app.py — header commun à tous les appels Wikimedia
headers={"User-Agent": "WUDD.ai/2.1.0 (news monitoring tool; ...) python-requests"}
```

---

### 5a. Géocodage — entités GPE / LOC

| Attribut | Valeur |
| --- | --- |
| Endpoints | `https://fr.wikipedia.org/w/api.php` (priorité) · `https://en.wikipedia.org/w/api.php` (fallback) |
| Prop utilisée | `coordinates` |
| Taille des batchs | 50 entités par requête |
| Timeout | 10 s par requête |
| Cache local | `data/geocode_cache.json` (TTL illimité) |

Stratégie de fallback : FR d'abord, EN pour les entités non trouvées. Redirections/normalisations Wikipedia gérées automatiquement. Entité sans coordonnées → `null` en cache, absente de la carte.

> **Note** : Si le cache contient des `null` erronés (suite à un problème réseau), supprimer `data/geocode_cache.json` pour forcer une nouvelle tentative.

---

### 5b. Galerie d'images — entités PERSON / ORG / PRODUCT

| Attribut | Valeur |
| --- | --- |
| Cache local | `data/images_cache.json` (TTL illimité) |
| Taille des batchs | 50 entités par requête |
| Timeout | 10 s par requête |

**Stratégie par type d'entité :**

**PERSON** — Wikipedia `pageimages` (portrait de la page Wikipedia) :

- Requête FR d'abord, EN en fallback
- L'image principale de l'article Wikipedia est retournée (généralement un portrait)

**ORG / PRODUCT** — Wikidata P154 (propriété « logo image ») + fallback `pageimages` :

1. `wbgetentities` sur Wikidata via enwiki puis frwiki → récupère la propriété P154 (nom de fichier du logo sur Commons)
2. Si P154 trouvée → `imageinfo` sur Commons pour résoudre l'URL de la miniature
3. Fallback `pageimages` si l'entité est connue de Wikidata avec un type ORG/PRODUCT (P31 ∈ liste blanche) mais sans P154

**Règle de rejet des faux positifs :**

Un nom de produit ou d'organisation peut correspondre à un article Wikipedia hors-scope (prénom, manuscrit, concept linguistique…). Pour éviter les images incorrectes, l'entité Wikidata trouvée est rejetée si :

- Son P31 (instance de) appartient aux types disqualifiants : `Q5` (humain), `Q202444` (prénom), `Q101352` (nom de famille), `Q4167410` (homonymie)
- Son P31 est absent ou n'inclut aucun type compatible (entreprise, logiciel, organisation…)

Dans les deux cas, la tuile affiche un placeholder avec les initiales de l'entité — aucun fallback `pageimages` n'est tenté.

Exemples de noms correctement filtrés : _Claude_ (prénom français), _Codex_ (manuscrit médiéval), _Word_ (mot du dictionnaire), _Gemini_ (signe du zodiaque).

---

## 6. OpenStreetMap — Tuiles cartographiques

**Rôle : fond de carte pour la visualisation** · Dépendance **optionnelle**

| Attribut | Valeur |
| --- | --- |
| URL des tuiles | `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` |
| Authentification | Aucune — service public |
| Bibliothèque | `leaflet` 1.9.4 + `react-leaflet` 4.2.1 |
| Attribution obligatoire | `© OpenStreetMap contributors` |

Les tuiles sont chargées à la volée par le navigateur lors de l'affichage de la carte. Aucune donnée n'est envoyée à OpenStreetMap (simple requête GET d'image).

**Comportement en cas d'indisponibilité** : le fond de carte est blanc, mais les marqueurs et tooltips restent fonctionnels si les coordonnées sont en cache.

> Pour un usage intensif en production, envisager [un serveur de tuiles auto-hébergé](https://switch2osm.org/) ou [Maptiler](https://www.maptiler.com/).

---

## 7. Sites éditeurs — Extraction d'articles

**Rôle : récupération du texte complet et des images** · Dépendance **critique**

Pour chaque article, le pipeline effectue un `GET` vers l'URL de l'article original afin d'en extraire le texte et les images.

| Attribut | Valeur |
| --- | --- |
| Bibliothèque HTTP | `requests` + `urllib3.Retry` |
| Parser HTML | `beautifulsoup4` |
| Timeout | 10–15 s selon le script |
| Filtrage images | Largeur > 500 px, protocole `https://`, max 3 par article |
| Module | `utils/http_utils.py` — `fetch_and_extract_text()`, `extract_top_n_largest_images()` |

### Stratégie de résilience HTTP

- **Codes HTTP retriés** : 429, 500, 502, 503, 504
- **Backoff** : facteur 0.5 (urllib3)
- **Robots.txt** : non vérifié — à surveiller selon les sources

### Comportement en cas d'échec d'extraction

Si un article est inaccessible (403, timeout, connexion refusée), le script log l'erreur et passe à l'article suivant. Le résumé ne peut pas être généré sans le texte source.

---

## 8. Tableau récapitulatif

| Service | Type | Criticité | Auth | Fichiers principaux |
| --- | --- | --- | --- | --- |
| **Infomaniak EurIA** | LLM / IA | Critique | Bearer token | `utils/api_client.py` |
| **Flux JSON (HTTP)** | Source d'articles JSON | Critique | URL (token optionnel) | `Get_data_from_JSONFile_AskSummary_v2.py` |
| **133+ flux RSS** | Sources d'actualité | Critique | Publique | `get-keyword-from-rss.py` |
| **Wikipedia API** | Géocodage + images PERSON | Optionnel | User-Agent | `viewer/app.py` |
| **Wikidata** | Logos ORG/PRODUCT (P154) | Optionnel | User-Agent | `viewer/app.py` |
| **Wikimedia Commons** | Résolution URLs logos | Optionnel | User-Agent | `viewer/app.py` |
| **OpenStreetMap** | Tuiles carte | Optionnel | Publique | `EntityWorldMap.jsx` |
| **Sites éditeurs** | Contenu articles | Critique | Aucune | `utils/http_utils.py` |

---

## 9. Variables d'environnement liées

Toutes définies dans `.env` (cf. `.env.example`) :

| Variable | Service | Requis |
| --- | --- | --- |
| `URL` | Infomaniak EurIA — endpoint API | Oui |
| `bearer` | Infomaniak EurIA — token Bearer | Oui |
| `REEDER_JSON_URL` | URL du flux JSON source | Oui |
| `MAX_RETRIES` | Tous appels HTTP — nombre max de tentatives | Non (défaut : 3) |
| `TIMEOUT_RESUME` | EurIA — timeout génération résumé | Non (défaut : 60 s) |
| `TIMEOUT_RAPPORT` | EurIA — timeout génération rapport | Non (défaut : 300 s) |

> **Règle absolue** : ne jamais modifier `.env` sans accord explicite. Ne jamais le committer (`.gitignore`).

---

## 10. Flux de données global

```text
┌──────────────────────────────────────────────────────────────┐
│  SOURCES D'ENTRÉE                                            │
│                                                              │
│  Flux JSON (HTTP) ─────────────────────────────────────┐     │
│  (URL configurée dans flux_json_sources.json)          │     │
│                                                        │     │
│  RSS / OPML (133 sources) ─────────────────────────────┤     │
│  (sites_actualite.json + keyword-to-search.json)       │     │
└────────────────────────────────────────────────────────┼─────┘
                                                         │
                                                         ▼
┌──────────────────────────────────────────────────────────────┐
│  EXTRACTION (utils/http_utils.py)                            │
│                                                              │
│  GET https://[site-éditeur]/article                          │
│  → Texte (BeautifulSoup) + Images (>500px)                   │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  ANALYSE IA — Infomaniak EurIA (Qwen/Qwen3.5-122B-A10B-FP8)  │
│  api.infomaniak.com/2/ai/.../openai/v1/chat/completions      │
│                                                              │
│  → Résumé 20 lignes (FR)                                     │
│  → Entités nommées NER (18 types : PERSON, ORG, GPE…)        │
│  → Rapport thématique multi-articles                         │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  STOCKAGE LOCAL (data/, rapports/)                           │
│  JSON → Markdown → PDF                                       │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  VIEWER (Flask :5050 + React)                                │
│                                                              │
│  Entités GPE/LOC → Wikipedia API (fr/en.wikipedia.org)       │
│                  → Cache geocode_cache.json                  │
│                  → OpenStreetMap (tile.openstreetmap.org)    │
│                  → Carte interactive Leaflet                 │
│                                                              │
│  Entités PERSON  → Wikipedia pageimages                      │
│  Entités ORG/    → Wikidata P154 + Commons imageinfo         │
│    PRODUCT       → Cache images_cache.json                   │
│                  → Galerie avec placeholders initiales       │
└──────────────────────────────────────────────────────────────┘
```

---

## 11. Droits, licences et attributions

### Synthèse par service

| Service | Licence du contenu | Attribution requise | Statut dans WUDD.ai |
| --- | --- | --- | --- |
| **OpenStreetMap** (tuiles) | ODbL 1.0 | Oui — `© OpenStreetMap contributors` | ✅ Affichée automatiquement par Leaflet dans l'UI |
| **Leaflet** (bibliothèque) | BSD 2-Clause | Oui — lien `Leaflet` | ✅ Affiché automatiquement en coin de carte |
| **Wikipedia** (images `pageimages`) | CC BY-SA 3.0 / 4.0 selon les fichiers | Oui — lien vers la page source | ⚠️ Usage éditorial non commercial — voir ci-dessous |
| **Wikidata** (données P154) | CC0 1.0 (domaine public) | Non | ✅ Aucune contrainte |
| **Wikimedia Commons** (URLs logos) | Variable par fichier | Dépend du fichier | ⚠️ Usage éditorial non commercial — voir ci-dessous |
| **Logos d'entreprises** (via P154) | Droit des marques | Non (usage informatif) | ✅ Usage éditorial acceptable |
| **Infomaniak EurIA** | API commerciale (CGU Infomaniak) | Non dans l'UI | ✅ Régulé par le contrat de service |
| **Flux JSON (HTTP)** | Propriété source | Non dans l'UI | ✅ Accès via URL configurée par l'utilisateur |

---

### OpenStreetMap — ODbL 1.0

La [Open Database License (ODbL)](https://www.openstreetmap.org/copyright) impose une attribution visible sur toute carte ou application dérivée des données OSM.

**Implémentation dans WUDD.ai :** la mention est insérée directement dans le composant `EntityWorldMap.jsx` via la prop `attribution` du `TileLayer` de react-leaflet. Leaflet la rend automatiquement sous forme de lien cliquable en bas à droite de la carte. Aucune action supplémentaire n'est requise.

```jsx
// viewer/src/components/EntityWorldMap.jsx
<TileLayer
  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
/>
```

---

### Leaflet — BSD 2-Clause

La bibliothèque [Leaflet](https://leafletjs.com) est sous licence BSD 2-Clause. Elle affiche automatiquement un lien « Leaflet » en coin de carte, satisfaisant l'attribution attendue. Aucune mention supplémentaire n'est requise dans l'interface.

---

### Wikimedia (Wikipedia · Wikidata · Commons)

**Images Wikipedia (`pageimages`) :**
Les images retournées par l'API `pageimages` proviennent d'articles Wikipedia. Chaque image possède sa propre licence, souvent CC BY-SA 3.0 ou 4.0, qui impose un lien vers la source et le nom de l'auteur. WUDD.ai affiche ces images dans un contexte de veille informationnelle personnelle et non commerciale, ce qui relève de l'usage éditorial toléré. Pour une publication ou redistribution publique, il faudrait afficher pour chaque image un lien vers la page Wikipedia source.

**Données Wikidata (P154) :**
Le contenu de Wikidata est publié sous [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (domaine public). Aucune attribution n'est requise pour l'utilisation des données P154. L'obligation se limite au respect du [User-Agent policy](https://meta.wikimedia.org/wiki/User-Agent_policy) de Wikimedia, déjà implémenté.

**Logos via Wikimedia Commons :**
Les fichiers hébergés sur Commons ont des licences variées (CC0, CC BY, CC BY-SA, domaine public, fair use…). Les logos d'entreprises sont le plus souvent déposés sous statut « non libre » ou fair use encyclopédique sur Commons. Leur affichage dans WUDD.ai s'inscrit dans un usage informatif non commercial (identification visuelle d'une entité dans un outil de veille), analogue à l'usage éditorial.

**Exigence User-Agent (toutes APIs Wikimedia) :**
Les APIs Wikipedia, Wikidata et Commons bloquent les requêtes sans `User-Agent` valide identifiant l'application. WUDD.ai respecte cette politique avec le header suivant, présent dans `viewer/app.py` :

```python
"WUDD.ai/2.1.0 (news monitoring tool; https://github.com/patrickostertag) python-requests"
```

---

### OntoNotes 5.0 — Standard de taxonomie NER

Le schéma de typage des entités nommées est emprunté au corpus **OntoNotes 5.0**, distribué par le [Linguistic Data Consortium (LDC)](https://catalog.ldc.upenn.edu/LDC2013T19) sous licence LDC. WUDD.ai utilise uniquement les noms de catégories (PERSON, ORG, GPE…) comme convention de typage, sans redistribuer les données du corpus. Aucune attribution contractuelle n'est requise pour cet usage nomenclatural.

La bibliothèque **spaCy** (MIT License), qui a popularisé cette taxonomie, n'est pas une dépendance de WUDD.ai : le typage est appliqué directement par Qwen/Qwen3.5-122B-A10B-FP8 via prompt.

---

### Logos d'entreprises et droit des marques

Les logos affichés dans la galerie (récupérés via Wikidata P154) sont des marques déposées appartenant à leurs sociétés respectives. Leur reproduction est acceptée dans un cadre informatif et non commercial — à titre d'identification visuelle des entités citées dans les articles de presse surveillés. Toute utilisation commerciale ou redistribution publique de ces logos nécessiterait l'accord des titulaires des marques concernées.
