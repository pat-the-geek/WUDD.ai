# DESIGN

## Palette HIG

- **Accent principal**: `--color-accent`, `--color-accent-hover`, `--color-accent-subtle`
- **Succès**: `--color-success`
- **Danger**: `--color-danger`
- **Avertissement**: `--color-warning`
- **Couleurs système**: `--color-yellow`, `--color-teal`, `--color-indigo`, `--color-purple`

`viewer/src/index.css` est la source de vérité pour les couleurs d'interface.

## Palette de marque

- `--brand-neutral-dark`: `#1a1814`
- `--brand-neutral-light`: `#f6f2ea`
- `--brand-accent-cool`: `#007AFF`
- `--brand-accent-warm`: `#a55233`
- `--brand-success`: `#3fb950`
- `--brand-danger`: `#FF3B30`

WUDD.ai utilise l'accent froid (`System Blue`) pour les interfaces d'analyse.

## Couleurs NER

Les 18 types NER sont centralisés dans `viewer/src/lib/entity-config.ts`.

- `PERSON`, `ORG`, `GPE`, `PRODUCT`, `EVENT`, `LAW`, `LOC`, `NORP`, `FAC`, `WORK_OF_ART`
- `MONEY`, `PERCENT`, `LANGUAGE`, `DATE`, `TIME`, `QUANTITY`, `CARDINAL`, `ORDINAL`

Ce fichier est la source de vérité pour les couleurs et labels entités.

## Règles

- **Violet = Obsidian**: ne pas l'utiliser comme accent général du viewer.
- **Aucune valeur hex dans JSX/TSX** hors source de vérité NER.
- **Nommer les tokens** avec `--color-{role}` pour le sémantique et `--{component}-{property}` pour les composants.

## Matériaux Liquid Glass

- `.glass-nav`
- `.glass-panel`
- `.glass-sidebar`
- `.glass-toolbar-mobile`
- `.glass-fab`
- `.glass-dark`

## Typographie et espacement

- typographie HIG dans `viewer/tailwind.config.js`
- espacement HIG: `hig-xs`, `hig-sm`, `hig-md`, `hig-lg`, `hig-xl`, `hig-2xl`

## Animations

- transitions d'accent courtes sur boutons et états actifs
- blur/verre pour les surfaces flottantes
- animations discrètes pour indicateurs d'activité et navigation mobile
