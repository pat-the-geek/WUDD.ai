# Plan de migration blue/green minimale sans interruption visible

Date: 2026-04-14

## Objectif

Préparer une migration de production minimale, adaptée à la machine actuelle, sans proxy externe et sans arrêt visible du viewer pendant la phase de préparation.

Le principe est le suivant:

- l'infrastructure actuelle reste active en `blue`
- une nouvelle infrastructure est montée en parallèle en `green`
- un seul writer est autorisé à écrire dans les vraies données à tout moment
- la bascule se fait en deux temps: d'abord l'écriture, puis l'interface

## Contrainte structurante du projet

L'état actuel du dépôt repose sur un service Docker unique qui:

- monte les volumes `data/`, `rapports/`, `config/`, `archives/`, `samples/`
- démarre le viewer Flask
- installe la crontab
- lance `cron -f`

Dans cet état, deux stacks parallèles ne peuvent pas écrire simultanément dans les mêmes volumes sans risque de:

- doublons
- écrasements de JSON
- incohérences d'index
- corruption logique des quotas et états de traitement

Conclusion opérationnelle:

- coexistence en lecture: oui
- coexistence avec deux writers actifs sur les mêmes volumes: non

## Résultat recherché

### Pendant la préparation

- `blue` reste la prod active
- `green` est déployée en parallèle sur un autre port
- `green` ne doit pas écrire dans les volumes de production

### Pendant la bascule

- on coupe d'abord le writer `blue`
- on attend la fin du job éventuel
- on active le writer `green`
- on bascule l'usage du viewer vers `green`

### En rollback

- on désactive le writer `green`
- on réactive le writer `blue`
- on revient sur l'interface `blue`

## Architecture cible minimale

### Blue

- conteneur actuel `analyse-actualites`
- port public: `5050`
- cron actif
- writer principal

### Green

- nouveau conteneur parallèle, par exemple `analyse-actualites-green`
- port public: `5051`
- viewer actif
- cron désactivé au démarrage
- lecture seule logique sur la prod tant que la bascule n'a pas eu lieu

## Décision d'implémentation

Pour cette version minimale, il ne faut pas essayer de résoudre toute l'architecture cible en une seule fois.

La bonne stratégie est:

1. rendre le démarrage du cron pilotable
2. permettre un déploiement parallèle sur un autre port
3. valider `green` en lecture
4. basculer ensuite l'écriture et l'interface de manière contrôlée

## Modifications techniques à prévoir

### 1. Rendre le cron désactivable par variable d'environnement

But:

- démarrer `green` sans écriture automatique

Modification attendue:

- dans `entrypoint.sh`, introduire une variable de type `ENABLE_CRON=true|false`
- si `ENABLE_CRON=false`, ne pas installer ni lancer `cron -f`
- le viewer doit pouvoir démarrer seul

Comportement cible:

- `blue`: `ENABLE_CRON=true`
- `green`: `ENABLE_CRON=false` pendant toute la préparation

### 2. Rendre le viewer démarrable seul

But:

- permettre une stack `green` consultable sans writer actif

Modification attendue:

- dans `entrypoint.sh`, conserver le lancement du viewer indépendamment du cron
- introduire éventuellement `ENABLE_VIEWER=true|false` pour clarifier les rôles futurs

Comportement cible:

- `blue`: viewer + cron
- `green`: viewer seul pendant la préparation

### 3. Préparer un compose parallèle minimal

But:

- lancer `green` sans toucher à `blue`

Option recommandée:

- conserver `docker-compose.yml` pour `blue`
- créer un fichier dédié, par exemple `docker-compose.green.yml`

Ce fichier devra:

- utiliser la même image ou le même build
- définir un nom de conteneur différent
- publier `5051:5050`
- définir `ENABLE_CRON=false`
- garder les mêmes montages utiles au viewer

Note:

- pendant la phase de validation, il vaut mieux ne pas donner à `green` un pouvoir d'écriture automatique
- si une sécurité supplémentaire est souhaitée, certains volumes peuvent être montés en lecture seule

### 4. Prévoir un mode de validation sûr

Deux stratégies possibles:

#### Option A — la plus simple

- `green` lit les vrais volumes
- `green` n'exécute aucun cron
- les opérations de modification manuelle via l'UI sont évitées pendant la validation

Avantage:

- effort minimal

Risque résiduel:

- un utilisateur peut déclencher une écriture manuelle si l'UI le permet

#### Option B — la plus sûre

- `green` lit une copie de `data/` et `rapports/`
- `green` ne touche jamais aux vrais fichiers pendant la validation

Avantage:

- isolement complet

Inconvénient:

- préparation plus lourde

Pour une migration minimale sur machine locale, l'option A est acceptable si l'accès à `green` reste réservé aux tests et si le cron est bien désactivé.

## Séquence opérationnelle détaillée

### Phase 1 — Préparation

Durée indicative: 2 à 4 heures

1. Vérifier que `blue` fonctionne normalement sur `5050`.
2. Ajouter le contrôle `ENABLE_CRON` dans l'entrypoint.
3. Créer la variante `docker-compose.green.yml`.
4. Démarrer `green` sur `5051` avec `ENABLE_CRON=false`.
5. Vérifier que `blue` continue à fonctionner sans impact.

Critère de sortie:

- `blue` reste stable sur `5050`
- `green` est consultable sur `5051`

### Phase 2 — Validation de green

Durée indicative: 2 à 4 heures

Vérifier sur `green`:

- chargement du viewer
- navigation dans la liste des fichiers
- ouverture de JSON et Markdown
- accès aux dashboards critiques
- lecture des indexes et caches
- affichage correct des routes SSE majeures si utilisées

À ne pas faire pendant cette phase:

- lancer un cron
- déclencher des opérations d'écriture non nécessaires
- utiliser `green` comme environnement quotidien de production

Critère de sortie:

- `green` fournit les mêmes lectures fonctionnelles que `blue`

### Phase 3 — Pré-bascule

Durée indicative: 15 à 30 minutes

Choisir une fenêtre calme, idéalement hors exécution d'un job important.

Checklist:

- vérifier qu'aucun traitement critique n'est en cours sur `blue`
- vérifier les derniers logs cron
- vérifier l'état des volumes et de l'espace disque
- préparer les commandes de rollback avant la bascule

Critère de sortie:

- environnement prêt, rollback prêt, pas de job en cours à fort impact

### Phase 4 — Bascule du writer

Durée indicative: 5 à 10 minutes

Ordre strict:

1. arrêter le cron de `blue` ou arrêter proprement le conteneur `blue`
2. confirmer qu'aucun job résiduel n'écrit encore
3. redémarrer `green` avec `ENABLE_CRON=true`
4. vérifier que `green` est devenu le seul writer actif

Critère de sortie:

- un seul writer actif, désormais `green`

### Phase 5 — Bascule de l'interface

Sans proxy, deux modes sont possibles:

#### Mode 1 — sans interruption perceptible mais avec changement d'URL

- `blue` reste sur `5050`
- `green` reste sur `5051`
- les utilisateurs passent sur `http://localhost:5051`

Avantage:

- aucune micro-coupure

Inconvénient:

- changement d'URL

#### Mode 2 — retour sur le port standard `5050`

- arrêter `blue`
- relancer `green` sur `5050`

Avantage:

- l'URL finale reste identique

Inconvénient:

- micro-coupure technique pendant le redémarrage et la republication du port

Pour une machine locale sans reverse proxy, le mode 1 est le vrai mode "sans interruption visible".

### Phase 6 — Observation post-bascule

Durée indicative: 2 à 24 heures selon le niveau de prudence

Surveiller:

- logs viewer
- logs cron
- génération des rapports
- mise à jour des indexes
- comportement des dashboards
- absence de doublons ou d'erreurs d'écriture

Pendant cette phase:

- garder `blue` disponible en secours
- ne pas supprimer l'ancienne stack trop tôt

## Procédure de rollback

Rollback simple en cas d'incident:

1. arrêter le writer `green`
2. s'assurer qu'il ne reste aucun job `green` en cours
3. réactiver `blue` avec son cron
4. revenir à l'interface `blue`

Règle impérative:

- ne jamais réactiver `blue` avant d'avoir coupé l'écriture `green`

## Commandes cibles à prévoir

Les noms exacts dépendront de la mise en œuvre finale, mais le jeu de commandes doit ressembler à ceci:

### Démarrage green en validation

```bash
docker compose -f docker-compose.green.yml up -d --build
```

### Vérification des logs green

```bash
docker logs -f analyse-actualites-green
```

### Bascule writer vers green

```bash
docker compose stop analyse-actualites
docker compose -f docker-compose.green.yml up -d
```

### Rollback vers blue

```bash
docker compose -f docker-compose.green.yml stop analyse-actualites-green
docker compose up -d analyse-actualites
```

Ces commandes sont volontairement schématiques. Elles devront être figées une fois les fichiers Docker ajustés.

## Risques principaux

### Risque 1 — double écriture

Cause:

- `blue` et `green` écrivent en même temps dans les mêmes volumes

Prévention:

- variable `ENABLE_CRON`
- procédure stricte de bascule

### Risque 2 — green écrit via l'UI pendant la validation

Cause:

- tests sur `green` avec endpoints d'écriture actifs

Prévention:

- limiter l'accès à `green`
- éviter les opérations d'édition pendant la validation
- si nécessaire, isoler les volumes ou monter certains chemins en lecture seule

### Risque 3 — micro-coupure au changement de port standard

Cause:

- absence de reverse proxy

Prévention:

- accepter temporairement le port `5051` comme nouvelle URL
- ou planifier une micro-coupure assumée si l'URL `5050` doit être conservée

## Découpage en livrables

### Livrable 1

- `entrypoint.sh` compatible `ENABLE_CRON`

### Livrable 2

- fichier `docker-compose.green.yml`

### Livrable 3

- procédure de validation green

### Livrable 4

- procédure de cutover et rollback testée

## Estimation

Pour cette version minimale:

- préparation technique: 0.5 à 1 jour
- validation et tests de bascule: 0.5 jour
- total réaliste: 1 à 1.5 jour

## Recommandation finale

Pour votre machine actuelle, la meilleure trajectoire est:

1. préparer `green` sur `5051`
2. désactiver totalement son cron
3. valider l'interface en parallèle de `blue`
4. basculer ensuite le writer
5. garder `blue` en secours

Cette approche minimise le risque, ne demande pas d'ajouter un reverse proxy, et crée une première vraie discipline blue/green sans refonte complète de l'infrastructure.
