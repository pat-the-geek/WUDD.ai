import { lazy, Suspense, useEffect, useState, useRef, useCallback } from 'react'
import { X, FileText, Download, Loader2, ExternalLink, ChevronLeft, Network, GripHorizontal, Maximize2, Minimize2, Info, Calendar, Layers, Terminal, BookOpen, Hash, FolderOpen } from 'lucide-react'
import EntityWorldMap from './EntityWorldMap'
import TTSButton from './TTSButton'
import { openInObsidian } from '../utils/obsidian'

const EntityMarkdownContent = lazy(() => import('./EntityMarkdownContent'))
const EntityGraph = lazy(() => import('./EntityGraph'))
const EntityCalendar = lazy(() => import('./EntityCalendar'))
const EntityFullReportDialog = lazy(() => import('./EntityFullReportDialog'))
const GraphArticlePanel = lazy(() => import('./GraphArticlePanel'))

// ── Composants Markdown ────────────────────────────────────────────────────────
const MD = {
  h1: ({ children }) => <h1 className="text-lg font-bold text-slate-800 dark:text-slate-100 mt-4 mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100 mt-5 mb-2 pb-1 border-b border-slate-200 dark:border-slate-700">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mt-3 mb-1">{children}</h3>,
  p:  ({ children }) => <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed mb-3">{children}</p>,
  ul: ({ children }) => <ul className="list-disc ml-5 mb-3 space-y-1 text-sm text-slate-700 dark:text-slate-300">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal ml-5 mb-3 space-y-1 text-sm text-slate-700 dark:text-slate-300">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-slate-800 dark:text-slate-200">{children}</strong>,
  a:  ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#5856D6] dark:text-[#5E5CE6] hover:underline">{children}</a>,
  code: ({ className, children }) => className
    ? <code className="block bg-slate-100 dark:bg-slate-800/70 rounded-lg p-0.5 font-mono text-xs">{children}</code>
    : <code className="bg-slate-100 dark:bg-slate-800/70 px-1.5 py-0.5 rounded-full font-mono text-xs text-slate-700 dark:text-slate-300">{children}</code>,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-violet-400 pl-3 italic text-slate-600 dark:text-slate-400 mb-3">{children}</blockquote>,
  hr: () => <hr className="border-slate-200 dark:border-slate-700 my-4" />,
}

// ── Vue Informations — présentation pure (état géré par le parent) ─────────────
function EntityInfoView({ text, loading, error }) {
  if (error) return (
    <div className="flex items-center justify-center h-full text-sm text-red-500 dark:text-red-400 p-6">{error}</div>
  )
  return (
    <div className="flex-1 overflow-y-auto p-5 min-h-0">
      {loading && text.length === 0 && (
        <div className="flex items-center gap-2 text-slate-400 dark:text-slate-500 text-sm">
          <Loader2 size={16} className="animate-spin" />
          <span>Synthèse en cours…</span>
        </div>
      )}
      {text.length > 0 && (
        <>
          {!loading && (
            <div className="flex justify-end mb-2">
              <TTSButton text={text} size={13} />
            </div>
          )}
          <Suspense fallback={<PanelSectionFallback label="Chargement du rendu…" />}>
            <EntityMarkdownContent content={text} components={MD} />
          </Suspense>
        </>
      )}
      {loading && text.length > 0 && (
        <span className="inline-block w-1.5 h-4 bg-violet-400 dark:bg-violet-500 animate-pulse rounded-sm ml-0.5 align-middle" />
      )}
    </div>
  )
}

const IMAGE_TYPES = new Set(['PERSON', 'ORG', 'PRODUCT'])

// Taille et position initiales centrées.
// Retourne null sur mobile (< 640px) → fullscreen automatique.
function initialWin() {
  if (window.innerWidth < 640) return null
  const w = Math.round(Math.min(window.innerWidth  * 0.82, 1300))
  const h = Math.round(Math.min(window.innerHeight * 0.86, 920))
  return {
    x: Math.round((window.innerWidth  - w) / 2),
    y: Math.round((window.innerHeight - h) / 2),
    w,
    h,
  }
}

function EntityAvatar({ image, type, name, size = 40 }) {
  const [imgError, setImgError] = useState(false)
  const isPortrait = type === 'PERSON'
  const hasImage   = image != null && !imgError
  const initials   = name.split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')

  return (
    <div
      className={[
        'shrink-0 overflow-hidden border border-slate-200 dark:border-slate-700',
        isPortrait ? 'rounded-full' : 'rounded-lg',
        hasImage && !isPortrait ? 'bg-white dark:bg-white' : 'bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center',
      ].join(' ')}
      style={{ width: size, height: size }}
    >
      {hasImage ? (
        <img
          src={image.url} alt={name} onError={() => setImgError(true)}
          className={['w-full h-full', isPortrait ? 'object-cover' : 'object-contain p-1'].join(' ')}
        />
      ) : (
        <span className="text-violet-500 dark:text-violet-300 font-semibold text-xs select-none">{initials}</span>
      )}
    </div>
  )
}

// Poignée de redimensionnement (coin bas-droite)
function ResizeHandle({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="absolute bottom-0 right-0 w-5 h-5 cursor-se-resize opacity-30 hover:opacity-70 transition-opacity flex items-end justify-end p-1"
    >
      <svg width="9" height="9" viewBox="0 0 9 9" className="text-slate-500 fill-current">
        <path d="M9 3L3 9M9 6L6 9M9 0L0 9" stroke="currentColor" strokeWidth="1.2" fill="none" />
      </svg>
    </div>
  )
}

function PanelSectionFallback({ label = 'Chargement…' }) {
  return (
    <div className="flex items-center justify-center h-full min-h-32 text-sm text-slate-400 dark:text-slate-500 gap-2">
      <Loader2 size={16} className="animate-spin" />
      <span>{label}</span>
    </div>
  )
}

/**
 * EntityArticlePanel — fenêtre flottante (déplaçable + redimensionnable).
 *
 * Props:
 *   entityType  {string}  — type NER initial (ex. "ORG")
 *   entityValue {string}  — valeur initiale (ex. "OpenAI")
 *   onClose     {fn}      — ferme le panneau
 */
export default function EntityArticlePanel({ entityType, entityValue, onClose, onOpenFile }) {
  // ── Navigation ─────────────────────────────────────────────────────────────
  const [history, setHistory]   = useState([{ type: entityType, value: entityValue }])
  const current = history[history.length - 1]

  const [viewMode, setViewMode] = useState('articles')
  const [articles, setArticles] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [entityImage, setEntityImage] = useState(null)

  // ── Info / Synthèse IA ──────────────────────────────────────────────────────
  const [infoText, setInfoText]       = useState('')
  const [infoLoading, setInfoLoading] = useState(false)
  const [infoError, setInfoError]     = useState(null)
  const infoCtrlRef  = useRef(null)   // AbortController du fetch en cours
  const infoStarted  = useRef(false)  // true dès que le fetch a été lancé pour l'entité courante

  // ── RAG / Synthèse multi-sources ───────────────────────────────────────────
  const [ragText, setRagText]       = useState('')
  const [ragLoading, setRagLoading] = useState(false)
  const [ragError, setRagError]     = useState(null)
  const ragCtrlRef  = useRef(null)
  const ragStarted  = useRef(false)

  // ── Position / taille de la fenêtre ────────────────────────────────────────
  const [win, setWin] = useState(initialWin)   // null = fullscreen mobile
  const [isMaximized, setIsMaximized] = useState(false)
  const isMobileFullscreen = win === null
  const dragData = useRef(null)   // { type: 'move'|'resize', startX, startY, ...init }

  // Drag document-level (move + resize)
  useEffect(() => {
    const onMove = (e) => {
      const d = dragData.current
      if (!d) return
      const dx = e.clientX - d.startX
      const dy = e.clientY - d.startY
      if (d.type === 'move') {
        setWin(prev => ({
          ...prev,
          x: Math.max(0, Math.min(window.innerWidth  - prev.w, d.initX + dx)),
          y: Math.max(0, Math.min(window.innerHeight - 48,     d.initY + dy)),
        }))
      } else {
        setWin(prev => ({
          ...prev,
          w: Math.max(480, d.initW + dx),
          h: Math.max(340, d.initH + dy),
        }))
      }
    }
    const onUp = () => { dragData.current = null }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }
  }, [])

  // Drag du séparateur carte/articles
  useEffect(() => {
    const onMove = (e) => {
      const d = splitDragRef.current
      if (!d) return
      const dy = e.clientY - d.startY
      const pct = Math.max(20, Math.min(80, d.startPct + (dy / d.containerH) * 100))
      setSplitPct(pct)
    }
    const onUp = () => { splitDragRef.current = null }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [])

  const handleSplitMouseDown = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const container = splitContainerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    splitDragRef.current = { startY: e.clientY, startPct: splitPct, containerH: rect.height }
  }

  const handleHeaderMouseDown = (e) => {
    if (isMaximized || isMobileFullscreen) return  // pas de drag en plein écran
    if (e.target.closest('button')) return   // ne pas déclencher sur les boutons
    e.preventDefault()
    dragData.current = { type: 'move', startX: e.clientX, startY: e.clientY, initX: win.x, initY: win.y }
  }

  const handleResizeMouseDown = (e) => {
    if (isMobileFullscreen) return
    e.preventDefault()
    e.stopPropagation()
    dragData.current = { type: 'resize', startX: e.clientX, startY: e.clientY, initW: win.w, initH: win.h }
  }

  // ── Données ────────────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true); setError(null)
    const params = new URLSearchParams({ type: current.type, value: current.value })
    fetch(`/api/entities/articles?${params}`)
      .then(r => r.json())
      .then(data => {
        if (data?.error) throw new Error(data.error)
        const sorted = (Array.isArray(data) ? data : []).sort((a, b) => {
          const parseD = raw => { const m = (raw||'').match(/^(\d{2})\/(\d{2})\/(\d{4})$/); return m ? new Date(parseInt(m[3]), parseInt(m[2])-1, parseInt(m[1])) : new Date(raw||0) }
          const ta = parseD(a['Date de publication']).getTime()
          const tb = parseD(b['Date de publication']).getTime()
          return tb - ta
        })
        setArticles(sorted)
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [current.type, current.value])

  useEffect(() => {
    setEntityImage(null)
    if (!IMAGE_TYPES.has(current.type)) return
    fetch('/api/entities/images', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([{ name: current.value, type: current.type }]),
    })
      .then(r => r.json())
      .then(data => setEntityImage(data[current.value] ?? null))
      .catch(() => setEntityImage(null))
  }, [current.type, current.value])

  useEffect(() => {
    const h = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  // ── Info : reset quand l'entité change ─────────────────────────────────────
  useEffect(() => {
    setInfoText('')
    setInfoLoading(false)
    setInfoError(null)
    infoStarted.current = false
    if (infoCtrlRef.current) { infoCtrlRef.current.abort(); infoCtrlRef.current = null }
    // reset RAG aussi
    setRagText('')
    setRagLoading(false)
    setRagError(null)
    ragStarted.current = false
    if (ragCtrlRef.current) { ragCtrlRef.current.abort(); ragCtrlRef.current = null }
  }, [current.type, current.value])

  // ── RAG : lance le fetch au 1er affichage de l'onglet ─────────────────────
  useEffect(() => {
    if (viewMode !== 'rag' || ragStarted.current) return
    ragStarted.current = true

    const ctrl = new AbortController()
    ragCtrlRef.current = ctrl
    setRagText('')
    setRagLoading(true)
    setRagError(null)

    let inThink = false

    ;(async () => {
      try {
        const params = new URLSearchParams({
          entity_type: current.type,
          entity_value: current.value,
          n: 15,
        })
        const res = await fetch(`/api/synthesize-topic?${params}`, { signal: ctrl.signal })
        if (!res.ok) throw new Error(`Erreur serveur ${res.status}`)

        const reader  = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop()
          for (const line of lines) {
            // Accepte "data: {...}" et également "{...}" (JSON brut sans préfixe SSE)
            let raw
            if (line.startsWith('data: ')) raw = line.slice(6).trim()
            else if (line.startsWith('{')) raw = line.trim()
            else continue
            if (!raw) continue
            if (raw === '[DONE]') { setRagLoading(false); return }
            let chunk
            try {
              const parsed = JSON.parse(raw)
              if (parsed.error) throw new Error(parsed.error)
              chunk = parsed.choices?.[0]?.delta?.content ?? ''
            } catch (e) { if (e.message?.startsWith('Erreur')) throw e; continue }
            if (!chunk) continue

            // Filtre les blocs <think>…</think>
            let rem = chunk
            while (rem.length > 0) {
              if (!inThink) {
                const s = rem.indexOf('<think>')
                if (s === -1) { setRagText(p => p + rem); break }
                setRagText(p => p + rem.slice(0, s))
                rem = rem.slice(s + 7)
                inThink = true
              } else {
                const e = rem.indexOf('</think>')
                if (e === -1) break
                rem = rem.slice(e + 8)
                inThink = false
              }
            }
          }
        }
        setRagLoading(false)
      } catch (e) {
        setRagLoading(false)
        if (e.name !== 'AbortError') setRagError(e.message)
      }
    })()
  }, [viewMode, current.type, current.value])

  // ── Info : lance le fetch uniquement au 1er affichage de l'onglet ──────────
  useEffect(() => {
    if (viewMode !== 'info' || infoStarted.current) return
    infoStarted.current = true

    const ctrl = new AbortController()
    infoCtrlRef.current = ctrl
    setInfoText('')
    setInfoLoading(true)
    setInfoError(null)

    const entityType = current.type
    const entityValue = current.value
    let inThink = false

    ;(async () => {
      try {
        const params = new URLSearchParams({ type: entityType, value: entityValue })
        const res = await fetch(`/api/entities/info?${params}`, { signal: ctrl.signal })
        if (!res.ok) throw new Error(`Erreur serveur ${res.status}`)

        const reader  = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop()

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const raw = line.slice(6).trim()
            if (raw === '[DONE]') continue
            let chunk
            try {
              const parsed = JSON.parse(raw)
              if (parsed.error) throw new Error(parsed.error)
              chunk = parsed.choices?.[0]?.delta?.content ?? ''
            } catch (e) { if (e.message?.startsWith('Erreur')) throw e; continue }
            if (!chunk) continue

            // Filtre les blocs <think>…</think> des réponses Qwen
            let rem = chunk
            while (rem.length > 0) {
              if (!inThink) {
                const s = rem.indexOf('<think>')
                if (s === -1) { setInfoText(p => p + rem); break }
                setInfoText(p => p + rem.slice(0, s))
                rem = rem.slice(s + 7)
                inThink = true
              } else {
                const e = rem.indexOf('</think>')
                if (e === -1) break
                rem = rem.slice(e + 8)
                inThink = false
              }
            }
          }
        }
        setInfoLoading(false)
      } catch (e) {
        setInfoLoading(false)
        if (e.name !== 'AbortError') setInfoError(e.message)
      }
    })()
    // Pas de cleanup ici : le stream continue en arrière-plan si on change d'onglet.
    // L'abort se fait via l'effet de reset (changement d'entité) ou démontage.
  }, [viewMode, current.type, current.value])

  // ── Nettoyage au démontage ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      infoCtrlRef.current?.abort()
      ragCtrlRef.current?.abort()
    }
  }, [])

  // ── Navigation interne ─────────────────────────────────────────────────────
  const navigateTo = useCallback((type, value) => {
    setHistory(prev => [...prev, { type, value }])
  }, [])

  const goBack = useCallback(() => {
    setHistory(prev => prev.length > 1 ? prev.slice(0, -1) : prev)
  }, [])

  // ── Rapports précédents de l'entité ────────────────────────────────────────
  const [entityRapports, setEntityRapports]   = useState([])
  const [obsidianVaultName, setObsidianVaultName] = useState(null)
  const [rapportsFetchKey, setRapportsFetchKey] = useState(0)

  useEffect(() => {
    const params = new URLSearchParams({ entity_type: current.type, entity_value: current.value })
    fetch(`/api/entity/get-report-meta?${params}`)
      .then(r => r.ok ? r.json() : { rapports: [] })
      .then(d => setEntityRapports(Array.isArray(d.rapports) ? d.rapports : []))
      .catch(() => setEntityRapports([]))
  }, [current.type, current.value, rapportsFetchKey])

  useEffect(() => {
    fetch('/api/config/obsidian')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.vault_name) setObsidianVaultName(d.vault_name) })
      .catch(() => {})
  }, [])

  // ── Exports ────────────────────────────────────────────────────────────────
  const [showReportDialog, setShowReportDialog] = useState(false)
  const [reportArticle, setReportArticle] = useState(null)

  // ── Splitter carte/articles (GPE · LOC) ────────────────────────────────────
  const [splitPct, setSplitPct]   = useState(50)
  const splitDragRef              = useRef(null)
  const splitContainerRef         = useRef(null)

  const handleGenerateReport = () => {
    if (!articles.length) return
    setShowReportDialog(true)
  }

  const handleExportJSON = () => {
    const safe = current.value.replace(/[^a-zA-Z0-9_\-]/g, '_')
    const blob = new Blob([JSON.stringify(articles, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    Object.assign(document.createElement('a'), { href: url, download: `entites_${current.type}_${safe}_${new Date().toISOString().slice(0, 10)}.json` }).click()
    URL.revokeObjectURL(url)
  }

  // ── Rendu ──────────────────────────────────────────────────────────────────
  return (
    <>
      {/* Fond semi-transparent (clic → ferme) */}
      <div
        className="hig-overlay-enter fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]"
        onClick={onClose}
      />

      {/* Fenêtre flottante */}
      <div
        className={`hig-modal-enter fixed z-[61] flex flex-col bg-slate-50/90 dark:bg-slate-900/90 backdrop-blur-2xl shadow-2xl border border-white/30 dark:border-slate-700/50 overflow-hidden ${isMaximized ? '' : 'rounded-2xl'}`}
        style={isMaximized || isMobileFullscreen
          ? { inset: 0 }
          : { left: win.x, top: win.y, width: win.w, height: win.h, minWidth: 320, minHeight: 300 }}
      >
        {/* ── En-tête (drag zone) ── */}
        <div
          className={`flex items-center gap-2 px-4 py-3 bg-white/70 dark:bg-slate-800/70 backdrop-blur-xl border-t border-white/40 dark:border-slate-700/50 md:border-t-0 md:border-b shrink-0 flex-wrap gap-y-2 select-none order-last md:order-first ${isMaximized ? 'cursor-default' : 'cursor-move'}`}
          style={{ paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))' }}
          onMouseDown={handleHeaderMouseDown}
        >
          {/* Icône de déplacement — desktop uniquement */}
          {!isMaximized && (
            <GripHorizontal size={14} className="hidden md:block text-slate-300 dark:text-slate-600 shrink-0 pointer-events-none" />
          )}

          {/* Bouton retour */}
          {history.length > 1 && (
            <button
              onClick={goBack}
              title={`Retour à ${history[history.length - 2].value}`}
              className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer"
            >
              <ChevronLeft size={13} />
              {history[history.length - 2].value}
            </button>
          )}

          {/* Avatar — desktop uniquement */}
          {IMAGE_TYPES.has(current.type) && (
            <div className="hidden md:flex">
              <EntityAvatar image={entityImage} type={current.type} name={current.value} size={36} />
            </div>
          )}

          {/* Titre — desktop uniquement */}
          <div className="hidden md:flex items-center gap-1.5 min-w-0 flex-1 pointer-events-none">
            <span className="font-semibold text-slate-800 dark:text-slate-100 text-sm truncate">
              Occurrences de{' '}
              <span className="text-[#5856D6] dark:text-[#5E5CE6]">{current.value}</span>
            </span>
            <span className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 shrink-0">
              {current.type}
            </span>
            {!loading && (
              <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">
                — {articles.length} article{articles.length !== 1 ? 's' : ''}
              </span>
            )}
            {/* Badge rapports générés */}
            {entityRapports.length > 0 && (
              <span className="pointer-events-auto flex items-center gap-1 shrink-0">
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[11px] font-medium bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-700">
                  <BookOpen size={9} />
                  {entityRapports.length} rapport{entityRapports.length > 1 ? 's' : ''}
                </span>
                {/* Lien Obsidian pour le rapport le plus récent */}
                {entityRapports[entityRapports.length - 1]?.fichier && (
                  <button
                    onClick={() => {
                      const rap = entityRapports[entityRapports.length - 1]
                      openInObsidian(rap.fichier, obsidianVaultName)
                    }}
                    title={`Ouvrir dans Obsidian : ${entityRapports[entityRapports.length - 1].fichier}`}
                    className="inline-flex items-center gap-0.5 text-[11px] text-[#5856D6] dark:text-[#5E5CE6] hover:text-[#3d3bab] dark:hover:text-[#8785ff] underline underline-offset-2 transition-colors"
                  >
                    Ouvrir
                  </button>
                )}
              </span>
            )}
          </div>

          {/* Titre — mobile */}
          <div className="flex md:hidden items-center gap-1.5 min-w-0 w-full pointer-events-none">
            <span className="font-semibold text-slate-800 dark:text-slate-100 text-sm truncate">
              {current.value}
            </span>
            <span className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 shrink-0">
              {current.type}
            </span>
            {!loading && (
              <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0 ml-auto">
                {articles.length} article{articles.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {/* Badge rapports générés — mobile uniquement */}
          {entityRapports.length > 0 && (
            <span className="flex md:hidden items-center gap-1.5 w-full pointer-events-auto">
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[11px] font-medium bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-700">
                <BookOpen size={9} />
                {entityRapports.length} rapport{entityRapports.length > 1 ? 's' : ''}
              </span>
              {entityRapports[entityRapports.length - 1]?.fichier && (
                <button
                  onClick={() => {
                    const rap = entityRapports[entityRapports.length - 1]
                    openInObsidian(rap.fichier, obsidianVaultName)
                  }}
                  title={`Ouvrir dans Obsidian : ${entityRapports[entityRapports.length - 1].fichier}`}
                  className="inline-flex items-center gap-0.5 text-[11px] text-[#5856D6] dark:text-[#5E5CE6] hover:text-[#3d3bab] dark:hover:text-[#8785ff] underline underline-offset-2 transition-colors"
                >
                  Ouvrir
                </button>
              )}
            </span>
          )}

          {/* Actions */}
          <div className="flex items-center gap-1.5 sm:gap-1.5 w-full md:w-auto shrink-0 flex-wrap cursor-default">
            {/* Toggle Articles / Graphe / Informations */}
            <div className="flex flex-1 md:flex-none rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
              <button
                onClick={() => setViewMode('articles')}
                title="Articles"
                className={`flex-1 md:flex-none inline-flex items-center justify-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 text-xs font-medium transition-colors ${
                  viewMode === 'articles'
                    ? 'bg-violet-500 text-white'
                    : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
              >
                <FileText size={18} className="md:hidden" />
                <FileText size={12} className="hidden md:block" />
                <span className="hidden sm:inline">Articles</span>
              </button>
              <button
                onClick={() => setViewMode('graph')}
                title="Graphe de co-occurrences"
                className={`flex-1 md:flex-none inline-flex items-center justify-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                  viewMode === 'graph'
                    ? 'bg-violet-500 text-white'
                    : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
              >
                <Network size={18} className="md:hidden" />
                <Network size={12} className="hidden md:block" />
                <span className="hidden sm:inline">Graphe</span>
              </button>
              <button
                onClick={() => setViewMode('info')}
                title="Synthèse générée par l'IA"
                className={`flex-1 md:flex-none inline-flex items-center justify-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                  viewMode === 'info'
                    ? 'bg-violet-500 text-white'
                    : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
              >
                <Info size={18} className="md:hidden" />
                <Info size={12} className="hidden md:block" />
                <span className="hidden sm:inline">Infos</span>
              </button>
              <button
                onClick={() => setViewMode('calendar')}
                title="Calendrier des articles"
                className={`flex-1 md:flex-none inline-flex items-center justify-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                  viewMode === 'calendar'
                    ? 'bg-violet-500 text-white'
                    : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
              >
                <Calendar size={18} className="md:hidden" />
                <Calendar size={12} className="hidden md:block" />
                <span className="hidden sm:inline">Calendrier</span>
              </button>
              <button
                onClick={() => setViewMode('rag')}
                title="Synthèse comparative multi-sources (RAG)"
                className={`flex-1 md:flex-none inline-flex items-center justify-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                  viewMode === 'rag'
                    ? 'bg-emerald-500 text-white'
                    : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
              >
                <Layers size={18} className="md:hidden" />
                <Layers size={12} className="hidden md:block" />
                <span className="hidden sm:inline">RAG</span>
              </button>
            </div>

            <button
              onClick={() => {
                window.dispatchEvent(new CustomEvent('wudd:openEntityChatbot', {
                  detail: { type: current.type, value: current.value }
                }))
              }}
              disabled={loading || articles.length === 0}
              title="Ouvrir le Terminal IA avec le contexte de cette entité"
              className="inline-flex items-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 rounded-lg text-xs font-medium bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-200 dark:hover:bg-emerald-900/70 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Terminal size={18} className="md:hidden" />
              <Terminal size={12} className="hidden md:block" />
              <span className="hidden sm:inline">Terminal IA</span>
            </button>
            <button
              onClick={handleGenerateReport}
              disabled={loading || articles.length === 0}
              title="Générer un rapport Markdown complet (streaming, Mermaid, Export Obsidian)"
              className="inline-flex items-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 rounded-lg text-xs font-medium bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 hover:bg-violet-200 dark:hover:bg-violet-900/70 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <FileText size={18} className="md:hidden" />
              <FileText size={12} className="hidden md:block" />
              <span className="hidden sm:inline">Rapport</span>
            </button>
            <button
              onClick={handleExportJSON}
              disabled={loading || articles.length === 0}
              title="Exporter les articles en JSON"
              className="inline-flex items-center gap-1 px-3 py-3 md:px-2.5 md:py-1.5 rounded-lg text-xs font-medium bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-900/70 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Download size={18} className="md:hidden" />
              <Download size={12} className="hidden md:block" />
              <span className="hidden sm:inline">JSON</span>
            </button>
            {/* Bouton maximize masqué sur mobile (déjà fullscreen) */}
            {!isMobileFullscreen && (
              <button
                onClick={() => setIsMaximized(m => !m)}
                title={isMaximized ? 'Réduire la fenêtre' : 'Agrandir à la taille de l\'écran'}
                className="w-11 h-11 md:w-8 md:h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
              >
                {isMaximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              </button>
            )}
            <button
              onClick={onClose}
              className="w-11 h-11 md:w-8 md:h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* ── Corps (prend tout l'espace restant) ── */}
        {viewMode === 'info' ? (
          /* Mode informations : synthèse streaming Markdown */
          <EntityInfoView text={infoText} loading={infoLoading} error={infoError} />
        ) : viewMode === 'rag' ? (
          /* Mode RAG : synthèse comparative multi-sources */
          <div className="flex-1 min-h-0 overflow-y-auto p-5">
            {ragLoading && !ragText && (
              <div className="flex items-center gap-2 text-slate-400 dark:text-slate-500 text-sm py-8 justify-center">
                <Loader2 size={16} className="animate-spin" />
                <span>Synthèse en cours à partir des articles…</span>
              </div>
            )}
            {ragError && (
              <div className="text-red-500 dark:text-red-400 text-sm py-4">{ragError}</div>
            )}
            {ragText && (
              <div className="prose-sm dark:prose-invert max-w-none">
                {!ragLoading && (
                  <div className="flex justify-end mb-2">
                    <TTSButton text={ragText} size={13} />
                  </div>
                )}
                <Suspense fallback={<PanelSectionFallback label="Chargement du rendu…" />}>
                  <EntityMarkdownContent content={ragText} components={MD} />
                </Suspense>
                {ragLoading && (
                  <span className="inline-block w-2 h-4 bg-emerald-500 animate-pulse ml-1 rounded-sm" />
                )}
              </div>
            )}
            {!ragLoading && !ragText && !ragError && (
              <div className="text-center text-slate-400 dark:text-slate-500 text-sm py-8">
                Aucun contenu trouvé pour cette entité.
              </div>
            )}
          </div>
        ) : viewMode === 'calendar' ? (
          /* Mode calendrier */
          <div className="flex-1 min-h-0 overflow-y-auto">
            <Suspense fallback={<PanelSectionFallback label="Chargement du calendrier…" />}>
              <EntityCalendar articles={articles} />
            </Suspense>
          </div>
        ) : viewMode === 'graph' ? (
          /* Mode graphe : flex-col sans scroll pour que le SVG remplisse la hauteur */
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden px-4 pt-3 pb-2">
            <Suspense fallback={<PanelSectionFallback label="Chargement du graphe…" />}>
              <EntityGraph
                entityType={current.type}
                entityValue={current.value}
                onNavigate={navigateTo}
              />
            </Suspense>
          </div>
        ) : (
        /* Mode articles : visuel en haut + liste en bas (avec splitter) */
        <div ref={splitContainerRef} className="flex-1 min-h-0 flex flex-col overflow-hidden">

          {/* ── Carte géographique — GPE / LOC ── */}
          {(current.type === 'GPE' || current.type === 'LOC') && (
            <>
              <div style={{ height: `${splitPct}%` }} className="shrink-0 overflow-hidden">
                <EntityWorldMap
                  key={current.value}
                  entities={[{ name: current.value, type: current.type, count: Math.max(1, articles.length) }]}
                  onEntityClick={() => {}}
                  style={{ height: '100%' }}
                />
              </div>
              <div
                onMouseDown={handleSplitMouseDown}
                className="h-2 shrink-0 bg-slate-200 dark:bg-slate-700 hover:bg-violet-400 dark:hover:bg-violet-600 cursor-row-resize flex items-center justify-center transition-colors group select-none"
              >
                <div className="w-10 h-1 rounded-full bg-slate-400 dark:bg-slate-500 group-hover:bg-white transition-colors" />
              </div>
            </>
          )}

          {/* ── Photo — PERSON / ORG / PRODUCT ── */}
          {(current.type === 'PERSON' || current.type === 'ORG' || current.type === 'PRODUCT') && (
            <>
              <div
                style={{ height: `${splitPct}%` }}
                className={`shrink-0 overflow-hidden flex items-center justify-center ${
                  current.type === 'PERSON' || current.type === 'PRODUCT'
                    ? 'bg-slate-900'
                    : 'bg-white dark:bg-slate-800/60'
                }`}
              >
                {entityImage ? (
                  current.type === 'PERSON' || current.type === 'PRODUCT' ? (
                    /* Portrait : fond flouté plein cadre + image centrée au-dessus */
                    <div className="relative w-full h-full overflow-hidden">
                      {/* Arrière-plan flouté */}
                      <img
                        src={entityImage.url}
                        alt=""
                        aria-hidden="true"
                        className="absolute inset-0 w-full h-full object-cover scale-110"
                        style={{ filter: 'blur(22px)', transform: 'scale(1.15)' }}
                      />
                      <div className="absolute inset-0 bg-black/30" />
                      {/* Portrait centré */}
                      <img
                        src={entityImage.url}
                        alt={current.value}
                        className="relative h-full w-auto mx-auto object-cover drop-shadow-2xl"
                        onError={(e) => { e.currentTarget.parentElement.style.display = 'none' }}
                      />
                    </div>
                  ) : (
                    <img
                      src={entityImage.url}
                      alt={current.value}
                      className="object-contain max-h-full max-w-full p-6"
                      onError={(e) => { e.currentTarget.style.display = 'none' }}
                    />
                  )
                ) : (
                  <div className="flex flex-col items-center gap-3 text-slate-400 dark:text-slate-500">
                    <div className={`w-20 h-20 bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center ${current.type === 'PERSON' ? 'rounded-full' : 'rounded-xl'}`}>
                      <span className="text-violet-500 dark:text-violet-300 font-semibold text-2xl select-none">
                        {current.value.split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')}
                      </span>
                    </div>
                    <span className="text-xs">Aucune image disponible</span>
                  </div>
                )}
              </div>
              <div
                onMouseDown={handleSplitMouseDown}
                className="h-2 shrink-0 bg-slate-200 dark:bg-slate-700 hover:bg-violet-400 dark:hover:bg-violet-600 cursor-row-resize flex items-center justify-center transition-colors group select-none"
              >
                <div className="w-10 h-1 rounded-full bg-slate-400 dark:bg-slate-500 group-hover:bg-white transition-colors" />
              </div>
            </>
          )}
          {/* Liste des articles */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4 min-h-0">
          {loading ? (
            <div className="flex items-center justify-center py-16 gap-2 text-slate-400 dark:text-slate-500">
              <Loader2 size={20} className="animate-spin" />
              <span className="text-sm">Chargement des articles…</span>
            </div>
          ) : error ? (
            <div className="text-center py-16 text-red-500 dark:text-red-400 text-sm">{error}</div>
          ) : articles.length === 0 ? (
            <div className="text-center py-16 text-slate-400 dark:text-slate-500 text-sm">
              Aucun article trouvé pour cette entité.
            </div>
          ) : (
            articles.map((art, i) => (
              <article
                key={i}
                className="bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700/60 rounded-xl p-4 space-y-2 cursor-pointer hover:border-[#007AFF]/40 dark:hover:border-[#0A84FF]/40 hover:shadow-sm transition-all"
                onClick={() => setReportArticle(art)}
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 flex-wrap">
                    {art['Date de publication'] && <span>{art['Date de publication']}</span>}
                    {art['Sources'] && (
                      <><span>·</span><span className="font-medium text-slate-700 dark:text-slate-300">{art['Sources']}</span></>
                    )}
                    {art['mot_cle'] && (() => {
                      const terme = art['terme_declencheur']
                      const termeAnd = art['terme_and']
                      const isDifferent = terme && terme.toLowerCase() !== art['mot_cle'].toLowerCase()
                      const label = isDifferent ? terme : art['mot_cle']
                      const tooltip = [
                        isDifferent ? `Mot-clé parent : ${art['mot_cle']}` : 'Mot-clé de collecte',
                        termeAnd ? `Confirmé par (et) : ${termeAnd}` : null,
                      ].filter(Boolean).join('\n')
                      return (
                        <span
                          className="inline-flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/30 px-1.5 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800"
                          title={tooltip}
                        >
                          <Hash size={9} />{label}
                          {termeAnd && (
                            <span className="text-emerald-500 dark:text-emerald-400 opacity-60 italic">+{termeAnd}</span>
                          )}
                        </span>
                      )
                    })()}
                    {art['fichier_source'] && (
                      <button
                        onClick={e => { e.stopPropagation(); onOpenFile?.(art['fichier_source']) }}
                        className="inline-flex items-center gap-1 text-[11px] text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-900/30 px-1.5 py-0.5 rounded-full border border-sky-200 dark:border-sky-800 hover:bg-sky-100 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
                        title={`Ouvrir ${art['fichier_source']}`}
                      >
                        <FolderOpen size={9} />{art['fichier_source'].split('/').pop()}
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                    {art['Résumé'] && <TTSButton text={art['Résumé']} size={12} />}
                    {art['URL'] && (
                      <a
                        href={art['URL']} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-[#007AFF] dark:text-[#0A84FF] hover:underline"
                      >
                        Lire <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                </div>
                {art['Résumé'] && (
                  <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed line-clamp-4">
                    {art['Résumé']}
                  </p>
                )}
                {/* Badge rapport exporté pour cet article */}
                {Array.isArray(art['rapports']) && art['rapports'].length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {art['rapports'].map((rap, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-violet-50 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-700"
                        title={`Rapport ${rap.cible === 'obsidian' ? 'Obsidian' : 'local'} — ${rap.date_creation ?? ''}\n${rap.chemin ?? ''}`}
                      >
                        <BookOpen size={9} />
                        {rap.cible === 'obsidian' ? 'Obsidian' : 'Local'}
                        {rap.date_creation && (
                          <span className="opacity-70">
                            {' '}{rap.date_creation.slice(0, 10)}
                          </span>
                        )}
                        {rap.cible === 'obsidian' && rap.fichier && (
                          <button
                            onClick={e => {
                              e.stopPropagation()
                              openInObsidian(rap.fichier, obsidianVaultName)
                            }}
                            className="ml-0.5 underline underline-offset-1 hover:text-violet-900 dark:hover:text-violet-100 transition-colors"
                            title="Ouvrir dans Obsidian"
                          >
                            ↗
                          </button>
                        )}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))
          )}
          </div>
        </div>
        )}

        {/* ── Poignée de redimensionnement (masquée en plein écran et sur mobile) ── */}
        {!isMaximized && !isMobileFullscreen && <ResizeHandle onMouseDown={handleResizeMouseDown} />}
      </div>

      {/* ── Dialogue rapport complet entité ── */}
      {showReportDialog && (
        <Suspense fallback={<PanelSectionFallback label="Chargement du rapport…" />}>
          <EntityFullReportDialog
            entityType={current.type}
            entityValue={current.value}
            articles={articles}
            onClose={() => { setShowReportDialog(false); setRapportsFetchKey(k => k + 1) }}
          />
        </Suspense>
      )}

      {/* ── Panel article complet (image, NER, résumé enrichi) ── */}
      {reportArticle && (
        <Suspense fallback={<PanelSectionFallback label="Chargement de l'article…" />}>
          <GraphArticlePanel
            article={reportArticle}
            filePath={reportArticle._source_file ?? null}
            onClose={() => setReportArticle(null)}
          />
        </Suspense>
      )}
    </>
  )
}
