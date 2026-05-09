# WUDD.ai — Spécification Fonctionnelle Client Natif
## Version 1.0 — Mars 2026

---

## 1. Vue d'ensemble

### 1.1 Objectif

L'application WUDD.ai Client est une application native universelle (macOS + iOS) permettant d'accéder à l'interface de veille intelligente d'actualités depuis n'importe quel appareil Apple. Elle communique exclusivement avec le backend Flask (port 5050) via réseau local ou Internet. La seule dépendance de configuration est l'URL/IP du serveur.

### 1.2 Plateformes cibles

| Plateforme | Version minimale | Format |
|---|---|---|
| iOS | 17.0+ | iPhone et iPad (Universal) |
| macOS | 14.0 (Sonoma)+ | Application native (Mac Catalyst ou SwiftUI AppKit) |

### 1.3 Principes UX

- **Langue de l'interface :** Français (identique au backend)
- **Thème :** Clair/Sombre automatique (suit les préférences système)
- **Responsive :** Adaptatif sidebar-detail sur iPad/Mac, tab-based sur iPhone
- **Offline-aware :** Affichage clair de l'état de connexion, gestion gracieuse des erreurs réseau
- **Streaming natif :** Rendu progressif des synthèses IA (SSE)

---

## 2. Architecture de Navigation

### 2.1 iPhone (Compact Width)

```
TabBar (5 onglets)
├── 📰 Articles        → ArticlesTabView
├── 🔍 Recherche       → SearchView
├── 🏷️ Entités         → EntitiesTabView
├── 🚨 Alertes         → AlertsTabView
└── ⚙️ Paramètres      → SettingsTabView
```

### 2.2 iPad & macOS (Regular Width)

```
NavigationSplitView (3 colonnes)
├── Sidebar (colonne 1)
│   ├── Flux d'articles
│   │   ├── [Nom du flux 1]
│   │   ├── [Nom du flux 2]
│   │   └── [Mots-clés RSS]
│   ├── Tableaux de bord
│   │   ├── Entités
│   │   ├── Top Articles
│   │   ├── Alertes
│   │   └── Sources
│   ├── Rapports
│   │   ├── Markdown
│   │   └── JSON brut
│   ├── Outils
│   │   ├── Chatbot IA
│   │   ├── Planificateur
│   │   └── Quotas
│   └── Paramètres
├── Liste/Détail (colonne 2)
└── Détail contextuel (colonne 3, optionnelle)
```

---

## 3. Écrans & Fonctionnalités

### 3.1 Écran de Configuration Serveur

**Déclencheur :** Premier lancement ou URL invalide/non joignable.

**Éléments UI :**
- Logo WUDD.ai + tagline "Votre veille intelligente"
- Champ texte : `Adresse du serveur` (ex: `http://192.168.1.10:5050` ou `https://wudd.mondomaine.com`)
- Bouton `Tester la connexion` → indicateur spinner + résultat OK/Erreur
- Bouton `Enregistrer et continuer`
- Lien `Aide` → description du format attendu

**Comportement :**
- L'URL est persistée dans `UserDefaults` (clé `serverURL`)
- Test de connexion : `GET /api/files` → réponse 200 = succès
- En cas d'erreur : message descriptif (ex: "Serveur inaccessible", "URL invalide")
- Accessible ultérieurement via Paramètres → Serveur

---

### 3.2 Articles — Navigation par Flux

**Vue Liste des Flux (`FluxListView`)**

Affiche la liste des flux disponibles récupérés via `GET /api/flux-sources`.

Éléments par flux :
- Nom du flux
- Badge : nombre d'articles (issu de `GET /api/files`)
- Date de dernière mise à jour
- Indicateur de nouveautés (si articles récents < 24h)

**Vue Articles d'un Flux (`ArticleListView`)**

Source : `GET /api/files` filtré par flux, puis lecture du JSON via `GET /api/content?path=...`

Barre de filtres :
- Tri : Date ↓ / Date ↑ / Score ↓
- Sentiment : Tous / Positif / Neutre / Négatif
- Source : Menu déroulant des sources présentes
- Période : Ce mois / 7 jours / 30 jours / Tout

Carte article (`ArticleCard`) :
- Titre ou extrait du résumé (2 lignes max)
- Source + date de publication
- Badge sentiment (couleur : vert/gris/rouge)
- Badge ton éditorial
- Durée de lecture (icône horloge)
- Vignette image (si disponible, `Images[0].URL`)
- Score de pertinence (si présent)
- Chips entités top 3 (PERSON, ORG, GPE)

**Vue Détail Article (`ArticleDetailView`)**

- Image pleine largeur en en-tête (si disponible)
- Métadonnées : Source, Date, Durée de lecture, Sentiment, Ton
- Résumé complet avec mise en évidence des entités (couleur par type)
- Section Entités : chips groupées par type NER
- Actions :
  - `Rapport complet` → génère via SSE `/api/article/full-report`
  - `Articles similaires` → panel flottant via `/api/articles/merge/search`
  - `Annotations` → éditer notes + tags
  - Partager (share sheet natif)
  - Ouvrir URL originale dans Safari
  - TTS (lecture à voix haute via AVSpeechSynthesizer)

---

### 3.3 Mots-clés RSS

Même structure que les Flux mais pour `data/articles-from-rss/*.json`.

Navigation : Sidebar → section "Mots-clés RSS" → liste alphabétique des keywords.

Chaque keyword affiche son nombre d'articles et un indicateur de fraîcheur.

---

### 3.4 Recherche Globale (`SearchView`)

Correspond à `GET /api/search` avec paramètres.

**Interface :**
- Champ de recherche avec suggestions en temps réel (debounce 300ms)
- Filtres avancés (collapsible) :
  - Type de fichier (articles / rapports)
  - Sentiment
  - Source
  - Période (date_from / date_to avec date pickers natifs)
- Liste de résultats groupés par fichier
- Extrait avec terme surligné
- Tap → ouvre ArticleDetailView ou MarkdownReportView

**Recherche d'entités :**
- Onglet "Entités" dans la vue recherche
- Source : `GET /api/search/entity?q=...&type=...`
- Résultats avec type NER + nb d'articles associés

---

### 3.5 Tableau de Bord Entités (`EntityDashboardView`)

Source : `GET /api/entities/dashboard`

**Sections :**

**Statistiques globales :**
- Total articles analysés
- % avec entités extraites
- Nb entités uniques

**Distribution par type NER :**
- Graphique barres horizontales (SwiftUI Charts)
- Liste déroulante : top 20 entités par type avec compteur

**Tabs :**
- `Liste` : tableau trié par nb de mentions, filtrable par type
- `Carte` : MapKit — pins géographiques pour GPE/LOC (source: `/api/entities/geocode`)
- `Galerie` : grille d'images pour PERSON/ORG/PRODUCT (source: `/api/entities/images`)
- `Chronologie` : timeline par date de mention (source: `/api/entities/timeline`)

**Tap sur une entité → `EntityDetailView`**

---

### 3.6 Détail Entité (`EntityDetailView`)

**En-tête :**
- Image (Wikimedia si disponible)
- Nom + type NER (badge coloré)
- Nb d'articles + nb de sources
- Bouton "Surveiller" (toggle watch list)

**Tabs :**

**Info :**
- Synthèse IA streamée via SSE `/api/synthesize-topic?entity_type=...&entity_value=...`
- Rendu Markdown progressif avec indicateur de chargement
- Bouton "Régénérer"
- Bouton "Rapport complet" → `EntityFullReportView`

**Articles :**
- Liste des articles mentionnant cette entité
- Source : `/api/entities/articles?type=...&value=...`
- Même format que `ArticleCard`
- Paramètres avancés :
  - `match_mode=strict|canonical|contains|aggregate`
  - `all_types=1` pour agréger un sujet sur plusieurs types NER

**Graphe :**
- Visualisation des co-occurrences (entités liées)
- Source : `/api/entities/cooccurrences?type=...&value=...`
- Représentation : liste avec force d'association (pas de WebGL requis)
- Sur iPad/Mac : graphe force-directed (SwiftUI Canvas)
- Sémantique des compteurs :
  - `count` = poids relationnel dans le graphe courant (articles partagés entre deux entités)
  - `total_count` = volume d'articles total du nœud, utilisé comme contexte visuel
  - ce `total_count` n'est pas comparable directement à la timeline quotidienne

**Calendrier :**
- Grille mensuelle des mentions
- Source : `/api/entities/timeline?type=...&value=...`
- Intensité de couleur = nombre de mentions par jour
- Cette timeline mesure une **évolution quotidienne** ; elle ne doit pas être comparée directement au `total_count` du graphe, qui est un compteur de couverture globale par nœud
- Paramètres avancés :
  - `match_mode=strict` pour une variante exacte
  - `match_mode=canonical` pour appliquer les alias connus
  - `match_mode=contains` pour le comportement historique large
  - `match_mode=aggregate&all_types=1` pour obtenir une vue cross-variant / cross-type sur un sujet fragmenté

---

### 3.7 Rapport Complet Entité (`EntityFullReportView`)

- Modal plein écran
- Streaming progressif SSE en 3 phases (Info → RAG → Articles)
- Rendu Markdown avec support Mermaid (WebView embarquée pour les diagrammes)
- Actions : Copier texte, Partager, Exporter .md, Régénérer

---

### 3.8 Rapport Complet Article (`ArticleFullReportView`)

- Modal plein écran
- Streaming SSE depuis `/api/article/full-report`
- Image article en en-tête
- Band d'avatars entités
- Rendu Markdown avec diagrammes Mermaid (WebView)
- Actions : Copier, Partager, Télécharger .md, Imprimer, Régénérer

---

### 3.9 Alertes (`AlertsView`)

Source : `GET /api/alerts`

**Liste d'alertes :**
- Badge niveau : CRITIQUE (rouge), ÉLEVÉ (orange), MODÉRÉ (jaune)
- Entité concernée + type NER
- Raison textuelle
- Nombre d'articles liés
- Date de détection
- Tap → liste des articles liés

**Actions :**
- Filtrer par niveau (segmented control)
- Bouton "Lancer détection" → `POST /api/alerts/run` avec spinner
- Configurer règles → `AlertRulesView`

**`AlertRulesView` :**
- Seuils par type d'entité (PERSON / ORG / GPE / etc.)
- Niveaux modéré / élevé / critique
- Source/destination : `GET /POST /api/alerts/rules`

---

### 3.10 Top Articles (`TopArticlesView`)

Source : `GET /api/articles/top?n=20&hours=48`

- Podium visuel : rang 1, 2, 3 mis en avant
- Liste numérotée pour les suivants
- Carte avec score + composantes (pertinence, crédibilité, fraîcheur)
- Sélecteur de fenêtre temporelle : 24h / 48h / 7j / Tout
- Tap → `ArticleDetailView`

---

### 3.11 Sources (`SourceBiasView`)

Source : `GET /api/sources/bias` + `GET /api/sources/credibility`

- Score de crédibilité par source (0–100) avec jauge couleur
- Indicateurs : Transparence éditoriale, Âge du domaine, Notation MBFC
- Regroupement par score (Fiable ≥ 70 / Modéré 40–69 / À vérifier < 40)
- Graphique en barres (SwiftUI Charts)

---

### 3.12 Visualiseur de Rapports Markdown (`MarkdownReportView`)

Source : `GET /api/content?path=rapports/markdown/...`

- Liste des rapports par flux/période
- Rendu Markdown complet :
  - Titres, paragraphes, tableaux, listes
  - Images HTTP embarquées
  - Blocs de code
  - Blocs Mermaid → rendu via WKWebView avec bibliothèque mermaid.js
  - Blocs `flux-chart` → rendu natif SwiftUI (barres horizontales)
  - Blocs `keyword-graph` → liste SwiftUI des mots-clés
- Actions : Partager, Imprimer, Copier

---

### 3.13 Chatbot IA (`ChatbotView`)

Source : `POST /api/chat/stream` (SSE)

- Interface conversation (bulles message)
- Champ texte + bouton Envoyer
- Streaming de la réponse en temps réel (tokens affichés progressivement)
- Historique de conversation dans la session
- Bouton "Nouvelle conversation"
- Sélection de contexte : fichiers de référence (picker de fichiers data/)
- Bouton "Sauvegarder" → `POST /api/chat/save`

---

### 3.14 Planificateur (`SchedulerView`)

Source : `GET /api/scheduler`

- Liste des tâches cron groupées par catégorie :
  - Surveillance en continu
  - Enrichissement nocturne
  - Rapports matinaux
  - Pipeline mensuel
- Pour chaque tâche : nom, script, cron schedule, prochain passage, dernier passage
- Indicateur de santé (vert si cron Docker actif)
- Console script : `GET /api/scripts/keyword-rss/stream` (SSE logs)

---

### 3.15 Quotas (`QuotaView`)

Source : `GET /api/quota/config` + `GET /api/quota/stats`

- 4 sliders de configuration :
  - Limite globale journalière
  - Limite par mot-clé
  - Limite par source
  - Limite par entité nommée
- Graphiques d'utilisation actuelle vs limite
- Bouton "Réinitialiser compteurs" → `POST /api/quota/reset`
- Sauvegarde → `POST /api/quota/config`

---

### 3.16 Paramètres (`SettingsView`)

Sections :

**Serveur :**
- URL du serveur (modifiable + test de connexion)
- Version du backend (affichée si accessible)
- Statut de connexion (en ligne / hors ligne)

**Flux RSS :**
- Liste des flux (`GET /api/flux-sources`)
- Ajouter / modifier / supprimer un flux
- Validation URL avant sauvegarde

**Mots-clés :**
- Liste des keywords (`GET /api/keywords`)
- Ajouter / modifier / supprimer

**Sources RSS (OPML) :**
- Liste des feeds (`GET /api/rss-feeds`)
- Statistiques par feed
- Ajouter feed (résolution URL → `POST /api/rss-feeds/resolve`)

**Sources Web :**
- Liste (`GET /api/web-sources`)
- Ajouter / modifier

**Fournisseur IA :**
- Sélecteur EurIA / Claude
- Test de connectivité (`POST /api/ai-check`)

**Exports & Notifications :**
- Configuration webhook (Discord / Slack / Ntfy)
- Test webhook (`POST /api/export/webhook-test`)

**Sauvegardes :**
- Chemins BACKUP_L1 / BACKUP_L2 (lecture seule)

**À propos :**
- Version de l'app
- Liens : GitHub, Documentation
- Mentions légales / MIT License

---

### 3.17 Contradictions (`ContradictionsView`)

Source : `GET /api/contradictions`

- Liste des contradictions détectées
- Pour chaque contradiction : entité, affirmation 1 vs affirmation 2, sources, score de confiance
- Lancer une analyse sur un article : `GET /api/contradictions/stream?url=...` (SSE)
- Feedback utilisateur : `POST /api/contradiction/feedback`

---

### 3.18 Clustering Thématique (`ClusterView`)

Source : `GET /api/analytics/clusters?days=7`

- Articles groupés par thème (IA, Géopolitique, Économie, etc.)
- Nb d'articles + sentiment moyen par cluster
- Expansion du cluster → liste des articles
- Sélecteur de fenêtre : 7j / 14j / 30j

---

## 4. Interactions et Patterns Transversaux

### 4.1 Gestion de Connexion

- Indicateur de statut réseau permanent (barre de statut ou badge dans la sidebar)
- En mode hors ligne : affichage des données en cache (NSCache / Core Data simple)
- Timeout API : 30s pour les requêtes standard, illimité pour SSE
- Retry automatique ×3 avec backoff exponentiel pour les erreurs 5xx

### 4.2 Streaming SSE

- Toutes les vues de rapport/synthèse utilisent `URLSession.dataTask` avec lecture chunked
- Affichage progressif : le Markdown est rendu au fur et à mesure
- Indicateur de chargement animé pendant le stream
- Bouton d'arrêt pour interrompre un stream en cours

### 4.3 Mise en Cache

- Réponses de liste (fichiers, alertes) : cache mémoire TTL 5 minutes
- Images articles et entités : cache disque (URLCache système)
- Contenu des rapports lus : cache mémoire session

### 4.4 Partage et Export

- Share Sheet natif iOS/macOS pour tout contenu textuel
- Export .md des rapports et synthèses
- Copier dans le presse-papiers
- Impression via UIPrintInteractionController / NSPrintOperation

### 4.5 TTS (Lecture à voix haute)

- AVSpeechSynthesizer avec langue fr-FR
- Contrôles : play/pause/stop
- Vitesse de lecture ajustable
- Disponible sur tout contenu textuel

### 4.6 Annotations

- Notes et tags locaux sur les articles
- Persistance via l'API backend : `POST /api/annotations`
- Visible dans ArticleDetailView et ArticleCard (badge si annotée)

---

## 5. Gestion des Erreurs

| Erreur | Affichage | Action proposée |
|---|---|---|
| Serveur inaccessible | Banner rouge + message | Aller aux Paramètres |
| Erreur 401/403 | Alert | Vérifier la configuration |
| Erreur 500 | Toast + log | Réessayer |
| Timeout SSE | Toast | Bouton "Réessayer" |
| Fichier JSON invalide | Message inline | Afficher le JSON brut |
| Aucun article disponible | Illustration + texte | Lien vers la documentation |

---

## 6. Accessibilité

- Support complet VoiceOver (labels, hints, traits)
- Support Dynamic Type (toutes les tailles de police système)
- Support du mode réduit de mouvement (pas d'animations si `reduceMotion` activé)
- Contraste conforme WCAG AA
- Navigation clavier complète (macOS + iPad hardware keyboard)
