import { useEffect, useState, useCallback, useRef, Fragment } from 'react'
import {
  X, Settings, Clock, Tag, Rss, Globe, Plus, Trash2, RefreshCw,
  CheckCircle2, HelpCircle, Calendar, Check, AlertTriangle, Save,
  Maximize2, Minimize2, ExternalLink, Database, Clipboard, BarChart2,
  ToggleLeft, ToggleRight, RotateCcw, ShieldOff,
  Sun, Moon, Monitor, Terminal, TrendingUp, Eye, Lock, EyeOff, Pencil,
  BookOpen, Network, Layers, Sparkles, Cpu,
} from 'lucide-react'
import KeywordForceGraph from './KeywordForceGraph'

// ─── Helpers partagés ────────────────────────────────────────────────────────
function formatDateTime(isoStr) {
  if (!isoStr) return null
  return new Date(isoStr).toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatRelative(isoStr) {
  if (!isoStr) return null
  const diff = new Date(isoStr) - Date.now()
  const abs = Math.abs(diff)
  const rtf = new Intl.RelativeTimeFormat('fr', { numeric: 'auto' })
  if (abs < 3_600_000)  return rtf.format(Math.round(diff / 60_000),    'minute')
  if (abs < 86_400_000) return rtf.format(Math.round(diff / 3_600_000), 'hour')
  return rtf.format(Math.round(diff / 86_400_000), 'day')
}

function Spinner() {
  return (
    <div className="flex items-center justify-center h-40 gap-3 text-slate-400 dark:text-slate-500">
      <div className="w-4 h-4 border-2 border-slate-300 dark:border-slate-600 border-t-blue-500 rounded-full animate-spin" />
      <span className="text-sm">Chargement…</span>
    </div>
  )
}

function SaveButton({ saving, saved, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={saving}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
        saved
          ? 'bg-green-700 text-green-100 border border-green-600'
          : 'bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white border border-blue-500 disabled:opacity-60'
      }`}
    >
      {saved
        ? <><Check size={12} /> Sauvegardé</>
        : saving
          ? <><RefreshCw size={12} className="animate-spin" /> Sauvegarde…</>
          : <><Save size={12} /> Sauvegarder</>
      }
    </button>
  )
}

function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div className="px-5 py-2 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-700/30 text-xs text-red-600 dark:text-red-400 flex items-center gap-2 shrink-0">
      <AlertTriangle size={12} /> {message}
    </div>
  )
}

// ─── Onglet Planification ────────────────────────────────────────────────────

function StatusBadge({ task }) {
  const nextMs = task.next_run ? new Date(task.next_run) - Date.now() : null
  const isSoon = nextMs !== null && nextMs > 0 && nextMs < 3_600_000

  if (!task.last_run) return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
      <HelpCircle size={12} /> Jamais exécuté
    </span>
  )
  if (isSoon) return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#007AFF] dark:text-[#0A84FF]">
      <span className="w-2 h-2 rounded-full bg-blue-500 dark:bg-blue-400 animate-pulse" /> Bientôt
    </span>
  )
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#1a7a34] dark:text-[#30D158]">
      <CheckCircle2 size={12} /> Actif
    </span>
  )
}

function TaskTable({ title, tasks }) {
  if (!tasks.length) return null
  return (
    <div>
      <div className="sticky top-0 bg-slate-50 dark:bg-slate-900 px-5 py-2 border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
        {title}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider border-b border-slate-200/50 dark:border-slate-700/50">
            <th className="text-left px-5 py-2.5">Tâche</th>
            <th className="text-left px-4 py-2.5">Fréquence</th>
            <th className="text-left px-4 py-2.5">Dernière exécution</th>
            <th className="text-left px-4 py-2.5">Prochaine exécution</th>
            <th className="text-left px-4 py-2.5">Statut</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task, i) => (
            <tr key={i} className="border-b border-slate-200/40 dark:border-slate-700/40 last:border-0 hover:bg-slate-100/20 dark:hover:bg-slate-700/20 transition-colors">
              <td className="px-5 py-3">
                <div className="font-medium text-slate-800 dark:text-slate-200 text-sm">{task.name}</div>
                <div className="text-[11px] text-slate-400 dark:text-slate-500 font-mono mt-0.5">{task.script}</div>
                {task.detail && (
                  <div className="text-[11px] text-[#007AFF] dark:text-[#0A84FF] mt-1">{task.detail}</div>
                )}
              </td>
              <td className="px-4 py-3">
                <div className="text-slate-700 dark:text-slate-300 text-sm">{task.label}</div>
                <div className="text-[11px] text-slate-400 dark:text-slate-600 font-mono mt-0.5">{task.cron}</div>
              </td>
              <td className="px-4 py-3">
                {task.last_run ? (
                  <>
                    <div className="text-slate-700 dark:text-slate-300 text-sm">{formatDateTime(task.last_run)}</div>
                    <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{formatRelative(task.last_run)}</div>
                  </>
                ) : <span className="text-slate-400 dark:text-slate-600 italic text-sm">Jamais</span>}
              </td>
              <td className="px-4 py-3">
                {task.next_run ? (
                  <>
                    <div className="text-slate-700 dark:text-slate-300 text-sm">{formatDateTime(task.next_run)}</div>
                    <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{formatRelative(task.next_run)}</div>
                  </>
                ) : <span className="text-slate-400 dark:text-slate-600 text-sm">—</span>}
              </td>
              <td className="px-4 py-3"><StatusBadge task={task} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const CRON_CATEGORIES = [
  { id: "Surveillance en continu", label: "Surveillance en continu",   desc: "Tâches fréquentes : chaque 5 min, 10 min ou toutes les 2h" },
  { id: "Enrichissement nocturne", label: "Enrichissement nocturne",   desc: "Pipeline 01h–04h30 : backup, NER, images, sentiment, réparation, crédibilité sources" },
  { id: "Rapports & digests",      label: "Rapports & digests",        desc: "Digests quotidiens, briefing hebdomadaire et collecte multi-flux" },
  { id: "Pipeline mensuel",        label: "Pipeline mensuel",          desc: "Radar, Markdown et rapports générés le dernier jour du mois" },
  { id: "Système auto-apprenant",  label: "Système auto-apprenant",   desc: "Optimisation des poids, calibration alertes, qualité articles, dérive mots-clés" },
]

function SchedulerTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/scheduler')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const upcoming = data?.tasks
    .filter(t => t.next_run && new Date(t.next_run) > Date.now())
    .sort((a, b) => new Date(a.next_run) - new Date(b.next_run))[0]

  const tasksByCategory = Object.fromEntries(
    CRON_CATEGORIES.map(c => [c.id, data?.tasks.filter(t => !t.flux && t.category === c.id) ?? []])
  )
  const fluxTasks = data?.tasks.filter(t => t.flux) ?? []

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Prochaine tâche imminente */}
      {upcoming && (
        <div className="px-5 py-2.5 bg-[#007AFF]/5 dark:bg-[#0A84FF]/10 border-b border-blue-200 dark:border-blue-500/20 shrink-0">
          <div className="flex items-center gap-2 text-sm">
            <Calendar size={13} className="text-[#007AFF] dark:text-[#0A84FF] shrink-0" />
            <span className="text-blue-700 dark:text-blue-300">
              Prochaine tâche :{' '}
              <span className="font-medium text-blue-800 dark:text-blue-200">{upcoming.name}</span>
              {' — '}
              <span className="text-blue-600 dark:text-blue-300">{formatRelative(upcoming.next_run)}</span>
              <span className="text-blue-400 dark:text-blue-500 text-xs ml-2">({formatDateTime(upcoming.next_run)})</span>
            </span>
          </div>
        </div>
      )}

      {/* Corps */}
      <div className="flex-1 overflow-auto">
        {loading ? <Spinner /> : !data?.tasks?.length ? (
          <div className="flex items-center justify-center h-40 text-slate-400 dark:text-slate-500 text-sm">
            Aucune tâche planifiée trouvée
          </div>
        ) : (
          <>
            {CRON_CATEGORIES.map(cat => {
              const tasks = tasksByCategory[cat.id] ?? []
              if (!tasks.length) return null
              return (
                <div key={cat.id}>
                  <div className="sticky top-0 z-10 bg-slate-50 dark:bg-slate-900 px-5 py-2 border-b border-slate-200 dark:border-slate-700 flex items-baseline gap-3">
                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      {cat.label}
                    </span>
                    <span className="text-[11px] text-slate-400 dark:text-slate-600 normal-case tracking-normal">{cat.desc}</span>
                    <span className="ml-auto text-[11px] text-slate-400 dark:text-slate-600">{tasks.length} tâche{tasks.length !== 1 ? 's' : ''}</span>
                  </div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider border-b border-slate-200/50 dark:border-slate-700/50">
                        <th className="text-left px-5 py-2.5">Tâche</th>
                        <th className="text-left px-4 py-2.5">Fréquence</th>
                        <th className="text-left px-4 py-2.5">Dernière exécution</th>
                        <th className="text-left px-4 py-2.5">Prochaine exécution</th>
                        <th className="text-left px-4 py-2.5">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tasks.map((task, i) => (
                        <tr key={i} className="border-b border-slate-200/40 dark:border-slate-700/40 last:border-0 hover:bg-slate-100/20 dark:hover:bg-slate-700/20 transition-colors">
                          <td className="px-5 py-3">
                            <div className="font-medium text-slate-800 dark:text-slate-200 text-sm">{task.name}</div>
                            <div className="text-[11px] text-slate-400 dark:text-slate-500 font-mono mt-0.5">{task.script}</div>
                            {task.detail && <div className="text-[11px] text-[#007AFF] dark:text-[#0A84FF] mt-1">{task.detail}</div>}
                          </td>
                          <td className="px-4 py-3">
                            <div className="text-slate-700 dark:text-slate-300 text-sm">{task.label}</div>
                            <div className="text-[11px] text-slate-400 dark:text-slate-600 font-mono mt-0.5">{task.cron}</div>
                          </td>
                          <td className="px-4 py-3">
                            {task.last_run ? (
                              <>
                                <div className="text-slate-700 dark:text-slate-300 text-sm">{formatDateTime(task.last_run)}</div>
                                <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{formatRelative(task.last_run)}</div>
                              </>
                            ) : <span className="text-slate-400 dark:text-slate-600 italic text-sm">Jamais</span>}
                          </td>
                          <td className="px-4 py-3">
                            {task.next_run ? (
                              <>
                                <div className="text-slate-700 dark:text-slate-300 text-sm">{formatDateTime(task.next_run)}</div>
                                <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{formatRelative(task.next_run)}</div>
                              </>
                            ) : <span className="text-slate-400 dark:text-slate-600 text-sm">—</span>}
                          </td>
                          <td className="px-4 py-3"><StatusBadge task={task} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })}
            {fluxTasks.length > 0 && (
              <div>
                <div className="sticky top-0 z-10 bg-slate-50 dark:bg-slate-900 px-5 py-2 border-b border-slate-200 dark:border-slate-700 flex items-baseline gap-3">
                  <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    Tâches par flux
                  </span>
                  <span className="text-[11px] text-slate-400 dark:text-slate-600 normal-case tracking-normal">Collecte IA planifiée par flux JSON source</span>
                  <span className="ml-auto text-[11px] text-slate-400 dark:text-slate-600">{fluxTasks.length} flux</span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider border-b border-slate-200/50 dark:border-slate-700/50">
                      <th className="text-left px-5 py-2.5">Tâche</th>
                      <th className="text-left px-4 py-2.5">Fréquence</th>
                      <th className="text-left px-4 py-2.5">Dernière exécution</th>
                      <th className="text-left px-4 py-2.5">Prochaine exécution</th>
                      <th className="text-left px-4 py-2.5">Statut</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fluxTasks.map((task, i) => (
                      <tr key={i} className="border-b border-slate-200/40 dark:border-slate-700/40 last:border-0 hover:bg-slate-100/20 dark:hover:bg-slate-700/20 transition-colors">
                        <td className="px-5 py-3">
                          <div className="font-medium text-slate-800 dark:text-slate-200 text-sm">{task.name}</div>
                          <div className="text-[11px] text-slate-400 dark:text-slate-500 font-mono mt-0.5">{task.script}</div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="text-slate-700 dark:text-slate-300 text-sm">{task.label}</div>
                          <div className="text-[11px] text-slate-400 dark:text-slate-600 font-mono mt-0.5">{task.cron}</div>
                        </td>
                        <td className="px-4 py-3">
                          {task.last_run ? (
                            <>
                              <div className="text-slate-700 dark:text-slate-300 text-sm">{formatDateTime(task.last_run)}</div>
                              <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{formatRelative(task.last_run)}</div>
                            </>
                          ) : <span className="text-slate-400 dark:text-slate-600 italic text-sm">Jamais</span>}
                        </td>
                        <td className="px-4 py-3">
                          {task.next_run ? (
                            <>
                              <div className="text-slate-700 dark:text-slate-300 text-sm">{formatDateTime(task.next_run)}</div>
                              <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{formatRelative(task.next_run)}</div>
                            </>
                          ) : <span className="text-slate-400 dark:text-slate-600 text-sm">—</span>}
                        </td>
                        <td className="px-4 py-3"><StatusBadge task={task} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {/* Pied */}
      {data && (
        <div className="px-5 py-2 bg-slate-50/50 dark:bg-slate-900/50 border-t border-slate-200 dark:border-slate-700 text-xs text-slate-400 dark:text-slate-600 shrink-0 flex items-center gap-2">
          <span>
            {data.tasks.length} tâche{data.tasks.length !== 1 ? 's' : ''} planifiée{data.tasks.length !== 1 ? 's' : ''}
            {' · '}Actualisé à {new Date(data.now).toLocaleTimeString('fr-FR')}
          </span>
          <button
            onClick={load}
            className="text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            title="Actualiser"
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Saisie de tags (termes OU / ET) ────────────────────────────────────────

function TagInput({ tags, onChange, placeholder, color }) {
  const [input, setInput] = useState('')

  const styles = {
    blue:  { tag: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700/50',  btn: 'hover:text-blue-600 dark:hover:text-blue-200 text-[#007AFF] dark:text-[#0A84FF]'  },
    green: { tag: 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300 border-green-300 dark:border-green-700/50', btn: 'hover:text-green-600 dark:hover:text-green-200 text-green-500 dark:text-green-400' },
  }
  const s = styles[color] || styles.blue

  const commit = () => {
    const v = input.trim()
    if (v && !tags.includes(v)) onChange([...tags, v])
    setInput('')
  }

  const remove = (t) => onChange(tags.filter(x => x !== t))

  return (
    <div className="flex flex-wrap gap-1.5 items-center min-h-[28px]">
      {tags.map(tag => (
        <span key={tag} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${s.tag}`}>
          {tag}
          <button
            onClick={() => remove(tag)}
            className={`${s.btn} hover:text-red-500 dark:hover:text-red-300 transition-colors`}
            aria-label={`Supprimer ${tag}`}
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <div className="flex items-center gap-1">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); commit() }
          }}
          placeholder={placeholder}
          className="text-xs bg-slate-100 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-0.5 text-slate-700 dark:text-slate-300 placeholder-slate-400 dark:placeholder-slate-600 focus:outline-none focus:border-[#007AFF] w-40 transition-colors"
        />
        <button
          onClick={commit}
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
          aria-label="Ajouter"
        >
          <Plus size={13} />
        </button>
      </div>
    </div>
  )
}

// ─── Modale champ sémantique ────────────────────────────────────────────────

function SemanticFieldModal({ keyword, onClose, onApply }) {
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [suggestions, setSuggestions] = useState(null)
  const [selectedOu, setSelectedOu]   = useState(new Set())
  const [selectedEt, setSelectedEt]   = useState(new Set())

  const toggle = (set, setter, val) =>
    setter(prev => { const s = new Set(prev); s.has(val) ? s.delete(val) : s.add(val); return s })

  useEffect(() => {
    setLoading(true); setError(null); setSuggestions(null)
    fetch('/api/keywords/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { setError(d.error); return }
        setSuggestions(d)
        setSelectedOu(new Set(d.ou || []))
        setSelectedEt(new Set(d.et || []))
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [keyword])

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-lg flex flex-col overflow-hidden border border-slate-200 dark:border-slate-700">
        {/* Header */}
        <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <Sparkles size={16} className="text-amber-500" />
          <div className="flex-1">
            <h3 className="font-semibold text-slate-800 dark:text-slate-100 text-sm">Champ sémantique IA</h3>
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">Suggestions pour <strong>"{keyword}"</strong></p>
          </div>
          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Contenu */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {loading && (
            <div className="flex items-center justify-center py-12 gap-3 text-slate-400 dark:text-slate-500 text-sm">
              <RefreshCw size={16} className="animate-spin" />
              L'IA génère des propositions…
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 rounded-xl p-3 text-sm text-red-700 dark:text-red-300">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}
          {suggestions && (
            <>
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[11px] bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400 border border-blue-300 dark:border-blue-700/50 rounded-full px-1.5 py-0.5 font-bold">OU</span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">Synonymes & variantes — élargissent la recherche</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {suggestions.ou.map(t => (
                    <button
                      key={t}
                      onClick={() => toggle(selectedOu, setSelectedOu, t)}
                      className={`text-xs px-2.5 py-1 rounded-full border transition-all ${
                        selectedOu.has(t)
                          ? 'bg-blue-500 dark:bg-blue-600 text-white border-blue-500 dark:border-blue-600'
                          : 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-700/50 hover:bg-blue-100 dark:hover:bg-blue-800/40'
                      }`}
                    >
                      {selectedOu.has(t) && <Check size={10} className="inline mr-1" />}{t}
                    </button>
                  ))}
                  {suggestions.ou.length === 0 && <span className="text-xs text-slate-400 italic">Aucune proposition</span>}
                </div>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[11px] bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700/50 rounded-full px-1.5 py-0.5 font-bold">ET</span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">Champ lexical — restreignent au bon contexte</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {suggestions.et.map(t => (
                    <button
                      key={t}
                      onClick={() => toggle(selectedEt, setSelectedEt, t)}
                      className={`text-xs px-2.5 py-1 rounded-full border transition-all ${
                        selectedEt.has(t)
                          ? 'bg-green-500 dark:bg-green-600 text-white border-green-500 dark:border-green-600'
                          : 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700/50 hover:bg-green-100 dark:hover:bg-green-800/40'
                      }`}
                    >
                      {selectedEt.has(t) && <Check size={10} className="inline mr-1" />}{t}
                    </button>
                  ))}
                  {suggestions.et.length === 0 && <span className="text-xs text-slate-400 italic">Aucune proposition</span>}
                </div>
              </div>
              <p className="text-[11px] text-slate-400 dark:text-slate-500 italic">
                Cliquez sur un terme pour le sélectionner ou désélectionner. Les termes sélectionnés (colorés) seront ajoutés.
              </p>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-200 dark:border-slate-700 shrink-0 bg-slate-50/50 dark:bg-slate-900/30">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors border border-slate-200 dark:border-slate-600"
          >
            Annuler
          </button>
          <button
            disabled={!suggestions || (selectedOu.size === 0 && selectedEt.size === 0)}
            onClick={() => onApply([...selectedOu], [...selectedEt])}
            className="px-4 py-1.5 text-xs bg-[#007AFF] dark:bg-[#0A84FF] text-white rounded-lg hover:bg-blue-600 dark:hover:bg-blue-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            <Check size={12} /> Appliquer ({selectedOu.size + selectedEt.size} termes)
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Onglet Mots-clés ────────────────────────────────────────────────────────

function KeywordsTab() {
  const [keywords, setKeywords]   = useState(null)
  const [loading, setLoading]     = useState(true)
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)
  const [error, setError]         = useState(null)
  const [showMindmap, setShowMindmap] = useState(false)
  const [semanticModal, setSemanticModal] = useState(null) // { idx, keyword }

  useEffect(() => {
    fetch('/api/keywords')
      .then(r => r.json())
      .then(d => {
        const sorted = [...d].sort((a, b) =>
          (a.keyword || '').localeCompare(b.keyword || '', 'fr', { sensitivity: 'base' })
        )
        setKeywords(sorted)
        setLoading(false)
      })
      .catch(() => { setError('Impossible de charger les mots-clés'); setLoading(false) })
  }, [])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      const r = await fetch('/api/keywords', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(keywords),
      })
      if (!r.ok) throw new Error()
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      setError('Erreur lors de la sauvegarde')
    } finally { setSaving(false) }
  }

  const add = () => setKeywords(k => [...k, { keyword: '', or: [], and: [] }])

  const remove = (idx) => setKeywords(k => k.filter((_, i) => i !== idx))

  const update = (idx, field, value) =>
    setKeywords(k => k.map((kw, i) => i === idx ? { ...kw, [field]: value } : kw))

  if (loading) return <Spinner />

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {semanticModal && (
        <SemanticFieldModal
          keyword={semanticModal.keyword}
          onClose={() => setSemanticModal(null)}
          onApply={(ouTerms, etTerms) => {
            const idx = semanticModal.idx
            setKeywords(k => k.map((kw, i) => {
              if (i !== idx) return kw
              const newOr  = [...new Set([...(kw.or  || []), ...ouTerms])]
              const newAnd = [...new Set([...(kw.and || []), ...etTerms])]
              return { ...kw, or: newOr, and: newAnd }
            }))
            setSemanticModal(null)
          }}
        />
      )}
      {/* Texte explicatif — masqué sur mobile pour ne pas agrandir la toolbar */}
      <p className="hidden sm:block text-xs text-slate-400 dark:text-slate-500 px-5 pt-3 pb-1 shrink-0">
        Mots-clés extraits des flux RSS.{' '}
        <span className="text-[#007AFF] dark:text-[#0A84FF] font-medium">OU</span> élargit la recherche,{' '}
        <span className="text-[#1a7a34] dark:text-[#30D158] font-medium">ET</span> la restreint.
        Appuyez sur <kbd className="bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 px-1 rounded text-[11px]">Entrée</kbd> pour valider un terme.
      </p>
      {/* Barre d'outils */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0">
        <button
          onClick={() => setShowMindmap(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 dark:bg-indigo-900/30 hover:bg-indigo-100 dark:hover:bg-indigo-800/40 border border-indigo-200 dark:border-indigo-700/50 rounded-lg text-xs text-indigo-700 dark:text-indigo-300 transition-colors shrink-0"
          title="Voir la carte des mots-clés"
        >
          <Network size={12} /> Carte
        </button>
        <button
          onClick={add}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-xs text-slate-700 dark:text-slate-300 transition-colors shrink-0"
        >
          <Plus size={12} /> Ajouter
        </button>
        <SaveButton saving={saving} saved={saved} onClick={save} />
      </div>

      <ErrorBanner message={error} />

      {/* Modal mindmap — rendu hors du toolbar pour éviter tout clipping */}
      {showMindmap && (
        <div
          className="fixed inset-0 z-[9999] flex flex-col bg-white dark:bg-slate-900"
          style={{ top: 0, left: 0, right: 0, bottom: 0 }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0 bg-white dark:bg-slate-900">
            <div className="flex items-center gap-2">
              <Network size={16} className="text-indigo-500" />
              <h3 className="font-semibold text-slate-800 dark:text-slate-100 text-sm">Carte des mots-clés de veille</h3>
              <span className="text-xs text-slate-400 dark:text-slate-500">({keywords?.length ?? 0} mots-clés)</span>
            </div>
            <button
              onClick={() => setShowMindmap(false)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-xs text-slate-700 dark:text-slate-300 transition-colors"
            >
              <X size={14} /> Fermer
            </button>
          </div>
          {/* Graphe force-directed — occupe tout l'espace restant */}
          <div className="flex-1 overflow-hidden">
            <KeywordForceGraph keywords={keywords} />
          </div>
        </div>
      )}

      {/* Liste */}
      <div className="flex-1 overflow-y-auto p-5 space-y-3">
        {!keywords?.length ? (
          <div className="text-center py-16 text-slate-400 dark:text-slate-500 text-sm">
            Aucun mot-clé configuré.{' '}
            <button onClick={add} className="text-[#007AFF] dark:text-[#0A84FF] hover:text-blue-500 dark:hover:text-blue-300 underline">
              Ajouter le premier
            </button>
          </div>
        ) : keywords.map((kw, idx) => (
          <div key={idx} className="bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 rounded-xl p-4 space-y-3">

            {/* Mot-clé principal */}
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <label className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-1 block">
                  Mot-clé principal
                </label>
                <input
                  type="text"
                  value={kw.keyword}
                  onChange={e => update(idx, 'keyword', e.target.value)}
                  placeholder="ex. Intelligence Artificielle"
                  className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-600 focus:outline-none focus:border-[#007AFF] transition-colors"
                />
              </div>
              <button
                onClick={() => kw.keyword.trim() && setSemanticModal({ idx, keyword: kw.keyword.trim() })}
                disabled={!kw.keyword.trim()}
                className="mt-5 flex items-center gap-1 px-2.5 py-1.5 text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 hover:bg-amber-100 dark:hover:bg-amber-800/30 border border-amber-200 dark:border-amber-700/50 rounded-lg text-xs transition-colors disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
                title="Générer un champ sémantique par IA"
              >
                <Sparkles size={12} /> IA
              </button>
              <button
                onClick={() => remove(idx)}
                className="mt-5 p-1.5 text-slate-400 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                title="Supprimer ce mot-clé"
              >
                <Trash2 size={14} />
              </button>
            </div>

            {/* Termes OU */}
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[11px] bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400 border border-blue-300 dark:border-blue-700/50 rounded-full px-1.5 py-0.5 font-bold">OU</span>
                <span className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                  correspond si l'un de ces termes est présent
                </span>
              </div>
              <TagInput
                tags={kw.or || []}
                onChange={v => update(idx, 'or', v)}
                placeholder="Synonyme ou variante…"
                color="blue"
              />
            </div>

            {/* Termes ET */}
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[11px] bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700/50 rounded-full px-1.5 py-0.5 font-bold">ET</span>
                <span className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                  doit aussi contenir au moins un de ces termes
                </span>
              </div>
              <TagInput
                tags={kw.and || []}
                onChange={v => update(idx, 'and', v)}
                placeholder="Filtre obligatoire…"
                color="green"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Onglet RSS ───────────────────────────────────────────────────────────────

function RssTab() {
  const [feeds, setFeeds]           = useState(null)
  const [search, setSearch]         = useState('')
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [checking, setChecking]     = useState(new Set())   // xmlUrls en cours de vérif
  const [results, setResults]       = useState({})          // xmlUrl → true|false
  const [isDirty, setIsDirty]       = useState(false)
  const [saving, setSaving]         = useState(false)
  const [saveMsg, setSaveMsg]       = useState(null)        // {ok, text}
  const [checkingAll, setCheckingAll] = useState(false)
  const [showPasteInput, setShowPasteInput] = useState(false)
  const [pasteUrl, setPasteUrl]       = useState('')
  const [pasteMsg, setPasteMsg]       = useState(null)  // {state:'checking'|'ok'|'error', text}
  const [feedStats, setFeedStats]     = useState({})    // domain → {count, lastDate}
  const pasteInputRef                 = useRef(null)

  useEffect(() => {
    fetch('/api/rss-feeds')
      .then(r => r.json())
      .then(d => { setFeeds(Array.isArray(d) ? d : []); setLoading(false) })
      .catch(() => { setError('Impossible de charger les flux RSS'); setLoading(false) })
  }, [])

  // Chargement en tâche de fond : stats articles par domaine
  useEffect(() => {
    fetch('/api/rss-feeds/stats')
      .then(r => r.json())
      .then(d => { if (d && typeof d === 'object' && !d.error) setFeedStats(d) })
      .catch(() => {})
  }, [])

  const removeFeed = useCallback((xmlUrl) => {
    setFeeds(prev => prev.filter(f => f.xmlUrl !== xmlUrl))
    setIsDirty(true)
  }, [])

  const toggleBypassQuota = useCallback((xmlUrl) => {
    setFeeds(prev => prev.map(f => f.xmlUrl === xmlUrl ? { ...f, bypassQuota: !f.bypassQuota } : f))
    setIsDirty(true)
  }, [])

  const checkOne = useCallback(async (xmlUrl) => {
    setChecking(prev => new Set([...prev, xmlUrl]))
    try {
      const r = await fetch('/api/rss-feeds/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: xmlUrl }),
      })
      const data = await r.json()
      const ok = !!data.ok
      setResults(prev => ({ ...prev, [xmlUrl]: ok }))
      if (!ok) {
        // Supprimer automatiquement après un bref délai pour que l'utilisateur voie le résultat
        setTimeout(() => removeFeed(xmlUrl), 1200)
      }
    } catch {
      setResults(prev => ({ ...prev, [xmlUrl]: false }))
      setTimeout(() => removeFeed(xmlUrl), 1200)
    } finally {
      setChecking(prev => { const s = new Set(prev); s.delete(xmlUrl); return s })
    }
  }, [removeFeed])

  const checkAll = useCallback(async () => {
    if (!feeds || checkingAll) return
    setCheckingAll(true)
    setResults({})
    // Vérification séquentielle pour ne pas surcharger
    for (const f of feeds) {
      await checkOne(f.xmlUrl)
    }
    setCheckingAll(false)
  }, [feeds, checkingAll, checkOne])

  const handlePaste = useCallback(async () => {
    const url = pasteUrl.trim()
    if (!url.startsWith('http')) {
      setPasteMsg({ state: 'error', text: `URL invalide : "${url.slice(0, 60)}"` })
      return
    }
    // Normalisation : retire le slash final et force lowercase pour la comparaison
    const normalize = u => u.replace(/\/+$/, '').toLowerCase()
    const urlNorm = normalize(url)
    const duplicate = feeds?.find(f => normalize(f.xmlUrl) === urlNorm)
    if (duplicate) {
      setPasteMsg({ state: 'error', text: `Ce flux est déjà dans la liste : « ${duplicate.title} »` })
      return
    }
    setPasteMsg({ state: 'checking', text: `Vérification de ${url}…` })
    try {
      const r = await fetch('/api/rss-feeds/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      })
      const data = await r.json()
      if (data.ok) {
        const newFeed = { title: data.title, xmlUrl: data.xmlUrl, htmlUrl: data.htmlUrl || '' }
        setFeeds(prev => [...(prev || []), newFeed].sort((a, b) => a.title.localeCompare(b.title, 'fr', { sensitivity: 'base' })))
        setIsDirty(true)
        setResults(prev => ({ ...prev, [url]: true }))
        setPasteMsg({ state: 'ok', text: `« ${data.title} » ajouté à la liste.` })
        setPasteUrl('')
        setShowPasteInput(false)
      } else {
        setPasteMsg({ state: 'error', text: data.error || 'URL non accessible' })
      }
    } catch (e) {
      setPasteMsg({ state: 'error', text: String(e) })
    } finally {
      setTimeout(() => setPasteMsg(null), 5000)
    }
  }, [feeds, pasteUrl])

  const saveFeed = useCallback(async () => {
    if (!feeds || saving) return
    setSaving(true)
    setSaveMsg(null)
    try {
      const r = await fetch('/api/rss-feeds/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(feeds),
      })
      const data = await r.json()
      if (data.ok) {
        setSaveMsg({ ok: true, text: `${data.count} flux sauvegardés dans WUDD.opml` })
        setIsDirty(false)
      } else {
        setSaveMsg({ ok: false, text: data.error || 'Erreur lors de la sauvegarde' })
      }
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) })
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMsg(null), 4000)
    }
  }, [feeds, saving])

  const filtered = feeds
    ? feeds.filter(f => f.title.toLowerCase().includes(search.toLowerCase()) || f.htmlUrl.toLowerCase().includes(search.toLowerCase()))
    : []

  const grouped = filtered.reduce((acc, f) => {
    const letter = f.title[0]?.toUpperCase() ?? '#'
    if (!acc[letter]) acc[letter] = []
    acc[letter].push(f)
    return acc
  }, {})
  const letters = Object.keys(grouped).sort()

  if (loading) return <Spinner />

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Barre d'outils */}
      <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0 flex-wrap">
        <Database size={12} className="text-slate-400 dark:text-slate-500 shrink-0" />
        <p className="text-xs text-slate-400 dark:text-slate-500 flex-1 min-w-0">
          {feeds
            ? <><span className="font-medium text-slate-600 dark:text-slate-300">{feeds.length}</span> flux RSS</>
            : 'Flux RSS'}
        </p>
        {/* Coller une URL */}
        <button
          onClick={() => {
            setShowPasteInput(v => {
              const next = !v
              if (next) setTimeout(() => pasteInputRef.current?.focus(), 50)
              return next
            })
            setPasteMsg(null)
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors
            ${showPasteInput
              ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 border border-blue-400/40'
              : 'bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200'}`}
          title="Ajouter un flux RSS en collant son URL"
        >
          <Clipboard size={11} />
          <span className="hidden sm:inline">Coller</span>
        </button>
        {/* Vérifier tous */}
        <button
          onClick={checkAll}
          disabled={checkingAll || !feeds?.length}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors disabled:opacity-40
            bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200"
          title="Vérifier toutes les URLs (supprime les non-répondants)"
        >
          {checkingAll
            ? <RefreshCw size={11} className="animate-spin" />
            : <Check size={11} />}
          <span className="hidden sm:inline">Vérifier</span>
        </button>
        {/* Sauvegarder */}
        <button
          onClick={saveFeed}
          disabled={!isDirty || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors disabled:opacity-40
            bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white"
          title="Sauvegarder les flux dans data/WUDD.opml"
        >
          {saving
            ? <RefreshCw size={11} className="animate-spin" />
            : <Save size={11} />}
          <span className="hidden sm:inline">Sauver</span>
        </button>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filtrer…"
          className="pl-3 pr-3 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 focus:border-[#007AFF] transition-colors w-36"
        />
      </div>

      {/* Barre de saisie URL */}
      {showPasteInput && (
        <div className="flex items-center gap-2 px-5 py-2.5 border-b border-slate-200/50 dark:border-slate-700/50 bg-blue-50/60 dark:bg-blue-900/20 shrink-0">
          <Rss size={12} className="text-blue-400 shrink-0" />
          <input
            ref={pasteInputRef}
            type="url"
            value={pasteUrl}
            onChange={e => { setPasteUrl(e.target.value); setPasteMsg(null) }}
            onKeyDown={e => { if (e.key === 'Enter') handlePaste(); if (e.key === 'Escape') { setShowPasteInput(false); setPasteUrl('') } }}
            placeholder="Coller l'URL RSS ici (Entrée pour valider)"
            className="flex-1 min-w-0 pl-3 pr-3 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 focus:border-[#007AFF] transition-colors"
          />
          <button
            onClick={handlePaste}
            disabled={!pasteUrl.trim() || pasteMsg?.state === 'checking'}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white disabled:opacity-40 transition-colors shrink-0"
          >
            {pasteMsg?.state === 'checking' ? <RefreshCw size={11} className="animate-spin" /> : <Plus size={11} />}
            Ajouter
          </button>
          <button onClick={() => { setShowPasteInput(false); setPasteUrl(''); setPasteMsg(null) }}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors shrink-0">
            <X size={13} />
          </button>
        </div>
      )}
      {pasteMsg && (
        <div className={`mx-5 mt-3 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${
          pasteMsg.state === 'checking' ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
          : pasteMsg.state === 'ok'     ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
          :                               'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
          {pasteMsg.state === 'checking' && <RefreshCw size={13} className="animate-spin shrink-0" />}
          {pasteMsg.state === 'ok'       && <CheckCircle2 size={13} className="shrink-0" />}
          {pasteMsg.state === 'error'    && <AlertTriangle size={13} className="shrink-0" />}
          <span className="truncate">{pasteMsg.text}</span>
        </div>
      )}

      {saveMsg && (
        <div className={`mx-5 mt-3 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${saveMsg.ok ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
          {saveMsg.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
          {saveMsg.text}
        </div>
      )}

      <ErrorBanner message={error} />

      {/* Liste groupée par lettre */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        {letters.length === 0 ? (
          <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-sm">Aucun flux trouvé.</div>
        ) : letters.map(letter => (
          <div key={letter}>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-xs font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest w-5 text-center">{letter}</span>
              <div className="flex-1 h-px bg-slate-100 dark:bg-slate-700/60" />
            </div>
            <div className="space-y-1 ml-8">
              {grouped[letter].map((f) => {
                const isChecking = checking.has(f.xmlUrl)
                const result = results[f.xmlUrl]  // undefined | true | false
                const fDomain = (() => { try { return new URL(f.htmlUrl || f.xmlUrl).hostname.replace(/^www\./, '') } catch { return '' } })()
                const stat = feedStats[fDomain]
                return (
                  <div key={f.xmlUrl} className={`flex items-center gap-2 py-1 group rounded-lg transition-colors ${result === false ? 'bg-red-50/60 dark:bg-red-900/20' : ''}`}>
                    <Rss size={11} className="text-orange-400 dark:text-orange-500 shrink-0" />
                    <span className="text-sm text-slate-700 dark:text-slate-200 flex-1 truncate">{f.title}</span>
                    <span className="text-xs text-slate-400 dark:text-slate-500 truncate max-w-[160px] hidden sm:block">
                      {f.htmlUrl.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                    </span>
                    {/* Stats articles en tâche de fond */}
                    {stat && (
                      <span
                        className="flex items-center gap-1 text-xs text-blue-400/80 dark:text-blue-400/60 shrink-0 tabular-nums"
                        title={`${stat.count} article${stat.count > 1 ? 's' : ''} stocké${stat.count > 1 ? 's' : ''}${stat.lastDate ? ' · dernière publication : ' + new Date(stat.lastDate).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : ''}`}
                      >
                        <Calendar size={10} className="shrink-0" />
                        <span>{stat.count}</span>
                        {stat.lastDate && (
                          <span className="hidden md:inline text-slate-400 dark:text-slate-500">
                            · {new Date(stat.lastDate).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}
                          </span>
                        )}
                      </span>
                    )}
                    {/* Icône de résultat */}
                    {isChecking && <RefreshCw size={11} className="animate-spin text-blue-400 shrink-0" />}
                    {!isChecking && result === true  && <CheckCircle2 size={11} className="text-green-500 shrink-0" />}
                    {!isChecking && result === false && <AlertTriangle size={11} className="text-red-400 shrink-0" />}
                    {/* Bouton vérifier individuel */}
                    {!isChecking && result === undefined && (
                      <button
                        onClick={() => checkOne(f.xmlUrl)}
                        className="opacity-30 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF]"
                        title="Vérifier ce flux"
                      >
                        <Check size={11} />
                      </button>
                    )}
                    <a href={f.xmlUrl} target="_blank" rel="noopener noreferrer"
                      className="opacity-30 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF]"
                      title="Ouvrir le flux RSS">
                      <ExternalLink size={11} />
                    </a>
                    <button
                      onClick={() => toggleBypassQuota(f.xmlUrl)}
                      className={`transition-opacity shrink-0 ${f.bypassQuota ? 'text-amber-500 dark:text-amber-400 opacity-100' : 'opacity-30 group-hover:opacity-100 text-slate-400 hover:text-amber-500 dark:hover:text-amber-400'}`}
                      title={f.bypassQuota ? 'Quota ignoré pour ce flux (cliquer pour réactiver)' : 'Ignorer le quota pour ce flux'}
                    >
                      <ShieldOff size={11} />
                    </button>
                    <button
                      onClick={() => removeFeed(f.xmlUrl)}
                      className="opacity-30 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-red-500 dark:hover:text-red-400"
                      title="Supprimer ce flux"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Onglet Flux Reeder ───────────────────────────────────────────────────────

const CRON_PRESETS = [
  { label: 'Toutes les 2h (6h-22h)', value: '0 6-22/2 * * *' },
  { label: 'Quotidien à 06:00',      value: '0 6 * * *' },
  { label: 'Lundi à 06:00',          value: '0 6 * * 1' },
  { label: 'Dimanche à 06:00',       value: '0 6 * * 0' },
  { label: 'Toutes les heures',      value: '0 * * * *' },
]

function cronLabel(cron) {
  if (!cron) return ''
  const p = cron.trim().split(/\s+/)
  if (p.length !== 5) return cron
  const [min, hour, , , dow] = p
  const jours = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
  if (min.startsWith('*/')) return `Toutes les ${min.slice(2)} min`
  if (min === '0' && hour.includes('/') && hour.includes('-')) {
    const [range, step] = hour.split('/')
    const [start, end] = range.split('-')
    return `Toutes les ${step}h de ${start}h à ${end}h`
  }
  if (min === '0' && /^\d+$/.test(hour)) {
    const t = `${String(hour).padStart(2, '0')}:00`
    if (dow === '*') return `Quotidien à ${t}`
    if (/^\d$/.test(dow)) return `${jours[parseInt(dow) % 7]} à ${t}`
  }
  return cron
}

function FluxTab() {
  const [sources, setSources] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [saved, setSaved]     = useState(false)
  const [error, setError]     = useState(null)

  useEffect(() => {
    fetch('/api/flux-sources')
      .then(r => r.json())
      .then(d => { setSources(d); setLoading(false) })
      .catch(() => { setError('Impossible de charger les flux'); setLoading(false) })
  }, [])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      const r = await fetch('/api/flux-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sources),
      })
      if (!r.ok) throw new Error()
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      setError('Erreur lors de la sauvegarde')
    } finally { setSaving(false) }
  }

  const add = () => setSources(s => [
    ...s,
    { title: '', url: '', scheduler: { cron: '0 6 * * 1', timeout: 60 } },
  ])

  const remove = (idx) => setSources(s => s.filter((_, i) => i !== idx))

  const updateField = (idx, field, value) =>
    setSources(s => s.map((src, i) => i === idx ? { ...src, [field]: value } : src))

  const updateScheduler = (idx, field, value) =>
    setSources(s => s.map((src, i) => i === idx
      ? { ...src, scheduler: { ...(src.scheduler || {}), [field]: value } }
      : src
    ))

  if (loading) return <Spinner />

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Barre d'outils */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0">
        <p className="text-xs text-slate-400 dark:text-slate-500 flex-1">
          Sources de flux JSON Reeder. Chaque flux est traité indépendamment avec son propre planning cron.
        </p>
        <button
          onClick={add}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-xs text-slate-700 dark:text-slate-300 transition-colors shrink-0"
        >
          <Plus size={12} /> Ajouter
        </button>
        <SaveButton saving={saving} saved={saved} onClick={save} />
      </div>

      <ErrorBanner message={error} />

      {/* Liste */}
      <div className="flex-1 overflow-y-auto p-5 space-y-3">
        {!sources?.length ? (
          <div className="text-center py-16 text-slate-400 dark:text-slate-500 text-sm">
            Aucun flux configuré.{' '}
            <button onClick={add} className="text-[#007AFF] dark:text-[#0A84FF] hover:text-blue-500 dark:hover:text-blue-300 underline">
              Ajouter le premier flux
            </button>
          </div>
        ) : sources.map((src, idx) => {
          const cron = src.scheduler?.cron || src.cron || ''
          const timeout = src.scheduler?.timeout ?? src.timeout ?? 60
          const label = cronLabel(cron)

          return (
            <div key={idx} className="bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 rounded-xl p-4 space-y-3">
              {/* Titre + URL + Supprimer */}
              <div className="flex items-start gap-3">
                <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-1 block">
                      Titre du flux
                    </label>
                    <input
                      type="text"
                      value={src.title}
                      onChange={e => updateField(idx, 'title', e.target.value)}
                      placeholder="ex. Intelligence-artificielle"
                      className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-600 focus:outline-none focus:border-[#007AFF] transition-colors"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-1 block">
                      URL du flux JSON
                    </label>
                    <input
                      type="url"
                      value={src.url}
                      onChange={e => updateField(idx, 'url', e.target.value)}
                      placeholder="https://…/feed.json"
                      className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-600 font-mono focus:outline-none focus:border-[#007AFF] transition-colors"
                    />
                  </div>
                </div>
                <button
                  onClick={() => remove(idx)}
                  className="mt-5 p-1.5 text-slate-400 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors shrink-0"
                  title="Supprimer ce flux"
                >
                  <Trash2 size={14} />
                </button>
              </div>

              {/* Planning + Timeout */}
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-1 block">
                    Planning (cron){label && <span className="text-slate-500 dark:text-slate-400 normal-case ml-2 font-normal">→ {label}</span>}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={cron}
                      onChange={e => updateScheduler(idx, 'cron', e.target.value)}
                      placeholder="0 6 * * 1"
                      className="flex-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-sm font-mono text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-600 focus:outline-none focus:border-[#007AFF] transition-colors"
                    />
                    <select
                      value=""
                      onChange={e => e.target.value && updateScheduler(idx, 'cron', e.target.value)}
                      className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-1.5 text-xs text-slate-500 dark:text-slate-400 focus:outline-none focus:border-[#007AFF] transition-colors"
                    >
                      <option value="">Préréglage…</option>
                      {CRON_PRESETS.map(p => (
                        <option key={p.value} value={p.value}>{p.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="w-32 shrink-0">
                  <label className="text-[11px] text-slate-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-1 block">
                    Timeout (s)
                  </label>
                  <input
                    type="number"
                    value={timeout}
                    onChange={e => updateScheduler(idx, 'timeout', parseInt(e.target.value) || 60)}
                    min={10}
                    max={600}
                    className="w-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-[#007AFF] transition-colors"
                  />
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Onglet Quota ────────────────────────────────────────────────────────────

function QuotaBar({ count, limit, color = 'blue' }) {
  const pct = limit > 0 ? Math.min(100, Math.round(count / limit * 100)) : 0
  const colors = {
    blue:   'bg-blue-500 dark:bg-blue-400',
    amber:  'bg-amber-500 dark:bg-amber-400',
    rose:   'bg-rose-500 dark:bg-rose-400',
    green:  'bg-green-500 dark:bg-green-400',
    violet: 'bg-violet-500 dark:bg-violet-400',
  }
  const barColor = pct >= 90 ? colors.rose : pct >= 70 ? colors.amber : (colors[color] ?? colors.blue)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs tabular-nums w-20 text-right ${
        pct >= 90 ? 'text-rose-500 dark:text-rose-400 font-semibold'
                  : 'text-slate-500 dark:text-slate-400'
      }`}>
        {count} / {limit}
      </span>
      <span className="text-xs text-slate-400 dark:text-slate-500 w-9 text-right">{pct}%</span>
    </div>
  )
}

function QuotaTab() {
  const [config, setConfig]   = useState(null)
  const [stats, setStats]     = useState(null)
  const [saving, setSaving]   = useState(false)
  const [saved, setSaved]     = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    try {
      const [cfgRes, statsRes] = await Promise.all([
        fetch('/api/quota/config'),
        fetch('/api/quota/stats?top_keywords=25&top_sources=5&top_entities=20&top_global_sources=20'),
      ])
      const cfg   = await cfgRes.json()
      const st    = await statsRes.json()
      setConfig(cfg)
      setStats(st)
    } catch (e) {
      setError('Impossible de charger les données de quota.')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch('/api/quota/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (!res.ok) throw new Error(await res.text())
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!window.confirm('Réinitialiser tous les compteurs de quota du jour ?')) return
    setResetting(true)
    try {
      await fetch('/api/quota/reset', { method: 'POST' })
      await load()
    } catch (e) {
      setError('Erreur lors de la réinitialisation.')
    } finally {
      setResetting(false)
    }
  }

  if (!config) return <Spinner />

  const allKeywords = stats?.keywords ?? {}
  const kwEntries = Object.entries(allKeywords).sort(
    ([, a], [, b]) => b.pct - a.pct
  )

  // Palette de couleurs pour les mots-clés
  const palette = ['blue', 'violet', 'green', 'amber', 'blue', 'violet', 'green']

  return (
    <div className="flex flex-col flex-1 overflow-y-auto">
      <ErrorBanner message={error} />

      {/* ── En-tête + boutons ── */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-700/50 shrink-0">
        <h3 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
          Régulation des quotas
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={resetting}
            title="Réinitialiser les compteurs du jour"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 border border-slate-200 dark:border-slate-700 transition-colors disabled:opacity-50"
          >
            <RotateCcw size={12} className={resetting ? 'animate-spin' : ''} />
            Réinitialiser
          </button>
          <SaveButton saving={saving} saved={saved} onClick={handleSave} />
        </div>
      </div>

      <div className="flex flex-col gap-6 px-5 py-5">

        {/* ── Activation ── */}
        <div className="flex items-center justify-between p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
          <div>
            <p className="text-sm font-medium text-slate-800 dark:text-slate-200">Activer la régulation</p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Limite le nombre d'articles du jour présents dans 48-heures et déjà intégrés au pipeline</p>
          </div>
          <button
            onClick={() => setConfig(c => ({ ...c, enabled: !c.enabled }))}
            className="text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] transition-colors"
          >
            {config.enabled
              ? <ToggleRight size={28} className="text-[#007AFF] dark:text-[#0A84FF]" />
              : <ToggleLeft  size={28} />}
          </button>
        </div>

        {/* ── Plafonds ── */}
        {config.enabled && (
          <div className="flex flex-col gap-4">
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Plafonds journaliers</p>

            <p className="text-xs text-slate-500 dark:text-slate-400">
              Les quotas sont calculés sur les articles datés d'aujourd'hui présents dans <span className="font-mono">data/articles-from-rss/_WUDD.AI_/48-heures.json</span>.
            </p>

            {/* Global */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Plafond global</label>
                <span className="text-xs text-slate-400">articles du jour dans 48-heures</span>
              </div>
              <input
                type="range" min="10" max="500" step="10"
                value={config.global_daily_limit}
                onChange={e => setConfig(c => ({ ...c, global_daily_limit: +e.target.value }))}
                className="w-full accent-blue-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>10</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">⬦ {config.global_daily_limit} articles</span>
                <span>500</span>
              </div>
            </div>

            {/* Taille du résumé IA */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Taille du résumé IA</label>
                <span className="text-xs text-slate-400">lignes max</span>
              </div>
              <input
                type="range" min="5" max="50" step="5"
                value={config.summary_max_lines ?? 20}
                onChange={e => setConfig(c => ({ ...c, summary_max_lines: +e.target.value }))}
                className="w-full accent-cyan-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>5</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">⬦ {config.summary_max_lines ?? 20} lignes</span>
                <span>50</span>
              </div>
            </div>

            {/* Par mot-clé */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Par mot-clé</label>
                <span className="text-xs text-slate-400">articles du jour / mot-clé / dans 48-heures</span>
              </div>
              <input
                type="range" min="1" max="100" step="1"
                value={config.per_keyword_daily_limit}
                onChange={e => setConfig(c => ({ ...c, per_keyword_daily_limit: +e.target.value }))}
                className="w-full accent-violet-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>1</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">⬦ {config.per_keyword_daily_limit} articles</span>
                <span>100</span>
              </div>
            </div>

            {/* Par source */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Par source</label>
                <span className="text-xs text-slate-400">articles du jour / source / mot-clé / dans 48-heures</span>
              </div>
              <input
                type="range" min="1" max="20" step="1"
                value={config.per_source_daily_limit}
                onChange={e => setConfig(c => ({ ...c, per_source_daily_limit: +e.target.value }))}
                className="w-full accent-green-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>1</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">⬦ {config.per_source_daily_limit} articles</span>
                <span>20</span>
              </div>
            </div>

            {/* Par entité */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Par entité</label>
                <span className="text-xs text-slate-400">articles du jour / entité nommée / dans 48-heures</span>
              </div>
              <input
                type="range" min="1" max="50" step="1"
                value={config.per_entity_daily_limit ?? 10}
                onChange={e => setConfig(c => ({ ...c, per_entity_daily_limit: +e.target.value }))}
                className="w-full accent-amber-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>1</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">⬦ {config.per_entity_daily_limit ?? 10} articles</span>
                <span>50</span>
              </div>
            </div>

            {/* Tri adaptatif */}
            <div className="flex items-center justify-between p-3.5 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
              <div>
                <p className="text-sm text-slate-700 dark:text-slate-300">Tri adaptatif</p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  Priorité aux mots-clés les moins consommés pour équilibrer la diversité
                </p>
              </div>
              <button
                onClick={() => setConfig(c => ({ ...c, adaptive_sorting: !c.adaptive_sorting }))}
                className="text-slate-400 hover:text-green-500 dark:hover:text-green-400 transition-colors"
              >
                {config.adaptive_sorting
                  ? <ToggleRight size={24} className="text-green-500 dark:text-green-400" />
                  : <ToggleLeft  size={24} />}
              </button>
            </div>

            {/* Par passage */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Par passage</label>
                <span className="text-xs text-slate-400">articles du jour / exécution (0 = illimité)</span>
              </div>
              <input
                type="range" min="0" max="100" step="5"
                value={config.per_run_limit ?? 30}
                onChange={e => setConfig(c => ({ ...c, per_run_limit: +e.target.value }))}
                className="w-full accent-orange-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>0</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">
                  ⬦ {(config.per_run_limit ?? 30) === 0 ? 'illimité' : ((config.per_run_limit ?? 30) + ' articles')}
                </span>
                <span>100</span>
              </div>
            </div>

            {/* Source cross-keyword */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm text-slate-700 dark:text-slate-300">Source cross-keyword</label>
                <span className="text-xs text-slate-400">articles du jour / source / dans 48-heures (0 = illimité)</span>
              </div>
              <input
                type="range" min="0" max="50" step="1"
                value={config.global_source_daily_limit ?? 15}
                onChange={e => setConfig(c => ({ ...c, global_source_daily_limit: +e.target.value }))}
                className="w-full accent-teal-500"
              />
              <div className="flex justify-between text-xs text-slate-400">
                <span>0</span>
                <span className="font-semibold text-slate-700 dark:text-slate-200">
                  ⬦ {(config.global_source_daily_limit ?? 15) === 0 ? 'illimité' : ((config.global_source_daily_limit ?? 15) + ' articles')}
                </span>
                <span>50</span>
              </div>
            </div>
          </div>
        )}

        {/* ── Consommation du jour ── */}
        <div className="flex flex-col gap-3">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            Consommation aujourd'hui — {stats?.date ?? '…'}
          </p>

          {/* Global */}
          {stats && (
            <div className="flex flex-col gap-1 p-3.5 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">Global</span>
                {stats.global.exhausted && (
                  <span className="text-xs font-semibold text-rose-500 dark:text-rose-400 flex items-center gap-1">
                    <AlertTriangle size={10} /> Plafond atteint
                  </span>
                )}
              </div>
              <QuotaBar count={stats.global.count} limit={stats.global.limit} color="blue" />
            </div>
          )}

          {/* Par mot-clé */}
          {kwEntries.length > 0 ? (
            <div className="flex flex-col gap-2">
              {kwEntries.map(([kw, data], i) => (
                <div key={kw} className="p-3.5 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate max-w-[60%]">{kw}</span>
                    {data.pct >= 100 && (
                      <span className="text-xs text-rose-500 dark:text-rose-400 font-semibold">Saturé</span>
                    )}
                  </div>
                  <QuotaBar count={data.total} limit={data.limit} color={palette[i % palette.length]} />
                  {Object.keys(data.sources ?? {}).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {Object.entries(data.sources).map(([src, info]) => (
                        <span
                          key={src}
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${
                            info.saturated
                              ? 'bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400'
                              : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
                          }`}
                        >
                          {src} <span className="opacity-60">{info.count}/{info.limit}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400 dark:text-slate-500 italic px-1">
              Aucun article du jour trouvé dans 48-heures.
            </p>
          )}
        </div>

        {/* ── Top entités ── */}
        <div className="flex flex-col gap-3">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            Entités nommées — top {Object.keys(stats?.entities ?? {}).length}
          </p>
          {stats && Object.keys(stats.entities ?? {}).length > 0 ? (
            <div className="flex flex-col gap-2">
              {Object.entries(stats.entities).map(([name, info]) => (
                <div key={name} className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate max-w-[70%]">{name}</span>
                    {info.saturated && (
                      <span className="text-xs font-semibold text-rose-500 dark:text-rose-400 flex items-center gap-1">
                        <AlertTriangle size={10} /> Saturée
                      </span>
                    )}
                  </div>
                  <QuotaBar count={info.count} limit={info.limit} color="amber" />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400 dark:text-slate-500 italic px-1">
              Aucune entité enregistrée aujourd'hui.
            </p>
          )}
        </div>

        {/* ── Sources cross-keyword ── */}
        {stats && Object.keys(stats.global_sources ?? {}).length > 0 && (
          <div className="flex flex-col gap-3">
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Sources cross-keyword du jour — top {Object.keys(stats.global_sources).length}
            </p>
            <div className="flex flex-col gap-2">
              {Object.entries(stats.global_sources).map(([src, info]) => (
                <div key={src} className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate max-w-[70%]">{src}</span>
                    {info.saturated && (
                      <span className="text-xs font-semibold text-rose-500 dark:text-rose-400 flex items-center gap-1">
                        <AlertTriangle size={10} /> Saturée
                      </span>
                    )}
                  </div>
                  <QuotaBar count={info.count} limit={info.limit} color="teal" />
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

// ─── Onglet Variables d'environnement ────────────────────────────────────────

// ─── Onglet Fiabilité des sources ────────────────────────────────────────────

const MBFC_BADGE_SETTINGS = {
  'VERY HIGH':      'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300',
  'HIGH':           'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  'MOSTLY FACTUAL': 'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-300',
  'MIXED':          'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300',
  'LOW':            'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300',
  'VERY LOW':       'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
}

function FiabiliteTab() {
  const [sources, setSources]     = useState([])
  const [loading, setLoading]     = useState(true)
  const [enriching, setEnriching] = useState(false)
  const [enrichLog, setEnrichLog] = useState([])
  const [enrichDone, setEnrichDone] = useState(false)
  const [search, setSearch]       = useState('')
  const logRef = useRef(null)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/sources/credibility')
      .then(r => r.json())
      .then(d => { setSources(Array.isArray(d.sources) ? d.sources : []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { logRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [enrichLog])

  const startEnrich = () => {
    setEnriching(true)
    setEnrichLog([])
    setEnrichDone(false)
    fetch('/api/sources/enrich', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      .then(async r => {
        const reader = r.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const parts = buf.split('\n\n'); buf = parts.pop()
          for (const part of parts) {
            const line = part.replace(/^data: /, '').trim()
            if (!line) continue
            try {
              const obj = JSON.parse(line)
              if (obj.line) setEnrichLog(prev => [...prev, obj.line])
              if (obj.done) { setEnrichDone(true); load() }
            } catch {}
          }
        }
        setEnrichDone(true); setEnriching(false); load()
      })
      .catch(e => { setEnrichLog(prev => [...prev, `Erreur : ${e.message}`]); setEnriching(false); setEnrichDone(true) })
  }

  const enrichedCount = sources.filter(s => s.enrichi).length
  const filtered = sources.filter(s => !search || s.source.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Barre d'actions */}
      <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 flex items-center gap-3 flex-wrap shrink-0">
        <div className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-400">
          <Eye size={14} className="text-blue-500" />
          <span>{enrichedCount}/{sources.length} sources enrichies v2</span>
        </div>
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Filtrer…"
          className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm w-40"
        />
        <button
          onClick={startEnrich}
          disabled={enriching}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] disabled:opacity-60 text-white rounded-lg transition-colors"
        >
          <RefreshCw size={12} className={enriching ? 'animate-spin' : ''} />
          {enriching ? 'Enrichissement…' : 'Actualiser fiabilité'}
        </button>
      </div>

      {/* Log d'enrichissement */}
      {(enriching || enrichDone) && enrichLog.length > 0 && (
        <div className="mx-5 mt-3 bg-slate-950/80 dark:bg-slate-950 rounded-lg border border-slate-700 overflow-hidden shrink-0">
          <div className="px-3 py-1.5 border-b border-slate-700 text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-2">
            <Terminal size={10} />
            Journal d'enrichissement
            {enrichDone && <span className="text-green-400 ml-1">✓ Terminé</span>}
          </div>
          <div className="p-3 font-mono text-[11px] text-green-300 max-h-32 overflow-auto space-y-0.5">
            {enrichLog.slice(-20).map((l, i) => <div key={i}>{l}</div>)}
            <div ref={logRef} />
          </div>
        </div>
      )}

      {/* Notice */}
      {!loading && enrichedCount === 0 && (
        <div className="mx-5 mt-3 p-3 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 rounded-lg text-xs flex items-center gap-2 shrink-0">
          <AlertTriangle size={12} />
          Aucune source enrichie. Cliquez sur "Actualiser fiabilité" pour lancer l'enrichissement WHOIS + MBFC + transparence des 40 sources.
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading ? <Spinner /> : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 sticky top-0">
                <th className="text-left px-5 py-2.5">Source</th>
                <th className="text-center px-4 py-2.5">Score</th>
                <th className="text-center px-4 py-2.5">Âge</th>
                <th className="text-center px-4 py-2.5">Transp.</th>
                <th className="text-center px-4 py-2.5">MBFC</th>
                <th className="text-left px-4 py-2.5 hidden md:table-cell">Pays · Type</th>
                <th className="text-center px-4 py-2.5">Enrichi</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s, i) => (
                <tr key={i} className="border-b border-slate-100 dark:border-slate-700/40 hover:bg-slate-50 dark:hover:bg-slate-700/20 transition-colors">
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-800 dark:text-slate-200 text-sm">{s.source}</div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{s.biais || '—'} · fact-check : {s.fact_checking ? '✓' : '✗'}</div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <div className="flex flex-col items-center gap-0.5">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-semibold tabular-nums ${
                        (s.score_composite ?? s.score) >= 80 ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                        : (s.score_composite ?? s.score) >= 60 ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                        : 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300'
                      }`}>{Math.round(s.score_composite ?? s.score)}</span>
                      {s.enrichi && s.score !== s.score_composite && (
                        <span className="text-[11px] text-slate-400">(base: {s.score})</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center text-xs tabular-nums">
                    {s.domain_age_years != null ? (
                      <span className={s.domain_age_years < 2 ? 'text-orange-500 font-medium' : 'text-slate-500 dark:text-slate-400'}>
                        {s.domain_age_years < 2 && '⚠ '}{s.domain_age_years >= 1 ? `${Math.floor(s.domain_age_years)} ans` : '< 1 an'}
                      </span>
                    ) : <span className="text-slate-400 dark:text-slate-500">—</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {s.transparence != null ? (
                      <span className="flex justify-center gap-0.5">
                        {[0,1,2,3].map(j => (
                          <span key={j} className={`w-2 h-2 rounded-full ${j < s.transparence ? 'bg-blue-500' : 'bg-slate-200 dark:bg-slate-700'}`} />
                        ))}
                      </span>
                    ) : <span className="text-slate-400 dark:text-slate-500 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {s.mbfc_rating ? (
                      <span className={`text-[11px] px-1.5 py-0.5 rounded-full font-medium ${MBFC_BADGE_SETTINGS[s.mbfc_rating] || 'bg-slate-100 text-slate-600'}`}>
                        {s.mbfc_rating}
                      </span>
                    ) : <span className="text-slate-400 dark:text-slate-500 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell">
                    <div className="text-[11px] text-slate-500 dark:text-slate-400">{s.pays || '—'}</div>
                    <div className="text-[11px] text-slate-400 dark:text-slate-500">{s.type || '—'}</div>
                  </td>
                  <td className="px-4 py-3 text-center text-xs">
                    {s.enrichi ? (
                      <span className="text-green-500" title={`Enrichi le ${s.enrich_date}`}>✓ {s.enrich_date}</span>
                    ) : <span className="text-slate-400">En attente</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pied */}
      <div className="px-5 py-2 border-t border-slate-200 dark:border-slate-700 text-xs text-slate-400 dark:text-slate-600 shrink-0">
        Score composite = statique × 0.60 + âge × 0.15 + transparence × 0.10 + MBFC × 0.15 · Enrichissement mensuel automatique (1er du mois, 04h30)
      </div>
    </div>
  )
}

function EnvTab() {
  const [entries, setEntries]     = useState([])
  const [loading, setLoading]     = useState(true)
  const [editKey, setEditKey]     = useState(null)   // clé en cours d'édition
  const [editVal, setEditVal]     = useState('')
  const [newKey, setNewKey]       = useState('')
  const [newVal, setNewVal]       = useState('')
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState(null)
  const [showMasked, setShowMasked] = useState({})   // {key: bool}

  // Check IA : { euria: null | 'checking' | {ok, message, latency_ms}, claude: ..., ollama: ... }
  const [aiCheck, setAiCheck]     = useState({ euria: null, claude: null, ollama: null })

  // Ollama local
  const [ollamaStatus, setOllamaStatus] = useState(null) // null | {available, models, active_model, ner_provider}
  const [ollamaLoading, setOllamaLoading] = useState(false)

  // Check répertoires backup
  const [backupCheck, setBackupCheck] = useState({ l1: null, l2: null }) // null | 'checking' | {ok, message}
  const [backupL1, setBackupL1]   = useState('')
  const [backupL2, setBackupL2]   = useState('')
  const [backupSaving, setBackupSaving] = useState({ l1: false, l2: false })

  // Répertoire Obsidian
  const [obsidianDir, setObsidianDir]       = useState('')
  const [obsidianCheck, setObsidianCheck]   = useState(null) // null | 'checking' | {ok, message}
  const [obsidianSaving, setObsidianSaving] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/env')
      .then(r => r.json())
      .then(d => { setEntries(d); setLoading(false) })
      .catch(() => { setError('Impossible de charger le fichier .env'); setLoading(false) })
  }, [])

  const loadOllamaStatus = useCallback(() => {
    setOllamaLoading(true)
    fetch('/api/ollama/status')
      .then(r => r.json())
      .then(d => { setOllamaStatus(d); setOllamaLoading(false) })
      .catch(() => { setOllamaStatus({ available: false, models: [], active_model: '', ner_provider: '' }); setOllamaLoading(false) })
  }, [])

  useEffect(() => { load(); loadOllamaStatus() }, [load, loadOllamaStatus])

  const saveVar = async (key, value) => {
    setSaving(true)
    setError(null)
    try {
      const r = await fetch('/api/env', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      })
      const text = await r.text()
      let d
      try { d = JSON.parse(text) } catch {
        setError(`Erreur serveur (HTTP ${r.status}) — le backend Flask est-il démarré ? Réponse : ${text.substring(0, 120)}`)
        return
      }
      if (!d.ok) { setError(d.error || 'Erreur inconnue'); return }
      setEditKey(null)
      load()
    } catch (e) {
      setError(`Impossible de joindre le backend Flask (/api/env) : ${String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const deleteVar = async (key) => {
    if (!confirm(`Supprimer la variable ${key} ?`)) return
    try {
      await fetch(`/api/env/${encodeURIComponent(key)}`, { method: 'DELETE' })
      load()
    } catch (e) {
      setError(String(e))
    }
  }

  const addVar = async () => {
    if (!newKey.trim()) return
    await saveVar(newKey.trim(), newVal)
    setNewKey(''); setNewVal('')
  }

  // Initialise les champs backup + obsidian depuis les variables .env
  useEffect(() => {
    const v = entries.filter(e => e.type === 'var')
    const l1  = v.find(e => e.key === 'BACKUP_L1')?.value || ''
    const l2  = v.find(e => e.key === 'BACKUP_L2')?.value || ''
    const obs = v.find(e => e.key === 'OBSIDIAN_DIR')?.value || ''
    if (l1  !== '***') setBackupL1(l1)
    if (l2  !== '***') setBackupL2(l2)
    if (obs !== '***') setObsidianDir(obs)
  }, [entries])

  const checkAI = async (provider) => {
    setAiCheck(prev => ({ ...prev, [provider]: 'checking' }))
    try {
      const r = await fetch('/api/ai-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider }),
      })
      const d = await r.json()
      setAiCheck(prev => ({ ...prev, [provider]: d }))
    } catch (e) {
      setAiCheck(prev => ({ ...prev, [provider]: { ok: false, message: String(e), latency_ms: 0, active_model: '' } }))
    }
  }

  const checkBackupDir = async (level) => {
    const path = level === 'l1' ? backupL1 : backupL2
    if (!path.trim()) return
    setBackupCheck(prev => ({ ...prev, [level]: 'checking' }))
    try {
      const r = await fetch('/api/backup/check-dir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path.trim() }),
      })
      const d = await r.json()
      setBackupCheck(prev => ({ ...prev, [level]: d }))
    } catch (e) {
      setBackupCheck(prev => ({ ...prev, [level]: { ok: false, message: String(e) } }))
    }
  }

  const saveBackupDir = async (level) => {
    const key = level === 'l1' ? 'BACKUP_L1' : 'BACKUP_L2'
    const value = level === 'l1' ? backupL1 : backupL2
    setBackupSaving(prev => ({ ...prev, [level]: true }))
    await saveVar(key, value)
    setBackupSaving(prev => ({ ...prev, [level]: false }))
  }

  const vars = entries.filter(e => e.type === 'var')

  // Fournisseur IA actif
  const currentProvider = vars.find(v => v.key === 'AI_PROVIDER')?.value || 'euria'
  const currentNerProvider = vars.find(v => v.key === 'AI_PROVIDER_NER')?.value || ''
  const currentSummaryProvider = vars.find(v => v.key === 'AI_PROVIDER_SUMMARY')?.value || ''

  // Alerte si configuration incomplète
  const missingConfig = (() => {
    if (currentProvider === 'claude') {
      const apiKeyEntry = vars.find(v => v.key === 'ANTHROPIC_API_KEY')
      return !apiKeyEntry || (!apiKeyEntry.masked && !apiKeyEntry.value?.trim())
    } else {
      const urlEntry = vars.find(v => v.key === 'URL')
      const bearerEntry = vars.find(v => v.key === 'bearer')
      return !urlEntry?.value?.trim() || !bearerEntry
    }
  })()

  // Groupes visuels : { label, keys, provider }
  const ENV_GROUPS = [
    { label: 'IA EurIA (Infomaniak)', keys: ['URL', 'bearer'], provider: 'euria' },
    { label: 'IA Claude (Anthropic)', keys: ['ANTHROPIC_API_KEY', 'CLAUDE_MODEL_BATCH', 'CLAUDE_MODEL_SYNTHESIS'], provider: 'claude' },
    { label: 'IA Locale — Ollama (NER/Sentiment batch)', keys: ['AI_PROVIDER_NER', 'OLLAMA_MODEL'], provider: 'ollama' },
    { label: 'IA Locale — Ollama (Résumés d’articles)', keys: ['AI_PROVIDER_SUMMARY'], provider: 'ollama' },
  ]
  // AI_PROVIDER est géré par le sélecteur — exclure de la table générique
  const groupedKeys = [...ENV_GROUPS.flatMap(g => g.keys), 'AI_PROVIDER']

  // Clés considérées sensibles côté frontend (masquées par défaut)
  const _SENSITIVE_FRONT = new Set(['bearer', 'ANTHROPIC_API_KEY', 'SMTP_PASSWORD', 'NTFY_TOKEN'])
  const isSensitiveFront = k => _SENSITIVE_FRONT.has(k) || k.endsWith('_KEY') || k.endsWith('_TOKEN') || k.endsWith('_PASSWORD')

  // Rendu d'une ligne de variable
  const renderVarRow = ({ key, value, masked }) => (
    <tr key={key} className="border-b border-slate-200/40 dark:border-slate-700/40 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors group">
      <td className="px-5 py-2.5">
        <span className="font-mono text-xs text-slate-700 dark:text-slate-300">{key}</span>
        {masked && <Lock size={10} className="inline ml-1.5 text-amber-500" />}
      </td>
      <td className="px-4 py-2.5">
        {editKey === key ? (
          <div className="flex items-center gap-2">
            <input
              type={masked && !showMasked[key] ? 'password' : 'text'}
              value={editVal}
              onChange={e => setEditVal(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') saveVar(key, editVal); if (e.key === 'Escape') setEditKey(null) }}
              className="flex-1 bg-white dark:bg-slate-900 border border-blue-400 rounded-lg px-2 py-1 text-xs font-mono focus:outline-none"
              autoFocus
            />
            <button onClick={() => saveVar(key, editVal)} disabled={saving}
              className="p-1 text-green-600 hover:text-green-500 disabled:opacity-50">
              <Check size={14} />
            </button>
            <button onClick={() => setEditKey(null)} className="p-1 text-slate-400 hover:text-slate-600">
              <X size={14} />
            </button>
          </div>
        ) : (
          <span className="font-mono text-xs text-slate-600 dark:text-slate-400 break-all">
            {masked && !showMasked[key]
              ? (value ? '•••••••••••' : <em className="text-slate-400 text-[11px]">non configurée</em>)
              : (value || <em className="text-slate-400">vide</em>)}
          </span>
        )}
      </td>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-1 justify-end">
          {masked && (
            <button onClick={() => setShowMasked(s => ({ ...s, [key]: !s[key] }))}
              title={showMasked[key] ? 'Masquer' : 'Afficher'}
              className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg">
              {showMasked[key] ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          )}
          <button onClick={() => { setEditKey(key); setEditVal(masked ? '' : value) }}
            title="Modifier"
            className="p-1 text-slate-400 hover:text-blue-500 rounded-lg">
            <Pencil size={13} />
          </button>
          <button onClick={() => deleteVar(key)}
            title="Supprimer"
            className="p-1 text-slate-400 hover:text-red-500 rounded-lg">
            <Trash2 size={13} />
          </button>
        </div>
      </td>
    </tr>
  )

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <ErrorBanner message={error} />

      {/* Sélecteur de fournisseur IA */}
      <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-800/30 shrink-0">
        <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 mb-3 uppercase tracking-wider">
          Fournisseur IA actif
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          {[
            { value: 'euria',  label: `EurIA · Infomaniak${vars.find(v => v.key === 'EURIA_MODEL')?.value ? ' / ' + vars.find(v => v.key === 'EURIA_MODEL').value : ''}` },
            { value: 'claude', label: 'Claude · Anthropic' },
          ].map(opt => (
            <button
              key={opt.value}
              onClick={() => saveVar('AI_PROVIDER', opt.value)}
              disabled={saving}
              className={`px-4 py-2 rounded-lg text-xs font-medium border transition-colors ${
                currentProvider === opt.value
                  ? 'bg-[#007AFF] dark:bg-[#0A84FF] text-white border-[#007AFF] shadow-sm'
                  : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-600 hover:border-[#007AFF] hover:text-[#007AFF] dark:hover:text-[#0A84FF]'
              }`}
            >
              {currentProvider === opt.value && <span className="mr-1">●</span>}
              {opt.label}
            </button>
          ))}
        </div>

        {/* Sélecteur NER local (Ollama) */}
        <div className="mt-4 pt-3 border-t border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Cpu size={11} /> NER · Sentiment batch
              <span className="text-[10px] font-normal text-slate-400 normal-case tracking-normal">(enrich_entities / enrich_sentiment)</span>
            </p>
            {/* Pill statut Ollama */}
            <div className="flex items-center gap-1.5">
              {ollamaLoading
                ? <span className="text-[11px] text-slate-400 flex items-center gap-1"><RefreshCw size={10} className="animate-spin" /> …</span>
                : ollamaStatus?.available
                  ? <span className="text-[11px] text-[#1a7a34] dark:text-[#30D158] flex items-center gap-1"><CheckCircle2 size={11} /> Ollama actif · {ollamaStatus.models.length} modèle{ollamaStatus.models.length !== 1 ? 's' : ''}</span>
                  : <span className="text-[11px] text-orange-500 flex items-center gap-1"><AlertTriangle size={11} /> Ollama hors ligne</span>
              }
              <button
                onClick={loadOllamaStatus}
                disabled={ollamaLoading}
                title="Rafraîchir le statut Ollama"
                className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 disabled:opacity-40 rounded transition-colors"
              >
                <RefreshCw size={10} className={ollamaLoading ? 'animate-spin' : ''} />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {[
              { value: '',       label: 'Cloud (AI_PROVIDER)', desc: 'Utilise EurIA ou Claude' },
              { value: 'ollama', label: 'Ollama local', desc: ollamaStatus?.available ? `${ollamaStatus.active_model}` : 'Serveur non détecté' },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => saveVar('AI_PROVIDER_NER', opt.value)}
                disabled={saving || (opt.value === 'ollama' && !ollamaStatus?.available)}
                title={opt.desc}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  currentNerProvider === opt.value
                    ? opt.value === 'ollama'
                      ? 'bg-emerald-600 dark:bg-emerald-500 text-white border-emerald-600 shadow-sm'
                      : 'bg-[#007AFF] dark:bg-[#0A84FF] text-white border-[#007AFF] shadow-sm'
                    : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-600 hover:border-slate-400'
                }`}
              >
                {currentNerProvider === opt.value && <span className="mr-1">●</span>}
                {opt.value === 'ollama' && <Cpu size={10} className="inline mr-1" />}
                {opt.label}
              </button>
            ))}
          </div>
          {/* Modèles disponibles */}
          {ollamaStatus?.available && ollamaStatus.models.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ollamaStatus.models.map(m => (
                <button
                  key={m}
                  onClick={() => saveVar('OLLAMA_MODEL', m)}
                  className={`px-2 py-0.5 rounded-md text-[11px] font-mono border transition-colors ${
                    (ollamaStatus.active_model === m || vars.find(v => v.key === 'OLLAMA_MODEL')?.value === m)
                      ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700'
                      : 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-600 hover:border-slate-400'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
          {!ollamaStatus?.available && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1.5 flex items-start gap-1">
              <AlertTriangle size={10} className="mt-0.5 shrink-0 text-orange-400" />
              Pour activer : <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">brew services start ollama</code> puis <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">ollama pull qwen2.5:7b</code>
            </p>
          )}
        </div>

        {/* Sélecteur Résumés d'articles (Ollama) */}
        <div className="mt-4 pt-3 border-t border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Cpu size={11} /> Résumés d'articles
              <span className="text-[10px] font-normal text-slate-400 normal-case tracking-normal">(flux_watcher / get-keyword-from-rss / web_watcher)</span>
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {[
              { value: '',       label: 'Cloud (AI_PROVIDER)', desc: 'Utilise EurIA ou Claude' },
              { value: 'ollama', label: 'Ollama local', desc: ollamaStatus?.available ? `${ollamaStatus.active_model}` : 'Serveur non détecté' },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => saveVar('AI_PROVIDER_SUMMARY', opt.value)}
                disabled={saving || (opt.value === 'ollama' && !ollamaStatus?.available)}
                title={opt.desc}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  currentSummaryProvider === opt.value
                    ? opt.value === 'ollama'
                      ? 'bg-emerald-600 dark:bg-emerald-500 text-white border-emerald-600 shadow-sm'
                      : 'bg-[#007AFF] dark:bg-[#0A84FF] text-white border-[#007AFF] shadow-sm'
                    : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-600 hover:border-slate-400'
                }`}
              >
                {currentSummaryProvider === opt.value && <span className="mr-1">●</span>}
                {opt.value === 'ollama' && <Cpu size={10} className="inline mr-1" />}
                {opt.label}
              </button>
            ))}
          </div>
          {!ollamaStatus?.available && (
            <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1.5 flex items-start gap-1">
              <AlertTriangle size={10} className="mt-0.5 shrink-0 text-orange-400" />
              Ollama requis — <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">brew services start ollama</code>
            </p>
          )}
        </div>
      </div>

      {/* Contenu scrollable — alertes, variables, backup, obsidian, footer */}
      <div className="flex-1 overflow-auto">

      {/* Alerte configuration incomplète */}
      {!loading && missingConfig && (
        <div className="px-5 py-2.5 border-b border-orange-200 dark:border-orange-800/50 bg-orange-50/70 dark:bg-orange-900/10">
          <p className="text-xs text-orange-700 dark:text-orange-400 flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            {currentProvider === 'claude'
              ? 'Claude est sélectionné mais ANTHROPIC_API_KEY est vide. Les traitements IA échoueront jusqu\'à ce que la clé soit renseignée.'
              : 'EurIA est sélectionné mais URL ou bearer est vide. Les traitements IA échoueront jusqu\'à ce que les champs soient renseignés.'}
          </p>
        </div>
      )}

      <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700 bg-amber-50/50 dark:bg-amber-900/10">
        <p className="text-xs text-amber-700 dark:text-amber-400 flex items-start gap-1.5">
          <Lock size={12} className="mt-0.5 shrink-0" />
          Variables sensibles (clés d'API, mots de passe) sont masquées. Les modifications sont écrites dans le fichier <code>.env</code> à la racine du projet.
        </p>
      </div>

      <div>
        {loading ? <Spinner /> : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider border-b border-slate-200/50 dark:border-slate-700/50">
                <th className="text-left px-5 py-2.5 w-1/3">Variable</th>
                <th className="text-left px-4 py-2.5">Valeur</th>
                <th className="px-4 py-2.5 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {/* Groupes visuels — groupe actif mis en évidence, groupe inactif grisé */}
              {ENV_GROUPS.map(group => {
                // Toujours afficher toutes les clés du groupe, même si absentes du .env
                const groupVars = group.keys.map(k =>
                  vars.find(v => v.key === k) ?? { key: k, value: '', masked: isSensitiveFront(k), _missing: true }
                )
                // Le groupe Ollama est "actif" si AI_PROVIDER_NER=ollama
                const isActive = group.provider === 'ollama'
                  ? currentNerProvider === 'ollama'
                  : group.provider === currentProvider
                // Pour Ollama : statut disponibilité au lieu du simple check
                const isOllama  = group.provider === 'ollama'
                const checkState = isOllama
                  ? (ollamaStatus ? (ollamaStatus.available ? { ok: true, message: `${ollamaStatus.models.length} modèle(s)` } : { ok: false, message: 'Serveur hors ligne' }) : null)
                  : aiCheck[group.provider]
                return (
                  <Fragment key={group.label}>
                    <tr className={isActive
                      ? 'bg-blue-50/60 dark:bg-blue-900/15 border-l-2 border-blue-400'
                      : 'bg-slate-100/40 dark:bg-slate-800/40 opacity-50'}>
                      <td colSpan={3} className="px-5 py-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`text-[11px] font-semibold uppercase tracking-wider ${
                            isActive ? 'text-[#007AFF] dark:text-[#0A84FF]' : 'text-slate-500 dark:text-slate-400'
                          }`}>
                            {group.label}{isActive && ' ✓'}
                          </span>
                          {/* Bouton Check IA */}
                          <div className="flex items-center gap-2">
                            {checkState && checkState !== 'checking' && !isOllama && (
                              <span className={`text-[11px] flex items-center gap-1 ${checkState.ok ? 'text-[#1a7a34] dark:text-[#30D158]' : 'text-red-500 dark:text-red-400'}`}>
                                {checkState.ok
                                  ? <><CheckCircle2 size={11} /> OK {checkState.active_model ? `· ${checkState.active_model}` : ''}{checkState.latency_ms > 0 ? ` · ${checkState.latency_ms}ms` : ''}</>
                                  : <><AlertTriangle size={11} /> {checkState.message.slice(0, 60)}</>
                                }
                              </span>
                            )}
                            {isOllama && ollamaStatus && (
                              <span className={`text-[11px] flex items-center gap-1 ${ollamaStatus.available ? 'text-[#1a7a34] dark:text-[#30D158]' : 'text-orange-500 dark:text-orange-400'}`}>
                                {ollamaStatus.available
                                  ? <><CheckCircle2 size={11} /> Actif · {ollamaStatus.active_model}</>
                                  : <><AlertTriangle size={11} /> Hors ligne</>
                                }
                              </span>
                            )}
                            <button
                              onClick={() => isOllama ? loadOllamaStatus() : checkAI(group.provider)}
                              disabled={isOllama ? ollamaLoading : checkState === 'checking'}
                              className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-medium border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:border-[#007AFF] hover:text-[#007AFF] dark:hover:text-[#0A84FF] disabled:opacity-50 transition-colors"
                            >
                              {(isOllama ? ollamaLoading : checkState === 'checking')
                                ? <><RefreshCw size={10} className="animate-spin" /> Test…</>
                                : <><Check size={10} /> Check</>
                              }
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                    {groupVars.map(v => renderVarRow(v))}
                  </Fragment>
                )
              })}

              {/* Variables hors groupes */}
              {vars.filter(v => !groupedKeys.includes(v.key)).map(v => renderVarRow(v))}

              {/* Ligne d'ajout */}
              <tr className="border-t-2 border-slate-200 dark:border-slate-700">
                <td className="px-5 py-3">
                  <input
                    type="text"
                    value={newKey}
                    onChange={e => setNewKey(e.target.value)}
                    placeholder="NOM_VARIABLE"
                    className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-1.5 text-xs font-mono focus:outline-none focus:border-blue-400"
                  />
                </td>
                <td className="px-4 py-3">
                  <input
                    type="text"
                    value={newVal}
                    onChange={e => setNewVal(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && addVar()}
                    placeholder="valeur"
                    className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-1.5 text-xs font-mono focus:outline-none focus:border-blue-400"
                  />
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={addVar}
                    disabled={!newKey.trim() || saving}
                    className="flex items-center gap-1 px-3 py-1.5 bg-[#007AFF] dark:bg-[#0A84FF] text-white text-xs rounded-lg hover:bg-[#0071EB] disabled:opacity-40 transition-colors"
                  >
                    <Plus size={12} /> Ajouter
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>

      {/* ── Section Backup ───────────────────────────────────────────────── */}
      <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/20">
        <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1.5">
          <Database size={11} /> Backup des données
        </p>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mb-3 leading-relaxed">
          Copie automatique de <code className="text-xs bg-slate-100 dark:bg-slate-700 px-1 rounded">data/</code> vers les répertoires ci-dessous chaque nuit à 01h00.
          L1 est mis à jour en premier, L2 reçoit ensuite une copie de L1.
          En Docker, montez les chemins comme volumes supplémentaires.
        </p>
        {[
          { key: 'l1', label: 'Backup L1 (principal)', varKey: 'BACKUP_L1', val: backupL1, setVal: setBackupL1 },
          { key: 'l2', label: 'Backup L2 (secondaire)', varKey: 'BACKUP_L2', val: backupL2, setVal: setBackupL2 },
        ].map(({ key, label, varKey, val, setVal }) => {
          const chk = backupCheck[key]
          return (
            <div key={key} className="mb-3">
              <label className="text-[11px] text-slate-600 dark:text-slate-400 font-medium block mb-1">{label}</label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={val}
                  onChange={e => { setVal(e.target.value); setBackupCheck(prev => ({ ...prev, [key]: null })) }}
                  onKeyDown={e => e.key === 'Enter' && saveBackupDir(key)}
                  placeholder={`/chemin/absolu/backup-${key}`}
                  className="flex-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-blue-400"
                />
                <button
                  onClick={() => checkBackupDir(key)}
                  disabled={!val.trim() || chk === 'checking'}
                  title="Vérifier l'accessibilité du répertoire"
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:border-[#007AFF] hover:text-[#007AFF] dark:hover:text-[#0A84FF] disabled:opacity-40 transition-colors"
                >
                  {chk === 'checking'
                    ? <RefreshCw size={11} className="animate-spin" />
                    : <Check size={11} />
                  }
                  Check
                </button>
                <button
                  onClick={() => saveBackupDir(key)}
                  disabled={!val.trim() || backupSaving[key]}
                  title="Sauvegarder dans .env"
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-[#007AFF] dark:bg-[#0A84FF] text-white hover:bg-[#0071EB] disabled:opacity-40 transition-colors"
                >
                  {backupSaving[key] ? <RefreshCw size={11} className="animate-spin" /> : <Save size={11} />}
                </button>
              </div>
              {chk && chk !== 'checking' && (
                <p className={`text-[11px] mt-1 flex items-center gap-1 ${chk.ok ? 'text-[#1a7a34] dark:text-[#30D158]' : 'text-red-500 dark:text-red-400'}`}>
                  {chk.ok ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
                  {chk.message}
                </p>
              )}
            </div>
          )
        })}
      </div>

      {/* ── Section Obsidian ─────────────────────────────────────────────── */}
      <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-700 bg-violet-50/30 dark:bg-violet-900/10">
        <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1.5">
          <BookOpen size={11} /> Export Obsidian
        </p>
        <p className="text-[11px] text-slate-500 dark:text-slate-400 mb-3 leading-relaxed">
          Répertoire cible pour l'export des rapports vers Obsidian (<code className="text-xs bg-slate-100 dark:bg-slate-700 px-1 rounded">OBSIDIAN_DIR</code>).
          En Docker, montez ce chemin comme volume supplémentaire.
        </p>
        <div className="mb-1">
          <label className="text-[11px] text-slate-600 dark:text-slate-400 font-medium block mb-1">
            Répertoire Obsidian
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={obsidianDir}
              onChange={e => { setObsidianDir(e.target.value); setObsidianCheck(null) }}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  setObsidianSaving(true)
                  saveVar('OBSIDIAN_DIR', obsidianDir).finally(() => setObsidianSaving(false))
                }
              }}
              placeholder="/chemin/absolu/vers/vault-obsidian"
              className="flex-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-violet-400"
            />
            <button
              onClick={async () => {
                if (!obsidianDir.trim()) return
                setObsidianCheck('checking')
                try {
                  const r = await fetch('/api/backup/check-dir', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: obsidianDir.trim() }),
                  })
                  setObsidianCheck(await r.json())
                } catch (e) {
                  setObsidianCheck({ ok: false, message: String(e) })
                }
              }}
              disabled={!obsidianDir.trim() || obsidianCheck === 'checking'}
              title="Vérifier l'accessibilité du répertoire"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:border-violet-400 hover:text-[#5856D6] dark:hover:text-[#5E5CE6] disabled:opacity-40 transition-colors"
            >
              {obsidianCheck === 'checking'
                ? <RefreshCw size={11} className="animate-spin" />
                : <Check size={11} />
              }
              Check
            </button>
            <button
              onClick={async () => {
                if (!obsidianDir.trim()) return
                setObsidianSaving(true)
                await saveVar('OBSIDIAN_DIR', obsidianDir)
                setObsidianSaving(false)
              }}
              disabled={!obsidianDir.trim() || obsidianSaving}
              title="Sauvegarder dans .env"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-40 transition-colors"
            >
              {obsidianSaving ? <RefreshCw size={11} className="animate-spin" /> : <Save size={11} />}
            </button>
          </div>
          {obsidianCheck && obsidianCheck !== 'checking' && (
            <p className={`text-[11px] mt-1 flex items-center gap-1 ${obsidianCheck.ok ? 'text-[#1a7a34] dark:text-[#30D158]' : 'text-red-500 dark:text-red-400'}`}>
              {obsidianCheck.ok ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
              {obsidianCheck.message}
            </p>
          )}
        </div>
        <p className="text-[11px] text-[#5856D6] dark:text-[#5E5CE6] mt-2 flex items-start gap-1">
          <BookOpen size={10} className="mt-0.5 shrink-0" />
          En Docker : ajoutez <code className="bg-violet-100 dark:bg-violet-900/50 px-1 rounded">- /votre/vault:/obsidian</code> dans <code className="bg-violet-100 dark:bg-violet-900/50 px-1 rounded">docker-compose.yml</code>, puis définissez <code className="bg-violet-100 dark:bg-violet-900/50 px-1 rounded">OBSIDIAN_DIR=/obsidian</code>.
        </p>
      </div>

      {/* Footer */}
      <div className="px-5 py-2 border-t border-slate-200 dark:border-slate-700 flex justify-end">
        <button onClick={load} className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 border border-slate-200 dark:border-slate-700 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
          <RefreshCw size={11} /> Actualiser
        </button>
      </div>

      </div>{/* fin contenu scrollable */}
    </div>
  )
}

// ─── Panneau principal Réglages ───────────────────────────────────────────────

// ─── Onglet Sources Web (sites sans RSS, scraping sitemap) ───────────────────

function WebSourcesTab() {
  const [sources, setSources]         = useState(null)
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(null)
  const [isDirty, setIsDirty]         = useState(false)
  const [saving, setSaving]           = useState(false)
  const [saveMsg, setSaveMsg]         = useState(null)
  const [checking, setChecking]       = useState(new Set())  // names en cours de vérif
  const [results, setResults]         = useState({})         // name → true|false
  const [checkingAll, setCheckingAll] = useState(false)
  const [stateInfo, setStateInfo]     = useState({})         // name → nb URLs traitées
  const [showAddForm, setShowAddForm] = useState(false)
  const [addUrl, setAddUrl]           = useState('')
  const [addPattern, setAddPattern]   = useState('')
  const [addKeyword, setAddKeyword]   = useState('')
  const [addTitle, setAddTitle]       = useState('')
  const [addSitemap, setAddSitemap]   = useState('')
  const [addBaseUrl, setAddBaseUrl]   = useState('')
  const [addMsg, setAddMsg]           = useState(null)  // {state, text}
  const [resolving, setResolving]     = useState(false)
  const addUrlRef                     = useRef(null)

  // — Édition inline d'une source existante —
  const [editingName, setEditingName] = useState(null)   // name de la source en cours d'édition
  const [editFields, setEditFields]   = useState({})     // champs éditables

  const startEdit = useCallback((src) => {
    setEditingName(src.name)
    setEditFields({
      title:       src.title       || '',
      base_url:    src.base_url    || '',
      sitemap_url: src.sitemap_url || '',
      url_pattern: src.url_pattern || '',
      keyword:     src.keyword     || '',
    })
  }, [])

  const cancelEdit = useCallback(() => {
    setEditingName(null)
    setEditFields({})
  }, [])

  const saveEdit = useCallback(() => {
    if (!editingName) return
    setSources(prev => prev.map(s => {
      if (s.name !== editingName) return s
      const newSlug = editFields.title
        ? editFields.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
        : s.name
      return {
        ...s,
        name:        newSlug,
        title:       editFields.title,
        base_url:    editFields.base_url,
        sitemap_url: editFields.sitemap_url,
        url_pattern: editFields.url_pattern,
        keyword:     editFields.keyword,
      }
    }))
    setIsDirty(true)
    setEditingName(null)
    setEditFields({})
  }, [editingName, editFields])

  useEffect(() => {
    Promise.all([
      fetch('/api/web-sources').then(r => r.json()),
      fetch('/api/web-sources/state').then(r => r.json()).catch(() => ({})),
    ]).then(([srcs, st]) => {
      setSources(Array.isArray(srcs) ? srcs : [])
      setStateInfo(typeof st === 'object' && !st.error ? st : {})
      setLoading(false)
    }).catch(() => { setError('Impossible de charger les sources web'); setLoading(false) })
  }, [])

  const removeSource = useCallback((name) => {
    setSources(prev => prev.filter(s => s.name !== name))
    setIsDirty(true)
  }, [])

  const toggleActive = useCallback((name) => {
    setSources(prev => prev.map(s => s.name === name ? { ...s, actif: !s.actif } : s))
    setIsDirty(true)
  }, [])

  const checkOne = useCallback(async (source) => {
    const url = source.sitemap_url || source.base_url
    setChecking(prev => new Set([...prev, source.name]))
    try {
      const r = await fetch('/api/web-sources/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      })
      const data = await r.json()
      setResults(prev => ({ ...prev, [source.name]: !!data.ok }))
    } catch {
      setResults(prev => ({ ...prev, [source.name]: false }))
    } finally {
      setChecking(prev => { const s = new Set(prev); s.delete(source.name); return s })
    }
  }, [])

  const checkAll = useCallback(async () => {
    if (!sources || checkingAll) return
    setCheckingAll(true)
    setResults({})
    for (const s of sources) await checkOne(s)
    setCheckingAll(false)
  }, [sources, checkingAll, checkOne])

  const handleResolve = useCallback(async () => {
    const url = addUrl.trim()
    if (!url.startsWith('http')) {
      setAddMsg({ state: 'error', text: `URL invalide : "${url.slice(0, 60)}"` })
      return
    }
    setResolving(true)
    setAddMsg({ state: 'checking', text: `Résolution de ${url}…` })
    try {
      const r = await fetch('/api/web-sources/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      })
      const data = await r.json()
      if (data.ok) {
        setAddTitle(data.title || '')
        setAddBaseUrl(data.base_url || '')
        setAddSitemap(data.sitemap_url || '')
        setAddMsg({ state: 'ok', text: `Site résolu : « ${data.title} »${data.sitemap_url ? '' : ' — sitemap non détecté, à saisir manuellement'}` })
      } else {
        setAddMsg({ state: 'error', text: data.error || 'Impossible de résoudre ce site' })
      }
    } catch (e) {
      setAddMsg({ state: 'error', text: String(e) })
    } finally {
      setResolving(false)
    }
  }, [addUrl])

  const handleAdd = useCallback(() => {
    if (!addTitle || !addBaseUrl || !addPattern || !addKeyword) {
      setAddMsg({ state: 'error', text: 'Tous les champs sont requis.' })
      return
    }
    const slug = addTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    const newSource = {
      name: slug,
      title: addTitle,
      base_url: addBaseUrl,
      sitemap_url: addSitemap,
      url_pattern: addPattern,
      keyword: addKeyword,
      langue: 'fr',
      max_per_run: 5,
      actif: true,
    }
    setSources(prev => [...(prev || []), newSource])
    setIsDirty(true)
    setShowAddForm(false)
    setAddUrl(''); setAddTitle(''); setAddBaseUrl(''); setAddSitemap('')
    setAddPattern(''); setAddKeyword(''); setAddMsg(null)
  }, [addTitle, addBaseUrl, addSitemap, addPattern, addKeyword])

  const saveSources = useCallback(async () => {
    if (!sources || saving) return
    setSaving(true)
    setSaveMsg(null)
    try {
      const r = await fetch('/api/web-sources/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sources),
      })
      const data = await r.json()
      if (data.ok) {
        setSaveMsg({ ok: true, text: `${data.count} source(s) sauvegardée(s) dans web_sources.json` })
        setIsDirty(false)
      } else {
        setSaveMsg({ ok: false, text: data.error || 'Erreur lors de la sauvegarde' })
      }
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) })
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMsg(null), 4000)
    }
  }, [sources, saving])

  if (loading) return <Spinner />

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Barre d'outils */}
      <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0 flex-wrap">
        <Globe size={12} className="text-slate-400 dark:text-slate-500 shrink-0" />
        <p className="text-xs text-slate-400 dark:text-slate-500 flex-1 min-w-0">
          {sources
            ? <><span className="font-medium text-slate-600 dark:text-slate-300">{sources.length}</span> source{sources.length !== 1 ? 's' : ''} web</>
            : 'Sources web'}
        </p>
        {/* Ajouter */}
        <button
          onClick={() => {
            setShowAddForm(v => !v)
            setAddMsg(null)
            setTimeout(() => addUrlRef.current?.focus(), 50)
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors
            ${showAddForm
              ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 border border-blue-400/40'
              : 'bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200'}`}
          title="Ajouter une source web"
        >
          <Plus size={11} />
          <span className="hidden sm:inline">Ajouter</span>
        </button>
        {/* Vérifier tout */}
        <button
          onClick={checkAll}
          disabled={checkingAll || !sources?.length}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors disabled:opacity-40
            bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200"
          title="Vérifier l'accessibilité de toutes les sources"
        >
          {checkingAll ? <RefreshCw size={11} className="animate-spin" /> : <Check size={11} />}
          <span className="hidden sm:inline">Vérifier</span>
        </button>
        {/* Sauver */}
        <button
          onClick={saveSources}
          disabled={!isDirty || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors disabled:opacity-40
            bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white"
          title="Sauvegarder dans config/web_sources.json"
        >
          {saving ? <RefreshCw size={11} className="animate-spin" /> : <Save size={11} />}
          <span className="hidden sm:inline">Sauver</span>
        </button>
      </div>

      {/* Formulaire d'ajout */}
      {showAddForm && (
        <div className="mx-5 mt-3 p-4 rounded-xl border border-blue-200 dark:border-blue-700/50 bg-blue-50/60 dark:bg-blue-900/10 space-y-2.5 shrink-0">
          <p className="text-xs font-semibold text-blue-700 dark:text-blue-300 flex items-center gap-1.5">
            <Globe size={12} /> Ajouter une source web
          </p>
          {/* Étape 1 : URL du site */}
          <div className="flex gap-2">
            <input
              ref={addUrlRef}
              type="url"
              value={addUrl}
              onChange={e => { setAddUrl(e.target.value); setAddMsg(null) }}
              onKeyDown={e => { if (e.key === 'Enter') handleResolve() }}
              placeholder="URL du site (ex: https://www.example.com/news)"
              className="flex-1 min-w-0 px-3 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors"
            />
            <button
              onClick={handleResolve}
              disabled={!addUrl.trim() || resolving}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium bg-slate-200 hover:bg-slate-300 dark:bg-slate-600 dark:hover:bg-slate-500 text-slate-700 dark:text-slate-200 disabled:opacity-40 transition-colors shrink-0"
            >
              {resolving ? <RefreshCw size={11} className="animate-spin" /> : <ExternalLink size={11} />}
              Résoudre
            </button>
          </div>

          {addMsg && (
            <div className={`px-3 py-1.5 rounded-lg text-xs flex items-center gap-2 ${
              addMsg.state === 'checking' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
              : addMsg.state === 'ok'     ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
              :                             'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
              {addMsg.state === 'checking' && <RefreshCw size={11} className="animate-spin shrink-0" />}
              {addMsg.state === 'ok'       && <CheckCircle2 size={11} className="shrink-0" />}
              {addMsg.state === 'error'    && <AlertTriangle size={11} className="shrink-0" />}
              <span className="truncate">{addMsg.text}</span>
            </div>
          )}

          {/* Étape 2 : détails (visibles après résolution) */}
          {addBaseUrl && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">Titre</label>
                  <input type="text" value={addTitle} onChange={e => setAddTitle(e.target.value)}
                    placeholder="Nom affiché"
                    className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors" />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">Mot-clé (bucket)</label>
                  <input type="text" value={addKeyword} onChange={e => setAddKeyword(e.target.value)}
                    placeholder="ex: Anthropic, MoMA, Louvre"
                    className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">URL sitemap</label>
                  <input type="url" value={addSitemap} onChange={e => setAddSitemap(e.target.value)}
                    placeholder="https://…/sitemap.xml"
                    className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors" />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">Pattern URL (regex)</label>
                  <input type="text" value={addPattern} onChange={e => setAddPattern(e.target.value)}
                    placeholder="ex: /news/  ou  /en/programs/\d+"
                    className="w-full px-2.5 py-1.5 text-xs font-mono bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors" />
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-1">
                <button onClick={() => { setShowAddForm(false); setAddUrl(''); setAddTitle(''); setAddBaseUrl(''); setAddSitemap(''); setAddPattern(''); setAddKeyword(''); setAddMsg(null) }}
                  className="px-3 py-1.5 text-xs rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
                  Annuler
                </button>
                <button
                  onClick={handleAdd}
                  disabled={!addTitle || !addBaseUrl || !addPattern || !addKeyword}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white disabled:opacity-40 transition-colors"
                >
                  <Plus size={11} /> Ajouter la source
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {saveMsg && (
        <div className={`mx-5 mt-3 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${saveMsg.ok ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
          {saveMsg.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
          {saveMsg.text}
        </div>
      )}

      <ErrorBanner message={error} />

      {/* Liste des sources */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {!sources || sources.length === 0 ? (
          <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-sm">
            Aucune source web configurée. Cliquez sur «&nbsp;Ajouter&nbsp;» pour commencer.
          </div>
        ) : sources.map((src) => {
          const isChecking = checking.has(src.name)
          const result = results[src.name]
          const processed = stateInfo[src.name] ?? null
          const domain = (() => { try { return new URL(src.base_url || src.html_url || '').hostname.replace(/^www\./, '') } catch { return src.base_url || '' } })()
          const isEditing = editingName === src.name
          return (
            <div key={src.name} className={`rounded-xl border transition-colors group
              ${result === false ? 'border-red-200 dark:border-red-700/40 bg-red-50/40 dark:bg-red-900/10'
                : isEditing ? 'border-blue-300 dark:border-blue-600/60 bg-blue-50/40 dark:bg-blue-900/10'
                : src.actif ? 'border-slate-200 dark:border-slate-700/50 bg-white/70 dark:bg-slate-800/40'
                : 'border-slate-200/60 dark:border-slate-700/30 bg-slate-50/60 dark:bg-slate-800/20 opacity-60'}`}>

              {/* Ligne principale */}
              <div className="flex items-start gap-3 p-3">
                {/* Icône */}
                <Globe size={14} className={`mt-0.5 shrink-0 ${src.actif ? 'text-[#007AFF] dark:text-[#0A84FF]' : 'text-slate-400'}`} />

                {/* Infos */}
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">{src.title}</span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded-md bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-300 font-medium shrink-0">
                      {src.keyword}
                    </span>
                    {!src.actif && (
                      <span className="text-[11px] px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-slate-700 text-slate-400 shrink-0">
                        inactif
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 dark:text-slate-500 truncate">{domain}</div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <code className="text-[11px] text-slate-500 dark:text-slate-400 font-mono bg-slate-100 dark:bg-slate-700/60 px-1.5 py-0.5 rounded">
                      {src.url_pattern}
                    </code>
                    {processed !== null && (
                      <span className="text-[11px] text-slate-400 dark:text-slate-500 flex items-center gap-1">
                        <CheckCircle2 size={9} className="text-green-500" />
                        {processed} URL{processed !== 1 ? 's' : ''} traité{processed !== 1 ? 'es' : 'e'}
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0">
                  {isChecking && <RefreshCw size={12} className="animate-spin text-blue-400" />}
                  {!isChecking && result === true  && <CheckCircle2 size={12} className="text-green-500" />}
                  {!isChecking && result === false && <AlertTriangle size={12} className="text-red-400" />}

                  {/* Toggle actif */}
                  <button
                    onClick={() => toggleActive(src.name)}
                    title={src.actif ? 'Désactiver cette source' : 'Activer cette source'}
                    className="p-1.5 text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                  >
                    {src.actif ? <ToggleRight size={14} className="text-blue-500" /> : <ToggleLeft size={14} />}
                  </button>

                  {/* Éditer */}
                  <button
                    onClick={() => isEditing ? cancelEdit() : startEdit(src)}
                    title={isEditing ? 'Annuler la modification' : 'Modifier cette source'}
                    className={`p-1.5 rounded-lg transition-all
                      ${isEditing
                        ? 'text-blue-500 bg-blue-100 dark:bg-blue-900/40 dark:text-blue-300'
                        : 'opacity-40 group-hover:opacity-100 text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-slate-100 dark:hover:bg-slate-700'}`}
                  >
                    <Pencil size={12} />
                  </button>

                  {/* Vérifier */}
                  {!isChecking && (
                    <button
                      onClick={() => checkOne(src)}
                      title="Vérifier l'accessibilité du sitemap"
                      className="opacity-40 group-hover:opacity-100 p-1.5 text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-all"
                    >
                      <Check size={12} />
                    </button>
                  )}

                  {/* Lien externe */}
                  <a href={src.base_url} target="_blank" rel="noopener noreferrer"
                    className="opacity-40 group-hover:opacity-100 p-1.5 text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-all"
                    title="Ouvrir le site">
                    <ExternalLink size={12} />
                  </a>

                  {/* Supprimer */}
                  <button
                    onClick={() => removeSource(src.name)}
                    title="Supprimer cette source"
                    className="opacity-40 group-hover:opacity-100 p-1.5 text-slate-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-all"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>

              {/* Formulaire d'édition inline */}
              {isEditing && (
                <div className="px-3 pb-3 pt-0 space-y-2 border-t border-blue-200 dark:border-blue-700/40">
                  <p className="pt-2.5 text-[11px] font-semibold text-[#007AFF] dark:text-[#0A84FF] uppercase tracking-wide flex items-center gap-1">
                    <Pencil size={10} /> Modifier la source
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">Titre</label>
                      <input
                        type="text"
                        value={editFields.title}
                        onChange={e => setEditFields(f => ({ ...f, title: e.target.value }))}
                        className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">Mot-clé (bucket)</label>
                      <input
                        type="text"
                        value={editFields.keyword}
                        onChange={e => setEditFields(f => ({ ...f, keyword: e.target.value }))}
                        className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors"
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">URL de base</label>
                    <input
                      type="url"
                      value={editFields.base_url}
                      onChange={e => setEditFields(f => ({ ...f, base_url: e.target.value }))}
                      className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">URL sitemap</label>
                      <input
                        type="url"
                        value={editFields.sitemap_url}
                        onChange={e => setEditFields(f => ({ ...f, sitemap_url: e.target.value }))}
                        placeholder="https://…/sitemap.xml"
                        className="w-full px-2.5 py-1.5 text-xs bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">Pattern URL (regex)</label>
                      <input
                        type="text"
                        value={editFields.url_pattern}
                        onChange={e => setEditFields(f => ({ ...f, url_pattern: e.target.value }))}
                        placeholder="ex: /news/  ou  /en/programs/\d+"
                        className="w-full px-2.5 py-1.5 text-xs font-mono bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#007AFF]/40 transition-colors"
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      onClick={cancelEdit}
                      className="px-3 py-1.5 text-xs rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                    >
                      Annuler
                    </button>
                    <button
                      onClick={saveEdit}
                      disabled={!editFields.title || !editFields.base_url || !editFields.url_pattern || !editFields.keyword}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white disabled:opacity-40 transition-colors"
                    >
                      <Save size={11} /> Enregistrer
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'rss',        label: 'RSS',            short: 'RSS',      Icon: Rss       },
  { id: 'web',        label: 'Web',            short: 'Web',      Icon: Globe     },
  { id: 'scheduler',  label: 'Planification',  short: 'Cron',     Icon: Clock     },
  { id: 'keywords',   label: 'Mots-clés',      short: 'Mots-cl.', Icon: Tag       },
  { id: 'flux',       label: 'Flux Reeder',    short: 'Flux',     Icon: Database  },
  { id: 'quota',      label: 'Quota',          short: 'Quota',    Icon: BarChart2 },
  { id: 'fiabilite',  label: 'Fiabilité',      short: 'Fiab.',    Icon: Eye       },
  { id: 'env',        label: 'Environnement',  short: 'Env',      Icon: Lock      },
]

// Mobile : sous-onglets du groupe Sources (inclut Mots-clés)
const SOURCE_TABS = [
  { id: 'rss',      label: 'RSS',       Icon: Rss      },
  { id: 'web',      label: 'Web',       Icon: Globe    },
  { id: 'flux',     label: 'Flux',      Icon: Database },
  { id: 'keywords', label: 'Mots-clés', Icon: Tag      },
]

// Mobile : onglets principaux hors Sources (affiché dans la tab bar du bas)
const MOBILE_BOTTOM_TABS = [
  { id: 'scheduler', short: 'Cron',  Icon: Clock     },
  { id: 'quota',     short: 'Quota', Icon: BarChart2 },
  { id: 'env',       short: 'Env',   Icon: Lock      },
]

const THEME_OPTIONS_SETTINGS = [
  { key: 'jour', Icon: Sun,     label: 'Jour' },
  { key: 'auto', Icon: Monitor, label: 'Auto' },
  { key: 'nuit', Icon: Moon,    label: 'Nuit' },
]

export default function SettingsPanel({ onClose, theme, onThemeChange, rssStatus, onOpenConsole, onOpenTendances, onOpenBiais }) {
  const [activeTab, setActiveTab] = useState('rss')
  const [isMaximized, setIsMaximized] = useState(false)
  const [sourcesMenuOpen, setSourcesMenuOpen] = useState(false)

  const isSourceTab = SOURCE_TABS.some(tab => tab.id === activeTab)

  const handleTabSelect = (id) => { setActiveTab(id); setSourcesMenuOpen(false) }

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className={`hig-overlay-enter fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex justify-center ${isMaximized ? 'items-stretch' : 'items-stretch md:items-start md:pt-10 md:px-4 md:pb-4'}`}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className={`hig-modal-enter glass-panel shadow-2xl w-full border border-white/45 dark:border-white/[0.09] flex flex-col overflow-hidden relative ${isMaximized ? '' : 'md:max-w-5xl md:max-h-[88vh] md:rounded-2xl'}`}>

        {/* ── Navigation tabs — desktop header / mobile floating pills ── */}
        {/* Desktop header */}
        <div className="hidden md:flex items-center gap-2 px-5 py-3 shrink-0 glass-nav border-b border-white/35 dark:border-white/[0.08]">
            <Settings size={15} className="text-slate-400 dark:text-slate-400" />
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200 mr-3">Réglages</h2>
            <div className="flex items-center gap-1 flex-1">
              {TABS.map(({ id, label, Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  title={label}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    activeTab === id
                      ? 'bg-[#007AFF]/10 text-[#007AFF] dark:text-[#0A84FF] border border-blue-400/40 dark:border-blue-500/40'
                      : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <Icon size={12} /><span>{label}</span>
                </button>
              ))}
            </div>
            <button
              onClick={() => setIsMaximized(m => !m)}
              title={isMaximized ? 'Réduire la fenêtre' : "Agrandir à la taille de l'écran"}
              className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              aria-label={isMaximized ? 'Réduire' : 'Agrandir'}
            >
              {isMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              aria-label="Fermer"
            >
              <X size={14} />
            </button>
        </div>

        {/* Mobile : tab bar floating pills — absolute, le contenu défile dessous */}
        <div
          className="md:hidden absolute bottom-0 left-0 right-0 z-20 flex flex-col"
          style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        >
          {/* Sous-menu Sources — pill floating transparent */}
          {sourcesMenuOpen && (
            <div className="flex items-stretch mx-3 mb-2 rounded-2xl overflow-hidden glass-nav">
                {SOURCE_TABS.map(({ id, label, Icon }) => (
                  <button
                    key={id}
                    onClick={() => handleTabSelect(id)}
                    className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] h-10 transition-colors active:opacity-60 ${
                      activeTab === id
                        ? 'text-[#007AFF] dark:text-[#0A84FF]'
                        : 'text-slate-400 dark:text-slate-500'
                    }`}
                  >
                    {activeTab === id && <span className="nav-active-pill" />}
                    <Icon size={18} strokeWidth={activeTab === id ? 2.2 : 1.8} />
                    <span className="text-[11px] font-medium leading-none">{label}</span>
                  </button>
                ))}
            </div>
          )}
          {/* Barre principale — pill floating transparent */}
          <div className="flex items-stretch h-[49px] mx-3 mb-3 rounded-2xl overflow-hidden glass-nav">
              {/* Bouton Sources avec sous-menu */}
              <button
                onClick={() => setSourcesMenuOpen(o => !o)}
                className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
                  isSourceTab || sourcesMenuOpen
                    ? 'text-[#007AFF] dark:text-[#0A84FF]'
                    : 'text-slate-400 dark:text-slate-500'
                }`}
              >
                {(isSourceTab || sourcesMenuOpen) && <span className="nav-active-pill" />}
                <Layers size={22} strokeWidth={(isSourceTab || sourcesMenuOpen) ? 2.2 : 1.8} />
                <span className="text-[11px] font-medium leading-none">Sources</span>
              </button>
              {/* Onglets principaux */}
              {MOBILE_BOTTOM_TABS.map(({ id, short, Icon }) => (
                <button
                  key={id}
                  onClick={() => handleTabSelect(id)}
                  className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
                    activeTab === id
                      ? 'text-[#007AFF] dark:text-[#0A84FF]'
                      : 'text-slate-400 dark:text-slate-500'
                  }`}
                >
                  {activeTab === id && <span className="nav-active-pill" />}
                  <Icon size={22} strokeWidth={activeTab === id ? 2.2 : 1.8} />
                  <span className="text-[11px] font-medium leading-none">{short}</span>
                </button>
              ))}
              {/* Bouton fermer — bord droit, séparé des onglets */}
              <button
                onClick={onClose}
                aria-label="Fermer"
                className="flex items-center justify-center px-4 text-slate-400 dark:text-slate-500 border-l border-slate-200/60 dark:border-slate-700/50 active:opacity-60 transition-colors"
              >
                <X size={20} />
              </button>
          </div>
        </div>

        {/* ── Accès rapide — mobile uniquement (actions retirées de la tab bar) ── */}
        <div className="md:hidden shrink-0 border-b border-slate-200/70 dark:border-slate-700/50 bg-slate-50/60 dark:bg-slate-800/40 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-2.5">Accès rapide</p>
          <div className="flex items-center gap-2">
            {/* Sélecteur de thème compact */}
            <div className="flex items-center rounded-xl border border-slate-200 dark:border-slate-600/70 overflow-hidden bg-white/70 dark:bg-slate-700/50 backdrop-blur-sm">
              {THEME_OPTIONS_SETTINGS.map(({ key, Icon, label }) => (
                <button
                  key={key}
                  onClick={() => onThemeChange?.(key)}
                  title={label}
                  className={`flex flex-col items-center gap-[3px] px-3 py-2 transition-colors ${
                    theme === key
                      ? 'bg-[#007AFF] dark:bg-[#0A84FF] text-white'
                      : 'text-slate-500 dark:text-slate-400 active:opacity-60'
                  }`}
                >
                  <Icon size={16} />
                  <span className="text-[11px] font-medium leading-none">{label}</span>
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1 ml-auto">
              {/* Console RSS */}
              {onOpenConsole && (
                <button
                  onClick={onOpenConsole}
                  title="Mots-clés RSS"
                  className="flex flex-col items-center gap-[3px] px-3 py-2 rounded-xl bg-white/70 dark:bg-slate-700/50 backdrop-blur-sm border border-slate-200 dark:border-slate-600/70 text-slate-500 dark:text-slate-400 active:opacity-60 relative"
                >
                  <span className="relative">
                    <Terminal size={18} />
                    {rssStatus?.running && (
                      <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-[#34C759] animate-pulse" />
                    )}
                  </span>
                  <span className="text-[11px] font-medium leading-none">RSS</span>
                </button>
              )}

              {/* Fiabilité — raccourci vers l'onglet Fiabilité (avant Tendances) */}
              <button
                onClick={() => setActiveTab('fiabilite')}
                title="Fiabilité des sources"
                className={`flex flex-col items-center gap-[3px] px-3 py-2 rounded-xl bg-white/70 dark:bg-slate-700/50 backdrop-blur-sm border border-slate-200 dark:border-slate-600/70 active:opacity-60 transition-colors ${
                  activeTab === 'fiabilite'
                    ? 'text-[#007AFF] dark:text-[#0A84FF] border-blue-400/40 dark:border-blue-500/40'
                    : 'text-slate-500 dark:text-slate-400'
                }`}
              >
                <Eye size={18} />
                <span className="text-[11px] font-medium leading-none">Fiab.</span>
              </button>

              {/* Tendances */}
              {onOpenTendances && (
                <button
                  onClick={onOpenTendances}
                  title="Tendances & alertes"
                  className="flex flex-col items-center gap-[3px] px-3 py-2 rounded-xl bg-white/70 dark:bg-slate-700/50 backdrop-blur-sm border border-slate-200 dark:border-slate-600/70 text-slate-500 dark:text-slate-400 active:opacity-60"
                >
                  <TrendingUp size={18} />
                  <span className="text-[11px] font-medium leading-none">Tendances</span>
                </button>
              )}

              {/* Biais éditoriaux */}
              {onOpenBiais && (
                <button
                  onClick={onOpenBiais}
                  title="Biais éditoriaux"
                  className="flex flex-col items-center gap-[3px] px-3 py-2 rounded-xl bg-white/70 dark:bg-slate-700/50 backdrop-blur-sm border border-slate-200 dark:border-slate-600/70 text-slate-500 dark:text-slate-400 active:opacity-60"
                >
                  <Eye size={18} />
                  <span className="text-[11px] font-medium leading-none">Biais</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ── Contenu de l'onglet actif ── */}
        <div className="flex flex-col flex-1 overflow-hidden settings-tabs-content">
          {activeTab === 'rss'       && <RssTab />}
          {activeTab === 'web'       && <WebSourcesTab />}
          {activeTab === 'scheduler' && <SchedulerTab />}
          {activeTab === 'keywords'  && <KeywordsTab />}
          {activeTab === 'flux'      && <FluxTab />}
          {activeTab === 'quota'     && <QuotaTab />}
          {activeTab === 'fiabilite' && <FiabiliteTab />}
          {activeTab === 'env'       && <EnvTab />}
        </div>
      </div>
    </div>
  )
}
