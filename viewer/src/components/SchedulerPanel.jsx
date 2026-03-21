import { useEffect, useState, useCallback } from 'react'
import { X, Clock, Calendar, RefreshCw, CheckCircle2, HelpCircle } from 'lucide-react'

const CRON_CATEGORIES = [
  { id: "Surveillance en continu", label: "Surveillance en continu",   desc: "Tâches fréquentes : chaque 5 min, 10 min ou toutes les 2h" },
  { id: "Enrichissement nocturne", label: "Enrichissement nocturne",   desc: "Pipeline 01h–04h30 : backup, NER, images, sentiment, réparation, crédibilité sources" },
  { id: "Rapports & digests",      label: "Rapports & digests",        desc: "Digests quotidiens, briefing hebdomadaire et collecte multi-flux" },
  { id: "Pipeline mensuel",        label: "Pipeline mensuel",          desc: "Radar, Markdown et rapports générés le dernier jour du mois" },
]

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
  if (abs < 3_600_000) return rtf.format(Math.round(diff / 60_000), 'minute')
  if (abs < 86_400_000) return rtf.format(Math.round(diff / 3_600_000), 'hour')
  return rtf.format(Math.round(diff / 86_400_000), 'day')
}

function StatusBadge({ task }) {
  const nextMs = task.next_run ? new Date(task.next_run) - Date.now() : null
  const isSoon = nextMs !== null && nextMs > 0 && nextMs < 3_600_000

  if (!task.last_run) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
        <HelpCircle size={12} />
        Jamais exécuté
      </span>
    )
  }
  if (isSoon) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-blue-400">
        <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
        Bientôt
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-green-400">
      <CheckCircle2 size={12} />
      Actif
    </span>
  )
}

export default function SchedulerPanel({ onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/scheduler')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [load, onClose])

  // Prochaine tâche imminente
  const upcoming = data?.tasks
    .filter(t => t.next_run && new Date(t.next_run) > Date.now())
    .sort((a, b) => new Date(a.next_run) - new Date(b.next_run))[0]

  const tasksByCategory = Object.fromEntries(
    CRON_CATEGORIES.map(c => [c.id, data?.tasks.filter(t => !t.flux && t.category === c.id) ?? []])
  )
  const fluxTasks = data?.tasks.filter(t => t.flux) ?? []

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-start justify-center pt-16 px-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-4xl max-h-[80vh] glass-dark rounded-2xl shadow-2xl border border-white/[0.08] flex flex-col overflow-hidden">

        {/* ── En-tête ── */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-700/50 bg-slate-800/60 backdrop-blur-xl shrink-0">
          <Clock size={17} className="text-blue-400" />
          <h2 className="text-base font-semibold text-slate-100">Planification des tâches</h2>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={load}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition-colors"
              title="Actualiser"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* ── Prochaine tâche ── */}
        {upcoming && (
          <div className="px-5 py-2.5 bg-[#007AFF]/10 border-b border-blue-500/20 shrink-0">
            <div className="flex items-center gap-2 text-sm">
              <Calendar size={13} className="text-blue-400 shrink-0" />
              <span className="text-blue-300">
                Prochaine tâche :{' '}
                <span className="font-medium text-blue-200">{upcoming.name}</span>
                {' — '}
                <span className="text-blue-300">{formatRelative(upcoming.next_run)}</span>
                <span className="text-blue-500 text-xs ml-2">({formatDateTime(upcoming.next_run)})</span>
              </span>
            </div>
          </div>
        )}

        {/* ── Tableau par catégories ── */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="flex items-center justify-center h-40 gap-3 text-slate-500">
              <div className="w-4 h-4 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
              <span className="text-sm">Chargement…</span>
            </div>
          ) : !data?.tasks?.length ? (
            <div className="flex items-center justify-center h-40 text-slate-500 text-sm">
              Aucune tâche planifiée trouvée
            </div>
          ) : (
            <>
              {CRON_CATEGORIES.map(cat => {
                const tasks = tasksByCategory[cat.id] ?? []
                if (!tasks.length) return null
                return (
                  <TaskSection key={cat.id} title={cat.label} desc={cat.desc} tasks={tasks} />
                )
              })}
              {fluxTasks.length > 0 && (
                <TaskSection
                  title="Tâches par flux"
                  desc="Collecte IA planifiée par flux JSON source"
                  tasks={fluxTasks}
                />
              )}
            </>
          )}
        </div>

        {/* ── Pied ── */}
        {data && (
          <div className="px-5 py-2 bg-slate-900/50 border-t border-slate-700 text-xs text-slate-600 shrink-0 flex items-center gap-2">
            <span>
              {data.tasks.length} tâche{data.tasks.length !== 1 ? 's' : ''} planifiée{data.tasks.length !== 1 ? 's' : ''}
              {' · '}
              Actualisé à {new Date(data.now).toLocaleTimeString('fr-FR')}
            </span>
            <button onClick={load} className="text-slate-600 hover:text-slate-400 transition-colors" title="Actualiser">
              <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function TaskSection({ title, desc, tasks }) {
  if (!tasks.length) return null
  return (
    <div>
      <div className="sticky top-0 bg-slate-900 px-5 py-2 border-b border-slate-700 flex items-baseline gap-3">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</span>
        {desc && <span className="text-[11px] text-slate-600 normal-case tracking-normal">{desc}</span>}
        <span className="ml-auto text-[11px] text-slate-600">{tasks.length} tâche{tasks.length !== 1 ? 's' : ''}</span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] font-medium text-slate-500 uppercase tracking-wider border-b border-slate-700/50">
            <th className="text-left px-5 py-2.5">Tâche</th>
            <th className="text-left px-4 py-2.5">Fréquence</th>
            <th className="text-left px-4 py-2.5">Dernière exécution</th>
            <th className="text-left px-4 py-2.5">Prochaine exécution</th>
            <th className="text-left px-4 py-2.5">Statut</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task, i) => (
            <tr
              key={i}
              className="border-b border-slate-700/40 last:border-0 hover:bg-slate-700/20 transition-colors"
            >
              <td className="px-5 py-3">
                <div className="font-medium text-slate-200 text-sm">{task.name}</div>
                <div className="text-[11px] text-slate-500 font-mono mt-0.5">{task.script}</div>
                {task.detail && (
                  <div className="text-[11px] text-blue-400 mt-1">{task.detail}</div>
                )}
              </td>
              <td className="px-4 py-3">
                <div className="text-slate-300 text-sm">{task.label}</div>
                <div className="text-[11px] text-slate-600 font-mono mt-0.5">{task.cron}</div>
              </td>
              <td className="px-4 py-3">
                {task.last_run ? (
                  <>
                    <div className="text-slate-300 text-sm">{formatDateTime(task.last_run)}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">{formatRelative(task.last_run)}</div>
                  </>
                ) : (
                  <span className="text-slate-600 italic text-sm">Jamais</span>
                )}
              </td>
              <td className="px-4 py-3">
                {task.next_run ? (
                  <>
                    <div className="text-slate-300 text-sm">{formatDateTime(task.next_run)}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">{formatRelative(task.next_run)}</div>
                  </>
                ) : (
                  <span className="text-slate-600 text-sm">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                <StatusBadge task={task} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
