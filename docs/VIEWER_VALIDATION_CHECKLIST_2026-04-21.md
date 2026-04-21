# Checklist Validation Viewer 2026-04-21

Objectif: verifier que la deferisation des rendus Markdown et des overlays lourds ne casse pas l'UX principale du viewer.

## Preconditions

- Viewer local disponible sur `http://127.0.0.1:5050`
- Build de production valide via `npm run build`
- Ouvrir un jeu de donnees contenant au moins un article avec rapport complet, une entite avec rapport complet, et un Markdown avec bloc Mermaid

## Parcours prioritaires

### 1. Dialogue rapport article

- Ouvrir un article puis lancer le rapport complet
- Verifier que la modale s'ouvre sans ecran blanc ni delai anormal
- Pendant le streaming, verifier que le contenu apparait progressivement et que le curseur anime reste visible
- A la fin, verifier que le Markdown final remplace correctement la version streamée
- Verifier que les diagrammes Mermaid du rapport s'affichent toujours
- Verifier les actions: copier, telecharger, plein ecran, fermeture

### 2. Dialogue rapport entite

- Ouvrir une entite depuis le dashboard ou le panneau entite
- Generer le rapport complet d'entite
- Verifier que la modale s'ouvre sans erreur console visible
- Pendant le streaming, verifier que les sections Markdown s'affichent sans saut de mise en page majeur
- A la fin, verifier que les diagrammes Mermaid restent fonctionnels
- Verifier les actions: copier, export local, export Obsidian, regeneration, plein ecran, fermeture

### 3. Knowledge graph

- Ouvrir le graphe de connaissances
- Cliquer sur un article depuis le graphe
- Verifier que l'overlay article se charge correctement apres le fallback de chargement
- Cliquer sur une entite depuis le graphe
- Verifier que le panneau entite s'ouvre correctement apres le fallback de chargement
- Verifier que la navigation retour/fermeture fonctionne sans laisser d'overlay fantome

### 4. Recherche d'entites

- Ouvrir la recherche d'entites
- Lancer une recherche avec au moins un resultat article
- Ouvrir un article depuis la liste de resultats
- Verifier que l'overlay article s'affiche correctement apres le fallback de chargement
- Verifier la fermeture et la reouverture de plusieurs resultats successifs

### 5. Markdown viewer principal

- Ouvrir un fichier Markdown contenant un diagramme Mermaid
- Verifier que le diagramme apparait apres chargement et sans erreur MIME
- Ouvrir un Markdown contenant un bloc `keyword-graph`
- Verifier que le graphe de mots-cles se charge correctement
- Ouvrir un Markdown contenant un bloc `flux-chart`
- Verifier que le graphique de flux se charge correctement

## Signaux d'echec a surveiller

- Ecran blanc ou modale vide a l'ouverture
- Spinner infini sans contenu
- Markdown brut affiche au lieu du rendu attendu
- Diagramme Mermaid absent ou remplace par du texte source
- Overlay impossible a fermer ou fond bloque apres fermeture
- Regressions de focus ou de scroll dans les modales

## Constat technique utile

- `cytoscape.esm` et `cose-bilkent` proviennent des dependances transitives de Mermaid, pas d'un import direct dans `viewer/src`
- Le gros chunk `chunk-K5T4RW27` correspond majoritairement au coeur Mermaid et a ses grammaires de diagrammes
