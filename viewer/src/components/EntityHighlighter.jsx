/**
 * EntityHighlighter — surligne les entités nommées dans un texte.
 *
 * Reçoit un texte brut et un dict d'entités { TYPE: [valeur, …] },
 * et retourne le texte découpé en segments colorés selon le type NER.
 */

// Réutilise la même palette que EntityPanel
const CHIP_STYLE = {
  PERSON:      { bg: 'bg-violet-100 dark:bg-violet-900/50',   text: 'text-violet-800 dark:text-violet-200',   ring: 'ring-violet-300 dark:ring-violet-700' },
  ORG:         { bg: 'bg-blue-100 dark:bg-blue-900/50',       text: 'text-blue-800 dark:text-blue-200',       ring: 'ring-blue-300 dark:ring-blue-700'   },
  GPE:         { bg: 'bg-emerald-100 dark:bg-emerald-900/50', text: 'text-emerald-800 dark:text-emerald-200', ring: 'ring-emerald-300 dark:ring-emerald-700' },
  PRODUCT:     { bg: 'bg-orange-100 dark:bg-orange-900/50',   text: 'text-orange-800 dark:text-orange-200',   ring: 'ring-orange-300 dark:ring-orange-700' },
  EVENT:       { bg: 'bg-amber-100 dark:bg-amber-900/50',     text: 'text-amber-800 dark:text-amber-200',     ring: 'ring-amber-300 dark:ring-amber-700'  },
  LAW:         { bg: 'bg-red-100 dark:bg-red-900/50',         text: 'text-red-800 dark:text-red-200',         ring: 'ring-red-300 dark:ring-red-700'     },
  LOC:         { bg: 'bg-teal-100 dark:bg-teal-900/50',       text: 'text-teal-800 dark:text-teal-200',       ring: 'ring-teal-300 dark:ring-teal-700'   },
  NORP:        { bg: 'bg-fuchsia-100 dark:bg-fuchsia-900/50', text: 'text-fuchsia-800 dark:text-fuchsia-200', ring: 'ring-fuchsia-300 dark:ring-fuchsia-700' },
  FAC:         { bg: 'bg-cyan-100 dark:bg-cyan-900/50',       text: 'text-cyan-800 dark:text-cyan-200',       ring: 'ring-cyan-300 dark:ring-cyan-700'   },
  WORK_OF_ART: { bg: 'bg-rose-100 dark:bg-rose-900/50',       text: 'text-rose-800 dark:text-rose-200',       ring: 'ring-rose-300 dark:ring-rose-700'   },
  MONEY:       { bg: 'bg-yellow-100 dark:bg-yellow-900/50',   text: 'text-yellow-800 dark:text-yellow-200',   ring: 'ring-yellow-300 dark:ring-yellow-700' },
  PERCENT:     { bg: 'bg-lime-100 dark:bg-lime-900/50',       text: 'text-lime-800 dark:text-lime-200',       ring: 'ring-lime-300 dark:ring-lime-700'   },
  LANGUAGE:    { bg: 'bg-indigo-100 dark:bg-indigo-900/50',   text: 'text-indigo-800 dark:text-indigo-200',   ring: 'ring-indigo-300 dark:ring-indigo-700' },
  DATE:        { bg: 'bg-slate-100 dark:bg-slate-700',        text: 'text-slate-700 dark:text-slate-300',     ring: 'ring-slate-300 dark:ring-slate-600' },
  TIME:        { bg: 'bg-slate-100 dark:bg-slate-700',        text: 'text-slate-700 dark:text-slate-300',     ring: 'ring-slate-300 dark:ring-slate-600' },
  QUANTITY:    { bg: 'bg-stone-100 dark:bg-stone-700/60',     text: 'text-stone-700 dark:text-stone-300',     ring: 'ring-stone-300 dark:ring-stone-600' },
  CARDINAL:    { bg: 'bg-zinc-100 dark:bg-zinc-700/60',       text: 'text-zinc-700 dark:text-zinc-300',       ring: 'ring-zinc-300 dark:ring-zinc-600'   },
  ORDINAL:     { bg: 'bg-gray-100 dark:bg-gray-700/60',       text: 'text-gray-700 dark:text-gray-300',       ring: 'ring-gray-300 dark:ring-gray-600'   },
}

const FALLBACK_STYLE = {
  bg: 'bg-slate-100 dark:bg-slate-700',
  text: 'text-slate-600 dark:text-slate-300',
  ring: 'ring-slate-200 dark:ring-slate-600',
}

/**
 * Découpe `text` en segments { text, type } selon les entités du dict.
 * Les termes les plus longs sont cherchés en premier (greedy matching).
 * La recherche est insensible à la casse.
 */
function segmentText(text, entities) {
  if (!entities || !text) return [{ text, type: null }]

  // Construire la liste (valeur, type) triée par longueur décroissante
  const terms = []
  for (const [type, values] of Object.entries(entities)) {
    if (!Array.isArray(values)) continue
    for (const value of values) {
      if (typeof value === 'string' && value.trim()) {
        terms.push({ value: value.trim(), type })
      }
    }
  }
  if (terms.length === 0) return [{ text, type: null }]

  terms.sort((a, b) => b.value.length - a.value.length)

  // Construire un regex global insensible à la casse avec les termes échappés.
  // Les lookahead/lookbehind Unicode (?<![a-zA-ZÀ-ÿ0-9]) garantissent que
  // l'entité n'est détectée que si elle forme un mot indépendant.
  // Ex : "sion" ne matche pas dans "pression" ou "commission".
  const escaped = terms.map(t => t.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const regex = new RegExp(`(?<![a-zA-ZÀ-ÿ0-9])(${escaped.join('|')})(?![a-zA-ZÀ-ÿ0-9])`, 'gi')

  // Découper le texte
  const rawParts = text.split(regex)
  const termMap = new Map(terms.map(t => [t.value.toLowerCase(), t.type]))

  return rawParts
    .filter(p => p !== '')
    .map(part => ({
      text: part,
      type: termMap.get(part.toLowerCase()) ?? null,
    }))
}

/**
 * Segments surlignés (fragment React) — utilisé en mode inline dans des <p> mixtes.
 * Pas de balise conteneur : à wrapper par l'appelant.
 */
export function EntityHighlighterSegments({ text, entities, onEntityClick }) {
  const segments = segmentText(text, entities)
  return (
    <>
      {segments.map((seg, i) => {
        if (!seg.type) return <span key={i}>{seg.text}</span>
        const style = CHIP_STYLE[seg.type] ?? FALLBACK_STYLE
        if (onEntityClick) {
          return (
            <button
              key={i}
              type="button"
              title={`${seg.type} — cliquer pour voir l'identité`}
              onClick={() => onEntityClick(seg.type, seg.text)}
              className={`rounded px-0.5 mx-px ring-1 ring-inset font-medium cursor-pointer hover:ring-2 hover:brightness-95 transition-all ${style.bg} ${style.text} ${style.ring}`}
            >
              {seg.text}
            </button>
          )
        }
        return (
          <span
            key={i}
            title={seg.type}
            className={`rounded px-0.5 mx-px ring-1 ring-inset font-medium ${style.bg} ${style.text} ${style.ring}`}
          >
            {seg.text}
          </span>
        )
      })}
    </>
  )
}

/**
 * Composant principal.
 *
 * @param {string}   text           - Texte brut à annoter (ex: article.Résumé)
 * @param {object}   entities       - Dict { TYPE: [valeur, …] }
 * @param {string}   className      - Classes supplémentaires sur le <p> conteneur
 * @param {function} onEntityClick  - Callback(type, value) appelé au clic sur une entité
 */
export default function EntityHighlighter({ text, entities, className = '', onEntityClick }) {
  return (
    <p className={`leading-7 text-slate-700 dark:text-slate-300 ${className}`}>
      <EntityHighlighterSegments text={text} entities={entities} onEntityClick={onEntityClick} />
    </p>
  )
}
