import { useState, useEffect, useCallback, useRef } from 'react'
import Sidebar from './components/Sidebar'
import FileViewer from './components/FileViewer'
import SearchOverlay from './components/SearchOverlay'
import SettingsPanel from './components/SettingsPanel'
import EntitySearchModal from './components/EntitySearchModal'
import EntityDashboard from './components/EntityDashboard'
import ScriptConsolePanel from './components/ScriptConsolePanel'
import { Search, Settings, Sun, Moon, Monitor, BarChart2, Terminal, Menu, Clock, TrendingUp, Star, Eye, EyeOff, Share2, Layers, Bell, ArrowLeftRight, ChevronDown, MoreHorizontal, MessageSquare, Newspaper, Filter, Tag, BookOpen } from 'lucide-react'
import AlertsPanel from './components/AlertsPanel'
import ExportPanel from './components/ExportPanel'
import TopArticlesPanel from './components/TopArticlesPanel'
import SourceBiasPanel from './components/SourceBiasPanel'
import ComparePanel from './components/ComparePanel'
import EntityWatchPanel from './components/EntityWatchPanel'
import ClusterView from './components/ClusterView'
import ChatbotPanel from './components/ChatbotPanel'
import wuddLogo from './assets/wudd-prism-floyd.svg'

// Heures de passage du cron get-keyword-from-rss.py (Europe/Paris)
const RSS_CRON_HOURS = [6, 8, 10, 12, 14, 16, 18, 20, 22]

function useNextRssCountdown() {
  const [label, setLabel] = useState('')
  useEffect(() => {
    function compute() {
      const now = new Date()
      const parts = new Intl.DateTimeFormat('fr-FR', {
        timeZone: 'Europe/Paris',
        hour: '2-digit', minute: '2-digit', hour12: false,
      }).formatToParts(now)
      const h = parseInt(parts.find(p => p.type === 'hour').value)
      const m = parseInt(parts.find(p => p.type === 'minute').value)
      const curMin = h * 60 + m
      let diff = null
      for (const hr of RSS_CRON_HOURS) {
        if (hr * 60 > curMin) { diff = hr * 60 - curMin; break }
      }
      if (diff === null) diff = (24 - h) * 60 - m + RSS_CRON_HOURS[0] * 60
      if (diff <= 0) { setLabel('Actualisation en cours…'); return }
      if (diff < 60) { setLabel(`Actu. dans ${diff}min`); return }
      const hh = Math.floor(diff / 60)
      const mm = diff % 60
      setLabel(mm === 0 ? `Actu. dans ${hh}h` : `Actu. dans ${hh}h${String(mm).padStart(2, '0')}`)
    }
    compute()
    const interval = setInterval(compute, 60000)
    return () => clearInterval(interval)
  }, [])
  return label
}

// Formate un timestamp ISO UTC en label relatif français
function formatLastRun(isoStr) {
  if (!isoStr) return null
  const d = new Date(isoStr)
  const diffMin = Math.round((Date.now() - d.getTime()) / 60000)
  if (diffMin < 1) return 'il y a quelques sec'
  if (diffMin < 60) return `il y a ${diffMin}min`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `il y a ${diffH}h`
  return `il y a ${Math.floor(diffH / 24)}j`
}

// Interroge l'endpoint de statut du script get-keyword-from-rss.py
function useRssStatus() {
  const [status, setStatus] = useState(null)
  useEffect(() => {
    const fetchStatus = () => {
      fetch('/api/scripts/keyword-rss/status')
        .then(r => r.ok ? r.json() : null)
        .then(d => d && setStatus(d))
        .catch(() => {})
    }
    fetchStatus()
    // Poll rapide (5s) quand en cours, lent (15s) sinon
    let id = null
    function schedule(isRunning) {
      clearInterval(id)
      id = setInterval(() => {
        fetch('/api/scripts/keyword-rss/status')
          .then(r => r.ok ? r.json() : null)
          .then(d => {
            if (!d) return
            setStatus(d)
            if (!!d.running !== isRunning) schedule(!!d.running)
          })
          .catch(() => {})
      }, isRunning ? 5000 : 15000)
    }
    schedule(false)
    return () => clearInterval(id)
  }, [])
  return status
}

// Barre de statut RSS — affichée dans le header
function RssStatusBar({ status, nextRssLabel }) {
  if (!status) return null
  const prog = status.progress
  const running = status.running
  const pct = prog && prog.total_feeds > 0
    ? Math.round((prog.current_feed_idx / prog.total_feeds) * 100)
    : null

  // Durée écoulée depuis started_at
  let elapsed = ''
  if (prog?.started_at) {
    const mins = Math.round((Date.now() - new Date(prog.started_at).getTime()) / 60000)
    elapsed = mins < 60 ? `${mins}min` : `${Math.floor(mins/60)}h${String(mins%60).padStart(2,'0')}`
  }

  const tooltipLines = [
    prog?.current_feed_title && `Flux : ${prog.current_feed_title}`,
    prog?.last_action && `Action : ${prog.last_action}`,
    prog?.started_at && `Démarré : ${new Date(prog.started_at).toLocaleTimeString('fr-FR', {hour:'2-digit',minute:'2-digit'})}`,
    status.article_count > 0 && `${status.article_count} articles / ${status.file_count} mots-clés`,
  ].filter(Boolean).join(' • ')

  return (
    <div className="hidden sm:flex items-center gap-2 ml-3" title={tooltipLines}>
      {running ? (
        <>
          {/* Indicateur en cours */}
          <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse inline-block" />
            En cours{elapsed ? ` (${elapsed})` : ''}
          </span>
          {/* Progression flux X/Y */}
          {prog && prog.total_feeds > 0 && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <span className="tabular-nums">{prog.current_feed_idx}/{prog.total_feeds}</span>
              {/* barre de progression */}
              <span className="w-20 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden inline-block align-middle">
                <span
                  className="h-full bg-green-500 rounded-full block transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </span>
              <span className="tabular-nums">{pct}%</span>
            </span>
          )}
          {/* Dernier flux / action */}
          {prog?.current_feed_title && (
            <span className="text-xs text-slate-400 dark:text-slate-500 max-w-[160px] truncate">
              {prog.current_feed_title}
            </span>
          )}
          {/* Articles ajoutés cette passe */}
          {prog?.articles_added > 0 && (
            <span className="text-xs text-slate-400 dark:text-slate-500 tabular-nums">
              +{prog.articles_added} art.
            </span>
          )}
        </>
      ) : status.last_run || prog?.finished_at ? (
        <>
          <span className="inline-flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
            <span className="w-1.5 h-1.5 rounded-full inline-block bg-slate-400 dark:bg-slate-600" />
            {formatLastRun(status.last_run || prog?.finished_at)}
          </span>
          {status.article_count > 0 && (
            <span className="text-xs text-slate-400 dark:text-slate-500 tabular-nums">
              {status.article_count} art.
            </span>
          )}
        </>      ) : status.article_count > 0 ? (
        /* Script jamais suivi (avant instrumentation) — affiche juste le compteur */
        <span
          className="inline-flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500"
          title={`${status.article_count} articles dans ${status.file_count} fichiers mots-clés`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-slate-400 inline-block" />
          {status.article_count} art. / {status.file_count} mots-clés
        </span>      ) : null}
      {nextRssLabel && !running && (
        <span className="inline-flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
          <Clock size={11} />{nextRssLabel}
        </span>
      )}
    </div>
  )
}

const THEME_OPTIONS = [
  { key: 'jour', Icon: Sun,     title: 'Jour' },
  { key: 'auto', Icon: Monitor, title: 'Automatique' },
  { key: 'nuit', Icon: Moon,    title: 'Nuit' },
]

function applyTheme(theme) {
  const html = document.documentElement
  let isDark
  if (theme === 'nuit') {
    html.classList.add('dark')
    isDark = true
  } else if (theme === 'jour') {
    html.classList.remove('dark')
    isDark = false
  } else {
    isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    html.classList.toggle('dark', isDark)
  }
  let meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.remove()
  meta = document.createElement('meta')
  meta.name = 'theme-color'
  meta.content = isDark ? '#1e293b' : '#ffffff'
  document.head.appendChild(meta)
}

export default function App() {
  const nextRssLabel = useNextRssCountdown()
  const rssStatus = useRssStatus()
  const [files, setFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileContent, setFileContent] = useState(null)
  const [contentLoading, setContentLoading] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchTypeMenuOpen, setSearchTypeMenuOpen] = useState(false)
  const [searchMode, setSearchMode] = useState('file')
  const [articleSearchQuery, setArticleSearchQuery] = useState({ query: '', version: 0 })
  const articleSearchVersionRef = useRef(0)
  const [articleFocusSignal, setArticleFocusSignal] = useState(0)
  const articleFocusSignalRef = useRef(0)
  const [mobileFilterSignal, setMobileFilterSignal] = useState({ mode: null, version: 0 })
  const mobileFilterSignalRef = useRef({ mode: null, version: 0 })
  const [mobileFiltersActive, setMobileFiltersActive] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [typeFilter, setTypeFilter] = useState('all')
  const [nameSearch, setNameSearch] = useState('')
  const [entitySearch, setEntitySearch] = useState(null) // { value, type } | null
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [consoleOpen, setConsoleOpen]     = useState(false)
  const [alertsOpen, setAlertsOpen]       = useState(false)
  const [topOpen, setTopOpen]             = useState(false)
  const [biasOpen, setBiasOpen]           = useState(false)
  const [exportOpen, setExportOpen]       = useState(false)
  const [compareOpen, setCompareOpen]     = useState(false)
  const [watchOpen, setWatchOpen]         = useState(false)
  const [clusterOpen, setClusterOpen]     = useState(false)
  const [chatOpen, setChatOpen]           = useState(false)
  const [chatEntityContext, setChatEntityContext]   = useState(null) // { type, value } | null
  const [chatArticleContext, setChatArticleContext] = useState(null) // { titre, sources, date, url, entities, resume, reportMd } | null
  const [outilsOpen, setOutilsOpen]       = useState(false)
  const outilsMenuRef                     = useRef(null)
  const [sidebarOpen, setSidebarOpen]     = useState(() => window.innerWidth >= 768)
  const [loadingProgress, setLoadingProgress] = useState(0)
  const [isRefreshing, setIsRefreshing]   = useState(false)
  // Annotations manuelles (dict keyed par URL article)
  const [annotations, setAnnotations]     = useState({})
  // Compteur de requêtes pour ignorer les réponses périmées (race condition)
  const fetchIdRef = useRef(0)
  // Ref sur le fichier en cours de consultation (accessible dans les callbacks
  // sans créer de dépendances cycliques)
  const selectedFileRef = useRef(null)
  useEffect(() => { selectedFileRef.current = selectedFile }, [selectedFile])

  // ── Thème ──────────────────────────────────────────────────────────────────
  const [theme, setTheme] = useState(() => localStorage.getItem('wudd_theme') || 'auto')

  useEffect(() => {
    localStorage.setItem('wudd_theme', theme)
    applyTheme(theme)
  }, [theme])

  // En mode automatique, écouter les changements de préférence système
  useEffect(() => {
    if (theme !== 'auto') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyTheme('auto')
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [theme])

  // ── Données ────────────────────────────────────────────────────────────────
  const refreshFiles = useCallback(() => {
    setIsRefreshing(true)
    const id = ++fetchIdRef.current
    fetch('/api/files')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(data => {
        if (id !== fetchIdRef.current) return // réponse périmée ignorée
        if (!Array.isArray(data)) throw new Error('Réponse invalide')
        setFiles(prev => {
          // Ne jamais remplacer une liste non-vide par une liste vide
          if (data.length === 0 && prev.length > 0) return prev
          // Conserver les markdown présents dans l'état précédent mais absents
          // de la nouvelle réponse (virtiofs - listing partiel transitoire).
          // Ne s'applique pas aux suppressions car deleteFile() retire le fichier
          // de l'état via setFiles(filter) avant tout appel refreshFiles().
          const newPaths = new Set(data.map(f => f.path))
          const missingMd = prev.filter(f => f.type === 'markdown' && !newPaths.has(f.path))
          if (missingMd.length > 0) {
            return [...data, ...missingMd].sort((a, b) => b.modified - a.modified)
          }
          return data
        })
        // Si un fichier est en cours de consultation, vérifier s'il a été modifié
        const current = selectedFileRef.current
        if (current) {
          const updated = data.find(f => f.path === current.path)
          if (updated && updated.modified !== current.modified) {
            // Le fichier a été modifié : mettre à jour la référence et recharger
            setSelectedFile(updated)
            setFileContent(null)
            setContentLoading(true)
            setLoadingProgress(0)
            fetch(`/api/stream-content?path=${encodeURIComponent(current.path)}`)
              .then(async (response) => {
                const fileSize = parseInt(response.headers.get('X-File-Size') || '0', 10)
                const reader = response.body.getReader()
                const decoder = new TextDecoder()
                const chunks = []
                let loaded = 0
                while (true) {
                  const { done, value } = await reader.read()
                  if (done) break
                  chunks.push(decoder.decode(value, { stream: true }))
                  loaded += value.length
                  if (fileSize > 0) setLoadingProgress(Math.min(99, Math.round((loaded / fileSize) * 100)))
                }
                chunks.push(decoder.decode())
                return chunks.join('')
              })
              .then(text => { setFileContent(text); setContentLoading(false); setLoadingProgress(0) })
              .catch(() => { setContentLoading(false); setLoadingProgress(0) })
          }
          // Si le fichier n'a pas été modifié, le contenu chargé est conservé
        }
        setIsRefreshing(false)
      })
      .catch(err => {
        if (id !== fetchIdRef.current) return // réponse périmée ignorée
        console.error('Erreur chargement fichiers:', err)
        setIsRefreshing(false)
        // L'état précédent est conservé (pas de setFiles)
      })
  }, [])

  useEffect(() => { refreshFiles() }, [refreshFiles])

  // ── Annotations ─────────────────────────────────────────────────────────────
  // Chargement initial depuis /api/annotations
  useEffect(() => {
    fetch('/api/annotations')
      .then(r => r.ok ? r.json() : {})
      .then(data => setAnnotations(data || {}))
      .catch(() => {})
  }, [])

  // ── Fournisseurs IA disponibles ──────────────────────────────────────────────
  const [availableProviders, setAvailableProviders] = useState([])
  useEffect(() => {
    fetch('/api/ai-providers')
      .then(r => r.ok ? r.json() : { providers: [] })
      .then(d => setAvailableProviders(d.providers ?? []))
      .catch(() => {})
  }, [])

  // ── Terminal IA depuis une entité ─────────────────────────────────────────────
  // L'EntityArticlePanel dispatche "wudd:openEntityChatbot" quand l'utilisateur
  // clique sur le bouton "Terminal IA". On ouvre le chatbot avec le contexte entité.
  useEffect(() => {
    const handler = (e) => {
      const { type, value } = e.detail || {}
      if (!type || !value) return
      setChatEntityContext({ type, value })
      setChatOpen(true)
    }
    window.addEventListener('wudd:openEntityChatbot', handler)
    return () => window.removeEventListener('wudd:openEntityChatbot', handler)
  }, [])

  // ── Terminal IA depuis un rapport d'article ───────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      const ctx = e.detail || {}
      if (!ctx.reportMd) return
      setChatArticleContext(ctx)
      setChatEntityContext(null)
      setChatOpen(true)
    }
    window.addEventListener('wudd:openArticleChatbot', handler)
    return () => window.removeEventListener('wudd:openArticleChatbot', handler)
  }, [])

  // Callback : crée ou met à jour l'annotation d'un article (optimistic update)
  const handleAnnotate = useCallback(async (url, changes) => {
    if (!url) return
    // Mise à jour optimiste immédiate
    setAnnotations(prev => {
      const existing = prev[url] || {}
      return { ...prev, [url]: { ...existing, ...changes } }
    })
    try {
      const r = await fetch('/api/annotations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, ...changes }),
      })
      if (r.ok) {
        const data = await r.json()
        if (data.annotation) {
          setAnnotations(prev => ({ ...prev, [url]: data.annotation }))
        }
      }
    } catch {
      // L'optimistic update reste en place — non critique
    }
  }, [])

  // Recharge la liste au retour de l'application (mobile : mise en arrière-plan)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshFiles()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [refreshFiles])

  // Raccourci clavier Ctrl/Cmd+K pour la recherche plein texte
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // Fermer le menu Outils au clic en dehors
  useEffect(() => {
    if (!outilsOpen) return
    const handler = (e) => {
      if (outilsMenuRef.current && !outilsMenuRef.current.contains(e.target))
        setOutilsOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [outilsOpen])

  const reloadFileContent = useCallback(() => {
    if (!selectedFile) return
    setFileContent(null)
    setContentLoading(true)
    setLoadingProgress(0)
    fetch(`/api/stream-content?path=${encodeURIComponent(selectedFile.path)}`)
      .then(async (response) => {
        const fileSize = parseInt(response.headers.get('X-File-Size') || '0', 10)
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        const chunks = []
        let loaded = 0
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          chunks.push(decoder.decode(value, { stream: true }))
          loaded += value.length
          if (fileSize > 0) setLoadingProgress(Math.min(99, Math.round((loaded / fileSize) * 100)))
        }
        chunks.push(decoder.decode())
        return chunks.join('')
      })
      .then(text => { setFileContent(text); setContentLoading(false); setLoadingProgress(0) })
      .catch(() => { setContentLoading(false); setLoadingProgress(0) })
  }, [selectedFile])

  const selectFile = useCallback((file) => {
    setSelectedFile(file)
    setFileContent(null)
    setContentLoading(true)
    setLoadingProgress(0)
    setArticleSearchQuery({ query: '', version: 0 })
    articleSearchVersionRef.current = 0
    setArticleFocusSignal(0)
    articleFocusSignalRef.current = 0
    if (window.innerWidth < 768) setSidebarOpen(false)

    fetch(`/api/stream-content?path=${encodeURIComponent(file.path)}`)
      .then(async (response) => {
        const fileSize = parseInt(response.headers.get('X-File-Size') || '0', 10)
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        const chunks = []
        let loaded = 0

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          chunks.push(decoder.decode(value, { stream: true }))
          loaded += value.length
          if (fileSize > 0) {
            setLoadingProgress(Math.min(99, Math.round((loaded / fileSize) * 100)))
          }
        }
        // Flush le décodeur
        chunks.push(decoder.decode())
        return chunks.join('')
      })
      .then(text => {
        setFileContent(text)
        setContentLoading(false)
        setLoadingProgress(0)
      })
      .catch(() => {
        setContentLoading(false)
        setLoadingProgress(0)
      })
  }, [])

  // Auto-sélection de 48-heures.json au chargement initial si aucun fichier sélectionné
  const autoSelectDone = useRef(false)
  useEffect(() => {
    if (autoSelectDone.current || selectedFile || files.length === 0) return
    const file48h = files.find(f => f.name === '48-heures.json')
    if (file48h) {
      autoSelectDone.current = true
      selectFile(file48h)
    }
  }, [files, selectedFile, selectFile])

  const downloadFile = useCallback(() => {
    if (!selectedFile) return
    const a = document.createElement('a')
    a.href = `/api/download?path=${encodeURIComponent(selectedFile.path)}`
    a.download = selectedFile.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }, [selectedFile])

  const saveContent = useCallback(async (path, newContent) => {
    const r = await fetch('/api/content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content: newContent }),
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.description || 'Erreur lors de la sauvegarde')
    }
    setFileContent(newContent)
  }, [])

  const deleteFile = useCallback(async (file) => {
    const r = await fetch(`/api/files?path=${encodeURIComponent(file.path)}`, { method: 'DELETE' })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.description || 'Erreur lors de la suppression')
    }
    setFiles(prev => prev.filter(f => f.path !== file.path))
    setSelectedFile(null)
    setFileContent(null)
  }, [])

  const filteredFiles = files.filter(f => {
    if (typeFilter !== 'all' && f.type !== typeFilter) return false
    if (nameSearch && !f.name.toLowerCase().includes(nameSearch.toLowerCase())) return false
    return true
  })

  return (
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 overflow-hidden">
      {/* ── Barre de navigation desktop ── */}
      <header
        className="hidden md:flex items-center gap-1.5 px-3 py-2 glass-nav border-b border-white/35 dark:border-white/[0.08] shrink-0 relative z-50"
        style={{ paddingTop: 'max(8px, env(safe-area-inset-top))' }}
      >
        {/* Logo compact */}
        <div className="flex items-center gap-1.5 shrink-0 mr-1">
          <img src={wuddLogo} alt="WUDD.ai" className="w-8 h-8 rounded-md select-none" />
          <span className="hidden xl:block font-semibold text-hig-callout text-slate-900 dark:text-slate-100 whitespace-nowrap">WUDD.ai</span>
        </div>

        {/* Statut RSS */}
        <RssStatusBar status={rssStatus} nextRssLabel={nextRssLabel} />

        <div className="flex-1 min-w-0" />

        {/* ── Séparateur ── */}
        <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 shrink-0" />

        {/* Sélecteur de thème */}
        <div
          className="flex items-center rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden shrink-0"
          title="Thème d'affichage"
        >
          {THEME_OPTIONS.map(({ key, Icon, title }) => (
            <button
              key={key}
              onClick={() => setTheme(key)}
              title={title}
              className={`px-1.5 py-1.5 transition-colors ${
                theme === key
                  ? 'bg-[#007AFF] dark:bg-[#0A84FF] text-white'
                  : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
            >
              <Icon size={13} />
            </button>
          ))}
        </div>

        {/* ── Séparateur ── */}
        <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 shrink-0" />

        {/* Console RSS keywords */}
        <button
          onClick={() => setConsoleOpen(true)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 border rounded-lg text-sm transition-colors ${
            rssStatus?.running
              ? 'bg-green-50 dark:bg-green-900/20 border-green-300 dark:border-green-700 text-green-700 dark:text-green-400'
              : 'bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
          }`}
          title={rssStatus
            ? `Dernier : ${rssStatus.last_run ? new Date(rssStatus.last_run).toLocaleString('fr-FR') : 'inconnu'} • ${rssStatus.article_count ?? 0} articles / ${rssStatus.file_count ?? 0} mots-clés`
            : "Lancer l'extraction des mots-clés RSS"
          }
        >
          <Terminal size={13} />
          {rssStatus?.running ? (
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          ) : null}
          <span className="hidden xl:inline">RSS</span>
          {!rssStatus?.running && rssStatus?.file_count > 0 && (
            <span className="text-xs tabular-nums opacity-60">{rssStatus.file_count}</span>
          )}
        </button>

        {/* Top articles */}
        <button
          onClick={() => setTopOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          title="Top articles par score de pertinence"
        >
          <Star size={13} />
          <span className="hidden xl:inline">Top</span>
        </button>

        {/* Tendances & alertes */}
        <button
          onClick={() => setAlertsOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          title="Alertes de tendances"
        >
          <TrendingUp size={13} />
          <span className="hidden xl:inline">Tendances</span>
        </button>

        {/* Dashboard entités */}
        <button
          onClick={() => setDashboardOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          title="Dashboard des entités nommées"
        >
          <BarChart2 size={13} />
          <span className="hidden xl:inline">Entités</span>
        </button>

        {/* ── Séparateur ── */}
        <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 shrink-0" />

        {/* Chatbot IA */}
        <button
          onClick={() => setChatOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-green-50 dark:hover:bg-green-900/20 border border-slate-200 dark:border-slate-600 hover:border-green-300 dark:hover:border-green-700 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:text-green-700 dark:hover:text-green-400 transition-colors"
          title="Chatbot IA — interrogez vos données et rapports"
        >
          <span className="font-mono text-sm">&gt;_ IA</span>
        </button>

        {/* Menu déroulant Outils : Biais, Export, Clusters, Veille, Comparer */}
        <div ref={outilsMenuRef} className="relative shrink-0">
          <button
            onClick={() => setOutilsOpen(v => !v)}
            className={`flex items-center gap-1 px-2.5 py-1.5 border rounded-lg text-sm transition-colors ${
              outilsOpen
                ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-600 text-blue-700 dark:text-blue-300'
                : 'bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
            }`}
            title="Outils d'analyse : Biais, Export, Clusters, Veille, Comparer"
          >
            <MoreHorizontal size={13} />
            <span className="hidden xl:inline">Outils</span>
            <ChevronDown size={11} className={`transition-transform duration-200 ${outilsOpen ? 'rotate-180' : ''}`} />
          </button>

          {outilsOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-54 glass-panel rounded-xl border border-white/45 dark:border-white/[0.09] shadow-2xl z-[100] py-1 overflow-hidden min-w-[13rem]">
              {[
                { Icon: Eye,           label: 'Biais éditoriaux',    desc: 'Analyse par source',             action: () => { setBiasOpen(true);    setOutilsOpen(false) } },
                { Icon: Share2,        label: 'Export & Diffusion',  desc: 'Atom, Newsletter, Webhook',      action: () => { setExportOpen(true);  setOutilsOpen(false) } },
                { Icon: Layers,        label: 'Clusters thématiques',desc: 'Regroupement par thème',         action: () => { setClusterOpen(true); setOutilsOpen(false) } },
                { Icon: Bell,          label: 'Entités surveillées', desc: 'Veille & tendances 24h/7j',      action: () => { setWatchOpen(true);   setOutilsOpen(false) } },
                { Icon: ArrowLeftRight,label: 'Comparer périodes',   desc: 'Analyse deux fenêtres de temps', action: () => { setCompareOpen(true); setOutilsOpen(false) } },
              ].map(({ Icon, label, desc, action }) => (
                <button
                  key={label}
                  onClick={action}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-100/80 dark:hover:bg-slate-700/60 transition-colors group"
                >
                  <Icon size={14} className="text-slate-400 dark:text-slate-500 shrink-0 group-hover:text-slate-600 dark:group-hover:text-slate-300 transition-colors" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-slate-700 dark:text-slate-200">{label}</div>
                    <div className="text-[11px] text-slate-400 dark:text-slate-500 leading-tight">{desc}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ── Séparateur ── */}
        <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 shrink-0" />

        {/* Réglages */}
        <button
          onClick={() => setSettingsOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          title="Réglages — planification, mots-clés, flux"
        >
          <span className="relative">
            <Settings size={13} />
            {rssStatus?.running ? (
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            ) : null}
          </span>
          <span className="hidden xl:inline">Réglages</span>
        </button>

        {/* Recherche plein texte */}
        <button
          onClick={() => setSearchOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          title="Recherche plein texte (Ctrl+K)"
        >
          <Search size={13} />
        </button>
      </header>

      {/* ── Corps principal ── */}
      {/* safe-area-inset-top sur mobile (le header étant masqué, le contenu remonte sous l'encoche) */}
      <div className="flex flex-1 overflow-hidden relative pb-16 md:pb-0" style={{ paddingTop: 'env(safe-area-inset-top)' }}>
        {/* Overlay backdrop — mobile uniquement, ferme la sidebar au clic */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/40 z-30 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <Sidebar
          files={filteredFiles}
          selectedFile={selectedFile}
          onSelect={selectFile}
          typeFilter={typeFilter}
          onTypeFilterChange={setTypeFilter}
          nameSearch={nameSearch}
          onNameSearchChange={setNameSearch}
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onRefresh={refreshFiles}
          isRefreshing={isRefreshing}
        />
        <FileViewer
          file={selectedFile}
          content={fileContent}
          loading={contentLoading}
          loadingProgress={loadingProgress}
          onDownload={downloadFile}
          onContentSaved={saveContent}
          onEntitySearch={(value, type) => setEntitySearch({ value, type })}
          onDelete={deleteFile}
          annotations={annotations}
          onAnnotate={handleAnnotate}
          sidebarOpen={sidebarOpen}
          availableProviders={availableProviders}
          articleSearchQuery={articleSearchQuery}
          articleFocusSignal={articleFocusSignal}
          onMobileSearchClose={() => setArticleFocusSignal(0)}
          mobileFilterSignal={mobileFilterSignal}
          onMobileFilterClose={() => { setMobileFiltersActive(false) }}
          onMerged={reloadFileContent}
        />
      </div>

      {/* ── Barre de navigation bas — mobile uniquement (Apple HIG: 5 tabs max, labels, verre dépoli) ── */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-50 glass-nav border-t border-white/35 dark:border-white/[0.08]"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="flex items-stretch h-[49px]">

          {/* 1 — Fichiers : ouvre le drawer latéral */}
          <button
            onClick={() => setSidebarOpen(v => !v)}
            title="Fichiers"
            className={`flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
              sidebarOpen
                ? 'text-[#007AFF] dark:text-[#0A84FF]'
                : 'text-slate-400 dark:text-slate-500'
            }`}
          >
            <Menu size={24} strokeWidth={sidebarOpen ? 2.2 : 1.8} />
            <span className="text-[11px] font-medium leading-none">Fichiers</span>
          </button>

          {/* 2 — Top articles */}
          <button
            onClick={() => setTopOpen(true)}
            title="Top articles"
            className={`flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
              topOpen
                ? 'text-[#007AFF] dark:text-[#0A84FF]'
                : 'text-slate-400 dark:text-slate-500'
            }`}
          >
            <Star size={24} strokeWidth={topOpen ? 2.2 : 1.8} />
            <span className="text-[11px] font-medium leading-none">Top</span>
          </button>

          {/* 3 — Recherche : centre = zone pouce prioritaire */}
          <button
            onClick={() => { setSearchTypeMenuOpen(true) }}
            title="Recherche"
            className={`flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
              searchOpen || searchTypeMenuOpen
                ? 'text-[#007AFF] dark:text-[#0A84FF]'
                : 'text-slate-400 dark:text-slate-500'
            }`}
          >
            <span className="relative">
              <Search size={24} strokeWidth={searchOpen || searchTypeMenuOpen ? 2.2 : 1.8} />
              {mobileFiltersActive && (
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-violet-500" />
              )}
            </span>
            <span className="text-[11px] font-medium leading-none">Recherche</span>
          </button>

          {/* 4 — Entités */}
          <button
            onClick={() => setDashboardOpen(true)}
            title="Dashboard entités"
            className={`flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
              dashboardOpen
                ? 'text-[#007AFF] dark:text-[#0A84FF]'
                : 'text-slate-400 dark:text-slate-500'
            }`}
          >
            <BarChart2 size={24} strokeWidth={dashboardOpen ? 2.2 : 1.8} />
            <span className="text-[11px] font-medium leading-none">Entités</span>
          </button>

          {/* 5 — Réglages (inclut : thème, RSS, tendances, biais) */}
          <button
            onClick={() => setSettingsOpen(true)}
            title="Réglages"
            className={`flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${
              settingsOpen
                ? 'text-[#007AFF] dark:text-[#0A84FF]'
                : 'text-slate-400 dark:text-slate-500'
            }`}
          >
            <span className="relative">
              <Settings size={24} strokeWidth={settingsOpen ? 2.2 : 1.8} />
              {rssStatus?.running ? (
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              ) : null}
            </span>
            <span className="text-[11px] font-medium leading-none">Réglages</span>
          </button>

        </div>
      </nav>

      {/* ── Bouton flottant Chatbot — mobile ── */}
      <button
        onClick={() => setChatOpen(true)}
        className="md:hidden fixed bottom-[calc(7.5rem+env(safe-area-inset-bottom))] right-4 z-40 w-11 h-11 rounded-full bg-green-700 hover:bg-green-600 shadow-lg flex items-center justify-center text-white transition-colors"
        title="Chatbot IA"
      >
        <MessageSquare size={18} />
      </button>

      {/* ── Overlays ── */}
      {consoleOpen && (
        <ScriptConsolePanel onClose={() => setConsoleOpen(false)} onDone={refreshFiles} />
      )}
      {/* Sélecteur type de recherche — mobile uniquement */}
      {searchTypeMenuOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-end"
          onClick={() => setSearchTypeMenuOpen(false)}
        >
          <div
            className="w-full bg-white dark:bg-slate-800 rounded-t-2xl shadow-2xl border-t border-slate-200/60 dark:border-white/10"
            style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex justify-center pt-3 pb-1">
              <div className="w-10 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
            </div>
            <p className="text-sm font-semibold text-slate-600 dark:text-slate-300 px-4 pt-2 pb-3 text-center">
              Que souhaitez-vous ?
            </p>
            <div className="flex flex-col gap-2 px-4 pb-5">
              <button
                onClick={() => { setSearchMode('file'); setSearchTypeMenuOpen(false); setSearchOpen(true) }}
                className="flex items-center gap-3 px-4 py-3.5 rounded-xl bg-slate-100 dark:bg-slate-700 text-left active:opacity-70 transition-opacity"
              >
                <Search size={20} className="text-blue-500 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Recherche fichier</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">Trouver des fichiers contenant un mot-clé</div>
                </div>
              </button>
              <button
                onClick={() => {
                  if (selectedFile && selectedFile.type === 'json') {
                    articleFocusSignalRef.current += 1
                    setArticleFocusSignal(articleFocusSignalRef.current)
                    setSearchTypeMenuOpen(false)
                    if (window.innerWidth < 768) setSidebarOpen(false)
                  }
                }}
                disabled={!selectedFile || selectedFile?.type !== 'json'}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-opacity ${
                  selectedFile && selectedFile.type === 'json'
                    ? 'bg-slate-100 dark:bg-slate-700 active:opacity-70'
                    : 'bg-slate-50 dark:bg-slate-800/50 opacity-40 cursor-not-allowed'
                }`}
              >
                <Newspaper size={20} className="text-amber-500 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Recherche article</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {selectedFile && selectedFile.type === 'json'
                      ? `Dans : ${selectedFile.name}`
                      : "Ouvrez d'abord un fichier JSON"}
                  </div>
                </div>
              </button>

              {/* Séparateur */}
              <div className="border-t border-slate-200 dark:border-slate-600 my-1" />

              {/* Filtres articles — disponibles si un fichier JSON est ouvert */}
              <button
                onClick={() => {
                  if (selectedFile && selectedFile.type === 'json') {
                    mobileFilterSignalRef.current = { mode: 'star', version: (mobileFilterSignalRef.current.version ?? 0) + 1 }
                    setMobileFilterSignal({ ...mobileFilterSignalRef.current })
                    setMobileFiltersActive(true)
                    setSearchTypeMenuOpen(false)
                    if (window.innerWidth < 768) setSidebarOpen(false)
                  }
                }}
                disabled={!selectedFile || selectedFile?.type !== 'json'}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-opacity ${
                  selectedFile && selectedFile.type === 'json'
                    ? 'bg-slate-100 dark:bg-slate-700 active:opacity-70'
                    : 'bg-slate-50 dark:bg-slate-800/50 opacity-40 cursor-not-allowed'
                }`}
              >
                <Star size={20} className="text-amber-400 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Articles favoris</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">Afficher uniquement les articles marqués d’une étoile</div>
                </div>
              </button>
              <button
                onClick={() => {
                  if (selectedFile && selectedFile.type === 'json') {
                    mobileFilterSignalRef.current = { mode: 'source', version: (mobileFilterSignalRef.current.version ?? 0) + 1 }
                    setMobileFilterSignal({ ...mobileFilterSignalRef.current })
                    setMobileFiltersActive(true)
                    setSearchTypeMenuOpen(false)
                    if (window.innerWidth < 768) setSidebarOpen(false)
                  }
                }}
                disabled={!selectedFile || selectedFile?.type !== 'json'}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-opacity ${
                  selectedFile && selectedFile.type === 'json'
                    ? 'bg-slate-100 dark:bg-slate-700 active:opacity-70'
                    : 'bg-slate-50 dark:bg-slate-800/50 opacity-40 cursor-not-allowed'
                }`}
              >
                <Filter size={20} className="text-slate-500 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Filtrer par source</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">Sélectionner une ou plusieurs sources d’articles</div>
                </div>
              </button>
              <button
                onClick={() => {
                  if (selectedFile && selectedFile.type === 'json') {
                    mobileFilterSignalRef.current = { mode: 'entity', version: (mobileFilterSignalRef.current.version ?? 0) + 1 }
                    setMobileFilterSignal({ ...mobileFilterSignalRef.current })
                    setMobileFiltersActive(true)
                    setSearchTypeMenuOpen(false)
                    if (window.innerWidth < 768) setSidebarOpen(false)
                  }
                }}
                disabled={!selectedFile || selectedFile?.type !== 'json'}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-opacity ${
                  selectedFile && selectedFile.type === 'json'
                    ? 'bg-slate-100 dark:bg-slate-700 active:opacity-70'
                    : 'bg-slate-50 dark:bg-slate-800/50 opacity-40 cursor-not-allowed'
                }`}
              >
                <Tag size={20} className="text-violet-500 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Filtrer par entité</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">Filtrer par type d’entité nommée (personnes, organisations…)</div>
                </div>
              </button>
              <button
                onClick={() => {
                  if (selectedFile && selectedFile.type === 'json') {
                    mobileFilterSignalRef.current = { mode: 'obsidian', version: (mobileFilterSignalRef.current.version ?? 0) + 1 }
                    setMobileFilterSignal({ ...mobileFilterSignalRef.current })
                    setMobileFiltersActive(true)
                    setSearchTypeMenuOpen(false)
                    if (window.innerWidth < 768) setSidebarOpen(false)
                  }
                }}
                disabled={!selectedFile || selectedFile?.type !== 'json'}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-opacity ${
                  selectedFile && selectedFile.type === 'json'
                    ? 'bg-slate-100 dark:bg-slate-700 active:opacity-70'
                    : 'bg-slate-50 dark:bg-slate-800/50 opacity-40 cursor-not-allowed'
                }`}
              >
                <BookOpen size={20} className="text-violet-600 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Rapport Obsidian</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">Afficher uniquement les articles avec un rapport Obsidian attaché</div>
                </div>
              </button>
              <button
                onClick={() => {
                  if (selectedFile && selectedFile.type === 'json') {
                    mobileFilterSignalRef.current = { mode: 'hidden', version: (mobileFilterSignalRef.current.version ?? 0) + 1 }
                    setMobileFilterSignal({ ...mobileFilterSignalRef.current })
                    setMobileFiltersActive(true)
                    setSearchTypeMenuOpen(false)
                    if (window.innerWidth < 768) setSidebarOpen(false)
                  }
                }}
                disabled={!selectedFile || selectedFile?.type !== 'json'}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-xl text-left transition-opacity ${
                  selectedFile && selectedFile.type === 'json'
                    ? 'bg-slate-100 dark:bg-slate-700 active:opacity-70'
                    : 'bg-slate-50 dark:bg-slate-800/50 opacity-40 cursor-not-allowed'
                }`}
              >
                <EyeOff size={20} className="text-slate-500 shrink-0" />
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Articles masqués</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">Afficher uniquement les articles que vous avez masqués</div>
                </div>
              </button>
            </div>
          </div>
        </div>
      )}

      {searchOpen && (
        <SearchOverlay
          onClose={() => setSearchOpen(false)}
          mode={searchMode}
          currentFile={selectedFile}
          onSelect={(result) => {
            if (searchMode === 'article') {
              articleSearchVersionRef.current += 1
              setArticleSearchQuery({ query: result._query || '', version: articleSearchVersionRef.current })
            } else {
              selectFile(result)
            }
            setSearchOpen(false)
          }}
        />
      )}
      {settingsOpen && (
        <SettingsPanel
          onClose={() => setSettingsOpen(false)}
          theme={theme}
          onThemeChange={setTheme}
          rssStatus={rssStatus}
          onOpenConsole={() => { setSettingsOpen(false); setConsoleOpen(true) }}
          onOpenTendances={() => { setSettingsOpen(false); setAlertsOpen(true) }}
          onOpenBiais={() => { setSettingsOpen(false); setBiasOpen(true) }}
        />
      )}
      {dashboardOpen && (
        <EntityDashboard
          onClose={() => setDashboardOpen(false)}
          onEntitySearch={(value, type) => {
            setDashboardOpen(false)
            setEntitySearch({ value, type })
          }}
        />
      )}
      {alertsOpen && (
        <AlertsPanel
          onClose={() => setAlertsOpen(false)}
          onEntitySearch={(value, type) => { setEntitySearch({ value, type }) }}
        />
      )}
      {topOpen && (
        <TopArticlesPanel
          onClose={() => setTopOpen(false)}
          annotations={annotations}
          onAnnotate={handleAnnotate}
          availableProviders={availableProviders}
        />
      )}
      {biasOpen && (
        <SourceBiasPanel onClose={() => setBiasOpen(false)} />
      )}
      {exportOpen && (
        <ExportPanel onClose={() => setExportOpen(false)} files={files} />
      )}
      {clusterOpen && (
        <ClusterView onClose={() => setClusterOpen(false)} />
      )}
      {watchOpen && (
        <EntityWatchPanel
          onClose={() => setWatchOpen(false)}
          onOpenArticles={(type, value) => {
            setWatchOpen(false)
            setEntitySearch({ value, type })
          }}
        />
      )}
      {compareOpen && (
        <ComparePanel onClose={() => setCompareOpen(false)} />
      )}
      {chatOpen && (
        <ChatbotPanel
          onClose={() => { setChatOpen(false); setChatEntityContext(null); setChatArticleContext(null) }}
          onFileSaved={refreshFiles}
          initialFile={(chatEntityContext || chatArticleContext) ? null : selectedFile}
          entityContext={chatEntityContext}
          articleContext={chatArticleContext}
        />
      )}
      {entitySearch && (
        <EntitySearchModal
          query={entitySearch.value}
          entityType={entitySearch.type}
          onClose={() => setEntitySearch(null)}
          onSelectFile={(file) => {
            const full = files.find(f => f.path === file.path) ?? file
            selectFile(full)
            setEntitySearch(null)
          }}
        />
      )}
    </div>
  )
}
