/**
 * AlertsPanel — Affiche les alertes de tendance (Feature 2)
 * Appelé via le bouton "Tendances" dans la navbar.
 */
import { useState, useEffect, useCallback } from 'react'
import { X, RefreshCw, TrendingUp, AlertTriangle, Bell } from 'lucide-react'

// Couleurs HIG : systemRed #FF3B30 / systemOrange #FF9500 / systemYellow #FFCC00
const NIVEAU_CONFIG = {
  critique: { color: 'bg-red-50 dark:bg-red-900/25 text-[#c0392b] dark:text-[#FF453A] border-red-200 dark:border-red-800',       dot: 'bg-[#FF3B30] dark:bg-[#FF453A]', label: 'Critique' },
  élevé:    { color: 'bg-orange-50 dark:bg-orange-900/25 text-[#a05000] dark:text-[#FF9F0A] border-orange-200 dark:border-orange-800', dot: 'bg-[#FF9500] dark:bg-[#FF9F0A]', label: 'Élevé' },
  modéré:   { color: 'bg-yellow-50 dark:bg-yellow-900/20 text-[#7a6000] dark:text-[#FFD60A] border-yellow-200 dark:border-yellow-800', dot: 'bg-[#FFCC00] dark:bg-[#FFD60A]', label: 'Modéré' },
}

const ENTITY_TYPE_FR = {
  PERSON: 'Personne', ORG: 'Organisation', GPE: 'Lieu/Pays',
  PRODUCT: 'Produit', EVENT: 'Événement', NORP: 'Groupe', LOC: 'Lieu',
}

export default function AlertsPanel({ onClose, onEntitySearch }) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [threshold, setThreshold] = useState('2.0')
  const [filterNiveau, setFilterNiveau] = useState('all')

  const loadAlerts = useCallback(() => {
    setLoading(true)
    setError(null)
    const url = filterNiveau !== 'all' ? `/api/alerts?niveau=${encodeURIComponent(filterNiveau)}` : '/api/alerts'
    fetch(url)
      .then(r => r.json())
      .then(data => { setAlerts(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [filterNiveau])

  useEffect(() => { loadAlerts() }, [loadAlerts])

  const runDetector = async () => {
    setRunning(true)
    setError(null)
    try {
      const r = await fetch('/api/alerts/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ threshold: parseFloat(threshold), top: 20 }),
      })
      const data = await r.json()
      if (data.alerts) setAlerts(data.alerts)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const filtered = filterNiveau === 'all' ? alerts : alerts.filter(a => a.niveau === filterNiveau)

  return (
    <>
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="w-full max-w-2xl glass-panel rounded-2xl shadow-2xl mt-8 border border-white/45 dark:border-white/[0.09]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <TrendingUp size={18} className="text-orange-500" />
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">Tendances &amp; Alertes</h2>
            {alerts.length > 0 && (
              <span className="px-2 py-1 bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 text-xs rounded-full font-medium">
                {alerts.length}
              </span>
            )}
          </div>
          <button onClick={onClose} className="hidden md:block p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Controls (masqués sur mobile) */}
        <div className="hidden md:flex flex-wrap items-center gap-3 px-6 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40">
          <div className="flex items-center gap-2 text-sm">
            <label className="text-slate-500 dark:text-slate-400">Seuil :</label>
            <select
              value={threshold}
              onChange={e => setThreshold(e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm"
            >
              <option value="1.5">×1.5 (sensible)</option>
              <option value="2.0">×2.0 (normal)</option>
              <option value="3.0">×3.0 (strict)</option>
              <option value="5.0">×5.0 (critique seulement)</option>
            </select>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <label className="text-slate-500 dark:text-slate-400">Filtre :</label>
            <select
              value={filterNiveau}
              onChange={e => setFilterNiveau(e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm"
            >
              <option value="all">Tous</option>
              <option value="critique">Critique</option>
              <option value="élevé">Élevé</option>
              <option value="modéré">Modéré</option>
            </select>
          </div>
          <div className="flex-1" />
          <button
            onClick={runDetector}
            disabled={running}
            className="flex items-center gap-2 px-3 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            <RefreshCw size={13} className={running ? 'animate-spin' : ''} />
            {running ? 'Analyse…' : 'Lancer l\'analyse'}
          </button>
        </div>

        {/* Content */}
        <div className="p-6 pb-28 md:pb-6">
          {error && (
            <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm flex items-center gap-2">
              <AlertTriangle size={14} />
              {error}
            </div>
          )}

          {loading ? (
            <div className="text-center py-12 text-slate-400 dark:text-slate-500">
              <RefreshCw size={24} className="animate-spin mx-auto mb-3" />
              Chargement…
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-slate-400 dark:text-slate-500">
              <Bell size={32} className="mx-auto mb-3 opacity-40" />
              <p className="font-medium mb-1">Aucune alerte</p>
              <p className="text-sm">Lancez l'analyse pour détecter les tendances</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((alert, i) => {
                const cfg = NIVEAU_CONFIG[alert.niveau] || NIVEAU_CONFIG.modéré
                const typeLabel = ENTITY_TYPE_FR[alert.entity_type] || alert.entity_type
                return (
                  <div
                    key={i}
                    className={`flex items-center gap-4 p-4 rounded-xl border ${cfg.color} cursor-pointer hover:opacity-90 transition-opacity`}
                    onClick={() => onEntitySearch && onEntitySearch(alert.entity_value, alert.entity_type)}
                    title="Cliquez pour rechercher cet entité"
                  >
                    <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold">{alert.entity_value}</span>
                        <span className="text-xs opacity-70">{typeLabel}</span>
                        <span className={`text-xs px-2 py-0.5 rounded font-medium border ${cfg.color}`}>
                          {cfg.label}
                        </span>
                      </div>
                      <div className="text-xs opacity-70 mt-0.5">
                        {alert.count_24h} mentions/24h · {alert.count_7j} /7j · ratio ×{alert.ratio}
                      </div>
                    </div>
                    <TrendingUp size={16} className="shrink-0 opacity-60" />
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {alerts.length > 0 && (
          <div className="px-6 pb-4 text-xs text-slate-400 dark:text-slate-500">
            Mise à jour : {alerts[0]?.detected_at ? new Date(alerts[0].detected_at).toLocaleString('fr-FR') : 'inconnue'}
          </div>
        )}
      </div>
    </div>

    {/* ── Toolbar mobile fixée en bas ── */}
    <div
      className="md:hidden fixed bottom-0 left-0 right-0 z-[60] bg-white/80 dark:bg-slate-800/80 backdrop-blur-xl border-t border-slate-200/60 dark:border-slate-700/60 px-4 py-3 flex items-center gap-2"
      style={{ paddingBottom: 'max(12px, env(safe-area-inset-bottom))' }}
    >
      <div className="flex flex-wrap items-center gap-2 flex-1">
        <div className="flex items-center gap-2 text-sm">
          <label className="text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">Seuil :</label>
          <select
            value={threshold}
            onChange={e => setThreshold(e.target.value)}
            className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs"
          >
            <option value="1.5">×1.5 (sensible)</option>
            <option value="2.0">×2.0 (normal)</option>
            <option value="3.0">×3.0 (strict)</option>
            <option value="5.0">×5.0 (critique)</option>
          </select>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">Filtre :</label>
          <select
            value={filterNiveau}
            onChange={e => setFilterNiveau(e.target.value)}
            className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs"
          >
            <option value="all">Tous</option>
            <option value="critique">Critique</option>
            <option value="élevé">Élevé</option>
            <option value="modéré">Modéré</option>
          </select>
        </div>
        <button
          onClick={runDetector}
          disabled={running}
          className="flex items-center gap-2 px-3 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-xs rounded-lg transition-colors"
        >
          <RefreshCw size={12} className={running ? 'animate-spin' : ''} />
          {running ? 'Analyse…' : 'Lancer'}
        </button>
      </div>
      <button onClick={onClose}
        className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0">
        <X size={16} />
      </button>
    </div>
    </>
  )
}
