import { useMemo, useState } from 'react'
import { Tag, ChevronDown, ChevronRight, Search } from 'lucide-react'
import { getEntityConfig } from '../lib/entity-config'

/**
 * Agrège les entités de tous les articles d'un fichier JSON.
 * Retourne { [type]: [{ value, count }] } trié par fréquence décroissante.
 */
function extractEntities(jsonContent) {
  try {
    const data = JSON.parse(jsonContent)
    const articles = Array.isArray(data) ? data : [data]
    const aggregated = {}

    for (const article of articles) {
      if (!article?.entities || typeof article.entities !== 'object') continue
      for (const [type, values] of Object.entries(article.entities)) {
        if (!Array.isArray(values)) continue
        if (!aggregated[type]) aggregated[type] = new Map()
        for (const v of values) {
          if (typeof v === 'string' && v.trim()) {
            const key = v.trim()
            aggregated[type].set(key, (aggregated[type].get(key) || 0) + 1)
          }
        }
      }
    }

    const result = {}
    for (const [type, countMap] of Object.entries(aggregated)) {
      result[type] = [...countMap.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([value, count]) => ({ value, count }))
    }
    return result
  } catch {
    return {}
  }
}

function EntitySection({ type, entities, defaultOpen, onEntitySearch }) {
  const [open, setOpen] = useState(defaultOpen)
  const cfg = getEntityConfig(type)

  return (
    <div className="border border-slate-200 dark:border-slate-700/60 rounded-xl overflow-hidden">
      {/* En-tête de section */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 bg-white dark:bg-slate-800/60 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors text-left"
      >
        <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300 flex-1">
          {cfg.label || type}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-500 bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 rounded-full shrink-0">
          {entities.length}
        </span>
        {open
          ? <ChevronDown size={13} className="text-slate-400 shrink-0" />
          : <ChevronRight size={13} className="text-slate-400 shrink-0" />
        }
      </button>

      {/* Nuage de chips */}
      {open && (
        <div className="px-3.5 py-3 flex flex-wrap gap-1.5 bg-white/50 dark:bg-slate-900/40">
          {entities.map(({ value, count }) => {
            const chip = (
              <>
                {value}
                {count > 1 && (
                  <span className="opacity-55 font-semibold tabular-nums">×{count}</span>
                )}
              </>
            )

            if (onEntitySearch) {
              return (
                <button
                  key={value}
                  onClick={() => onEntitySearch(value, type)}
                  title={`Rechercher «${value}» dans tous les fichiers`}
                  className={`group inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border transition-all hover:ring-2 hover:ring-offset-1 hover:ring-[var(--color-accent-subtle)] hover:scale-105 active:scale-95 ${cfg.badge}`}
                >
                  {chip}
                  <Search size={9} className="opacity-0 group-hover:opacity-60 transition-opacity ml-0.5 shrink-0" />
                </button>
              )
            }

            return (
              <span
                key={value}
                title={count > 1 ? `Mentionné dans ${count} articles` : undefined}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${cfg.badge}`}
              >
                {chip}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

/**
 * EntityPanel — panneau des entités nommées agrégées d'un fichier JSON.
 *
 * @param {string}   content         — contenu JSON brut
 * @param {function} onEntitySearch  — appelé avec (value, type) quand on clique une entité
 *                                     Si absent, les chips sont non-cliquables.
 */
export default function EntityPanel({ content, onEntitySearch }) {
  const entities = useMemo(() => extractEntities(content), [content])

  const types = useMemo(
    () => Object.keys(entities).sort((a, b) => entities[b].length - entities[a].length),
    [entities],
  )

  const totalUnique = useMemo(
    () => types.reduce((sum, t) => sum + entities[t].length, 0),
    [types, entities],
  )

  if (types.length === 0) return null

  return (
    <div className="mt-6">
      {/* En-tête de section */}
      <div className="flex items-center gap-2 mb-3">
        <Tag size={14} className="text-slate-500 dark:text-slate-400" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Entités nommées
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-600 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded-full">
          {totalUnique} entités · {types.length} types
        </span>
        {onEntitySearch && (
          <span className="text-xs text-slate-400 dark:text-slate-500 italic ml-1">
            Cliquer une entité pour la chercher dans tous les fichiers
          </span>
        )}
      </div>

      {/* Sections par type (les 4 plus peuplées ouvertes par défaut) */}
      <div className="flex flex-col gap-2">
        {types.map((type, i) => (
          <EntitySection
            key={type}
            type={type}
            entities={entities[type]}
            defaultOpen={i < 4}
            onEntitySearch={onEntitySearch}
          />
        ))}
      </div>
    </div>
  )
}
