# Rapport dépendances et frameworks — 2026-04-21

## Objectif

Ce rapport dresse un état des lieux des librairies et frameworks utilisés dans WUDD.ai, compare les versions déclarées, les versions effectivement présentes dans l'environnement local, les dernières versions disponibles, puis propose un plan d'upgrade pragmatique.

Périmètre audité :

- `requirements.txt`
- `viewer/requirements.txt`
- `viewer/package.json`
- `viewer/package-lock.json`
- `Dockerfile`
- environnement local `.venv` au 2026-04-21

## Stack du projet

### Backend / traitement

- Python pour les scripts ETL, les utilitaires et le backend du viewer
- Flask pour l'API locale et le service du viewer
- requests pour les appels HTTP
- beautifulsoup4 pour le parsing HTML
- python-dotenv pour la configuration `.env`
- DuckDB pour la couche analytique optionnelle
- aiohttp pour les enrichissements asynchrones optionnels
- anthropic pour les batchs Claude optionnels
- python-whois pour l'enrichissement des sources
- pytest / pytest-cov pour les tests

### Frontend / viewer

- React 18
- Vite 6
- Tailwind CSS 3
- Mermaid 11
- Leaflet + react-leaflet pour la cartographie
- react-markdown / rehype-raw / remark-gfm pour le rendu Markdown

### Build / runtime

- Docker multi-stage
- Node.js pour la compilation du frontend
- Python slim pour l'image d'exécution

## Versions observées

### Python, backend et outillage

| Composant | Déclaré avant mise à jour | Environnement local | Dernière version | Statut |
|---|---:|---:|---:|---|
| Python local | 3.10+ | 3.14.1 | 3.14.4 | mineur disponible |
| Python Docker | 3.10-slim | n/a | 3.14.4 | écart runtime important |
| Flask | >=3.0.0 | 3.1.3 | 3.1.3 | à jour |
| requests | >=2.31.0 | 2.32.5 | 2.33.1 | upgrade mineur utile |
| beautifulsoup4 | >=4.12.0 | 4.14.3 | 4.14.3 | à jour |
| python-dotenv | >=1.0.0 | 1.2.1 | 1.2.2 | upgrade mineur utile |
| urllib3 | >=2.0.0 | 2.6.3 | 2.6.3 | à jour |
| python-whois | >=0.9.0 | absent | 0.9.6 | fonctionnalité locale incomplète |
| duckdb | >=0.10.0 | 1.5.2 | 1.5.2 | minimum obsolète |
| aiohttp | >=3.9.0 | absent | 3.13.5 | optimisation inactive localement |
| anthropic | >=0.40.0 | absent | 0.96.0 | batch Claude inactif localement |
| openpyxl | >=3.1.0 | absent | 3.1.5 | export Excel dégradé |
| pytest | >=7.4.0 | 9.0.2 | 9.0.3 | upgrade mineur utile |
| pytest-cov | >=4.1.0 | absent | 7.1.0 | outillage local incomplet |

### Frontend

| Composant | Déclaré | Lockfile | Dernière version | Statut |
|---|---:|---:|---:|---|
| React | ^19.2.5 | 19.2.5 | 19.2.5 | à jour |
| react-dom | ^19.2.5 | 19.2.5 | 19.2.5 | à jour |
| Vite | ^8.0.9 | 8.0.9 | 8.0.9 | à jour |
| @vitejs/plugin-react | ^6.0.1 | 6.0.1 | 6.0.1 | à jour |
| Tailwind CSS | ^3.4.19 | 3.4.19 | 4.2.3 | upgrade majeur avec impact config |
| Mermaid | ^11.14.0 | 11.14.0 | 11.14.0 | à jour dans la major |
| Leaflet | ^1.9.4 | 1.9.4 | 1.9.4 | à jour |
| react-leaflet | ^5.0.0 | 5.0.0 | 5.0.0 | à jour |
| react-markdown | ^9.1.0 | 9.1.0 | 10.1.0 | upgrade majeur modéré |
| rehype-raw | ^7.0.0 | 7.0.0 | 7.0.0 | à jour |
| remark-gfm | ^4.0.1 | 4.0.1 | 4.0.1 | à jour dans la major |
| lucide-react | ^0.469.0 | 0.469.0 | 1.8.0 | upgrade majeur possible |
| postcss | ^8.5.10 | 8.5.10 | 8.5.10 | à jour dans la major |
| autoprefixer | ^10.5.0 | 10.5.0 | 10.5.0 | à jour dans la major |

### Runtimes de build

| Runtime | Version utilisée | Dernière version pertinente | Statut |
|---|---:|---:|---|
| Node.js build Docker | 20 | 24 LTS / 25 current | Node 20 est hors support |
| Python runtime Docker | 3.10 | 3.14.4 stable | 3.10 encore supporté jusqu'à 2026-10, mais en retrait |

## Opportunités d'upgrade

### Priorité haute

1. Aligner les runtimes Docker sur des versions supportées et cohérentes avec le poste de dev.
2. Mettre à niveau les dépendances Python minimales pour refléter l'état réellement attendu du projet.
3. Installer par défaut les dépendances optionnelles déjà exploitées par le code : `aiohttp`, `anthropic`, `python-whois`, `openpyxl`, `pytest-cov`.

### Priorité moyenne

1. Mettre à jour les dépendances Python mineures à faible risque : `requests`, `python-dotenv`, `pytest`.
2. Monter légèrement le niveau de vérité des manifests pour éviter les installations partielles ou trop anciennes.
3. Mettre à jour quelques dépendances frontend non disruptives lors d'un prochain passage npm ciblé : `mermaid`, `postcss`, `autoprefixer`.

### Priorité plus lourde

1. Migrer Tailwind 3 vers 4.
2. Mettre à jour `react-markdown` 9 vers 10.
3. Évaluer le passage de `lucide-react` 0.x vers 1.x.

## Plan d'upgrade recommandé par lots

### Lot A — Plateforme et cohérence environnementale

Objectif : réduire le risque d'écart entre développement et production.

- Docker Node `20` → `24 LTS`
- Docker Python `3.10` → `3.14`
- rehausse des minimums Python critiques dans `requirements.txt`
- maintien des grandes migrations frontend pour plus tard

Risque : faible à modéré.

### Lot B — Dépendances Python réellement utilisées

Objectif : éviter les fonctionnalités silencieusement dégradées.

- `aiohttp` pour activer `utils/async_enricher.py`
- `anthropic` pour activer les batchs Claude
- `python-whois` pour l'enrichissement de crédibilité
- `openpyxl` pour l'export Excel du viewer
- `pytest-cov` pour l'outillage de test complet

Risque : faible.

### Lot C — Frontend mineur non disruptif

Objectif : moderniser sans chantier de migration.

- `mermaid`
- `postcss`
- `autoprefixer`
- éventuellement normaliser les plages `package.json` sur les versions déjà verrouillées

Risque : faible à modéré selon le lockfile.

Statut au 2026-04-21 : réalisé et validé.

- `mermaid` → `^11.14.0`
- `react-markdown` → `^9.1.0`
- `remark-gfm` → `^4.0.1`
- `@vitejs/plugin-react` → `^4.7.0`
- `autoprefixer` → `^10.5.0`
- `postcss` → `^8.5.10`
- `tailwindcss` → `^3.4.19`
- `vite` → `^6.4.2`

### Lot D — Frontend majeur restant

Objectif : préparer la prochaine étape de modernisation UI.

- Tailwind 4
- `react-markdown` 10
- éventuellement `lucide-react` 1

Risque : modéré à élevé. À traiter sur branche dédiée avec validation UI complète.

Statut au 2026-04-21 : partiellement réalisé.

- `react` → `^19.2.5`
- `react-dom` → `^19.2.5`
- `react-leaflet` → `^5.0.0`
- `vite` → `^8.0.9`
- `@vitejs/plugin-react` → `^6.0.1`
- build production validé sous Node 24 sans retouche de code applicatif

## Contraintes techniques vérifiées pour le lot majeur

Les contraintes suivantes ont été vérifiées dans un environnement Node 24 :

1. `react-leaflet@5` déclare un peer strict sur `react@^19` et `react-dom@^19`.
2. `@vitejs/plugin-react@6` déclare un peer sur `vite@^8`.
3. `tailwindcss@4` ne relève pas d'un simple bump de version : la chaîne PostCSS et une partie de la configuration doivent être revues.
4. Le point local le plus fragile côté application n'est pas React lui-même, mais la combinaison cartographie + styles utilitaires + build.

## Lecture des risques par composant

### React 19

État actuel : migré et validé au build.

- Le point d'entrée utilise déjà `createRoot()` et `StrictMode` dans `viewer/src/main.jsx`.
- Aucun usage critique détecté d'API legacy React retirées ou notoirement instables.
- Les patterns récents déjà présents dans le code (`useDeferredValue`, `startTransition`, `lazy`, `Suspense`) réduisent le risque de migration brute.

Conclusion : la migration React 18 → 19 a été absorbée sans changement de code visible dans ce dépôt.

### react-leaflet 5

État actuel : migré avec React 19, build validé.

- Utilisation réelle détectée dans `viewer/src/components/EntityWorldMap.jsx`.
- Utilisation réelle détectée dans `viewer/src/components/TopArticlesPanel.jsx`.
- La recette devra couvrir au minimum : rendu initial de carte, tooltips, `flyTo`, `fitBounds`, overlays et markers.

Conclusion : la contrainte de peer a bien été levée par la migration conjointe avec React 19.

### Vite 8 + `@vitejs/plugin-react` 6

État actuel : migré et validé au build.

- Le projet est déjà sur Vite 6 moderne, avec config ESM propre.
- La configuration custom la plus sensible est `manualChunks()` dans `viewer/vite.config.js`.
- Le vrai point à revalider sera la stabilité du graphe de chunks, pas le démarrage de dev server.

Conclusion : la migration Vite 8 a été absorbée sans modification de `viewer/vite.config.js`.

### Tailwind 4

État actuel : c'est le vrai lot lourd.

- Le projet repose sur `viewer/tailwind.config.js` avec `content`, `darkMode`, `safelist` riche et `theme.extend` conséquent.
- La chaîne PostCSS actuelle dans `viewer/postcss.config.js` est encore au modèle Tailwind 3.
- Une part importante de la sécurité visuelle repose sur la `safelist` des classes NER ; c'est un point critique à préserver pendant la migration.

Conclusion : Tailwind 4 doit rester le dernier sous-lot du chantier majeur frontend.

## Séquencement recommandé pour le prochain chantier

Ordre recommandé :

1. Vite 8 + `@vitejs/plugin-react` 6.
2. Tailwind 4 en dernier, sur un lot séparé si possible.
3. `react-markdown` 10 sur un sous-lot dédié si l'on veut poursuivre la modernisation du rendu Markdown.

## Recette ciblée cartes après React 19 + react-leaflet 5

Contrôles effectués :

1. build production OK sous Node 24 après migration React 19, react-leaflet 5 et Vite 8 ;
2. absence d'erreurs statiques sur `viewer/src/components/EntityWorldMap.jsx` ;
3. absence d'erreurs statiques sur `viewer/src/components/TopArticlesPanel.jsx` ;
4. vérification des usages critiques conservés : `MapContainer`, `TileLayer`, `Marker`, `CircleMarker`, `GeoJSON`, `useMap`, `flyTo`, `flyToBounds`, `fitBounds`.

Limite de recette :

- la page du viewer a bien été rouverte localement, mais sans outillage navigateur agentique activé il n'a pas été possible de cliquer automatiquement dans les vues carte pour valider visuellement les interactions.

## Pré-checks à exécuter avant de lancer le lot majeur

1. Garder Node 24 minimum pour toute validation frontend ; Node 11 local n'est pas exploitable pour ce chantier.
2. Vérifier manuellement les cartes de `TopArticlesPanel` et `EntityWorldMap` après migration React 19.
3. Comparer précisément le graphe de chunks avant/après migration Vite 8.
4. Préparer une recette visuelle dédiée pour les classes NER et le mode sombre avant de toucher à Tailwind 4.

## Changements appliqués dans ce dépôt

Les changements suivants ont été appliqués dans le cadre du lot sûr et limité :

1. Rehausse des minimums Python dans `requirements.txt` vers des versions courantes et supportées.
2. Rehausse des minimums Flask et openpyxl dans `viewer/requirements.txt`.
3. Mise à jour des images Docker vers `node:24-slim` et `python:3.14-slim`.
4. Mise à jour des dépendances frontend mineures dans `viewer/package.json`.
5. Régénération de `viewer/package-lock.json` avec Node 24.
6. Validation du build frontend sous Node 24.
7. Validation des tests Python en local et dans le conteneur.

Ce qui n'a pas été modifié volontairement :

1. Pas de migration React 19 / Vite 8 / Tailwind 4.
2. Pas de migration `react-leaflet` 4 → 5.
3. Pas de changement fonctionnel dans le code applicatif.

## Risques et points de vigilance

1. Le poste local reste en Node 11.9.0, donc les validations frontend locales directes ne sont pas représentatives tant que ce runtime n'est pas relevé.
2. Le build frontend passe sous Node 24, mais conserve un warning de chunks volumineux sur `mermaid-bundle` et `index`.
3. Les 2 vulnérabilités npm initialement restantes ont été corrigées sans changement de major déclaré, via mise à jour transitive du lockfile.
4. Les dépendances optionnelles devenues minimales dans le manifest augmentent légèrement le coût d'installation, mais réduisent fortement les états dégradés non visibles.

## Recommandation finale

La meilleure séquence est la suivante :

1. valider immédiatement le lot plateforme déjà appliqué ;
2. installer les dépendances Python manquantes dans le venv local ;
3. lancer les tests et le build viewer ;
4. ouvrir ensuite un chantier séparé pour les upgrades frontend majeurs.

## Validation exécutée

Contrôles réalisés dans ce lot :

1. installation des dépendances Python locales : OK ;
2. `pytest tests/ -q` dans le venv local : `1104 passed, 1 skipped` ;
3. build Docker complet : OK ;
4. `docker run --rm --entrypoint python3 wudd-ai-upgrade-check --version` : `Python 3.14.4` ;
5. `docker run --rm -e URL=https://example.invalid -e bearer=test-token --entrypoint pytest wudd-ai-upgrade-check tests/ -q` : `1104 passed, 1 skipped` ;
6. `docker run --rm -v "$PWD/viewer:/work" -w /work node:24-slim npm run build` : OK avec warning de chunks > 500 kB ;
7. `docker run --rm -v "$PWD/viewer:/work" -w /work node:24-slim npm audit --json` : `0` vulnérabilité.

## Correctifs de sécurité frontend

Les 2 vulnérabilités npm restantes étaient :

1. `dompurify` via `mermaid` ;
2. `picomatch` via `tailwindcss` et `vite`.

Elles ont été corrigées sans changement de major dans `viewer/package.json`.

Le correctif a été obtenu par mise à jour du lockfile seulement :

- `dompurify` : `3.3.1` → `3.4.0`
- `picomatch` : `2.3.1` → `2.3.2`
- `picomatch` : `4.0.3` → `4.0.4`

Conclusion : oui, ces vulnérabilités étaient corrigeables sans changement de major déclaré.
