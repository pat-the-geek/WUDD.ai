# Plan d'exécution optimisations — 30/04/2026

## Objectif

Finaliser les 3 chantiers prioritaires :
1. Validation performance en charge réelle
2. Fiabilisation async selon provider
3. Alignement documentaire et pilotage

Périmètre : viewer Flask/React, scripts d'enrichissement NER/sentiment, documentation technique.

---

## Axe 1 — Validation performance en charge réelle

### Cibles

- Confirmer la tenue de `workers=2`, `threads=4`, `timeout=120` sous charge métier
- Mesurer p50/p95 sur endpoints critiques
- Vérifier l'absence de régression fonctionnelle sous stress

### Endpoints à mesurer

- `GET /api/runtime-info`
- `GET /api/files`
- `GET /api/entities/articles?type=PERSON&value=Jack%20Dorsey&compact=1&max_articles=300`

### Protocole (J1-J2)

1. Lancer le stack Docker en mode viewer+worker
2. Exécuter une campagne courte (3 passes)
3. Exécuter une campagne prolongée (15 min)
4. Consolider p50/p95, taux d'erreur HTTP, saturation CPU/RAM

### Commandes type

```bash
# 1) Démarrage
cd /Users/patrickostertag/Documents/DataForIA/WUDD.ai
docker compose up -d

# 2) Sanity check runtime
curl -s http://localhost:5050/api/runtime-info

# 3) Mesures simples (exemple avec ab)
ab -n 300 -c 20 http://127.0.0.1:5050/api/runtime-info
ab -n 300 -c 20 http://127.0.0.1:5050/api/files

# 4) Vérification logs
docker compose logs --tail=200 analyse-actualites-viewer
docker compose logs --tail=200 analyse-actualites-worker
```

### Critères de sortie

- `p95 /api/files < 400 ms`
- `p95 /api/entities/articles compact < 500 ms`
- `HTTP 5xx = 0` sur la campagne courte
- Pas de crash/restart conteneur

---

## Axe 2 — Fiabilisation async selon provider

### Cibles

- Vérifier la cohérence provider entre sync et async
- Stabiliser les taux de succès sentiment/NER
- Quantifier le gain async réel par backend (EurIA vs Ollama fallback)

### Matrice de test (J3-J5)

1. `AI_PROVIDER_NER=ollama`, `--use-async` (attendu: fallback sync, résultats cohérents)
2. `AI_PROVIDER_NER=euria`, `--use-async` (attendu: gain latence batch, stabilité parsing)
3. Comparaison sync vs async à dataset fixe (5, 20, 50 articles)

### Commandes type

```bash
# Entités — sync
python3 scripts/enrich_entities.py --keyword intelligence-artificielle --dry-run

# Entités — async pilote
python3 scripts/enrich_entities.py --keyword intelligence-artificielle --use-async --async-concurrency 5 --dry-run

# Sentiment — sync
python3 scripts/enrich_sentiment.py --keyword intelligence-artificielle --dry-run

# Sentiment — async pilote
python3 scripts/enrich_sentiment.py --keyword intelligence-artificielle --use-async --async-concurrency 5 --dry-run
```

### Indicateurs

- `ok/total` enrichissements
- `durée totale` et `durée moyenne/article`
- répartition erreurs : `timeout`, `quota`, `auth`, `echec_parse`, `echec_api`

### Critères de sortie

- Cohérence provider confirmée (pas de divergence sync/async)
- `ok/total >= 98%` sur échantillon de validation
- Gain async documenté pour backend HTTP compatible

---

## Axe 3 — Alignement documentaire

### Cibles

- Supprimer les écarts doc/code encore visibles
- Créer un backlog unique et daté avec statuts clairs
- Harmoniser version courante et preuves

### Actions (J6-J7)

1. Mettre à jour les en-têtes version/date
2. Marquer explicitement `fait/en cours/à faire` dans les sections performance
3. Référencer les preuves code (scripts, utils, routes)
4. Ajouter un bloc "prochain contrôle" hebdomadaire

### Documents à aligner en priorité

- `docs/ameliorations/AMELIORATIONS.md`
- `docs/RAPPORT_TECHNIQUE_PERFORMANCES_2026-04-29.md`
- `CHANGELOG.md`

### Critères de sortie

- Aucune contradiction de version active
- Statut des actions P1/P2/P3 cohérent entre les documents
- Une seule source de vérité opérationnelle pour les optimisations

---

## Planning 2 semaines (proposé)

- Semaine 1
1. J1-J2 : charge réelle viewer + baseline métriques
2. J3-J5 : fiabilisation async provider + benchmark comparatif

- Semaine 2
1. J6-J7 : alignement documentaire complet
2. J8-J10 : suivi post-correctifs + re-mesure p95

---

## Livrables attendus

1. Tableau métriques avant/après (p50, p95, taux d'erreur)
2. Rapport sync/async par provider avec recommandation de réglage
3. Documentation alignée et prête pour passage v2.8.19+
