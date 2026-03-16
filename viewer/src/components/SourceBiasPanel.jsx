/**
 * SourceBiasPanel — Tableau de biais éditoriaux et fiabilité des sources (v2)
 *
 * Nouvelles colonnes v2 : score composite, âge domaine, transparence, MBFC
 * Bouton "Actualiser fiabilité" : lance enrich_source_credibility.py via SSE
 */
import { useState, useEffect, useRef } from 'react'
import { X, RefreshCw, Eye, AlertTriangle, ShieldCheck, Terminal } from 'lucide-react'

const SENTIMENT_COLORS = {
  positif: 'bg-green-500',
  neutre:  'bg-slate-400',
  négatif: 'bg-red-500',
}

const TON_BADGE = {
  factuel:      'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  alarmiste:    'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
  promotionnel: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
  critique:     'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
  analytique:   'bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400',
}

const MBFC_BADGE = {
  'VERY HIGH':     'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300',
  'HIGH':          'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  'MOSTLY FACTUAL':'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-300',
  'MIXED':         'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300',
  'LOW':           'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300',
  'VERY LOW':      'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
}

function SentimentBar({ counts }) {
  const total = (counts?.positif || 0) + (counts?.neutre || 0) + (counts?.négatif || 0)
  if (!total) return <span className="text-xs text-slate-400">—</span>
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex h-2 w-24 rounded-full overflow-hidden">
        {['positif', 'neutre', 'négatif'].map(s => {
          const pct = ((counts[s] || 0) / total) * 100
          return pct > 0 ? (
            <div key={s} className={`${SENTIMENT_COLORS[s]} h-full`}
              style={{ width: `${pct}%` }}
              title={`${s}: ${counts[s]} (${Math.round(pct)}%)`} />
          ) : null
        })}
      </div>
      <span className="text-xs text-slate-400 tabular-nums">{total}</span>
    </div>
  )
}

function TonBadge({ distribution }) {
  if (!distribution || Object.keys(distribution).length === 0) return null
  const dominant = Object.entries(distribution).sort((a, b) => b[1] - a[1])[0]
  if (!dominant) return null
  const [ton, count] = dominant
  const cls = TON_BADGE[ton] || 'bg-slate-100 text-slate-600'
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${cls}`} title={`${ton}: ${count}`}>
      {ton}
    </span>
  )
}

function ScoreBadge({ score }) {
  if (score == null) return <span className="text-slate-400 text-xs">—</span>
  const color = score >= 80 ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
              : score >= 60 ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
              : score >= 40 ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300'
              : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold tabular-nums ${color}`}>
      {Math.round(score)}
    </span>
  )
}

function AgeBadge({ years }) {
  if (years == null) return <span className="text-slate-400 text-xs">—</span>
  const label = years >= 1 ? `${Math.floor(years)} ans` : `< 1 an`
  const alert = years < 2
  return (
    <span className={`text-xs tabular-nums ${alert ? 'text-orange-500 dark:text-orange-400 font-medium' : 'text-slate-500 dark:text-slate-400'}`}
      title={alert ? 'Domaine récent — source à vérifier' : undefined}>
      {alert && '⚠ '}{label}
    </span>
  )
}

function TransparenceDots({ score }) {
  if (score == null) return <span className="text-slate-400 text-xs">—</span>
  return (
    <span className="flex gap-0.5" title={`Transparence : ${score}/4`}>
      {[0,1,2,3].map(i => (
        <span key={i} className={`w-2 h-2 rounded-full ${i < score ? 'bg-blue-500' : 'bg-slate-200 dark:bg-slate-700'}`} />
      ))}
    </span>
  )
}

function MbfcBadge({ rating }) {
  if (!rating) return <span className="text-slate-400 text-xs">—</span>
  const cls = MBFC_BADGE[rating] || 'bg-slate-100 text-slate-600'
  const short = { 'VERY HIGH': 'Très haut', 'HIGH': 'Haut', 'MOSTLY FACTUAL': 'Factuel', 'MIXED': 'Mixte', 'LOW': 'Bas', 'VERY LOW': 'Très bas' }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium whitespace-nowrap ${cls}`} title={`MBFC : ${rating}`}>
      {short[rating] || rating}
    </span>
  )
}

// ── Mini-terminal SSE pour l'enrichissement ────────────────────────────────

function EnrichConsole({ onClose, onDone }) {
  const [lines, setLines] = useState([])
  const [done, setDone] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    const es = new EventSource('/api/sources/enrich')
    // Note: SSE depuis POST n'est pas standard — on utilise fetch avec stream
    es.close()

    fetch('/api/sources/enrich', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      .then(async r => {
        const reader = r.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (true) {
          const { done: d, value } = await reader.read()
          if (d) break
          buf += decoder.decode(value, { stream: true })
          const parts = buf.split('\n\n')
          buf = parts.pop()
          for (const part of parts) {
            const line = part.replace(/^data: /, '').trim()
            if (!line) continue
            try {
              const obj = JSON.parse(line)
              if (obj.line) setLines(prev => [...prev, obj.line])
              if (obj.done) { setDone(true); if (onDone) onDone() }
            } catch {}
          }
        }
        setDone(true)
        if (onDone) onDone()
      })
      .catch(e => { setLines(prev => [...prev, `Erreur : ${e.message}`]); setDone(true) })
  }, [])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [lines])

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl bg-slate-900 rounded-xl shadow-2xl border border-slate-700 flex flex-col overflow-hidden max-h-[70vh]">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-700">
          <Terminal size={14} className="text-green-400" />
          <span className="text-sm font-medium text-slate-200">Enrichissement crédibilité sources</span>
          {done && <span className="ml-2 text-xs text-green-400">✓ Terminé</span>}
          <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-slate-700 text-slate-400">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4 font-mono text-xs text-green-300 space-y-0.5 bg-slate-950/50">
          {lines.map((l, i) => <div key={i}>{l}</div>)}
          {!done && <div className="animate-pulse text-slate-500">▌</div>}
          <div ref={bottomRef} />
        </div>
        {done && (
          <div className="px-4 py-3 border-t border-slate-700 flex justify-end">
            <button onClick={onClose} className="px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg">
              Fermer
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Panel principal ────────────────────────────────────────────────────────

export default function SourceBiasPanel({ onClose }) {
  const [sources, setSources]       = useState([])
  const [reliability, setReliability] = useState({})
  const [loading, setLoading]       = useState(true)
  const [search, setSearch]         = useState('')
  const [sortBy, setSortBy]         = useState('article_count')
  const [minArticles, setMinArticles] = useState(1)
  const [showEnrich, setShowEnrich] = useState(false)

  const loadData = () => {
    setLoading(true)
    // Charger biais + crédibilité en parallèle
    Promise.all([
      fetch('/api/sources/bias').then(r => r.json()).catch(() => []),
      fetch('/api/sources/credibility').then(r => r.json()).catch(() => ({ sources: [] })),
    ]).then(([biasData, credData]) => {
      setSources(Array.isArray(biasData) ? biasData : [])
      // Construire index de crédibilité par nom
      const credMap = {}
      ;(credData.sources || []).forEach(s => { credMap[s.source] = s })
      setReliability(credMap)
      setLoading(false)
    })
  }

  useEffect(() => { loadData() }, [])

  // Fusionner biais + crédibilité
  const merged = sources.map(s => ({
    ...s,
    ...(reliability[s.source] || {}),
  }))

  const enriched = merged.filter(s => s.avg_score_sentiment !== null && s.avg_score_sentiment !== undefined)

  const filtered = merged
    .filter(s => s.article_count >= minArticles)
    .filter(s => !search || s.source.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sortBy === 'article_count')    return b.article_count - a.article_count
      if (sortBy === 'score_composite')  return (b.score_composite ?? b.score ?? 0) - (a.score_composite ?? a.score ?? 0)
      if (sortBy === 'avg_score_ton')    return (b.avg_score_ton || 0) - (a.avg_score_ton || 0)
      if (sortBy === 'avg_score_ton_asc') return (a.avg_score_ton || 0) - (b.avg_score_ton || 0)
      if (sortBy === 'négatif') {
        const na = (a.sentiment_counts?.négatif || 0) / Math.max(a.article_count, 1)
        const nb = (b.sentiment_counts?.négatif || 0) / Math.max(b.article_count, 1)
        return nb - na
      }
      return 0
    })

  const enrichedCount = Object.values(reliability).filter(s => s.enrichi).length
  const totalCred = Object.keys(reliability).length

  return (
    <>
    {showEnrich && (
      <EnrichConsole
        onClose={() => setShowEnrich(false)}
        onDone={() => { setTimeout(loadData, 1000) }}
      />
    )}

    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="w-full max-w-4xl glass-panel rounded-2xl shadow-2xl mt-8 border border-white/45 dark:border-white/[0.09]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2 flex-wrap">
            <Eye size={18} className="text-purple-500" />
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">Biais éditoriaux par source</h2>
            <span className="text-xs text-slate-400">{enriched.length} sources enrichies / {sources.length} total</span>
            {totalCred > 0 && (
              <span className="text-xs text-slate-400">
                · <ShieldCheck size={11} className="inline mr-0.5 text-blue-400" />
                {enrichedCount}/{totalCred} sources avec fiabilité v2
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowEnrich(true)}
              className="hidden md:flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
              title="Lancer l'enrichissement WHOIS + MBFC + transparence"
            >
              <ShieldCheck size={12} />
              Actualiser fiabilité
            </button>
            <button onClick={onClose} className="hidden md:block p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Notice */}
        {!loading && enriched.length === 0 && (
          <div className="mx-6 mt-4 p-3 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 rounded-lg text-sm flex items-center gap-2">
            <AlertTriangle size={14} />
            Aucun article enrichi avec sentiment. Lancez d'abord <code className="font-mono bg-amber-100 dark:bg-amber-900/40 px-1 rounded">scripts/enrich_sentiment.py</code>
          </div>
        )}

        {/* Controls desktop */}
        <div className="hidden md:flex flex-wrap items-center gap-3 px-6 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40">
          <input
            type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filtrer par source…"
            className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm w-48"
          />
          <div className="flex items-center gap-2 text-sm">
            <label className="text-slate-500 dark:text-slate-400">Min. articles :</label>
            <select value={minArticles} onChange={e => setMinArticles(Number(e.target.value))}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm">
              <option value="1">≥ 1</option>
              <option value="5">≥ 5</option>
              <option value="10">≥ 10</option>
            </select>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <label className="text-slate-500 dark:text-slate-400">Tri :</label>
            <select value={sortBy} onChange={e => setSortBy(e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm">
              <option value="article_count">Volume d'articles</option>
              <option value="score_composite">Score fiabilité ↓</option>
              <option value="avg_score_ton">Ton le + factuel</option>
              <option value="avg_score_ton_asc">Ton le + biaisé</option>
              <option value="négatif">Taux négatif ↓</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto pb-28 md:pb-0">
          {loading ? (
            <div className="text-center py-12 text-slate-400">
              <RefreshCw size={24} className="animate-spin mx-auto mb-3" />Chargement…
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-slate-400">Aucune source</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 dark:text-slate-400 border-b border-slate-100 dark:border-slate-700">
                  <th className="px-6 py-3 text-left font-medium">Source</th>
                  <th className="px-4 py-3 text-right font-medium">Articles</th>
                  <th className="px-4 py-3 text-center font-medium">Fiabilité</th>
                  <th className="px-4 py-3 text-center font-medium hidden lg:table-cell">Âge</th>
                  <th className="px-4 py-3 text-center font-medium hidden lg:table-cell">Transp.</th>
                  <th className="px-4 py-3 text-center font-medium hidden lg:table-cell">MBFC</th>
                  <th className="px-4 py-3 text-left font-medium">Sentiment</th>
                  <th className="px-4 py-3 text-left font-medium">Ton dominant</th>
                  <th className="px-4 py-3 text-right font-medium">Score ton</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((s, i) => (
                  <tr key={i} className="border-b border-slate-50 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors">
                    <td className="px-6 py-3 font-medium text-slate-900 dark:text-slate-100 truncate max-w-[180px]">
                      {s.source}
                      {s.enrichi && <ShieldCheck size={10} className="inline ml-1 text-blue-400 opacity-60" title="Fiabilité enrichie v2" />}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-500">{s.article_count}</td>
                    <td className="px-4 py-3 text-center">
                      <ScoreBadge score={s.score_composite ?? s.score} />
                    </td>
                    <td className="px-4 py-3 text-center hidden lg:table-cell">
                      <AgeBadge years={s.domain_age_years} />
                    </td>
                    <td className="px-4 py-3 text-center hidden lg:table-cell">
                      <TransparenceDots score={s.transparence} />
                    </td>
                    <td className="px-4 py-3 text-center hidden lg:table-cell">
                      <MbfcBadge rating={s.mbfc_rating} />
                    </td>
                    <td className="px-4 py-3"><SentimentBar counts={s.sentiment_counts} /></td>
                    <td className="px-4 py-3"><TonBadge distribution={s.ton_distribution} /></td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {s.avg_score_ton !== null && s.avg_score_ton !== undefined ? (
                        <span className={`font-medium ${s.avg_score_ton >= 4 ? 'text-green-600 dark:text-green-400' : s.avg_score_ton <= 2 ? 'text-red-600 dark:text-red-400' : 'text-slate-500'}`}>
                          {s.avg_score_ton}/5
                        </span>
                      ) : (
                        <span className="text-slate-300 dark:text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-6 py-3 text-xs text-slate-400 dark:text-slate-500 border-t border-slate-100 dark:border-slate-700 flex flex-wrap gap-4">
          <span>Score ton : 5 = très factuel · 1 = très biaisé</span>
          <span>Fiabilité : score composite (statique × 0.60 + âge × 0.15 + transp × 0.10 + MBFC × 0.15)</span>
        </div>
      </div>
    </div>

    {/* ── Toolbar mobile fixée en bas ── */}
    <div
      className="md:hidden fixed bottom-0 left-0 right-0 z-[60] bg-white/80 dark:bg-slate-800/80 backdrop-blur-xl border-t border-slate-200/60 dark:border-slate-700/60 px-4 py-3 flex items-center gap-2"
      style={{ paddingBottom: 'max(12px, env(safe-area-inset-bottom))' }}
    >
      <div className="flex flex-wrap items-center gap-2 flex-1">
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Filtrer…"
          className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs w-28"
        />
        <div className="flex items-center gap-1.5">
          <label className="text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">Tri :</label>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)}
            className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs">
            <option value="article_count">Volume</option>
            <option value="score_composite">Fiabilité</option>
            <option value="avg_score_ton">Factuel</option>
            <option value="négatif">Négatif ↓</option>
          </select>
        </div>
      </div>
      <button onClick={onClose}
        className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0">
        <X size={16} />
      </button>
    </div>
    </>
  )
}
