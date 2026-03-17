# Use Cases — WUDD.ai

> Quinze scénarios typiques d'utilisation de la plateforme, du point de vue de l'utilisateur, dont deux optimisés pour une utilisation sur smartphone en situation de mobilité.
> Chaque use case est illustré par un diagramme Mermaid.

---

## Table des matières

1. [Veille quotidienne par mots-clés](#1-veille-quotidienne-par-mots-clés)
2. [Rapport de synthèse hebdomadaire multi-flux](#2-rapport-de-synthèse-hebdomadaire-multi-flux)
3. [Recherche transversale sur une entité nommée](#3-recherche-transversale-sur-une-entité-nommée)
4. [Cartographie géopolitique des sujets](#4-cartographie-géopolitique-des-sujets)
5. [Exploration du réseau sémantique](#5-exploration-du-réseau-sémantique)
6. [Rapport ad hoc avec Claude](#6-rapport-ad-hoc-avec-claude)
7. [Lecture des résumés en déplacement (mobile)](#7-lecture-des-résumés-en-déplacement-mobile)
8. [Briefing entités avant réunion (mobile)](#8-briefing-entités-avant-réunion-mobile)
9. [Rapport de veille quotidien Top 10 entités (48h)](#9-rapport-de-veille-quotidien-top-10-entités-48h)
10. [Sélection des articles les plus pertinents](#10-sélection-des-articles-les-plus-pertinents)
11. [Détection de tendances et alertes émergentes](#11-détection-de-tendances-et-alertes-émergentes)
12. [Analyse des biais éditoriaux par source](#12-analyse-des-biais-éditoriaux-par-source)
13. [Synthèse comparative RAG multi-sources](#13-synthèse-comparative-rag-multi-sources)
14. [Export et diffusion des résultats](#14-export-et-diffusion-des-résultats)
15. [Interrogation par terminal IA (local AI agent)](#15-interrogation-par-terminal-ia-local-ai-agent)
16. [Export vers Obsidian](#16-export-vers-obsidian)
17. [Vérification de la fiabilité des sources](#17-vérification-de-la-fiabilité-des-sources)

---

## 1. Veille quotidienne par mots-clés

**Contexte :** L'utilisateur suit un sujet précis (ex. « intelligence artificielle », « cybersécurité ») et veut être informé chaque matin des nouveaux articles correspondants, résumés en français par l'IA, sans lire les sources une par une.

**Acteurs :** Utilisateur · Docker/cron · API EurIA · Flux RSS (133+ sources)

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant V as Viewer (navigateur)
    participant F as Flask (app.py)
    participant S as get-keyword-from-rss.py
    participant E as API EurIA (Qwen3)
    participant R as Flux RSS

    Note over U,R: Configuration initiale (une fois)
    U->>V: Ouvre Réglages → onglet Mots-clés
    U->>V: Ajoute « intelligence artificielle »
    V->>F: POST /api/keywords
    F-->>V: { ok: true }

    Note over U,R: Extraction quotidienne (automatique ou manuelle)
    U->>V: Clique "Mots-clés RSS" → Démarrer
    V->>F: GET /api/scripts/keyword-rss/stream (SSE)
    F->>S: subprocess.Popen(get-keyword-from-rss.py)
    loop Pour chaque source RSS
        S->>R: GET feed (urllib)
        R-->>S: Articles des 7 derniers jours
        S->>S: Filtre par mot-clé (word-boundary)
        S->>E: POST résumé IA (60s)
        E-->>S: Résumé 20 lignes
        S->>E: POST extraction NER (18 types)
        E-->>S: { PERSON, ORG, GPE… }
        S-->>V: SSE log ligne par ligne
    end
    S-->>F: code retour 0
    F-->>V: { done: true, returncode: 0 }
    V->>F: GET /api/files (refresh auto)
    F-->>V: Liste mise à jour

    Note over U,R: Consultation
    U->>V: Sélectionne data/articles-from-rss/intelligence-artificielle.json
    V->>F: GET /api/content?path=…
    F-->>V: Contenu JSON
    U->>V: Bascule en vue "Articles"
    U->>U: Lit les résumés IA, consulte les images
```

**Valeur produite :** Un fichier JSON enrichi par flux de mots-clés, avec résumés IA et entités NER, consultable directement dans le viewer sans quitter l'interface.

---

## 2. Rapport de synthèse hebdomadaire multi-flux

**Contexte :** Chaque lundi, l'utilisateur veut recevoir un rapport de synthèse structuré couvrant l'ensemble de ses flux d'actualités (IA généraliste, Tech, Géopolitique…), rédigé et organisé automatiquement par l'IA.

**Acteurs :** Utilisateur · Docker/cron · scheduler_articles.py · API EurIA

```mermaid
flowchart TD
    START([Lundi 06h00 — cron déclenche]) --> SCHED[scheduler_articles.py\nlit flux_json_sources.json]
    SCHED --> LOOP{Pour chaque flux}
    LOOP --> FETCH[Collecte articles\nFlux JSON (HTTP)]
    FETCH --> FILTER[Filtre par date\n1er du mois → aujourd'hui]
    FILTER --> HTML[Extraction texte\nBeautifulSoup4]
    HTML --> CACHE{Cache API\n24h ?}
    CACHE -->|Oui| REUSE[Résumé en cache]
    CACHE -->|Non| EURIA1[POST EurIA\nRésumé 20 lignes · 60s]
    EURIA1 --> NER[POST EurIA\nExtraction NER]
    NER --> REUSE
    REUSE --> IMG[Images > 500px\nTop 3 par article]
    IMG --> JSON_OUT[data/articles/flux/\narticles_generated_*.json]
    JSON_OUT --> RAPPORT[POST EurIA\nRapport synthèse · 300s]
    RAPPORT --> MD[rapports/markdown/flux/\nrapport_sommaire_*.md]
    MD --> LOOP

    LOOP -->|Tous les flux traités| VIEWER

    subgraph VIEWER["Utilisateur — Viewer"]
        V1[Ouvre le viewer]
        V2[Sidebar → flux → rapport Markdown]
        V3[Lecture rendue avec images\net diagrammes Mermaid]
        V4[Télécharge le fichier MD]
        V1 --> V2 --> V3 --> V4
    end

    classDef auto fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    classDef storage fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px
    classDef viewer fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    class START,SCHED,FETCH,FILTER,HTML,EURIA1,NER,IMG,RAPPORT auto
    class JSON_OUT,MD storage
    class VIEWER,V1,V2,V3,V4 viewer
```

**Valeur produite :** Un rapport Markdown hebdomadaire prêt à lire, structuré par catégories thématiques identifiées par l'IA, avec images et tableau de références, sans aucune intervention manuelle.

---

## 3. Recherche transversale sur une entité nommée

**Contexte :** L'utilisateur veut savoir tout ce que le corpus d'articles dit sur un acteur précis — une entreprise, une personnalité, un pays — en agrégeant les mentions à travers tous les flux et toutes les dates.

**Acteurs :** Utilisateur · Viewer · Flask · Wikipedia/Wikidata · API EurIA

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant D as EntityDashboard
    participant P as EntityArticlePanel
    participant F as Flask
    participant W as Wikipedia / Wikidata
    participant E as API EurIA

    U->>D: Clique "Entités" dans la barre principale
    D->>F: GET /api/entities/dashboard
    F-->>D: Stats agrégées (top 50 par type)
    D-->>U: Liste : PERSON · ORG · GPE · PRODUCT…

    U->>D: Clique sur "OpenAI" (ORG)
    D->>P: Ouvre EntityArticlePanel

    par Articles
        P->>F: GET /api/entities/articles?type=ORG&value=OpenAI
        F-->>P: 47 articles triés par date
    and Image
        P->>F: POST /api/entities/images [{name:"OpenAI", type:"ORG"}]
        F->>W: Wikidata P154 (logo officiel)
        W-->>F: Logo URL
        F-->>P: { url, width, height }
    end

    U->>P: Lit les résumés des articles
    U->>P: Clique onglet "Infos"
    P->>F: GET /api/entities/info?type=ORG&value=OpenAI (SSE)
    F->>E: POST EurIA — synthèse encyclopédique streaming
    E-->>F: Tokens en streaming
    F-->>P: SSE chunks (filtre <think>)
    P-->>U: Markdown rendu progressivement

    U->>P: Clique "Rapport"
    P-->>U: Téléchargement rapport_ORG_OpenAI_2026-03-02.md
```

**Valeur produite :** En quelques clics, l'utilisateur obtient une vue 360° sur n'importe quelle entité : tous les articles qui la mentionnent, une synthèse encyclopédique à jour (web search), un logo, et un rapport Markdown exportable.

---

## 4. Cartographie géopolitique des sujets

**Contexte :** L'utilisateur veut identifier les zones géographiques les plus présentes dans ses sources d'actualités, détecter des hotspots émergents et explorer rapidement les articles associés à une région.

**Acteurs :** Utilisateur · Viewer · Flask · Wikipedia API (géocodage)

```mermaid
flowchart LR
    U([Utilisateur]) --> DASH[EntityDashboard\nonglet 🗺 Carte]
    DASH --> API1[GET /api/entities/dashboard\nEntités GPE + LOC]
    API1 --> GEO[POST /api/entities/geocode\nliste de noms]

    subgraph GEO_CACHE["Géocodage (Wikipedia API + cache JSON)"]
        CHECK{Dans le\ncache ?}
        WIKI[Wikipedia API\nfr puis en]
        STORE[data/geocode_cache.json\nmise à jour]
        CHECK -->|Non| WIKI --> STORE
        CHECK -->|Oui| HIT[Coordonnées\nen cache]
    end

    GEO --> CHECK
    STORE --> MAP
    HIT --> MAP

    MAP[Carte Leaflet\nCircleMarker par entité\nrayon ∝ nb mentions]
    MAP --> U2([Utilisateur voit\nles hotspots])

    U2 -->|Clique sur un marqueur| PANEL[EntityArticlePanel\narticles filtrés par GPE/LOC]
    PANEL --> ART[Articles mentionnant\ncette zone géographique]
    ART --> EXPORT[Exporte JSON\nou génère rapport MD]

    classDef ui fill:#e3f2fd,stroke:#1565c0,stroke-width:1px
    classDef api fill:#fff3e0,stroke:#f57c00,stroke-width:1px
    classDef cache fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px
    class DASH,MAP,PANEL,ART,EXPORT ui
    class API1,GEO,WIKI api
    class CHECK,STORE,HIT cache
```

![Cartographie géopolitique — carte mondiale des entités](Screen-captures/WWUD.ai-Viewer-entities-map-world.png)

**Valeur produite :** Une carte mondiale interactive où chaque cercle représente une entité géopolitique mentionnée dans le corpus — sa taille reflète la fréquence des mentions. Un clic ouvre instantanément les articles correspondants.

---

## 5. Exploration du réseau sémantique

**Contexte :** L'utilisateur part d'une entité connue et veut découvrir quelles autres entités lui sont le plus souvent associées dans les articles — pour identifier des acteurs, des tendances ou des connexions inattendues.

**Acteurs :** Utilisateur · EntityArticlePanel · EntityGraph · Flask

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant P as EntityArticlePanel
    participant G as EntityGraph (SVG)
    participant F as Flask

    U->>P: Ouvre l'entité "Anthropic" (ORG)
    U->>P: Clique onglet "Graphe"

    P->>F: GET /api/entities/cooccurrences?type=ORG&value=Anthropic&depth=1&limit=40
    F-->>P: { nodes: [...], edges: [...], total_cooc: 312 }
    P->>G: Rendu SVG — algorithme Fruchterman-Reingold\n240 itérations · nœud central ancré

    G-->>U: Graphe interactif\n"Anthropic" au centre\nClaude · OpenAI · Sam Altman\nFrance · 2026 · IA… autour

    U->>G: Survole un nœud → tooltip (nb co-occurrences)
    U->>G: Active "Profondeur 2"
    G->>F: GET /api/entities/cooccurrences?depth=2&limit=12
    F-->>G: Nœuds L2 (entités des entités)
    G-->>U: Graphe étendu — réseau à 2 degrés

    U->>G: Clique sur "Sam Altman" (PERSON)
    Note over U,F: Navigation interne : nouvelle entité centrale
    G->>F: GET /api/entities/articles?type=PERSON&value=Sam Altman
    F-->>P: Articles mis à jour
    G->>F: GET /api/entities/cooccurrences?type=PERSON&value=Sam Altman
    F-->>G: Nouveau graphe centré sur Sam Altman

    U->>P: Revient à la liste → Exporte JSON des articles
```

![Exploration du réseau sémantique — graphe de co-occurrences](Screen-captures/WWUD.ai-Viewer-entities-relations.png)

**Valeur produite :** L'utilisateur navigue dans le réseau sémantique de son corpus comme dans une carte mentale vivante — chaque clic recentre le graphe sur une nouvelle entité, révélant progressivement la structure relationnelle de l'information collectée.

---

## 6. Rapport ad hoc avec Claude

**Contexte :** L'utilisateur dispose d'un fichier JSON d'articles (généré par le pipeline ou l'extraction RSS) et veut obtenir rapidement un rapport de synthèse structuré, rédigé par Claude, sans passer par le pipeline automatique. Il utilise le [prompt dédié](instructions-for-claude-report.md) qui groupe les articles par thématiques, insère les images et produit un Markdown compatible iA Writer.

**Acteurs :** Utilisateur · Viewer · Claude (IA) · [instructions-for-claude-report.md](instructions-for-claude-report.md)

**Exemple de résultat :** [claude-generated-rapport-anthropic-20-28-fev-2026.pdf](../samples/claude-generated-rapport-anthropic-20-28-fev-2026.pdf)

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant V as Viewer (navigateur)
    participant F as Flask
    participant C as Claude (IA)

    U->>V: Selectionne un fichier JSON d articles
    V->>F: GET /api/content?path=...
    F-->>V: Contenu JSON (articles + resumes + entites)
    U->>V: Telecharge le fichier JSON

    Note over U,C: Hors pipeline — interaction directe avec Claude
    U->>C: Soumet le JSON + prompt instructions-for-claude-report.md
    Note over C: Groupe par thematiques societales\nRedige intro + sections + tableau references\nInsere images (URL HTTP > 500px)

    C-->>U: Rapport Markdown structure\n(frontmatter iA Writer · TOC · corps · references)

    U->>U: Copie le Markdown dans iA Writer
    U->>U: Exporte en PDF / partage
```

**Valeur produite :** Un rapport de synthèse thématique complet en quelques minutes, sans configuration ni attente de pipeline — idéal pour un corpus ponctuel (mot-clé, entité, période) ou une demande urgente. Le [prompt dédié](instructions-for-claude-report.md) garantit une structure et un style cohérents à chaque génération.

---

## 7. Lecture des résumés en déplacement (mobile)

**Contexte :** L'utilisateur consulte ses résumés pendant ses trajets quotidiens (métro, train, salle d'attente) depuis son iPhone. L'interface responsive du viewer — drawer hamburger, navigation en bas d'écran, vue cartes en pleine largeur — permet une lecture fluide sans souris ni clavier. En quelques secondes, il retrouve les derniers articles collectés, les parcourt en mode carte ou chronologique, et accède aux images associées.

**Acteurs :** Utilisateur (smartphone) · Viewer (Flask · React responsive) · Fichiers JSON locaux

**Caractéristiques iPhone :** sidebar en drawer (☰), barre de navigation fixée en bas (`safe-area-inset-bottom`), taille de police respectant les préférences système iOS, `theme-color` dynamique clair/sombre.

```mermaid
sequenceDiagram
    actor U as Utilisateur (iPhone)
    participant V as Viewer (navigateur mobile)
    participant F as Flask

    Note over U,F: Déplacement — connexion Wi-Fi ou LAN domestique
    U->>V: Ouvre http://localhost:5050 depuis Safari
    V->>F: GET /api/files
    F-->>V: Liste des flux et fichiers JSON
    V-->>U: Sidebar fermée — icône ☰ visible

    U->>V: Tape ☰ — drawer s'ouvre
    U->>V: Sélectionne le flux « Intelligence-IA »
    V-->>U: Liste des fichiers JSON du flux
    U->>V: Tape le fichier articles_generated_2026-02-01_2026-02-28.json
    V->>F: GET /api/stream-content?path=… (streaming)
    F-->>V: Contenu JSON en chunks (progress bar)
    V-->>U: Vue Articles — cartes en pleine largeur

    loop Pour chaque article
        U->>V: Scroll vertical — lit le résumé (20 lignes max)
        U->>V: Appuie sur une image → lien source
        U->>V: Appuie sur l'URL → ouvre dans Safari
    end

    U->>V: Appuie sur 🔍 (barre de nav bas) → Recherche plein texte
    U->>V: Tape « Mistral »
    V->>F: GET /api/search?q=Mistral
    F-->>V: Articles correspondants (cross-flux)
    V-->>U: Résultats avec extraits mis en évidence
```

![Liste des fichiers — vue iPhone](Screen-captures/WWUD.ai-Viewer-files.mobile.png)

![Articles — vue iPhone](Screen-captures/WWUD.ai-Viewer-articles-mobile.png)

**Valeur produite :** Accès instantané à l'ensemble des résumés collectés depuis un iPhone, sans application native ni synchronisation cloud — la veille se consulte comme un journal personnalisé, sur ses propres données, en toute confidentialité.

---

## 8. Briefing entités avant réunion (mobile)

**Contexte :** Avant d'entrer en réunion ou en conférence, l'utilisateur veut en deux minutes identifier quels acteurs (personnes, organisations, pays) dominent l'actualité de ses flux, visualiser leur répartition géographique sur une carte, et parcourir la galerie des images associées pour ancrer visuellement les sujets du jour.

**Acteurs :** Utilisateur (smartphone) · EntityDashboard · Carte Leaflet (mobile) · Galerie NER · Wikipedia/Wikidata

**Usage type :** couloir, salle de réunion, 2–3 minutes avant le début d'un entretien ou d'une présentation.

```mermaid
flowchart TD
    U([Utilisateur iPhone]) --> NAV[Barre de nav bas\nAppuie sur l icone Entites]
    NAV --> DASH[EntityDashboard\nchargement stats agregees]

    DASH --> CHOIX{Que cherche-t-il ?}

    CHOIX -->|Acteurs cles| LISTE[Vue Liste\nTop entites par type\nPERSON · ORG · GPE]
    LISTE --> CARD[Appuie sur une entite\nOuvre EntityArticlePanel]
    CARD --> ART[Articles filtres\nvue carte mobile pleine largeur]

    CHOIX -->|Zones geographiques| CARTE[Vue Carte Leaflet\nCircleMarker proportionnel\nau nb de mentions]
    CARTE --> MARKER[Appuie sur un marqueur\nnom + compteur]
    MARKER --> ART

    CHOIX -->|Apercu visuel rapide| GALERIE[Vue Galerie\nImages NER Wikipedia / Wikidata]
    GALERIE --> IMG[Grille d imagettes\nIdentification visuelle des acteurs]
    IMG --> ART

    ART --> READ[Lecture resume\nscroll vertical]
    READ --> DONE([Briefing termine\nReunion prete])

    classDef mobile fill:#e3f2fd,stroke:#1565c0,stroke-width:1px
    classDef entity fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px
    class U,NAV,CARD,ART,READ,DONE mobile
    class DASH,LISTE,CARTE,GALERIE,MARKER,IMG entity
```

![Dashboard entités — carte géographique mobile](Screen-captures/WWUD.ai-Viewer-entities-map-mobile.png)

![Dashboard entités — galerie d'images mobile](Screen-captures/WWUD.ai-Viewer-entities-galerie-mobile.png)

**Valeur produite :** En moins de trois minutes depuis un smartphone, l'utilisateur identifie les acteurs dominants de l'actualité récente, visualise leur ancrage géographique et les reconnaît visuellement — sans ordinateur, sans application dédiée, sur ses propres données.

## 9. Rapport de veille quotidien Top 10 entités (48h)

**Contexte :** Chaque soir à 23h00, un rapport de veille analytique est généré automatiquement à partir des articles collectés dans les 48 dernières heures. Le script identifie les 10 entités nommées les plus citées (personnes, organisations, pays, produits, événements), rédige une analyse structurée pour chacune — contexte encyclopédique, actualité des 48h avec sources, analyse stratégique — puis synthétise les corrélations et signaux faibles détectés.

**Acteurs :** Docker/cron · `generate_48h_report.py` · `get-keyword-from-rss.py` · API EurIA (Qwen3)

**Prérequis :** `data/articles-from-rss/_WUDD.AI_/48-heures.json` doit être à jour (généré par `get-keyword-from-rss.py` après chaque collecte RSS).

```mermaid
flowchart TD
    CRON([Cron 23h00 — chaque jour]) --> SCRIPT[generate_48h_report.py]
    SCRIPT --> READ[Lit 48-heures.json
data/articles-from-rss/_WUDD.AI_/]
    READ --> COUNT[Pré-calcule Top 10 entités
PERSON · ORG · GPE · PRODUCT · EVENT]
    COUNT --> SELECT[Sélectionne 5 articles
les plus récents par entité]
    SELECT --> PROMPT[Construit le prompt enrichi
Top 10 précalculé + 50 articles allégés]
    PROMPT --> EURIA[POST EurIA — timeout 300s
3 tentatives avec backoff]

    subgraph RAPPORT["Structure du rapport généré"]
        S0[Frontmatter YAML
titre · date · nb articles]
        S1[Section par entité × 10
Contexte · Actualité 48h · Analyse]
        S2[Image Markdown par section
une image par entité, sans doublon]
        S3[Corrélations inter-entités
3-5 liens significatifs]
        S4[Constatations générales
dynamiques · ruptures · signaux faibles]
        S5[Tableau de références
date · source · URL]
        S0 --> S1 --> S2 --> S3 --> S4 --> S5
    end

    EURIA --> RAPPORT
    RAPPORT --> CLEAN[Nettoyage post-LLM
suppression backticks parasites]
    CLEAN --> SAVE[rapports/markdown/_WUDD.AI_/
rapport_48h.md — remplacé chaque jour]
    SAVE --> VIEWER[Consultable dans le Viewer
Rendu Markdown avec images]

    classDef auto fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    classDef storage fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px
    classDef report fill:#fff3e0,stroke:#f57c00,stroke-width:1px
    classDef viewer fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    class CRON,SCRIPT,READ,COUNT,SELECT,PROMPT,EURIA,CLEAN auto
    class SAVE storage
    class S0,S1,S2,S3,S4,S5 report
    class VIEWER viewer
```

**Exemple de Top 10 généré (04/03/2026) :**

| Rang | Entité | Type | Articles |
|------|--------|------|----------|
| 1 | Apple | ORG | 202 |
| 2 | États-Unis | GPE | 83 |
| 3 | MacBook Neo | PRODUCT | 82 |
| 4 | Iran | GPE | 76 |
| 5 | iPhone 17e | PRODUCT | 54 |
| 6 | OpenAI | ORG | 47 |
| 7 | Suisse | GPE | 46 |
| 8 | MacBook Air M5 | PRODUCT | 46 |
| 9 | Studio Display XDR | PRODUCT | 45 |
| 10 | MacBook Air | PRODUCT | 40 |

**Test sans API :**
```bash
python3 scripts/generate_48h_report.py --dry-run
```

**Valeur produite :** Chaque matin, un rapport de veille analytique est disponible sans aucune intervention — 10 analyses d'entités avec contexte et sources, les corrélations entre acteurs, et une lecture des signaux faibles de la veille. Un seul fichier, toujours à jour : `rapports/markdown/_WUDD.AI_/rapport_48h.md`.

---

## 10. Sélection des articles les plus pertinents

**Contexte :** Après une collecte, des dizaines d'articles sont disponibles. L'utilisateur veut rapidement identifier les plus importants à lire, sans tout parcourir manuellement.

**Acteurs :** Analyste / Veilleur (viewer) · `utils/scoring.py` · route `/api/articles/top` · `TopArticlesPanel.jsx`

**Pré-condition :** Des fichiers JSON d'articles enrichis existent dans `data/articles/` ou `data/articles-from-rss/`.

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant V as Viewer (TopArticlesPanel)
    participant A as Flask /api/articles/top
    participant S as ScoringEngine

    U->>V: Ouvre "Top Articles" (sidebar)
    V->>A: GET /api/articles/top?flux=...&top=20
    A->>S: get_top_articles(flux, top_n=20)
    S->>S: Score chaque article (fréquence entités, fraîcheur, images)
    S->>S: Déduplique par URL (seen_urls: set)
    S-->>A: top_articles[] triés par score
    A-->>V: JSON [{titre, résumé, score, date, url}]
    V-->>U: Liste affichée avec score de pertinence
    U->>V: Clique sur article → ouvre URL source
```

**Algorithme de scoring :**
- **Fréquence des entités NER** : bonus proportionnel au nombre d'entités reconnues
- **Fraîcheur** : articles < 7 jours favorisés
- **Images** : bonus si au moins une image largeur > 500 px
- **Déduplication** : une URL ne peut apparaître qu'une seule fois dans le résultat

**Valeur produite :** En moins d'une seconde, l'utilisateur obtient un classement objectif des articles à lire en priorité, sans biais de présentation. Gain de temps estimé : 70 % sur la revue de presse manuelle.

---

## 11. Détection de tendances et alertes émergentes

**Contexte :** L'utilisateur souhaite être alerté lorsqu'un sujet monte en fréquence, sans surveiller chaque flux individuellement.

**Acteurs :** Système (cron 07h00) · `scripts/trend_detector.py` · route `/api/alerts` · `AlertsPanel.jsx` · `data/alertes.json`

**Pré-condition :** Des articles enrichis NER existent sur au moins deux périodes consécutives.

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant C as Cron (07h00)
    participant T as trend_detector.py
    participant D as data/alertes.json
    participant V as Viewer (AlertsPanel)
    participant A as Flask /api/alerts

    C->>T: Exécute (quotidien)
    T->>T: Compte occurrences entités (J-7 vs J-14)
    T->>T: Calcule ratio hausse (seuil configurable)
    T-->>D: Sauvegarde alertes JSON
    U->>V: Ouvre "Tendances" (sidebar)
    V->>A: GET /api/alerts
    A->>D: Lit alertes.json
    A-->>V: [{entity, type, count_recent, count_old, ratio}]
    V-->>U: Panel avec liste d'alertes + seuil ajustable
    U->>V: Ajuste seuil (ex. 2.0×)
    V->>A: POST /api/alerts/run {threshold: 2.0}
    A->>T: Relance détection (à la demande)
    T-->>D: Met à jour alertes.json
    A-->>V: Nouvelles alertes
    U->>V: Clique entité → recherche transversale
```

**Paramètres configurables (via UI) :**
- **Seuil de détection** : ratio minimum (défaut 2.0×) entre période récente et ancienne
- **Top N** : nombre maximum d'alertes affichées (défaut 20)

**Valeur produite :** Détection automatique des sujets émergents sans lecture exhaustive. Chaque matin, les tendances du jour sont pré-calculées. L'utilisateur peut affiner et naviguer directement vers les articles concernés.

---

## 12. Analyse des biais éditoriaux par source

**Contexte :** L'utilisateur veut comprendre si certaines sources présentent systématiquement un ton positif, négatif ou neutre sur les sujets couverts.

**Acteurs :** Analyste (viewer) · `scripts/enrich_sentiment.py` (Round-Robin) · route `/api/sources/bias` · `SourceBiasPanel.jsx`

**Pré-condition :** Les articles ont été enrichis avec le champ `"sentiment"` (via `enrich_sentiment.py`).

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant Cron as Cron 03h00
    participant ES as enrich_sentiment.py
    participant D as data/articles/**
    participant S as data/enrich_sentiment_state.json
    participant V as Viewer (SourceBiasPanel)
    participant A as Flask /api/sources/bias

    Cron->>ES: Exécute (Round-Robin quotidien)
    ES->>S: Lit dernier index traité
    ES->>D: Sélectionne fichier suivant (1 fichier/jour)
    ES->>ES: Appelle EurIA API (Prompt 4 sentiment)
    ES-->>D: Enrichit articles avec {sentiment, score, label}
    ES-->>S: Met à jour état (last_file_idx++)

    U->>V: Ouvre "Biais sources" (sidebar)
    V->>A: GET /api/sources/bias
    A->>D: Agrège sentiments par source
    A-->>V: [{source, pos%, neg%, neu%, count}]
    V-->>U: Tableau comparatif + jauges colorées
```

**Format du champ `sentiment` par article :**
```json
{
  "sentiment": {
    "label": "positif",
    "score": 0.72,
    "dominant_emotion": "confiance"
  }
}
```

**Mode Round-Robin :** 1 fichier JSON traité par jour, cycle complet toutes les N jours (N = nombre de fichiers). État persisté dans `data/enrich_sentiment_state.json`.

```bash
python3 scripts/enrich_sentiment.py --status   # Voir l'état du cycle
python3 scripts/enrich_sentiment.py            # Traiter le prochain fichier
python3 scripts/enrich_sentiment.py --all      # Traiter tous les fichiers
```

**Valeur produite :** Visualisation objective des tendances éditoriales par source. Permet d'identifier rapidement les sources militantes, les biais positifs/négatifs persistants, ou l'évolution du ton d'un média sur un sujet donné.

---

## 13. Synthèse comparative RAG multi-sources

**Contexte :** Sur un sujet complexe (ex. "IA et emploi"), l'utilisateur veut une analyse synthétique qui croise les points de vue de toutes les sources collectées, sans avoir à lire chaque article.

**Acteurs :** Analyste (viewer) · route `/api/synthesize-topic` · onglet RAG dans `EntityArticlePanel.jsx` · `utils/api_client.py`

**Pré-condition :** Des articles existent dans `data/` pour le flux ou le mot-clé sélectionné. L'entité ou le sujet est identifié.

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant V as "Viewer (EntityArticlePanel - onglet RAG)"
    participant A as "Flask /api/synthesize-topic"
    participant C as "api_client.generate_report()"
    participant AI as "EurIA API (Qwen3)"

    U->>V: Clique entité, ouvre EntityArticlePanel
    U->>V: Sélectionne onglet Synthèse RAG
    V->>A: POST /api/synthesize-topic [entity, flux]
    A->>A: Collecte articles - match NER ou texte
    A->>A: Déduplique par URL
    A->>A: Construit sources_block - résumés, sources, dates
    A->>C: generate_report - prompt, stream=True
    C->>AI: POST stream=True [Prompt 6 RAG]
    AI-->>C: Chunks SSE - text/event-stream
    C-->>A: Forwarde chunks normalisés data SSE
    A-->>V: SSE stream vers React
    V-->>U: Texte de synthèse affiché en temps réel
    U->>V: Lit synthèse, peut exporter
```

**Caractéristiques techniques :**
- **RAG pur** : `enable_web_search: False` — l'IA ne consulte que les articles collectés
- **Déduplication** : une URL ne peut contribuer qu'une fois à la synthèse
- **Streaming SSE** : le texte s'affiche mot par mot (expérience de lecture fluide)
- **Cache** : la synthèse est mise en cache (TTL 24h) pour éviter les appels répétés

**Valeur produite :** Analyse de fond croisant N sources en 30–60 secondes, sans biais de sélection manuelle. La réponse est ancrée sur les données réelles collectées — pas de d'hallucination sur des sources externes.

---

## 14. Export et diffusion des résultats

**Contexte :** L'utilisateur ou un système tiers veut consommer les articles et résumés dans un format standard (agrégateur RSS, newsletter, webhook Slack/Zapier).

**Acteurs :** Analyste (viewer) · routes `/api/export/atom`, `/api/export/newsletter`, `/api/export/webhook-test`

**Pré-condition :** Des articles JSON enrichis existent dans `data/articles/` ou `data/articles-from-rss/`.

```mermaid
flowchart TD
    U([Utilisateur / Système tiers]) --> V[Viewer - panneau Export]

    V -->|Flux RSS| A1[GET /api/export/atom?flux=...&limit=20]
    A1 --> F1[Atom XML\ncompatible RSS agrégateurs]
    F1 -->|Abonné via URL| AGG[Feedly / Inoreader / NetNewsWire]

    V -->|Newsletter| A2[GET /api/export/newsletter?flux=...&limit=20]
    A2 --> F2[HTML email\nwith inline images]
    F2 -->|Copie-colle ou export| ML[Client mail / SendGrid]

    V -->|Test webhook| A3[POST /api/export/webhook-test]
    A3 -->|POST JSON articles| WH[Endpoint externe\nSlack / Zapier / n8n]
    WH --> NOTIF[Notification temps réel]
```

**Formats de sortie :**

| Export | Format | Usage typique | Paramètres |
|--------|--------|---------------|------------|
| Atom | XML (RFC 4287) | Agrégateurs RSS | `flux`, `limit` |
| Newsletter | HTML5 responsive | Email / Mailchimp | `flux`, `limit` |
| Webhook | JSON POST | Slack, Zapier, n8n | `url` cible, payload |

**Exemple d'URL d'abonnement Atom :**
```
http://localhost:5050/api/export/atom?flux=Intelligence-artificielle&limit=20
```

**Valeur produite :** Intégration de la veille WUDD.ai dans les outils existants de l'utilisateur (agrégateur personnel, newsletter d'équipe, alertes Slack automatiques) sans copier-coller manuel. La veille devient un service consommable par d'autres systèmes.

---

## 15. Interrogation par terminal IA (local AI agent)

**Contexte :** L'utilisateur veut interroger son corpus de veille en langage naturel — sans naviguer dans le Viewer, sans écrire de requêtes manuelles — depuis son éditeur de code ou un outil IA. Le **terminal IA** (aussi appelé *local AI agent* ou *conversational data agent*) dispose d'outils (*tool use* / *function calling*) qui lui permettent de lire, analyser et modifier les fichiers JSON locaux de WUDD.ai directement, en réponse à des questions libres.

**Acteurs :** Utilisateur · Terminal IA (GitHub Copilot, Claude Desktop + MCP Filesystem, Cursor…) · Fichiers JSON / Markdown locaux (`data/`, `rapports/`, `config/`)

**Caractéristique clé :** Le terminal IA n'interprète pas seulement la question — il **agit** sur les données. Les fichiers JSON structurés, enrichis de résumés IA, d'entités NER et de scores de sentiment, constituent une base de connaissances locale idéale pour un agent conversationnel.

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant AI as Terminal IA
    participant FS as Fichiers locaux WUDD.ai

    U->>AI: « Quelles sont les 5 entités les plus mentionnées
            cette semaine dans le flux Intelligence-artificielle ? »
    AI->>FS: Lit data/articles/Intelligence-artificielle/*.json
    FS-->>AI: Articles + champ entities (PERSON, ORG...)
    AI->>AI: Agrège les entités, compte les occurrences
    AI-->>U: « 1. OpenAI (12), 2. Sam Altman (9), 3. Mistral (7)... »

    U->>AI: « Génère un résumé exécutif des articles de février
            sur la géopolitique, en mettant en avant les GPE. »
    AI->>FS: Lit articles_generated_2026-02-01_2026-02-28.json
    FS-->>AI: 47 articles + entities.GPE par article
    AI->>AI: Filtre, analyse, rédige
    AI-->>U: Markdown structuré (intro + sections + tableau)

    U->>AI: « Ajoute le mot-clé NVIDIA avec les synonymes
            Jensen Huang et GPU dans la configuration. »
    AI->>FS: Lit config/keyword-to-search.json
    AI->>FS: Écrit config/keyword-to-search.json (mise à jour)
    AI-->>U: « Fait. Entrée ajoutée : {keyword: NVIDIA, or: [...]} »
```

**Outils compatibles :**

| Outil | Mode d'accès | Compatibilité WUDD.ai |
|---|---|---|
| **GitHub Copilot** (VS Code — mode Agent) | Tool-calling, lecture/écriture workspace | ✅ JSON + Markdown + config |
| **Claude Desktop** (MCP Filesystem) | RAG + tool use sur répertoires configurés | ✅ Lecture directe `data/` et `rapports/` |
| **Cursor AI** | Tool-calling agent dans l'éditeur | ✅ JSON + config |
| **Windsurf / Codeium** | Tool-calling agent | ✅ JSON + config |

> **Prérequis :** Aucun. Les fichiers JSON WUDD.ai sont directement lisibles par tout agent disposant d'un accès fichier. Aucune API supplémentaire, aucun serveur à configurer.

**Exemples de requêtes en langage naturel :**

| Question | Fichiers accédés | Opération |
|---|---|---|
| « Top 5 entités ce mois » | `data/articles/*/` — champ `entities` | Agrégation |
| « Articles sur Trump et l'Otan » | `data/articles-from-rss/Trump.json` | Filtrage NER |
| « Sujets en hausse aujourd'hui » | `data/alertes.json` | Lecture |
| « Résumé exécutif IA février » | `articles_generated_*.json` | Synthèse libre |
| « Ajoute le mot-clé Mistral » | `config/keyword-to-search.json` | Écriture |
| « Quelles ORG sont liées à Sam Altman ? » | Tous les JSON — cross-fichiers | Co-occurrence |

**Complémentarité avec le Viewer :** Le Viewer assure la navigation visuelle et l'édition assistée dans un navigateur ; le terminal IA y ajoute l'interaction libre en langage naturel, l'analyse ad hoc et l'automatisation à la demande — sans infrastructure supplémentaire.

---

## 16. Export vers Obsidian

**Contexte :** L'utilisateur souhaite conserver dans son vault Obsidian les articles et rapports d'entités qu'il juge importants, enrichis de leur frontmatter YAML complet (entités, sentiment, géolocalisation, score de source), pour les annoter, les croiser avec d'autres notes et les interroger via Dataview ou Map View — sans copier-coller manuel.

**Acteurs :** Utilisateur · Viewer · Flask (`/api/export/obsidian`) · Vault Obsidian (dossier `OBSIDIAN_DIR`)

**Prérequis :** `OBSIDIAN_DIR` défini dans `.env` ; le répertoire doit être accessible en écriture depuis le serveur (ou le conteneur Docker).

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant V as Viewer (ArticleListViewer / EntityArticlePanel)
    participant F as Flask /api/export/obsidian
    participant D as Déduplication MD5
    participant FS as Vault Obsidian (OBSIDIAN_DIR)

    U->>V: Ouvre un article ou un rapport d'entité
    U->>V: Clique "Export Obsidian" (icône livre violet)
    V->>F: POST /api/export/obsidian { article | entity_report, target }

    F->>F: Génère le frontmatter YAML\ntitle · date · source · url · location\nsentiment · score_source · tags\npersonnes · organisations · lieux

    F->>D: Calcule MD5 du résumé
    D-->>F: hash

    alt Note déjà exportée (même MD5)
        F-->>V: { ok: true, deduplicated: true }
        V-->>U: Tooltip "Déjà dans le vault"
    else Nouvelle note
        F->>FS: Écrit YYYY-MM-DD_source_slug-titre.md\ndans articles/ ou rapports/
        FS-->>F: Fichier créé
        F-->>V: { ok: true, path: "..." }
        V-->>U: Notification "Exporté vers Obsidian"
    end

    Note over FS,U: Obsidian détecte le nouveau fichier en temps réel
    U->>FS: Ouvre la note dans Obsidian
    U->>FS: Interroge via Dataview (ex. articles positifs score ≥ 70)
    U->>FS: Visualise les GPE sur la carte Map View
```

**Exemple de note exportée (frontmatter) :**
```yaml
---
title: "OpenAI annonce GPT-5"
date: 2026-03-16
source: "Le Monde"
url: "https://www.lemonde.fr/..."
location: [48.8566, 2.3522]
sentiment: "positif"
score_sentiment: 4
ton_editorial: "factuel"
score_source: 92
temps_lecture: "3 min 10 s"
tags: ["Le-Monde", "OpenAI", "Sam-Altman", "France"]
organisations: ["OpenAI", "Microsoft"]
personnes: ["Sam Altman"]
lieux: ["France", "Paris"]
type: Rapport-WUDD-ai
statut: generated
---
```

**Requêtes Dataview typiques après export :**
```sql
-- Articles positifs à haute crédibilité
TABLE date, source, sentiment, score_source FROM "WUDD-ai"
WHERE sentiment = "positif" AND score_source >= 70
SORT score_source DESC

-- Toutes les mentions d'OpenAI
TABLE date, source FROM "WUDD-ai"
WHERE contains(organisations, "OpenAI") SORT date DESC
```

**Valeur produite :** Les articles et synthèses de veille deviennent des notes Obsidian structurées, interrogeables via Dataview, cartographiables via Map View, et connectables au reste des notes personnelles de l'utilisateur — sans aucune friction de copier-coller.

---

## 17. Vérification de la fiabilité des sources

**Contexte :** L'utilisateur veut savoir dans quelle mesure les sources qui alimentent sa veille sont fiables, transparentes et factuelles — avant d'accorder du crédit à un article ou de le partager. WUDD.ai calcule un **score composite de crédibilité** (0–100) pour chaque source, combinant une évaluation manuelle experte, l'âge du domaine (WHOIS), la transparence éditoriale du site, et le niveau factuel MBFC. Ce score influence directement le classement des articles dans les tops et les synthèses.

**Acteurs :** Utilisateur · Viewer (`SourceBiasPanel`) · Flask (`/api/sources/bias`) · `scripts/enrich_source_credibility.py` · WHOIS · HTTP direct · MBFC (scraping)

**Prérequis :** Articles enrichis avec `score_source` (ajouté automatiquement lors de la collecte). L'enrichissement composite est déclenché via `enrich_source_credibility.py`.

```mermaid
flowchart TD
    CRON([Cron planifié\nenrich_source_credibility.py]) --> READ[Lit sources_credibility.json\nliste des sources connues]
    READ --> LOOP{Pour chaque source\nnon enrichie ou obsolète}

    LOOP --> WHOIS[WHOIS python-whois\ndate de création du domaine]
    LOOP --> HTTP[HTTP HEAD/GET\ncheck mentions légales\nà propos · CGU · contact]
    LOOP --> MBFC[Scraping MBFC\nrating factuel]

    WHOIS --> AGE[score_age_domaine\n0–100]
    HTTP --> TRANSP[score_transparence\n0–100]
    MBFC --> MBFC_S[score_mbfc\n0–100]

    AGE & TRANSP & MBFC_S --> COMPOSITE["score_composite\n= statique×0.60\n+ âge×0.15\n+ transparence×0.10\n+ mbfc×0.15"]
    COMPOSITE --> SAVE[Mise à jour sources_credibility.json\nenrich_date · domain_age_years\ntransparence · mbfc_rating]

    SAVE --> SCORING[utils/scoring.py\nmultiplicateur 0.60–1.20\nappliqué à score_pertinence]
    SCORING --> TOP[Top articles et synthèses\nfavorisent les sources fiables]

    subgraph UI["Utilisateur — SourceBiasPanel"]
        B1[Ouvre Biais éditoriaux\nvia sidebar]
        B2[Tableau par source :\nscore · âge · transparence · MBFC\nsentiment · ton dominant]
        B3[Tri : fiabilité ↓\nou ton le + biaisé]
        B4[Identifie sources douteuses\nou ton alarmiste systématique]
        B1 --> B2 --> B3 --> B4
    end

    SAVE --> B1

    classDef auto fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    classDef ext fill:#fff3e0,stroke:#f57c00,stroke-width:1px
    classDef storage fill:#f3e5f5,stroke:#7b1fa2,stroke-width:1px
    classDef ui fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    class CRON,READ,LOOP,COMPOSITE,SCORING,TOP auto
    class WHOIS,HTTP,MBFC ext
    class AGE,TRANSP,MBFC_S,SAVE storage
    class UI,B1,B2,B3,B4 ui
```

**Score composite — exemples :**

| Source | Score statique | Âge domaine | Transparence | MBFC | **Score composite** | Multiplicateur |
|--------|---------------|-------------|--------------|------|---------------------|----------------|
| Reuters | 97 | 100 (28 ans) | 100 | 100 (VERY HIGH) | **98** | ×1.19 |
| Le Monde | 92 | 100 (30 ans) | 100 | 85 (HIGH) | **94** | ×1.16 |
| BFM TV | 68 | 85 (15 ans) | 75 | 65 (MOSTLY FACTUAL) | **73** | ×1.04 |
| Source inconnue | 50 | — | — | — | **50** | ×0.90 |
| Site < 1 an | 40 | 0 | 25 | null (50) | **35** | ×0.81 |

**Interprétation combinée (biais + ton) :**
- Source avec `score_ton` moyen < 2.5 et taux négatif > 60 % → profil **alarmiste systématique**
- Source avec `score_ton` > 4 et sentiment majoritairement neutre → profil **agence de presse**
- Écart entre `biais` déclaré et ton mesuré → mérite une investigation manuelle

**Lancer l'enrichissement composite :**
```bash
python3 scripts/enrich_source_credibility.py          # enrichit les sources non à jour
python3 scripts/enrich_source_credibility.py --all    # force toutes les sources
python3 scripts/enrich_source_credibility.py --status # état du cycle
```

**Valeur produite :** L'utilisateur dispose d'une vue objective et multi-critères de la fiabilité de chaque source — pas seulement un score manuel, mais des signaux vérifiables (ancienneté du domaine, transparence du site, référencement MBFC). Les articles issus de sources peu fiables sont automatiquement pénalisés dans les classements, sans aucune intervention manuelle.

---

```mermaid
quadrantChart
    title Use cases - Frequence vs Profondeur d analyse
    x-axis Ponctuel --> Quotidien/hebdomadaire
    y-axis Exploration libre --> Resultat structure
    quadrant-1 Production automatisee
    quadrant-2 Veille operationnelle
    quadrant-3 Analyse ad hoc
    quadrant-4 Exploration ouverte
    UC1 Veille mots-cles: [0.80, 0.52]
    UC2 Rapport multi-flux: [0.78, 0.90]
    UC3 Recherche entite: [0.10, 0.76]
    UC4 Carte geopolitique: [0.12, 0.40]
    UC5 Reseau semantique: [0.08, 0.12]
    UC6 Rapport Claude ad hoc: [0.38, 0.68]
    UC7 Lecture mobile: [0.70, 0.25]
    UC8 Briefing entites mobile: [0.55, 0.45]
    UC9 Rapport Top10 entites 48h: [0.96, 0.95]
    UC10 Top articles: [0.62, 0.65]
    UC11 Tendances alertes: [0.90, 0.75]
    UC12 Biais editoriaux: [0.18, 0.58]
    UC13 Synthese RAG: [0.22, 0.93]
    UC14 Export diffusion: [0.50, 0.86]
    UC15 Terminal IA agent: [0.30, 0.35]
    UC16 Export Obsidian: [0.20, 0.72]
    UC17 Fiabilite sources: [0.15, 0.60]
```

| # | Use Case | Déclencheur | Durée typique | Sortie |
|---|----------|-------------|-----------------|--------|
| 1 | Veille mots-clés | Manuel ou cron 01h00 | 5–15 min (script) | JSON enrichi NER |
| 2 | Rapport multi-flux | Cron lundi 06h00 | 30–90 min (pipeline) | Rapport Markdown |
| 3 | Recherche entité | Ad hoc (viewer) | 2–5 min | Rapport MD / export JSON |
| 4 | Carte géopolitique | Ad hoc (viewer) | 1–3 min | Lecture + export |
| 5 | Réseau sémantique | Ad hoc (viewer) | 5–20 min | Découverte / navigation |
| 6 | Rapport Claude ad hoc | Ad hoc (Claude) | 2–5 min | Rapport Markdown / PDF |
| 7 | Lecture mobile en déplacement | Quotidien (smartphone) | 5–10 min | Lecture · recherche plein texte |
| 8 | Briefing entités avant réunion | Ad hoc (smartphone) | 2–3 min | Orientation · sélection articles |
| 9 | Rapport Top 10 entités 48h | Cron 23h00 quotidien | ~5 min (script) | Rapport Markdown structuré |
| 10 | Top articles pertinents | Ad hoc (viewer) | < 1 min | Liste scorée des meilleurs articles |
| 11 | Tendances & alertes | Cron 07h00 / manuel | ~2 min (script) | Alertes JSON + panel interactif |
| 12 | Biais éditoriaux par source | Ad hoc (viewer) | 1–2 min | Tableau comparatif sources |
| 13 | Synthèse RAG multi-sources | Ad hoc (viewer) | 30–60s (streaming) | Analyse comparative Markdown |
| 14 | Export & diffusion | Ad hoc (viewer / cron) | < 1 min | Atom XML · Newsletter HTML · Webhook |
| 15 | Terminal IA (local AI agent) | Ad hoc (éditeur / outil IA) | Immédiat | Réponse en langage naturel · lecture / écriture fichiers |
| 16 | Export vers Obsidian | Ad hoc (viewer) | < 5 s / article | Note Markdown Obsidian avec frontmatter YAML complet |
| 17 | Vérification fiabilité des sources | Cron planifié / manuel | ~1 min (script) | Score composite · tableau comparatif sources · multiplicateur scoring |

---

**Maintenu par** : Patrick Ostertag · patrick.ostertag@gmail.com
**Créé le** : 2 mars 2026 · **Mis à jour le** : 17 mars 2026 (UC16 — export Obsidian · UC17 — fiabilité des sources)
