import { useState, useEffect } from 'react'
import { X, Layers, RefreshCw, ChevronDown, ChevronRight, Tag, Hash } from 'lucide-react'

const THEME_COLORS = {
  'Intelligence artificielle': 'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-700',
  'Géopolitique':             'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-red-200 dark:border-red-700',
  'Économie':                 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-700',
  'Technologie':              'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-700',
  'Santé':                    'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700',
  'Environnement':            'bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-700',
  'Politique française':      'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-700',
  'Sports':                   'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-700',
  'Autre':                    'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
}

const SENTIMENT_COLORS = {
  positif: 'text-[#1a7a34] dark:text-[#30D158]',
  neutre:  'text-slate-500 dark:text-slate-400',
  négatif: 'text-red-500 dark:text-red-400',
}

function ClusterCard({ cluster }) {
  const [open, setOpen] = useState(false)
  const colorClass = THEME_COLORS[cluster.theme] || THEME_COLORS['Autre']

  return (
    <div className={`rounded-xl border ${colorClass} overflow-hidden`}>
      {/* En-tête du cluster */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:opacity-80 transition-opacity"
        onClick={() => setOpen(o => !o)}
      >
        <span className="flex-1 font-semibold text-sm">{cluster.theme}</span>
        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-white/50 dark:bg-black/20">
          {cluster.count} article{cluster.count > 1 ? 's' : ''}
        </span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {open && (
        <div className="border-t border-current/10 bg-white/60 dark:bg-black/20">
          {/* Top entités */}
          {cluster.top_entities?.length > 0 && (
            <div className="px-4 py-2 flex flex-wrap gap-1.5 border-b border-current/10">
              {cluster.top_entities.slice(0, 8).map(e => (
                <span
                  key={e.value}
                  className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-full bg-white/70 dark:bg-black/30 font-medium"
                >
                  <Hash size={8} />
                  {e.value}
                  <span className="opacity-60">×{e.count}</span>
                </span>
              ))}
            </div>
          )}

          {/* Liste d'articles */}
          <ul className="divide-y divide-current/10">
            {cluster.articles.map((art, i) => (
              <li key={i} className="px-4 py-2.5 flex flex-col gap-0.5">
                <div className="flex items-start gap-2">
                  <span className="text-[11px] text-current/50 shrink-0 mt-0.5 tabular-nums">
                    {art['Date de publication']
                      ? parseArticleDate(art['Date de publication']).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })
                      : '—'}
                  </span>
                  <div className="flex-1 min-w-0">
                    {art.URL ? (
                      <a
                        href={art.URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-medium hover:underline line-clamp-2 leading-snug"
                      >
                        {art['Résumé']?.split('\n')[0] || art.URL}
                      </a>
                    ) : (
                      <p className="text-xs font-medium line-clamp-2 leading-snug">
                        {art['Résumé']?.split('\n')[0] || '—'}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-0.5">
                      {art.Sources && (
                        <span className="text-[11px] opacity-60">{art.Sources}</span>
                      )}
                      {art.sentiment && (
                        <span className={`text-[11px] font-medium ${SENTIMENT_COLORS[art.sentiment] || ''}`}>
                          {art.sentiment}
                        </span>
                      )}
                      {art.score_pertinence != null && (
                        <span className="text-[11px] opacity-50">⭐ {art.score_pertinence}</span>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function ClusterView({ onClose }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [days, setDays]       = useState(7)
  const [minSize, setMinSize] = useState(2)

  const load = () => {
    setLoading(true)
    setError(null)
    fetch(`/api/analytics/clusters?days=${days}&min_size=${minSize}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  useEffect(() => { load() }, [days, minSize])

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-panel w-full max-w-2xl max-h-[88vh] flex flex-col rounded-2xl shadow-2xl border border-white/45 dark:border-white/[0.09] overflow-hidden">

        {/* En-tête */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <Layers size={15} className="text-violet-500" />
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200 flex-1">
            Clusters thématiques
            {data && (
              <span className="ml-2 text-xs font-normal text-slate-400">
                {data.clusters?.length} clusters · {data.total_articles} articles
              </span>
            )}
          </h2>
          <button onClick={load} title="Actualiser"
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Contrôles */}
        <div className="px-5 py-2.5 border-b border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-800/30 shrink-0 flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <Tag size={11} />
            <label>Fenêtre</label>
            <select
              value={days}
              onChange={e => setDays(Number(e.target.value))}
              className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-1.5 py-1 focus:outline-none focus:border-blue-400"
            >
              {[1, 3, 7, 14, 30].map(d => (
                <option key={d} value={d}>{d} jour{d > 1 ? 's' : ''}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <label>Taille min.</label>
            <select
              value={minSize}
              onChange={e => setMinSize(Number(e.target.value))}
              className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-1.5 py-1 focus:outline-none focus:border-blue-400"
            >
              {[1, 2, 3, 5].map(n => (
                <option key={n} value={n}>{n} article{n > 1 ? 's' : ''}</option>
              ))}
            </select>
          </div>
          {data?.generated_at && (
            <span className="ml-auto text-[11px] text-slate-400">
              Calculé {new Date(data.generated_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>

        {/* Contenu */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading && (
            <div className="flex items-center justify-center h-40 gap-2 text-slate-400 text-sm">
              <div className="w-4 h-4 border-2 border-slate-300 border-t-violet-500 rounded-full animate-spin" />
              Clustering en cours…
            </div>
          )}
          {!loading && error && (
            <div className="flex items-center justify-center h-40 text-red-500 text-sm">{error}</div>
          )}
          {!loading && !error && data?.clusters?.length === 0 && (
            <div className="flex flex-col items-center justify-center h-40 text-slate-400 text-sm gap-2">
              <Layers size={28} strokeWidth={1} />
              <span>Aucun cluster trouvé pour cette fenêtre</span>
            </div>
          )}
          {!loading && !error && data?.clusters?.map(c => (
            <ClusterCard key={c.theme} cluster={c} />
          ))}
        </div>
      </div>
    </div>
  )
}
