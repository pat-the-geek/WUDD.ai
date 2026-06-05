let mermaidPromise = null
let lastConfigKey = null

// ── Thème Mermaid « OK-ia » ───────────────────────────────────────────────────
// Palette imposée (charte OK-ia). En l'absence de classDef explicite, Mermaid
// applique son thème par défaut (fond lavande #ECECFF, bordure violette
// #9370DB) — hors charte. Ce thème `base` + themeVariables force la palette
// OK-ia sur TOUS les diagrammes, y compris pie/mindmap auto-colorés.
//
// Couleurs (fond → texte) :
//   #E8972E→#111111  #111111→#FAFAF8  #9A9A90→#111111
//   #F0A840→#111111  #FAFAF8→#111111  #5A5A52→#FAFAF8
// Bordures : #9A9A90 ou #E8972E uniquement.
export const OKIA_MERMAID = {
  theme: 'base',
  themeVariables: {
    // Nœuds principaux (flowchart, graph…)
    primaryColor: '#E8972E',
    primaryTextColor: '#111111',
    primaryBorderColor: '#9A9A90',
    secondaryColor: '#9A9A90',
    secondaryTextColor: '#111111',
    secondaryBorderColor: '#9A9A90',
    tertiaryColor: '#FAFAF8',
    tertiaryTextColor: '#111111',
    tertiaryBorderColor: '#9A9A90',
    mainBkg: '#E8972E',
    nodeBorder: '#9A9A90',
    nodeTextColor: '#111111',
    clusterBkg: '#FAFAF8',
    clusterBorder: '#9A9A90',
    // Arêtes / liens
    lineColor: '#5A5A52',
    edgeLabelBackground: '#FAFAF8',
    // Fond / texte global
    background: '#FAFAF8',
    textColor: '#111111',
    titleColor: '#111111',
    // Palette catégorielle (mindmap, etc.) — ordre charte OK-ia
    cScale0: '#E8972E', cScale1: '#111111', cScale2: '#9A9A90',
    cScale3: '#F0A840', cScale4: '#FAFAF8', cScale5: '#5A5A52',
    cScale6: '#E8972E', cScale7: '#111111', cScale8: '#9A9A90',
    cScale9: '#F0A840', cScale10: '#FAFAF8', cScale11: '#5A5A52',
    cScaleLabel0: '#111111', cScaleLabel1: '#FAFAF8', cScaleLabel2: '#111111',
    cScaleLabel3: '#111111', cScaleLabel4: '#111111', cScaleLabel5: '#FAFAF8',
    cScaleLabel6: '#111111', cScaleLabel7: '#FAFAF8', cScaleLabel8: '#111111',
    cScaleLabel9: '#111111', cScaleLabel10: '#111111', cScaleLabel11: '#FAFAF8',
    // Camemberts (pie)
    pie1: '#E8972E', pie2: '#111111', pie3: '#9A9A90',
    pie4: '#F0A840', pie5: '#FAFAF8', pie6: '#5A5A52',
    pie7: '#E8972E', pie8: '#111111', pie9: '#9A9A90',
    pie10: '#F0A840', pie11: '#FAFAF8', pie12: '#5A5A52',
    pieTitleTextColor: '#111111',
    pieSectionTextColor: '#111111',
    pieLegendTextColor: '#111111',
    pieStrokeColor: '#9A9A90',
    pieOuterStrokeColor: '#9A9A90',
  },
}

function normalizeConfig(config = {}) {
  return { startOnLoad: false, ...config }
}

export async function getMermaid(config = {}) {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then(module => module.default)
  }

  const mermaid = await mermaidPromise
  const normalized = normalizeConfig(config)
  const configKey = JSON.stringify(normalized)

  if (configKey !== lastConfigKey) {
    mermaid.initialize(normalized)
    lastConfigKey = configKey
  }

  return mermaid
}

export function preloadMermaid(config = {}) {
  return getMermaid(config).then(() => undefined)
}