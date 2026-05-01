import { useState, useEffect, useCallback } from 'react'
import { X, Eye, Plus, Trash2, RefreshCw, TrendingUp, Bell, BarChart2, ChevronDown, ChevronUp } from 'lucide-react'

const ENTITY_TYPE_FR = {
  PERSON: 'Personne', ORG: 'Organisation', GPE: 'Lieu/Pays',
  PRODUCT: 'Produit', EVENT: 'Événement', NORP: 'Groupe',
  LOC: 'Lieu', FAC: 'Lieu',
}

const TYPE_COLORS = {
  PERSON: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300',
  ORG: 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300',
  GPE: 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300',
  PRODUCT: 'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300',
  EVENT: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300',
}

function TrendChip({ count24h, count7d }) {
  const avg = count7d / 7
  const ratio = avg > 0 ? count24h / avg : (count24h > 0 ? 99 : 0)
  const isHot = ratio >= 2
  const isVeryHot = ratio >= 5
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-slate-500 dark:text-slate-400">{count24h}/24h</span>
      <span className="text-slate-300 dark:text-slate-600">·</span>
      <span className="text-slate-500 dark:text-slate-400">{count7d}/7j</span>
      {isHot && (
        <span className={`flex items-center gap-0.5 font-medium ${isVeryHot ? 'text-red-500' : 'text-amber-500'}`}>
          <TrendingUp size={10} /> {ratio > 99 ? 'Nouveau' : `×${ratio.toFixed(1)}`}
        </span>
      )}
    </div>
  )
}

/** Mini sparkline SVG depuis les données timeline (30 derniers jours). */
function MentionSparkline({ entityKey, timeline }) {
  if (!timeline || !entityKey) return null
  const data = timeline[entityKey] || timeline[entityKey?.split(':')[1]] || null
  if (!data) return null

  // Construire un tableau de 30 jours (date → count)
  const mentions = data.mentions || []
  if (mentions.length < 2) return null

  const sorted = [...mentions].sort((a, b) => (a.date || '').localeCompare(b.date || ''))
  const last30 = sorted.slice(-30)
  const maxVal = Math.max(...last30.map(m => m.count || 0), 1)
  const W = 80
  const H = 24
  const pts = last30.map((m, i) => {
    const x = (i / (last30.length - 1)) * W
    const y = H - ((m.count || 0) / maxVal) * H
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  return (
    <svg width={W} height={H} className="overflow-visible" title="Historique 30 jours">
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        className="text-blue-400 dark:text-blue-500"
      />
    </svg>
  )
}

/** Détail historique de mentions — graphe SVG pleine largeur + table des 10 dernières dates. */
function MentionHistoryDetail({ entityKey, timeline, entity }) {
  const data = timeline[entityKey] || timeline[entityKey?.split(':')[1]] || null
  if (!data) return <p className="text-xs text-slate-400 italic">Aucune donnée de timeline disponible.</p>

  const mentions = [...(data.mentions || [])].sort((a, b) => (a.date || '').localeCompare(b.date || ''))
  const last60 = mentions.slice(-60)
  if (last60.length < 2) return <p className="text-xs text-slate-400 italic">Historique insuffisant.</p>

  const maxVal = Math.max(...last60.map(m => m.count || 0), 1)
  const W = 400
  const H = 48
  const pts = last60.map((m, i) => {
    const x = (i / (last60.length - 1)) * W
    const y = H - ((m.count || 0) / maxVal) * H
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const fillPts = `0,${H} ${pts} ${W},${H}`

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
        Historique de mentions — {entity.value} ({last60.length} points, {last60[0]?.date?.slice(0,10)} → {last60[last60.length-1]?.date?.slice(0,10)})
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-12 overflow-visible">
        <defs>
          <linearGradient id={`grad-${entityKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <polygon points={fillPts} fill={`url(#grad-${entityKey})`} />
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
      <div className="flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
        {last60.slice(-10).reverse().map((m, i) => (
          <span key={i} className="flex items-center gap-1">
            <span>{m.date?.slice(0,10)}</span>
            <span className="font-semibold text-slate-700 dark:text-slate-300">{m.count}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

export default function EntityWatchPanel({ onClose, onOpenArticles }) {
  const [entities, setEntities] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [newType, setNewType]   = useState('PERSON')
  const [newValue, setNewValue] = useState('')
  const [saving, setSaving]     = useState(false)
  const [timeline, setTimeline] = useState({})
  const [expandedKey, setExpandedKey] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    // Timeout sécurisé : 5s pour chaque fetch
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)
    Promise.all([
      fetch('/api/watched-entities', { signal: controller.signal })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
        .catch(e => { console.error('watched-entities fetch failed:', e); return [] }),
      fetch('/api/entity-timeline', { signal: controller.signal })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
        .catch(() => ({}))
    ])
      .then(([ents, tl]) => {
        if (!Array.isArray(ents)) ents = []
        if (!tl || typeof tl !== 'object') tl = {}
        setEntities(ents)
        setTimeline(tl)
        setLoading(false)
      })
      .catch(e => {
        console.error('EntityWatchPanel.load error:', e)
        setError('Erreur de chargement (délai dépassé?)')
        setLoading(false)
      })
      .finally(() => clearTimeout(timeout))
  }, [])

  useEffect(() => { load() }, [load])

  const addEntity = async () => {
    if (!newValue.trim()) return
    setSaving(true)
    try {
      const r = await fetch('/api/watched-entities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: newType, value: newValue.trim() }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setNewValue('')
      load()  // Recharger la liste
    } catch (e) {
      setError(`Erreur : ${String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const removeEntity = async (type, value) => {
    try {
      const r = await fetch(`/api/watched-entities?type=${encodeURIComponent(type)}&value=${encodeURIComponent(value)}`, {
        method: 'DELETE',
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      load()  // Recharger la liste
    } catch (e) {
      setError(`Erreur : ${String(e)}`)
    }
  }

  return (
    <div
      className="hig-overlay-enter hig-overlay-enter fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="hig-modal-enter glass-panel w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl shadow-2xl border border-white/45 dark:border-white/[0.09] overflow-hidden">

        {/* En-tête */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <Bell size={15} className="text-blue-500" />
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200 flex-1">
            Entités surveillées
            {entities.length > 0 && (
              <span className="ml-2 text-xs font-normal text-slate-400">({entities.length})</span>
            )}
          </h2>
          <button onClick={load} title="Actualiser"
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
            <RefreshCw size={13} />
          </button>
          <button onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Formulaire d'ajout */}
        <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-800/30 shrink-0">
          <div className="flex items-center gap-2">
            <select
              value={newType}
              onChange={e => setNewType(e.target.value)}
              className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-2 focus:outline-none focus:border-blue-400 shrink-0"
            >
              {Object.entries(ENTITY_TYPE_FR).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <input
              type="text"
              value={newValue}
              onChange={e => setNewValue(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addEntity()}
              placeholder="ex: OpenAI, Macron, France…"
              className="flex-1 text-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-400"
            />
            <button
              onClick={addEntity}
              disabled={!newValue.trim() || saving}
              className="flex items-center gap-1.5 px-3 py-2 bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50 shrink-0"
            >
              <Plus size={13} /> Surveiller
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </div>

        {/* Liste */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="flex items-center justify-center h-32 gap-2 text-slate-400 text-sm">
              <div className="w-4 h-4 border-2 border-slate-300 border-t-blue-500 rounded-full animate-spin" />
              Chargement…
            </div>
          ) : entities.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-slate-400 dark:text-slate-500 text-sm gap-2">
              <Eye size={28} strokeWidth={1} />
              <span>Aucune entité surveillée — ajoutez-en une ci-dessus</span>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider border-b border-slate-200/50 dark:border-slate-700/50">
                  <th className="text-left px-5 py-2.5">Entité</th>
                  <th className="text-left px-4 py-2.5">Activité</th>
                  <th className="text-left px-4 py-2.5 w-24">
                    <span className="flex items-center gap-1"><BarChart2 size={10} /> 30j</span>
                  </th>
                  <th className="text-left px-4 py-2.5">Ajoutée le</th>
                  <th className="px-4 py-2.5 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {entities.sort((a, b) => (b.mentions_24h || 0) - (a.mentions_24h || 0)).map((e, i) => {
                  const entityKey = `${e.type}:${e.value?.toLowerCase()}`
                  const isExpanded = expandedKey === entityKey
                  return (
                    <>
                      <tr key={i} className="border-b border-slate-200/40 dark:border-slate-700/40 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors group">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2">
                            <span className={`text-[11px] font-semibold px-1.5 py-0.5 rounded-full ${TYPE_COLORS[e.type] || 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'}`}>
                              {ENTITY_TYPE_FR[e.type] || e.type}
                            </span>
                            <button
                              onClick={() => onOpenArticles?.(e.type, e.value)}
                              className="font-medium text-slate-800 dark:text-slate-200 hover:text-[#007AFF] dark:hover:text-[#0A84FF] transition-colors text-left"
                            >
                              {e.value}
                            </button>
                          </div>
                          {e.notes && <p className="text-[11px] text-slate-400 mt-0.5 ml-1">{e.notes}</p>}
                        </td>
                        <td className="px-4 py-3">
                          <TrendChip count24h={e.mentions_24h || 0} count7d={e.mentions_7d || 0} />
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setExpandedKey(isExpanded ? null : entityKey)}
                            className="flex items-center gap-1 text-slate-400 hover:text-blue-500 transition-colors"
                            title={isExpanded ? "Masquer l'historique" : "Voir l'historique"}
                          >
                            <MentionSparkline entityKey={entityKey} timeline={timeline} />
                            {isExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs text-slate-400">
                            {e.added_at ? new Date(e.added_at).toLocaleDateString('fr-FR') : '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => removeEntity(e.type, e.value)}
                            title="Ne plus surveiller"
                            className="p-1 text-slate-300 dark:text-slate-600 hover:text-red-500 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                          >
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${i}-detail`} className="bg-slate-50/70 dark:bg-slate-800/30 border-b border-slate-200/30 dark:border-slate-700/30">
                          <td colSpan={5} className="px-5 py-3">
                            <MentionHistoryDetail entityKey={entityKey} timeline={timeline} entity={e} />
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
