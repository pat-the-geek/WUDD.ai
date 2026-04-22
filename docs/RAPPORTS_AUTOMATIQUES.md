# Rapports automatiques — WUDD.ai

> Dernière mise à jour : 6 mars 2026

Ce document décrit les 5 scripts de génération de rapports exécutés automatiquement par le cron Docker.

---

## 1. `scheduler_articles.py` — Lundi 06:00

**Rôle :** Orchestrateur mensuel intelligent. Décide quand lancer la collecte pour chaque flux configuré.

**Sources :**
- `config/flux_json_sources.json` — liste des flux
- `data/articles/<flux>/articles_generated_*.json` — articles existants
- EurIA API — recommandation de fréquence (indicatif)

**Fonctionnement :**
1. Pour chaque flux, vérifie si le fichier mensuel existe dans `data/articles/<flux>/`
2. Si absent → lance `Get_data_from_JSONFile_AskSummary_v2.py` pour générer les résumés du mois
3. Si présent → compte les articles de la semaine ; si ≥ 10 → déclenche une édition intermédiaire supplémentaire
4. Interroge EurIA pour une recommandation de fréquence (loggée, non encore utilisée automatiquement)

**Sorties :** `data/articles/<flux>/articles_generated_YYYY-MM-DD_YYYY-MM-DD.json`

---

## 2. `get-keyword-from-rss.py` — Toutes les 2h de 06:00 à 22:00 (9×/jour)

**Rôle :** Crawler RSS par mots-clés. Script central de la veille quotidienne.

**Sources :**
- `data/WUDD.opml` — liste des flux RSS
- `config/keyword-to-search.json` — mots-clés avec logique `OR`/`AND`
- Flux RSS/Atom en direct (HTTP, fenêtre 7 jours glissants)
- `data/articles-from-rss/*.json` — pour déduplification par URL
- `config/quota.json` — plafonds journaliers

**Fonctionnement :**
1. Pour chaque flux RSS, filtre les articles dont le titre correspond à un mot-clé (regex `\b`, logique `OR`/`AND`)
2. Vérifie les quotas (global / par mot-clé / par source×mot-clé) et déduplique par URL
3. Si OK : récupère le texte complet, génère résumé EurIA + entités NER + meilleure image (largeur > 500px)
4. Sauvegarde dans `data/articles-from-rss/<mot-clé>.json` (merge, pas d'écrasement)
5. Reconstruit entièrement `48-heures.json` en agrégeant tous les fichiers et en filtrant les < 48h

**Sorties :**
- `data/articles-from-rss/<mot-clé>.json` — un fichier par mot-clé, mis à jour en continu
- `data/articles-from-rss/_WUDD.AI_/48-heures.json` — reconstruit à chaque run
- `data/rss_progress.json` — suivi de progression (écritures atomiques)

---

## 3. `generate_48h_report.py` — Quotidien à 23:00

**Rôle :** Génère un rapport de veille analytique sur les 48 dernières heures.

**Sources :**
- `data/articles-from-rss/_WUDD.AI_/48-heures.json` — produit par le script précédent, doit contenir le champ `entities` (NER)

**Fonctionnement :**
1. Calcule le Top 10 des entités nommées les plus citées (personnes, organisations, pays, produits...)
2. Sélectionne jusqu'à 5 articles par entité, tronque les résumés à 400 caractères
3. Envoie un prompt structuré à EurIA (300s timeout) : analyse par entité, corrélations, conclusions, tableau de référence
4. Nettoie la réponse LLM (supprime les balises ```` ```markdown ```` parasites)

**Sorties :** `rapports/markdown/_WUDD.AI_/rapport_48h.md` — **écrasé à chaque run**

---

## 4. `radar_wudd.py` — Dernier jour du mois à 05:00

**Rôle :** Génère un radar thématique mensuel interactif comparant deux périodes.

**Sources :**
- Tous les `*.json` sous `data/` (récursif) — corpus complet
- EurIA API (Qwen/Qwen3.5-122B-A10B-FP8, web search désactivé, 120s timeout)

**Fonctionnement :**
1. Divise le corpus en deux périodes : **T0** (mois courant) et **T1** (fenêtre de 2 semaines la plus ancienne)
2. Envoie les résumés normalisés (ASCII, tronqués à 160 chars) à EurIA pour scorer 57 thèmes prédéfinis (`fréquence` + `vélocité`)
3. Recalcule la vélocité client-side (le LLM retourne souvent 0.5 uniforme) et normalise entre [0.1, 0.9]
4. Classifie chaque thème en 4 quadrants : **Dominant / Émergent / Habituel / Déclinant**
5. Génère un fichier HTML autonome (scatterplot interactif, aucune dépendance externe) + un rapport Markdown avec diagramme Mermaid

**Sorties :**
- `rapports/radar_wudd.html` — écrasé à chaque run
- `rapports/markdown/radar/radar_articles_generated_<date-début>_<date-fin>.md` — archivé par date

---

## 5. `articles_rss_to_markdown.py` — Dernier jour du mois à 05:30

**Rôle :** Convertit les articles du mois courant de chaque fichier JSON par mot-clé en rapport Markdown mensuel.

**Sources :**
- `data/articles-from-rss/*.json` — un fichier par mot-clé (ou un seul via `--keyword`)

**Fonctionnement :**
1. Calcule la plage du mois courant (1er jour → dernier jour)
2. Parcourt tous les fichiers JSON de `data/articles-from-rss/` (par ordre alphabétique)
3. Pour chaque fichier, filtre les articles dont `"Date de publication"` (format RFC 822) tombe dans le mois courant
4. Si aucun article ne correspond, logue un avertissement et passe au suivant (aucun fichier créé)
5. Écrit les articles filtrés dans un fichier temporaire, puis délègue la conversion à `json_to_markdown()` depuis `articles_json_to_markdown.py`
6. Les erreurs sur un fichier sont loggées et ignorées (les autres continuent)

**Sorties :** `rapports/markdown/keyword/<mot-clé>/<mot-clé>_<YYYY-MM-01>_<YYYY-MM-31>.md` — un fichier par mois et par mot-clé (archive historique, les anciens fichiers sont conservés)

---

## Récapitulatif

| # | Script | Déclenchement | Sources principales | Sorties |
|---|---|---|---|---|
| 1 | `scheduler_articles.py` | Lundi 06:00 | `config/flux_json_sources.json` · `data/articles/` | `data/articles/<flux>/articles_generated_*.json` |
| 2 | `get-keyword-from-rss.py` | Toutes les 2h (06:00–22:00) | `data/WUDD.opml` · `config/keyword-to-search.json` · Internet | `data/articles-from-rss/*.json` · `48-heures.json` |
| 3 | `generate_48h_report.py` | Quotidien 23:00 | `data/articles-from-rss/_WUDD.AI_/48-heures.json` | `rapports/markdown/_WUDD.AI_/rapport_48h.md` |
| 4 | `radar_wudd.py` | Dernier jour du mois 05:00 | `data/**/*.json` (tout le corpus) | `rapports/radar_wudd.html` · `rapports/markdown/radar/*.md` |
| 5 | `articles_rss_to_markdown.py` | Dernier jour du mois 05:30 | `data/articles-from-rss/*.json` (filtré sur le mois courant) | `rapports/markdown/keyword/<mot-clé>/<mot-clé>_YYYY-MM-01_YYYY-MM-31.md` |
