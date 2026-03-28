import { useEffect, useState } from 'react'
import { X, ExternalLink, FileText, Loader2, Tag } from 'lucide-react'
import GraphArticlePanel from './GraphArticlePanel'

/**
 * EntitySearchModal — recherche cross-fichiers pour une entité nommée.
 *
 * Props:
 *   query        {string}   — valeur de l'entité (ex: "OpenAI")
 *   entityType   {string}   — type NER (ex: "ORG"), optionnel
 *   onClose      {fn}       — fermeture du modal
 *   onSelectFile {fn(file)} — appelé quand l'utilisateur clique sur un fichier
 */

function parseArticleDate(raw) {
  if (!raw) return new Date(NaN)
  const m = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (m) return new Date(parseInt(m[3]), parseInt(m[2]) - 1, parseInt(m[1]))
  return new Date(raw)
}

function formatDate(raw) {
  if (!raw) return ''
  try {
    return parseArticleDate(raw).toLocaleDateString('fr-FR', {
      day: '2-digit', month: 'short', year: 'numeric',
    })
  } catch { return raw }
}

function HighlightedExcerpt({ text, query }) {
  if (!query || !text) return <span>{text}</span>
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase()
          ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700/50 text-yellow-900 dark:text-yellow-100 rounded px-0.5 not-italic font-medium">{part}</mark>
          : <span key={i}>{part}</span>
      )}
    </>
  )
}

export default function EntitySearchModal({ query, entityType, onClose, onSelectFile }) {
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [reportItem, setReportItem] = useState(null)

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams({ q: query })
    if (entityType) params.set('type', entityType)
    fetch(`/api/search/entity?${params}`)
      .then(r => r.json())
      .then(data => { setResults(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [query, entityType])

  // Grouper par fichier
  const byFile = {}
  for (const r of results) {
    if (!byFile[r.path]) byFile[r.path] = { name: r.name, path: r.path, items: [] }
    byFile[r.path].items.push(r)
  }
  const files = Object.values(byFile)

  // Fermeture clavier
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
  <>
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-panel rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col border border-white/45 dark:border-white/[0.09] overflow-hidden">

        {/* ── En-tête ── */}
        <div className="flex items-start gap-3 px-5 py-4 border-b border-slate-200/50 dark:border-slate-700/50 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0">
          <Tag size={15} className="text-violet-500 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-slate-800 dark:text-slate-100">
                Occurrences de
              </span>
              <code className="bg-violet-100 dark:bg-violet-900/50 text-violet-800 dark:text-violet-200 px-2 py-0.5 rounded-full text-sm font-mono">
                {query}
              </code>
              {entityType && (
                <span className="text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 rounded-full border border-slate-200 dark:border-slate-600">
                  {entityType}
                </span>
              )}
            </div>
            {!loading && (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {results.length} article{results.length !== 1 ? 's' : ''} dans {files.length} fichier{files.length !== 1 ? 's' : ''}
                {results.length === 100 && <span className="ml-1 text-amber-500">(limite 100)</span>}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* ── Corps ── */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-14 gap-2 text-slate-400 dark:text-slate-500">
              <Loader2 size={18} className="animate-spin" />
              <span className="text-sm">Recherche en cours…</span>
            </div>
          ) : results.length === 0 ? (
            <div className="text-center py-14 text-slate-400 dark:text-slate-500 text-sm">
              <div className="text-3xl mb-2">🔍</div>
              Aucun article ne contient «{query}»
            </div>
          ) : (
            <div className="p-4 space-y-5">
              {files.map(file => (
                <div key={file.path}>
                  {/* En-tête du fichier */}
                  <div className="flex items-center gap-2 mb-2.5">
                    <FileText size={12} className="text-slate-400 shrink-0" />
                    <button
                      onClick={() => onSelectFile({ path: file.path, name: file.name, type: 'json' })}
                      className="text-xs font-medium text-[#007AFF] dark:text-[#0A84FF] hover:underline truncate text-left"
                    >
                      {file.name}
                    </button>
                    <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0 ml-auto">
                      {file.items.length} occurrence{file.items.length > 1 ? 's' : ''}
                    </span>
                  </div>

                  {/* Résultats dans ce fichier */}
                  <div className="space-y-2 ml-4">
                    {file.items.map((item, i) => (
                      <div
                        key={i}
                        className="bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700/60 rounded-lg p-3 cursor-pointer hover:border-[#007AFF]/40 dark:hover:border-[#0A84FF]/40 hover:shadow-sm transition-all"
                        onClick={() => setReportItem(item)}
                      >
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                            {item.source || '—'}
                          </span>
                          {item.date && (
                            <span className="text-xs text-slate-400 dark:text-slate-500">
                              {formatDate(item.date)}
                            </span>
                          )}
                          <div className="flex gap-1 flex-wrap">
                            {item.types.map(t => (
                              <span
                                key={t}
                                className="text-[11px] text-[#5856D6] dark:text-[#5E5CE6] bg-violet-50 dark:bg-violet-900/30 px-1 py-0.5 rounded-full border border-violet-200 dark:border-violet-800"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                          {item.url && (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="ml-auto shrink-0 text-slate-300 dark:text-slate-600 hover:text-[#007AFF] dark:hover:text-[#0A84FF] transition-colors"
                              title="Ouvrir l'article"
                              onClick={e => { e.stopPropagation(); e.preventDefault(); window.open(item.url, '_blank', 'noopener,noreferrer') }}
                            >
                              <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                        <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed italic">
                          <HighlightedExcerpt text={item.excerpt} query={query} />
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>

    {reportItem && (
      <GraphArticlePanel
        article={{ url: reportItem.url, source: reportItem.source, date: reportItem.date }}
        filePath={reportItem.path}
        onClose={() => setReportItem(null)}
      />
    )}
  </>
  )
}
