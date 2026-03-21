import { useState, useEffect, useCallback } from 'react'
import { X, Eye, Plus, Trash2, RefreshCw, TrendingUp, Bell } from 'lucide-react'

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

export default function EntityWatchPanel({ onClose, onOpenArticles }) {
  const [entities, setEntities] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [newType, setNewType]   = useState('PERSON')
  const [newValue, setNewValue] = useState('')
  const [saving, setSaving]     = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/watched-entities')
      .then(r => r.json())
      .then(d => { setEntities(d); setLoading(false) })
      .catch(() => { setError('Erreur de chargement'); setLoading(false) })
  }, [])

  useEffect(() => { load() }, [load])

  const addEntity = async () => {
    if (!newValue.trim()) return
    setSaving(true)
    try {
      await fetch('/api/watched-entities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: newType, value: newValue.trim() }),
      })
      setNewValue('')
      load()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const removeEntity = async (type, value) => {
    try {
      await fetch(`/api/watched-entities?type=${encodeURIComponent(type)}&value=${encodeURIComponent(value)}`, {
        method: 'DELETE',
      })
      load()
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-panel w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl shadow-2xl border border-white/45 dark:border-white/[0.09] overflow-hidden">

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
                  <th className="text-left px-4 py-2.5">Ajoutée le</th>
                  <th className="px-4 py-2.5 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {entities.sort((a, b) => (b.mentions_24h || 0) - (a.mentions_24h || 0)).map((e, i) => (
                  <tr key={i} className="border-b border-slate-200/40 dark:border-slate-700/40 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors group">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <span className={`text-[11px] font-semibold px-1.5 py-0.5 rounded ${TYPE_COLORS[e.type] || 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'}`}>
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
                      <span className="text-xs text-slate-400">
                        {e.added_at ? new Date(e.added_at).toLocaleDateString('fr-FR') : '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => removeEntity(e.type, e.value)}
                        title="Ne plus surveiller"
                        className="p-1 text-slate-300 dark:text-slate-600 hover:text-red-500 rounded opacity-0 group-hover:opacity-100 transition-all"
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
