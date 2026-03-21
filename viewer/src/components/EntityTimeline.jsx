import { useEffect, useState, useCallback } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'

// ── Config types NER (couleurs cohérentes avec EntityDashboard) ───────────────
const TYPE_CFG = {
  PERSON:  { color: '#8b5cf6', badge: 'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-800' },
  ORG:     { color: '#3b82f6', badge: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800' },
  GPE:     { color: '#10b981', badge: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800' },
  PRODUCT: { color: '#f97316', badge: 'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-800' },
  EVENT:   { color: '#f59e0b', badge: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800' },
  NORP:    { color: '#a855f7', badge: 'bg-fuchsia-100 dark:bg-fuchsia-900/40 text-fuchsia-700 dark:text-fuchsia-300 border-fuchsia-200 dark:border-fuchsia-800' },
  LOC:     { color: '#14b8a6', badge: 'bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800' },
  FAC:     { color: '#06b6d4', badge: 'bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-800' },
}
const FALLBACK_CFG = { color: '#94a3b8', badge: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' }

const DAYS_OPTIONS = [7, 14, 30, 60]
const TYPE_OPTIONS = ['Tous', 'PERSON', 'ORG', 'GPE', 'PRODUCT', 'EVENT', 'NORP', 'LOC']

// ── Sparkline SVG ─────────────────────────────────────────────────────────────
function Sparkline({ counts, max, color }) {
  const W = 84, H = 24, PAD = 2
  const usableH = H - PAD * 2
  const n = counts.length

  if (max === 0) {
    return (
      <svg width={W} height={H} className="shrink-0 opacity-20">
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke={color} strokeWidth="1" strokeDasharray="3 2" />
      </svg>
    )
  }

  const points = counts.map((v, i) => {
    const x = n === 1 ? W / 2 : (i / (n - 1)) * W
    const y = PAD + usableH - (v / max) * usableH
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  return (
    <svg width={W} height={H} className="shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.85"
      />
      {/* Point pour le dernier jour */}
      {counts.length > 1 && counts[n - 1] > 0 && (() => {
        const lastX = W
        const lastY = PAD + usableH - (counts[n - 1] / max) * usableH
        return <circle cx={lastX.toFixed(1)} cy={lastY.toFixed(1)} r="2" fill={color} opacity="0.9" />
      })()}
    </svg>
  )
}

// ── Ligne d'entité ─────────────────────────────────────────────────────────────
function EntityRow({ entry, onEntitySearch }) {
  const { type, value, total, counts, max } = entry
  const cfg = TYPE_CFG[type] ?? FALLBACK_CFG

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-100 dark:border-slate-800/60 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors group">
      {/* Type badge */}
      <span className={`shrink-0 hidden sm:inline text-[11px] font-medium px-1.5 py-0.5 rounded-full border ${cfg.badge}`}>
        {type}
      </span>
      {/* Nom cliquable */}
      <button
        className="flex-1 min-w-0 text-left text-sm font-medium text-slate-800 dark:text-slate-100 truncate hover:text-[#5856D6] dark:hover:text-[#5E5CE6] transition-colors"
        onClick={() => onEntitySearch?.(value, type)}
        title={`Rechercher «${value}» dans les articles`}
      >
        {value}
      </button>
      {/* Sparkline */}
      <Sparkline counts={counts} max={max} color={cfg.color} />
      {/* Total */}
      <span className="shrink-0 text-xs font-bold tabular-nums text-slate-500 dark:text-slate-400 w-8 text-right">
        {total}
      </span>
    </div>
  )
}

// ── Composant principal ────────────────────────────────────────────────────────
export default function EntityTimeline({ onEntitySearch }) {
  const [days, setDays] = useState(30)
  const [typeFilter, setTypeFilter] = useState('Tous')
  const [rawData, setRawData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [generatedAt, setGeneratedAt] = useState(null)

  const fetchTimeline = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ days })
    if (typeFilter !== 'Tous') params.set('type', typeFilter)
    fetch(`/api/entities/timeline?${params}`)
      .then(r => r.json())
      .then(d => {
        setRawData(d)
        setGeneratedAt(d.generated_at ?? null)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [days, typeFilter])

  useEffect(() => { fetchTimeline() }, [fetchTimeline])

  // ── Construction des lignes : séries temporelles sur les `days` derniers jours ──
  const rows = (() => {
    if (!rawData?.top_entities) return []
    const now = new Date()
    const dateKeys = Array.from({ length: days }, (_, i) => {
      const d = new Date(now)
      d.setDate(d.getDate() - (days - 1 - i))
      return d.toISOString().slice(0, 10)
    })

    const source = typeFilter === 'Tous'
      ? rawData.top_entities
      : rawData.top_entities.filter(e => e.type === typeFilter)

    return source.map(e => {
      const timeline = rawData.timeline?.[e.key] ?? {}
      const counts = dateKeys.map(k => timeline[k] ?? 0)
      const max = Math.max(...counts, 1)
      return { ...e, counts, max }
    })
  })()

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── Barre de contrôle ── */}
      <div className="flex flex-wrap items-center gap-3 mb-4 shrink-0">
        {/* Filtre jours */}
        <div className="flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden text-xs">
          {DAYS_OPTIONS.map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 font-medium transition-colors border-l border-slate-200 dark:border-slate-700 first:border-l-0 ${
                days === d
                  ? 'bg-violet-500 text-white'
                  : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              {d}j
            </button>
          ))}
        </div>

        {/* Filtre type */}
        <div className="flex flex-wrap gap-1.5">
          {TYPE_OPTIONS.map(t => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`text-[11px] px-2 py-0.5 rounded-full border font-medium transition-colors ${
                typeFilter === t
                  ? 'bg-violet-500 text-white border-violet-500'
                  : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700 hover:border-violet-300 dark:hover:border-violet-600'
              }`}
            >
              {t === 'Tous' ? 'Tous types' : t}
            </button>
          ))}
        </div>

        {/* Rafraîchir */}
        <button
          onClick={fetchTimeline}
          title="Recalculer"
          className="ml-auto p-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-400 hover:text-violet-500 hover:border-violet-300 dark:hover:border-violet-600 transition-colors"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {/* ── Contenu ── */}
      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-slate-400 dark:text-slate-500">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Calcul des séries temporelles…</span>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500 text-sm gap-2">
          <span className="text-3xl">📈</span>
          <span>Aucune donnée disponible pour cette sélection.</span>
          <span className="text-xs text-center max-w-xs">
            Lancez <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded-full">entity_timeline.py</code> ou enrichissez d'abord les entités avec <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded-full">enrich_entities.py</code>.
          </span>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto rounded-2xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/40 min-h-0">
          {/* En-tête de tableau */}
          <div className="flex items-center gap-3 px-4 py-2 bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-700/60 text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 rounded-t-2xl sticky top-0 z-10">
            <span className="hidden sm:block w-16 shrink-0">Type</span>
            <span className="flex-1">Entité</span>
            <span className="w-[84px] shrink-0">Évolution ({days}j)</span>
            <span className="w-8 text-right shrink-0">Total</span>
          </div>
          {rows.map(row => (
            <EntityRow key={row.key} entry={row} onEntitySearch={onEntitySearch} />
          ))}
        </div>
      )}

      {/* Horodatage */}
      {generatedAt && !loading && (
        <p className="mt-2 text-[11px] text-slate-400 dark:text-slate-500 text-right shrink-0">
          Calculé le {new Date(generatedAt).toLocaleString('fr-FR')}
        </p>
      )}
    </div>
  )
}
