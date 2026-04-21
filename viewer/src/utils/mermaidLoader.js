let mermaidPromise = null
let lastConfigKey = null

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