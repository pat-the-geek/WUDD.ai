# Rapport technique performances et exploitation — 29/04/2026

## Résumé exécutif

Le socle performance du projet est globalement solide et plus avancé que ce que la documentation historique laisse penser.

Points clés :

- Les optimisations majeures de mars sont en production (indexation, rolling window unifié, cache backend viewer, robustesse du parsing IA).
- Le principal goulot restant est infrastructurel mais réduit : runtime viewer/worker séparé en Docker, avec un risque résiduel surtout lié au tuning sous charge métier réelle.
- Le principal écart est documentaire : plusieurs actions marquées à faire sont déjà livrées dans le code.

Niveau de maturité (estimation) :

- Performance pipeline data : élevé
- Performance API viewer : bon
- Exploitation/production runtime : moyen
- Alignement documentation/code : moyen-faible

---

## Méthode et périmètre

Analyse basée sur l'état actuel du dépôt au 29/04/2026.

Périmètre vérifié :

- Scripts de collecte et enrichissement
- Modules utilitaires index/cache/api
- Routes et état du viewer Flask
- Changelog et rapports techniques existants
- Tests liés aux optimisations

Sources utilisées dans le dépôt :

- docs/RAPPORT_ANALYSE_OPTIMISATIONS.md
- docs/ameliorations/AMELIORATIONS.md
- docs/WUDD-Feuille-de-route-2026.md
- CHANGELOG.md
- scripts/*.py
- utils/*.py
- viewer/routes/*.py
- tests/*.py

### Mise à jour post-correctifs du 29/04 (soir)

Cette section complète l'état des lieux initial avec les correctifs livrés après la première rédaction du rapport.

Correctifs appliqués et validés :

- v2.8.13 : optimisation du chargement d'articles d'entité (cache TTL route, paramètres `max_articles` et `compact`, tri côté API, réduction du travail côté front).
- v2.8.14 : accélération du panneau entité en mode compact avec désactivation du fallback disque complet (`rglob`) pour les appels UI.
- Déploiement Docker reconstruit et validé (`viewer` + `worker`), endpoint runtime OK.

Mesure terrain (cas signalé `PERSON:Jack Dorsey`) :

- avant correctif : requêtes intermittentes à timeout (jusqu'à 45s).
- après correctif + redéploiement : réponses stables en HTTP 200, ordre de grandeur observé ~0.001s à ~0.16s.

---

## État des optimisations

### 1. Optimisations confirmées en production

1. Mise à jour des index après enrichissement

   - Enrichissement entités : mise à jour article_index et entity_index après sauvegarde.
   - Enrichissement sentiment : mise à jour article_index après sauvegarde.
   - Effet : cohérence plus rapide entre fichiers JSON et index de lecture.

1. Fenêtre glissante 48h centralisée

   - Le watcher principal utilise update_rolling_window puis met à jour les index.
   - Effet : réduction des divergences de logique entre scripts.

1. score_source injecté dès la création d article

   - Présent dans les flux RSS keyword et web_watcher.
   - Effet : ranking plus fidèle dans les vues et exports qui utilisent le scoring.

1. Cache backend sur routes coûteuses

   - Cache TTL mémoire pour /api/files.
   - Cache TTL mémoire pour /api/sources/bias.
   - Effet : baisse des rescans disque répétitifs côté viewer.

1. Circuit breaker enrichi dans le client API

   - États différenciés (transient/quota/auth) et transitions explicites.
   - Effet : meilleure résilience et meilleure lisibilité des pannes.

1. Cache provider-aware + TTL par type de contenu

   - Isolation des clés par provider IA.
   - TTL différenciés selon la nature du contenu.
   - Effet : réduction des collisions et meilleure efficacité cache.

1. Distinction echec_parse vs echec_api

   - Parsing NER/sentiment renvoie un statut exploitable.
   - Effet : réparations ciblées plus fiables.

1. Couverture tests des briques optimisation

   - Présence de tests rolling window, parse_article_date, async_enricher et suites associées.
   - Effet : meilleure sécurité lors des évolutions.

1. Chargement des entités UI accéléré

   - Route `/api/entities/articles` optimisée pour le mode compact du panneau entité.
   - Effet : réduction forte des latences de premier affichage sur les entités fréquentes.

1. Quotas viewer optimisés

   - `get_stats()` quota resynchronisé avec stratégie mtime/TTL et payload compact côté API/UI.
   - Effet : affichage quasi instantané de l'onglet quotas après déploiement.

### 2. Points partiellement traités

1. AsyncEnricher disponible et désormais pilotable dans enrich_entities via feature flag (--use-async), à étendre ensuite à enrich_sentiment.
2. Fallback double scan de /api/files conservé mais allégé et borné (pause configurable, valeur par défaut réduite).
3. Gunicorn calibré avec charge légère, à confirmer sous charge métier réelle.
4. AsyncEnricher branché en pilote sur enrich_entities, extension à finaliser sur enrich_sentiment.

### 3. Points non résolus à fort impact

1. Exécution runtime (statut : traité en Docker Compose)

   - Le runtime est désormais séparé en 2 services : `analyse-actualites-viewer` et `analyse-actualites-worker`.
   - Le risque de contention interactive/batch est réduit en production Docker.
   - Risque résiduel : vérifier les limites CPU/RAM selon la volumétrie réelle.

1. Viewer en serveur Flask intégré (statut : partiellement traité)

   - Runtime Docker basculé vers Gunicorn.
   - Le mode local de développement conserve `app.run` (comportement attendu en dev).
   - Risque résiduel : tuning workers/threads à ajuster selon la charge réelle.

1. Documentation en retard sur l état réel

   - Plusieurs items marqués en backlog sont déjà implémentés.
   - Risque : priorisation biaisée et perte de temps de coordination.

---

## Écarts documentation vs code

Constat principal : les documents de mars (v2.5.0) ne reflètent plus complètement la base actuelle (v2.8.x).

Conséquences :

- Backlog technique faussement gonflé.
- Difficulté à distinguer le vrai reste à faire.
- Risque de réouvrir des sujets déjà traités.

Action prioritaire recommandée :

- Produire un backlog unique et daté, avec statut explicite : fait, en cours, à faire, dépriorisé.

---

## Priorisation recommandée (30 jours)

### Priorité P1 (immédiat)

1. Mettre à jour la documentation de référence

   - Cible : docs/ameliorations/AMELIORATIONS.md et docs/WUDD-Feuille-de-route-2026.md.
   - Livrable : statut factuel par item + liens vers fichiers de preuve.

1. Durcir le runtime viewer (fait en Docker, calibrage initial réalisé)

   - Cible : confirmer le tuning Gunicorn sous charge métier.
   - Livrable : paramètres workers/threads/timeouts validés avec campagne de tests dédiée.

### Priorité P2 (court terme)

1. Découpler exécution viewer et workers cron (fait en Docker)

   - Implémentation : deux services Docker dédiés `viewer` et `worker`.
   - Livrable atteint : architecture runtime séparée et logs isolables par service.

1. Brancher AsyncEnricher sur au moins un flux batch

   - Commencer sur enrich_entities ou enrich_sentiment avec feature flag.
   - Livrable : comparatif avant/après sur temps de traitement et taux d échec.

### Priorité P3 (après stabilisation)

1. Étendre l usage de DuckDB sur les endpoints analytiques restants.
2. Réduire progressivement le fallback double scan /api/files si l environnement le permet.

---

## Indicateurs de suivi recommandés

Mettre en place un relevé hebdomadaire simple :

- Latence p50 et p95 de /api/files.
- Latence p50 et p95 de /api/entities/articles en mode `compact=1`.
- Durée moyenne des jobs enrich_entities et enrich_sentiment.
- Ratio cache hit/miss sur routes analytiques viewer.
- Nombre d erreurs par catégorie IA : timeout, quota, auth, echec_parse.
- Délai de disponibilité d une entité entre écriture article et visibilité dashboard.

Objectif cible à 1 mois :

- p95 /api/files inférieur à 400 ms en usage nominal.
- Réduction de 30 % du temps moyen d'un batch d'enrichissement via async piloté.
- Aucune divergence documentaire majeure sur les sujets performance critiques.

Mesures rapides de calibration Gunicorn (endpoint `/api/runtime-info`) :

- baseline (avant split) : `conc=30` p95 ~43.2 ms
- après split + preload : `conc=30` p95 ~6.3 ms
- validation post-ajustements 29/04 : `n=120` p50 ~2.6 ms, p95 ~22.9 ms
- configuration retenue à date : `workers=2`, `threads=4`, `timeout=120`

### Campagne de validation en charge réelle (post-correctifs 29/04 soir)

Mesures locales sur stack Docker active (`analyse-actualites-viewer` + `analyse-actualites-worker`),
120 requêtes par endpoint.

| Endpoint | n | p50 | p95 | p99 | min | max | Codes HTTP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `/api/runtime-info` | 120 | 2.57 ms | 3.59 ms | 3.87 ms | 1.04 ms | 15.19 ms | 200×120 |
| `/api/files` | 120 | 2.86 ms | 4.04 ms | 44.64 ms | 1.61 ms | 73.78 ms | 200×120 |
| `/api/entities/articles?type=PERSON&value=Jack%20Dorsey&max_articles=300&compact=1` | 120 | 2.58 ms | 3.59 ms | 72.53 ms | 1.35 ms | 119.72 ms | 200×120 |

Conclusion opérationnelle : les trois endpoints restent stables en 200, avec des médianes < 3 ms ;
les pointes p99 demeurent contenues et compatibles avec l'objectif de réactivité UI.

### Benchmark `enrich_sentiment` sync vs async (29/04 soir)

Campagne réalisée sur 10 résumés réels extraits de `data/articles-from-rss/intelligence-artificielle.json`.

Constat clé : le premier benchmark du pilote async révélait une divergence de provider.
Le chemin synchrone utilisait correctement `AI_PROVIDER_NER=ollama`, alors que le batch async résolvait encore `AI_PROVIDER`.
Le correctif appliqué dans `utils/async_enricher.py` aligne désormais le routage sur `AI_PROVIDER_NER`, puis retombe volontairement sur le fallback synchrone/parallélisé quand le provider effectif est Ollama, car ce backend n'a pas encore d'implémentation async native dans WUDD.ai.

| Configuration | n | Succès | Temps total | Temps moyen/article | Gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sync (`get_ner_client()` → Ollama) | 10 | 10/10 | 38.53 s | 3.85 s | ref |
| Async demandé (`--use-async`, provider réel Ollama, fallback préservé) | 10 | 10/10 | 38.58 s | 3.86 s | 1.00x |

Conclusion opérationnelle :

- le pilote async sur `enrich_sentiment.py` est maintenant cohérent avec la configuration réelle du projet ;
- avec `AI_PROVIDER_NER=ollama`, il n'apporte pas d'accélération mesurable à ce stade, ce qui est cohérent avec le fallback de compatibilité ;
- le gain de parallélisation restera à mesurer avec un backend HTTP réellement exploitable en async (EurIA/Claude) ou avec une implémentation async native pour Ollama.

### Correctif EurIA sentiment (suite du 29/04 soir)

Le point bloquant sur EurIA a finalement été identifié puis corrigé :

- le modèle émettait souvent un `reasoning` sans `content` final utile ;
- avec un message système strict et un budget de sortie porté à `300`, le taux de réponses exploitables remonte fortement ;
- le parseur sentiment tolère désormais les JSON partiels/tronqués et reconstruit `sentiment` à partir de `score_sentiment` quand ce champ textuel manque.

Campagne de revalidation sur 5 résumés réels de `data/articles-from-rss/intelligence-artificielle.json` :

| Configuration | n | Succès | Temps total | Temps moyen/article | Gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sync EurIA corrigé | 5 | 4/5 | 5.84 s | 1.17 s | ref |
| Async EurIA corrigé (`provider='euria'`, concurrency=5) | 5 | 4/5 | 3.04 s | 0.61 s | 1.93x |

Conclusion pratique : le benchmark EurIA devient enfin lisible après correctif. Le gain async existe bien sur un backend HTTP compatible, même si un reliquat d'échec `1/5` subsiste encore sur cet échantillon court.

---

## Conclusion

Le projet n est pas en retard côté performance logicielle ; il est surtout en transition vers une maturité d exploitation.

Le meilleur levier immédiat n est pas une nouvelle couche d optimisation algorithmique, mais :

1. aligner la documentation avec le code réel,
2. durcir le runtime viewer,
3. découpler les workloads interactifs et batch.

Ces trois actions donneront le meilleur ratio effort/impact sur la stabilité perçue et la capacité à scaler proprement.
