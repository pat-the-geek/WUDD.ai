# Rapport sur les possibilités d'améliorations de performance en production

Date: 2026-04-14

Mise à jour: 2026-04-17

## Objectif

Ce rapport évalue les principaux leviers d'amélioration de performance pour l'exploitation de WUDD.ai en production, en se concentrant sur:

- la latence du viewer Flask/React
- le débit des traitements cron
- la contention entre interface web et batchs IA
- la montée en charge du stockage JSON et des indexes
- les optimisations déjà présentes mais encore incomplètement exploitées

L'analyse s'appuie sur l'architecture Docker actuelle, les routes Flask du viewer, les modules d'indexation, la couche DuckDB, les scripts cron et un benchmark interne déjà fourni par le dépôt.

## Synthèse exécutive

Le principal frein de performance en production n'est pas un algorithme isolé, mais l'architecture d'exécution actuelle: un seul conteneur exécute simultanément le viewer Flask, le cron, les batchs d'enrichissement et les tâches de maintenance. Cette cohabitation crée une contention CPU, I/O disque et réseau au moment même où l'interface doit rester réactive.

Le second frein est l'usage encore fréquent de scans complets sur le système de fichiers et de relectures JSON intégrales, alors même que le dépôt dispose déjà d'indexes dédiés et d'une couche DuckDB installée. Autrement dit, plusieurs briques d'optimisation existent déjà, mais elles ne sont pas encore utilisées partout où elles apporteraient le plus de valeur.

Depuis la rédaction initiale de ce rapport, la recommandation sur `/api/files` a été partiellement mise en oeuvre. La route utilise désormais un manifeste mémoire TTL avec invalidation sur écriture API et ne conserve le double scan qu'en fallback défensif. Ce point n'est donc plus une recommandation théorique, mais un gain déjà observé et mesuré localement.

Enfin, certaines optimisations annoncées existent dans le code mais ne sont pas encore pleinement branchées dans les chemins critiques. C'est le cas de l'enrichissement asynchrone, présent dans `utils/async_enricher.py`, mais pas encore exploité de façon visible dans les scripts batch principaux.

## État actuel observé

### Architecture d'exécution

- Le service Docker unique `analyse-actualites` regroupe Flask, cron et les batchs métier.
- L'entrypoint exécute un bootstrap applicatif avant de lancer le viewer puis cron.
- Le viewer est démarré via `python3 /app/viewer/app.py`, donc via le serveur Flask intégré.
- Les indexes peuvent être reconstruits au démarrage du viewer si considérés obsolètes.

### Volumétrie relevée

Mesures locales relevées pendant l'analyse:

- 151 fichiers JSON
- 150 fichiers Markdown
- `data/articles-from-rss`: environ 28 Mo
- `data/entity_index.json`: environ 8.5 Mo
- `data/article_index.json`: environ 3.3 Mo
- `data/geocode_cache.json`: environ 12 Mo

Le volume reste modéré, mais plusieurs indexes et caches pèsent déjà autant ou plus que certaines données sources. Cela signifie que la stratégie d'accélération doit rester sélective: un index utile doit vraiment éviter du travail, sinon il ajoute surtout du coût mémoire et de la complexité de synchronisation.

### Benchmark existant

Le script `scripts/benchmark_indexes.py --iterations 3` a donné les résultats suivants:

- Top articles via scan complet: 1.06 s
- Top articles via `article_index`: 2.69 s
- Recherche entité via scan complet: 100 ms
- Recherche entité via `entity_index`: 81 ms

Conclusion immédiate:

- `entity_index` apporte déjà un gain léger et crédible sur le cas testé.
- `article_index` n'apporte pas encore de gain sur le classement des top articles dans l'état actuel de l'implémentation et du corpus.
- Il faut donc éviter de supposer que "mettre plus d'index" accélère automatiquement le système.

Le benchmark s'interrompt ensuite sur une erreur de robustesse du corpus dans la partie cooccurrences. Ce point n'empêche pas l'analyse de performance, mais il limite la qualité actuelle de la mesure automatisée.

## Forces déjà en place

Plusieurs fondations sont bonnes et doivent être conservées:

- couche de cache fichier TTL
- quotas adaptatifs pour limiter la consommation IA
- `entity_index` et `article_index`
- couche analytique DuckDB installée dans `requirements.txt`
- pré-calcul nightly de `data/entity_stats.json`
- prise en charge d'un enrichissement asynchrone via `aiohttp`
- usage déjà partiel de DuckDB dans certaines routes analytiques et scripts

Le bon axe n'est donc pas une réécriture générale, mais une meilleure exploitation des briques déjà présentes sur les chemins réellement coûteux.

## Points de contention prioritaires

### 1. Un seul conteneur pour le viewer et les batchs

Impact: très élevé

Le même service Docker porte:

- l'interface Flask
- les SSE longues durées
- les batchs cron
- les enrichissements IA
- les rebuilds d'index
- les tâches de maintenance

Conséquences:

- pics CPU quand les enrichissements tournent
- contention disque pendant les scans JSON et les écritures d'index
- latence variable du viewer pendant les fenêtres cron
- absence d'isolation des incidents

Recommandation:

- séparer au minimum le viewer et le worker cron en deux services Docker distincts
- conserver les volumes partagés `data/`, `rapports/`, `config/`
- réserver le viewer aux lectures, recherches, SSE et actions interactives
- réserver le worker aux scripts planifiés et aux enrichissements

Gain attendu:

- amélioration nette de la stabilité perçue
- réduction des latences p95 du viewer
- meilleure prédictibilité des batchs

### 2. Utilisation du serveur Flask intégré en production

Impact: très élevé

Le viewer est lancé avec `app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)`. Ce mode est acceptable pour du local, mais pas comme cible de production durable, surtout avec des routes SSE et des lectures de fichiers parfois lourdes.

Recommandation:

- remplacer le lancement direct par Gunicorn
- privilégier un modèle de workers compatible avec SSE, par exemple `gevent` ou `gthread` selon le comportement observé
- définir explicitement le nombre de workers, le timeout, les limites de requêtes et les logs d'accès

Gain attendu:

- meilleure tenue sous charge concurrente
- gestion plus propre des connexions longues
- meilleure observabilité opérationnelle

### 3. `api/files` reste coûteuse par conception

Impact: élevé

La route `/api/files` effectue deux scans complets de l'arborescence, avec un `sleep(0.20)` entre les deux passes pour compenser des incohérences de listing sous Docker Desktop/virtiofs. Cette route relit ensuite tout `data/`, `rapports/` et `samples` via `collect_files()`.

Ce comportement devient rapidement coûteux quand:

- le nombre de fichiers augmente
- les volumes bind-mount sur macOS sont plus lents que le disque natif
- le frontend rafraîchit souvent le listing

Recommandation:

- introduire un manifeste de fichiers mis en cache en mémoire avec TTL court, par exemple 15 à 60 secondes
- alimenter ce manifeste par invalidation sur écriture API ou par tâche périodique légère
- garder le double scan uniquement en fallback derrière un feature flag ou sur erreur détectée

Gain attendu:

- baisse immédiate de la latence du listing
- réduction du bruit I/O sur les volumes Docker Desktop

État au 2026-04-17:

- la route `/api/files` a été modifiée pour servir un manifeste mémoire TTL au lieu de refaire systématiquement deux scans complets
- le TTL par défaut est configurable via `VIEWER_FILES_CACHE_TTL` et vaut actuellement 30 secondes
- le double scan avec `sleep(0.20)` n'est plus le chemin nominal ; il reste disponible comme fallback défensif si un refresh paraît anormalement incomplet
- l'invalidation du manifeste est branchée sur les écritures API qui touchent `data/` ou `rapports/`

Mesures relevées après implémentation:

- corpus de test: 214 éléments listés, réponse JSON d'environ 43.8 Ko
- avant optimisation: série de requêtes entre 301 ms et 363 ms, moyenne observée d'environ 320 ms
- après rebuild du conteneur: premier appel à froid à 84 ms sur l'instance principale
- appels à chaud sur cache: moyenne observée de 1.835 ms sur 10 requêtes consécutives
- benchmark warm sur 100 requêtes: p50 1.392 ms, p95 2.567 ms, p99 5.527 ms, avec un outlier isolé à 121.073 ms
- test TTL avec `VIEWER_FILES_CACHE_TTL=1`: premier appel à 117.149 ms, appel immédiat suivant à 1.634 ms, puis nouvel appel à 71.910 ms après expiration effective du cache
- test d'invalidation: création puis suppression d'un fichier via API immédiatement reflétées dans `/api/files` avec passage de 214 à 215 puis retour à 214 éléments

Conclusion mise à jour:

Cette optimisation apporte un gain immédiat et mesurable. Sur ce point précis, la priorité n'est plus d'implémenter un cache de listing, mais de l'instrumenter proprement et d'étendre la même discipline à d'autres routes interactives coûteuses.

### 4. Les recherches texte relisent encore les fichiers entiers

Impact: élevé

La route `/api/search` appelle `collect_files()`, puis:

- lit ligne par ligne le contenu complet des fichiers texte
- ou charge des JSON complets pour appliquer des filtres article

Cela donne un coût proportionnel au nombre total de fichiers et à leur taille, même quand la recherche porte sur une petite fenêtre temporelle ou un flux précis.

Recommandation:

- basculer la recherche article vers une stratégie hybride index + DuckDB
- conserver la recherche ligne à ligne uniquement pour les Markdown
- pour les JSON d'articles, interroger `article_index` pour restreindre les fichiers candidats puis laisser DuckDB ou un scan ciblé charger seulement ces fichiers

Gain attendu:

- amélioration sensible des recherches multi-critères
- coût mieux borné quand le corpus grossit

### 5. Les indexes ne sont pas encore utilisés de façon optimale

Impact: moyen à élevé

Le dépôt dispose déjà d'indexes, mais leur rendement est inégal.

Observation importante:

- la route `/api/articles/top` utilise encore `ScoringEngine.get_top_articles()` et non `get_top_articles_from_index()`
- toutefois le benchmark montre que le chemin indexé est actuellement plus lent sur le corpus testé

Conclusion:

- il ne faut pas juste remplacer l'appel existant par l'appel indexé
- il faut d'abord corriger le modèle de chargement du chemin indexé

Causes probables du manque de gain:

- le chemin indexé charge encore trop d'articles complets avant le scoring final
- le score n'est pas pré-calculé ni mis en cache pour les requêtes répétées
- l'index articles est bénéfique pour filtrer, mais pas encore pour réduire suffisamment le coût de chargement et de scoring

Recommandation:

- conserver `article_index` comme filtre de candidats seulement
- introduire un cache des top articles sur fenêtres standard, par exemple 24 h et 48 h
- limiter le scoring live à un sous-ensemble borné via un tri préalable par fraîcheur ou source
- éventuellement stocker dans l'index quelques signaux de scoring déjà calculables sans relire l'article complet

Gain attendu:

- amélioration réelle des endpoints "top articles" au lieu d'un simple déplacement du coût

### 6. DuckDB est présent, mais encore sous-exploité

Impact: élevé

`duckdb` est installé et déjà utilisé dans plusieurs endroits. C'est un bon choix pour ce projet, car il permet de garder JSON comme source de vérité tout en accélérant les lectures analytiques.

Aujourd'hui, DuckDB est déjà branché dans:

- certaines statistiques entités
- certaines routes analytiques
- certaines parties de `trend_detector.py`
- `generate_48h_report.py`

Mais de nombreux chemins restent encore en `rglob + json.loads()` alors que leur usage est typiquement analytique.

Recommandation:

- étendre DuckDB à toutes les routes de reporting et d'agrégation lourde
- standardiser un chemin rapide DuckDB puis un fallback Python unique, au lieu de duplications locales
- ajouter quelques vues ou helpers dédiés dans `utils/db.py` pour les cas fréquents: recherche articles filtrée, top fichiers récents, agrégations par flux, compteurs par période

Gain attendu:

- réduction forte des scans Python
- meilleure montée en charge analytique sans migration vers une base externe

État au 2026-04-17:

- `utils/db.py` expose désormais un chemin rapide unifié pour les lectures analytiques, avec normalisation des dates, union multi-glob, schéma explicite pour JSON hétérogènes, et helpers dédiés pour les cas fréquents
- `viewer/routes/analytics.py` utilise ce chemin DuckDB en priorité sur `/api/sources/reliability`, `/api/analytics/compare` et `/api/data-quality`, avec un fallback Python mutualisé au lieu de scans locaux dupliqués
- la version a été redéployée dans Docker et validée sur le service `analyse-actualites`

Mesures relevées en Docker après déploiement:

- `/api/data-quality?dir=all` : réponse `200`, charge utile d'environ 13.8 Ko, moyenne observée à 45.3 ms sur 10 requêtes, p50 45.1 ms, p95 48.0 ms
- `/api/analytics/compare?...` : réponse `200`, charge utile d'environ 750 octets, moyenne observée à 89.5 ms sur 10 requêtes, p50 88.3 ms, p95 91.1 ms
- `/api/sources/reliability?hours=48&min_articles=1` : réponse `200`, charge utile d'environ 12.4 Ko, premier appel mesuré à 17.16 s puis plateau autour de 13.2 à 13.3 s sur les requêtes suivantes

Conclusion mise à jour:

L'extension DuckDB produit bien l'effet attendu sur les endpoints dominés auparavant par le scan de fichiers et les relectures JSON. `data-quality` et `analytics/compare` répondent désormais en moins de 100 ms dans le conteneur déployé. En revanche, `sources/reliability` reste coûteux malgré le chargement DuckDB, ce qui indique que le prochain goulot n'est plus l'I/O mais l'algorithme de triangulation inter-sources, encore quadratique sur le volume d'articles retenus.

### 7. L'enrichissement asynchrone n'est pas encore pleinement exploité

Impact: élevé sur les batchs

Le module `utils/async_enricher.py` existe, `aiohttp` est installé, mais l'analyse du dépôt montre qu'il n'est pas visiblement branché dans les scripts batch principaux d'enrichissement. La capacité technique est donc disponible, mais la trajectoire de production semble encore majoritairement séquentielle ou faiblement parallèle.

Recommandation:

- intégrer `AsyncEnricher` dans `enrich_entities.py` et `enrich_sentiment.py`
- exposer une concurrence paramétrable par environnement
- limiter la concurrence selon le provider IA et les quotas
- mesurer séparément le débit réseau, le temps moyen par article et le taux d'erreur API

Gain attendu:

- réduction notable de la durée des batchs d'enrichissement
- meilleure exploitation des fenêtres nocturnes

### 8. Le démarrage du viewer déclenche encore du travail métier

Impact: moyen

Au démarrage:

- l'entrypoint synchronise le registre des sources
- le module Flask peut lancer une reconstruction d'index en arrière-plan si les indexes sont jugés trop anciens

Même si cette reconstruction est asynchrone, elle consomme des ressources au moment où le service redémarre et où les premières requêtes arrivent.

Recommandation:

- déplacer au maximum les reconstructions complètes en tâche cron ou commande d'admin explicite
- privilégier la maintenance incrémentale des indexes après chaque écriture significative
- réduire le rebuild au démarrage à un contrôle léger, pas à une action corrective lourde

Gain attendu:

- meilleur cold start
- moins de concurrence au redémarrage du service

### 9. Les routes interactives déclenchent encore trop de lecture disque directe

Impact: moyen

Plusieurs routes du viewer chargent encore les JSON complets sur disque pour répondre à des requêtes interactives. Cela reste acceptable à petite échelle, mais dégradera la réactivité à mesure que le corpus augmente ou si plusieurs utilisateurs consultent l'interface en même temps.

Recommandation:

- introduire des caches mémoire TTL ciblés par route
- centraliser l'invalidation lors des écritures via l'API
- privilégier des structures pré-calculées légères pour les dashboards ouverts souvent

Gain attendu:

- amélioration du temps de réponse perçu
- baisse du nombre de relectures des mêmes fichiers

## Priorisation recommandée

### P0: à traiter en premier

1. Séparer `viewer` et `worker cron` en deux services Docker.
2. Remplacer le serveur Flask intégré par Gunicorn en production.
3. Instrumenter et fiabiliser le cache du listing `/api/files` déjà implémenté.
4. Instrumenter les routes critiques avec temps d'exécution, volume lu et statut cache hit/miss.

### P1: gains rapides avec peu de risque

1. Brancher `AsyncEnricher` dans les batchs NER et sentiment.
2. Étendre les chemins DuckDB pour la recherche et les dashboards analytiques.
3. Pré-calculer les top articles sur fenêtres 24 h et 48 h.
4. Déplacer les rebuilds complets d'index hors du démarrage du viewer.

### P2: optimisation structurelle

1. Introduire un manifeste de fichiers incrémental pour le viewer.
2. Enrichir `article_index` avec des signaux partiels de scoring utiles au pré-filtrage.
3. Réduire le nombre de scans `rglob` dans les scripts de maintenance et de réparation.
4. Étudier une séparation future entre stockage source JSON et couche analytique persistante plus robuste si le volume continue de croître.

## Plan d'implémentation proposé

### Phase 1: stabiliser la prod

Durée indicative: 2 à 4 jours

- service Docker séparé pour le viewer
- Gunicorn pour le backend Flask
- métriques simples de latence route par route
- instrumentation du cache mémoire TTL sur `/api/files` déjà en place

### Phase 2: accélérer les batchs et les dashboards

Durée indicative: 1 à 2 semaines

- intégration effective de `AsyncEnricher`
- généralisation de DuckDB sur les agrégations lourdes
- réduction des scans complets sur les routes interactives

### Phase 3: industrialiser la couche d'accès aux données

Durée indicative: 2 à 4 semaines

- manifeste incrémental de fichiers
- stratégie cohérente index + cache + DuckDB
- revue de la taille et du rôle de chaque index

## Indicateurs à suivre

Pour piloter les améliorations, il faut mesurer avant et après:

- temps de réponse p50, p95 et p99 des routes `/api/files`, `/api/search`, `/api/articles/top`, `/api/entities/dashboard`
- durée totale des batchs `enrich_entities.py` et `enrich_sentiment.py`
- temps de cold start du viewer
- taux de cache hit sur `entity_stats.json`, cache mémoire viewer et caches IA
- nombre de scans disque complets par heure
- CPU, mémoire RSS et I/O du conteneur viewer
- nombre de connexions SSE simultanées

## Conclusion

Les meilleures améliorations de performance pour WUDD.ai en production sont d'abord architecturales et opérationnelles, pas micro-algorithmiques.

Le plus gros gain viendra de la séparation des rôles entre interface et traitements batch, puis du passage à un vrai serveur WSGI/ASGI adapté au trafic réel. Ensuite seulement, il faut rationaliser les accès aux données en faisant de DuckDB, des caches ciblés et des indexes des outils complémentaires, plutôt que des couches concurrentes.

Le code montre déjà une bonne direction technique. Le travail prioritaire consiste maintenant à brancher correctement les optimisations existantes sur les chemins critiques, à supprimer les scans complets les plus coûteux, et à ne conserver que les indexes qui démontrent un bénéfice mesurable.

Mise à jour au 2026-04-17: le chantier `/api/files` valide l'approche recommandée par ce rapport. La suite logique est d'ajouter une observabilité légère sur ce cache, puis d'appliquer le même modèle ciblé, mesuré et invalidé proprement aux autres endpoints interactifs les plus coûteux.
