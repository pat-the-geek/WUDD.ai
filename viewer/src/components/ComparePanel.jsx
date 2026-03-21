import { useState } from 'react'
import { X, BarChart2, RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-react'

function StatBlock({ label, value, delta, isPercent }) {
  const sign = delta > 0 ? '+' : delta < 0 ? '' : '='
  const color = delta > 0 ? 'text-green-600 dark:text-green-400'
    : delta < 0 ? 'text-red-500 dark:text-red-400'
    : 'text-slate-400'
  const Icon = delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{label}</span>
      <span className="text-xl font-bold text-slate-800 dark:text-slate-100">{value}</span>
      {delta !== null && (
        <span className={`flex items-center gap-0.5 text-xs font-medium ${color}`}>
          <Icon size={11} />
          {sign}{delta}{isPercent ? ' %' : ''}
        </span>
      )}
    </div>
  )
}

function SentimentBar({ label, sentiments }) {
  const total = Object.values(sentiments).reduce((a, b) => a + b, 0) || 1
  const COLORS = {
    positif: 'bg-green-500',
    neutre: 'bg-slate-400',
    négatif: 'bg-red-500',
  }
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{label}</span>
      <div className="flex h-4 rounded overflow-hidden gap-px">
        {Object.entries(sentiments).map(([s, c]) => (
          <div
            key={s}
            title={`${s}: ${c} articles`}
            className={`${COLORS[s] || 'bg-slate-300'}`}
            style={{ width: `${(c / total * 100).toFixed(1)}%` }}
          />
        ))}
      </div>
      <div className="flex gap-3 flex-wrap">
        {Object.entries(sentiments).map(([s, c]) => (
          <span key={s} className="text-[11px] text-slate-500 dark:text-slate-400">
            <span className={`inline-block w-2 h-2 rounded-full mr-1 ${COLORS[s] || 'bg-slate-300'}`} />
            {s} ({c})
          </span>
        ))}
      </div>
    </div>
  )
}

function TopList({ items, labelKey, countKey, title }) {
  if (!items?.length) return <span className="text-xs text-slate-400 italic">Aucune donnée</span>
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{title}</span>
      <ol className="space-y-0.5">
        {items.slice(0, 5).map((item, i) => (
          <li key={i} className="flex items-center gap-2 text-xs">
            <span className="text-slate-400 w-4 shrink-0">{i + 1}.</span>
            <span className="text-slate-700 dark:text-slate-300 truncate flex-1">{item[labelKey]}</span>
            <span className="text-slate-500 shrink-0">{item[countKey]}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function ComparePanel({ onClose }) {
  const today = new Date().toISOString().slice(0, 10)
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10)
  const twoWeeksAgo = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10)

  const [from1, setFrom1] = useState(weekAgo)
  const [to1,   setTo1]   = useState(today)
  const [from2, setFrom2] = useState(twoWeeksAgo)
  const [to2,   setTo2]   = useState(weekAgo)
  const [data, setData]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const compare = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ from1, to1, from2, to2 })
      const r = await fetch(`/api/analytics/compare?${params}`)
      const d = await r.json()
      if (d.error) { setError(d.error); return }
      setData(d)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const p1 = data?.period1
  const p2 = data?.period2
  const countDelta = p1 && p2 ? p1.count - p2.count : null

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-panel w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl shadow-2xl border border-white/45 dark:border-white/[0.09] overflow-hidden">

        {/* En-tête */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <BarChart2 size={16} className="text-blue-500" />
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200 flex-1">Comparaison temporelle</h2>
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Sélecteurs de période */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-700 shrink-0 bg-slate-50/60 dark:bg-slate-800/30">
          <div className="flex flex-wrap gap-4 items-end">
            {/* Période 1 */}
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold text-blue-600 dark:text-blue-400 uppercase tracking-wider">Période 1</span>
              <div className="flex items-center gap-2">
                <input type="date" value={from1} onChange={e => setFrom1(e.target.value)}
                  className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded px-2 py-1.5 focus:outline-none focus:border-blue-400" />
                <span className="text-xs text-slate-400">→</span>
                <input type="date" value={to1} onChange={e => setTo1(e.target.value)}
                  className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded px-2 py-1.5 focus:outline-none focus:border-blue-400" />
              </div>
            </div>

            <span className="text-slate-300 dark:text-slate-600 text-lg font-light self-end pb-1">vs</span>

            {/* Période 2 */}
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold text-purple-600 dark:text-purple-400 uppercase tracking-wider">Période 2</span>
              <div className="flex items-center gap-2">
                <input type="date" value={from2} onChange={e => setFrom2(e.target.value)}
                  className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded px-2 py-1.5 focus:outline-none focus:border-blue-400" />
                <span className="text-xs text-slate-400">→</span>
                <input type="date" value={to2} onChange={e => setTo2(e.target.value)}
                  className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded px-2 py-1.5 focus:outline-none focus:border-blue-400" />
              </div>
            </div>

            <button
              onClick={compare}
              disabled={loading}
              className="flex items-center gap-1.5 px-4 py-2 bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-60 self-end"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <BarChart2 size={12} />}
              Comparer
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </div>

        {/* Résultats */}
        <div className="flex-1 overflow-auto p-5">
          {!data && !loading && (
            <div className="flex flex-col items-center justify-center h-40 text-slate-400 dark:text-slate-500 text-sm gap-2">
              <BarChart2 size={32} strokeWidth={1} />
              <span>Sélectionnez deux périodes et cliquez sur Comparer</span>
            </div>
          )}

          {data && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Colonne Période 1 */}
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-2 pb-2 border-b border-blue-200 dark:border-blue-700/50">
                  <span className="w-3 h-3 rounded-full bg-blue-500 shrink-0" />
                  <span className="text-sm font-semibold text-blue-700 dark:text-blue-300">
                    Période 1 · {p1.from} → {p1.to}
                  </span>
                </div>
                <StatBlock label="Articles" value={p1.count} delta={countDelta} />
                {Object.keys(p1.sentiment).length > 0 && <SentimentBar label="Sentiments" sentiments={p1.sentiment} />}
                <TopList title="Top sources" items={p1.top_sources} labelKey="source" countKey="count" />
                <TopList title="Top entités" items={p1.top_entities} labelKey="value" countKey="count" />
              </div>

              {/* Colonne Période 2 */}
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-2 pb-2 border-b border-purple-200 dark:border-purple-700/50">
                  <span className="w-3 h-3 rounded-full bg-purple-500 shrink-0" />
                  <span className="text-sm font-semibold text-purple-700 dark:text-purple-300">
                    Période 2 · {p2.from} → {p2.to}
                  </span>
                </div>
                <StatBlock label="Articles" value={p2.count} delta={countDelta !== null ? -countDelta : null} />
                {Object.keys(p2.sentiment).length > 0 && <SentimentBar label="Sentiments" sentiments={p2.sentiment} />}
                <TopList title="Top sources" items={p2.top_sources} labelKey="source" countKey="count" />
                <TopList title="Top entités" items={p2.top_entities} labelKey="value" countKey="count" />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
