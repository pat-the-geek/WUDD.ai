import { useMemo, useState, useRef, useCallback, useEffect } from 'react'
import {
  ExternalLink, ChevronDown, ChevronUp, Tag, X,
  Filter, Search, ArrowUpDown, Newspaper,
  Download, LayoutGrid, AlignLeft, LayoutList, Maximize2, Clock,
  Star, Eye, Pencil, Check, RefreshCw, FileText, Scale,
} from 'lucide-react'
import EntityHighlighter from './EntityHighlighter'
import EntityArticlePanel from './EntityArticlePanel'
import ArticleFullReportDialog from './ArticleFullReportDialog'
import TTSButton from './TTSButton'

// ── Badge sentiment ───────────────────────────────────────────────────────────
const SENTIMENT_CFG = {
  positif: { label: 'Positif', score: null, dot: 'bg-emerald-500', text: 'text-emerald-700 dark:text-emerald-300', bg: 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800' },
  neutre:  { label: 'Neutre',  score: null, dot: 'bg-slate-400',   text: 'text-slate-600 dark:text-slate-400',     bg: 'bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600' },
  négatif: { label: 'Négatif', score: null, dot: 'bg-rose-500',    text: 'text-rose-700 dark:text-rose-300',       bg: 'bg-rose-50 dark:bg-rose-900/30 border-rose-200 dark:border-rose-800' },
}
const TON_LABELS = { factuel: 'Factuel', alarmiste: 'Alarmiste', promotionnel: 'Promo', critique: 'Critique', analytique: 'Analytique' }

function ReadingTimeBadge({ article }) {
  const label = article.temps_lecture_label
  if (!label) return null
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full border bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400">
      <Clock size={9} className="shrink-0" />
      {label}
    </span>
  )
}

function SentimentBadge({ article }) {
  const sentiment   = article.sentiment
  const scoreSent   = article.score_sentiment
  const ton         = article.ton_editorial
  const scoreTon    = article.score_ton
  if (!sentiment) return null
  const cfg = SENTIMENT_CFG[sentiment] ?? SENTIMENT_CFG.neutre
  return (
    <div className="flex items-center gap-1.5 flex-wrap mt-1">
      <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${cfg.bg} ${cfg.text}`}>
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
        {cfg.label}{scoreSent ? ` ${scoreSent}/5` : ''}
      </span>
      {ton && (
        <span className="inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded-full border bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400">
          {TON_LABELS[ton] ?? ton}{scoreTon ? ` ${scoreTon}/5` : ''}
        </span>
      )}
    </div>
  )
}

const CHIP_COLORS = {
  PERSON:      { idle: 'bg-violet-100 dark:bg-violet-900/50 text-violet-800 dark:text-violet-200 border-violet-200 dark:border-violet-800',       on: 'bg-violet-500 dark:bg-violet-600 text-white border-violet-600 dark:border-violet-500' },
  ORG:         { idle: 'bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-800',                   on: 'bg-blue-500 dark:bg-blue-600 text-white border-blue-600 dark:border-blue-500' },
  GPE:         { idle: 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-800', on: 'bg-emerald-500 dark:bg-emerald-600 text-white border-emerald-600 dark:border-emerald-500' },
  PRODUCT:     { idle: 'bg-orange-100 dark:bg-orange-900/50 text-orange-800 dark:text-orange-200 border-orange-200 dark:border-orange-800',       on: 'bg-orange-500 dark:bg-orange-600 text-white border-orange-600 dark:border-orange-500' },
  EVENT:       { idle: 'bg-amber-100 dark:bg-amber-900/50 text-amber-800 dark:text-amber-200 border-amber-200 dark:border-amber-800',             on: 'bg-amber-500 dark:bg-amber-600 text-white border-amber-600 dark:border-amber-500' },
  LAW:         { idle: 'bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-200 border-red-200 dark:border-red-800',                         on: 'bg-red-500 dark:bg-red-600 text-white border-red-600 dark:border-red-500' },
  LOC:         { idle: 'bg-teal-100 dark:bg-teal-900/50 text-teal-800 dark:text-teal-200 border-teal-200 dark:border-teal-800',                   on: 'bg-teal-500 dark:bg-teal-600 text-white border-teal-600 dark:border-teal-500' },
  NORP:        { idle: 'bg-fuchsia-100 dark:bg-fuchsia-900/50 text-fuchsia-800 dark:text-fuchsia-200 border-fuchsia-200 dark:border-fuchsia-800', on: 'bg-fuchsia-500 dark:bg-fuchsia-600 text-white border-fuchsia-600 dark:border-fuchsia-500' },
  FAC:         { idle: 'bg-cyan-100 dark:bg-cyan-900/50 text-cyan-800 dark:text-cyan-200 border-cyan-200 dark:border-cyan-800',                   on: 'bg-cyan-500 dark:bg-cyan-600 text-white border-cyan-600 dark:border-cyan-500' },
  WORK_OF_ART: { idle: 'bg-rose-100 dark:bg-rose-900/50 text-rose-800 dark:text-rose-200 border-rose-200 dark:border-rose-800',                   on: 'bg-rose-500 dark:bg-rose-600 text-white border-rose-600 dark:border-rose-500' },
  MONEY:       { idle: 'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-800 dark:text-yellow-200 border-yellow-200 dark:border-yellow-800',       on: 'bg-yellow-500 dark:bg-yellow-600 text-white border-yellow-600 dark:border-yellow-500' },
  PERCENT:     { idle: 'bg-lime-100 dark:bg-lime-900/50 text-lime-800 dark:text-lime-200 border-lime-200 dark:border-lime-800',                   on: 'bg-lime-500 dark:bg-lime-600 text-white border-lime-600 dark:border-lime-500' },
  LANGUAGE:    { idle: 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-800 dark:text-indigo-200 border-indigo-200 dark:border-indigo-800',       on: 'bg-indigo-500 dark:bg-indigo-600 text-white border-indigo-600 dark:border-indigo-500' },
  DATE:        { idle: 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-600',               on: 'bg-slate-500 dark:bg-slate-600 text-white border-slate-600 dark:border-slate-500' },
  TIME:        { idle: 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-600',               on: 'bg-slate-500 dark:bg-slate-600 text-white border-slate-600 dark:border-slate-500' },
  QUANTITY:    { idle: 'bg-stone-100 dark:bg-stone-700/60 text-stone-700 dark:text-stone-300 border-stone-200 dark:border-stone-600',             on: 'bg-stone-500 dark:bg-stone-600 text-white border-stone-600 dark:border-stone-500' },
  CARDINAL:    { idle: 'bg-zinc-100 dark:bg-zinc-700/60 text-zinc-700 dark:text-zinc-300 border-zinc-200 dark:border-zinc-600',                   on: 'bg-zinc-500 dark:bg-zinc-600 text-white border-zinc-600 dark:border-zinc-500' },
  ORDINAL:     { idle: 'bg-gray-100 dark:bg-gray-700/60 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-600',                   on: 'bg-gray-500 dark:bg-gray-600 text-white border-gray-600 dark:border-gray-500' },
}
const FALLBACK_CHIP = {
  idle: 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600',
  on:   'bg-slate-500 dark:bg-slate-600 text-white border-slate-600 dark:border-slate-500',
}

const SORT_OPTIONS = [
  { value: 'date-desc', label: 'Date ↓ (récent)' },
  { value: 'date-asc',  label: 'Date ↑ (ancien)' },
  { value: 'entities',  label: 'Entités ↓' },
  { value: 'source',    label: 'Source A→Z' },
]

const BUCKET_ORDER = [
  "Aujourd'hui", "Hier", "Cette semaine", "Ce mois",
  "Il y a 1 à 3 mois", "Plus ancien", "Date inconnue",
]

// ── Helpers ───────────────────────────────────────────────────────────────────

// Parse DD/MM/YYYY (standard projet), ISO 8601 ou RFC 822.
// new Date("11/03/2026") serait interprété par JS comme novembre 3 (format US),
// d'où ce helper qui détecte et corrige le format français en priorité.
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

function formatTime(raw) {
  // ISO 8601 : "2026-03-02T03:14:00Z"  — RFC 822 : "Fri, 27 Feb 2026 17:23:48 +0000" — DD/MM/YYYY n'a pas d'heure
  if (!raw || (!/T\d{2}:\d{2}/.test(raw) && !/\d{2}:\d{2}:\d{2}/.test(raw))) return ''
  try {
    return parseArticleDate(raw).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

function firstImage(images) {
  if (!Array.isArray(images)) return null
  // Le champ peut être "URL" (majuscule, standard JSON) ou "url" (minuscule)
  return images.find(i => i?.URL || i?.url)?.URL ?? images.find(i => i?.url)?.url ?? null
}

function entityCount(article) {
  if (!article.entities) return 0
  return Object.values(article.entities).reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0)
}

function toTimestamp(raw) {
  if (!raw) return 0
  const d = parseArticleDate(raw)
  return isNaN(d) ? 0 : d.getTime()
}

function getDateBucket(raw) {
  if (!raw) return 'Date inconnue'
  const d = parseArticleDate(raw)
  if (isNaN(d)) return 'Date inconnue'
  const now = new Date(); now.setHours(0, 0, 0, 0)
  const target = new Date(d); target.setHours(0, 0, 0, 0)
  const diff = Math.round((now - target) / 86400000)
  if (diff < 0)  return "Aujourd'hui"
  if (diff === 0) return "Aujourd'hui"
  if (diff === 1) return 'Hier'
  if (diff < 7)  return 'Cette semaine'
  if (diff < 30) return 'Ce mois'
  if (diff < 90) return 'Il y a 1 à 3 mois'
  return 'Plus ancien'
}

// ── Sous-composants ───────────────────────────────────────────────────────────

/** Surligne les occurrences de `query` dans `text` (plain text, sans NER). */
function SearchHighlighter({ text, query }) {
  if (!query || !text) {
    return <p className="leading-7 text-slate-700 dark:text-slate-300">{text}</p>
  }
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <p className="leading-7 text-base text-slate-700 dark:text-slate-300">
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase()
          ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700/60 text-yellow-900 dark:text-yellow-100 rounded px-0.5">{part}</mark>
          : <span key={i}>{part}</span>
      )}
    </p>
  )
}

/** Lightbox plein écran pour une image unique. */
function ImageLightbox({ url, alt, onClose }) {
  return (
    <div
      className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <img
        src={url}
        alt={alt}
        className="max-w-full max-h-[90vh] rounded-xl object-contain shadow-2xl"
      />
      <button
        onClick={onClose}
        className="absolute top-4 right-4 w-9 h-9 bg-slate-700/80 hover:bg-slate-600 rounded-full flex items-center justify-center text-slate-300 hover:text-white transition-colors"
        title="Fermer"
      >
        <X size={16} />
      </button>
    </div>
  )
}

/** Panneau d'annotation inline (notes + tags). */
function AnnotationPanel({ annotation, onSave, onClose }) {
  const [notes, setNotes]   = useState(annotation?.notes ?? '')
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags]     = useState(annotation?.tags ?? [])

  const addTag = () => {
    const t = tagInput.trim()
    if (t && !tags.includes(t) && tags.length < 20) {
      setTags(prev => [...prev, t])
      setTagInput('')
    }
  }
  const removeTag = t => setTags(prev => prev.filter(x => x !== t))

  return (
    <div className="mt-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/60">
      {/* Tags */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {tags.map(t => (
          <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-100 dark:bg-amber-800/50 text-amber-800 dark:text-amber-200 border border-amber-300 dark:border-amber-700">
            {t}
            <button onClick={() => removeTag(t)} className="hover:text-red-500 transition-colors"><X size={9} /></button>
          </span>
        ))}
        <div className="flex items-center gap-1">
          <input
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
            placeholder="+ tag"
            className="text-[11px] px-2 py-0.5 rounded-full border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-amber-400 w-16"
          />
        </div>
      </div>
      {/* Notes */}
      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Notes personnelles…"
        maxLength={5000}
        rows={2}
        className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-amber-400 resize-none"
      />
      <div className="flex items-center justify-end gap-2 mt-1.5">
        <button onClick={onClose} className="text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
          Annuler
        </button>
        <button
          onClick={() => {
            const t = tagInput.trim()
            const finalTags = t && !tags.includes(t) ? [...tags, t] : tags
            onSave({ notes, tags: finalTags })
            onClose()
          }}
          className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white font-medium transition-colors"
        >
          <Check size={10} /> Enregistrer
        </button>
      </div>
    </div>
  )
}

/** Hook : marque l'article comme lu quand il quitte le viewport après y avoir été visible. */
function useAutoRead(articleUrl, isRead, onAnnotate) {
  const ref = useRef(null)
  const wasVisible = useRef(false)

  useEffect(() => {
    if (!articleUrl || !onAnnotate || isRead) return
    const el = ref.current
    if (!el) return

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        wasVisible.current = true
      } else if (wasVisible.current && !isRead) {
        onAnnotate(articleUrl, { is_read: true })
        observer.disconnect()
      }
    }, { threshold: 0.2 })

    observer.observe(el)
    return () => observer.disconnect()
  }, [articleUrl, isRead, onAnnotate])

  return ref
}

/** Dialog popup de détection de contradictions — logs SSE en temps réel. */
function ContradictionDialog({ article, onClose }) {
  const [logs, setLogs]       = useState([])
  const [done, setDone]       = useState(false)
  const [error, setError]     = useState(null)
  const logsContainerRef      = useRef(null)
  const url                   = article['URL'] ?? ''

  useEffect(() => {
    if (!url) return
    const es = new EventSource(`/api/contradictions/stream?url=${encodeURIComponent(url)}`)
    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d.log)   setLogs(prev => [...prev, d.log])
        if (d.error) setError(d.error)
        if (d.done)  { setDone(true); es.close() }
      } catch { /* ignore */ }
    }
    es.onerror = () => { setError('Connexion interrompue'); es.close() }
    return () => es.close()
  }, [url])

  useEffect(() => {
    if (!logs.length) return   // ne pas scroller avant la première ligne
    const el = logsContainerRef.current
    if (!el) return
    // Double rAF : attend 2 cycles de rendu pour que scrollHeight soit à jour
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight + 9999
      })
    })
  }, [logs])

  const ICON_TYPE = {
    QUANTITATIVE:     '⚠️',
    FACTUELLE_BINAIRE:'🚨',
    TEMPORELLE:       '⚠️',
    ATTRIBUTION:      '⚠️',
    NUANCE:           'ℹ️',
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-white/50 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <div className="flex items-center gap-2">
            <Scale size={16} className="text-slate-600 dark:text-slate-400" />
            <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              Vérification des sources
            </span>
          </div>
          <button onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Log stream */}
        <div ref={logsContainerRef} className="flex-1 overflow-y-auto px-4 pt-4 pb-8 font-mono text-xs bg-slate-950 text-slate-200">
          {logs.map((line, i) => {
            const isContradiction = line.includes('CONTRADICTION') || line.includes('⚠️') || line.includes('🚨')
            const isOk  = line.includes('✅') || line.includes('✓')
            const isSep = line.startsWith('[') && line.includes('────')
            return (
              <div key={i} className={`leading-5 whitespace-pre-wrap ${
                isContradiction ? 'text-amber-300 font-semibold' :
                isOk            ? 'text-emerald-400' :
                isSep           ? 'text-slate-600' :
                                  'text-slate-300'
              }`}>
                {line}
              </div>
            )
          })}
          {!done && !error && logs.length === 0 && (
            <div className="text-slate-500 animate-pulse">Connexion en cours…</div>
          )}
          {!done && !error && logs.length > 0 && (
            <div className="flex items-center gap-1.5 mt-1 text-slate-500">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              En cours…
            </div>
          )}
          {error && (
            <div className="mt-1 text-rose-400">✗ {error}</div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-700 shrink-0 flex items-center justify-between">
          <span className="text-[11px] text-slate-400">
            {done ? 'Analyse terminée' : error ? 'Erreur' : 'Analyse en cours…'}
          </span>
          <button onClick={onClose}
            className="text-xs px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors">
            Fermer
          </button>
        </div>
      </div>
    </div>
  )
}

/** Modal de choix du fournisseur IA pour rafraîchir un résumé. */
function IAPickerModal({ providers, onPick, onClose }) {
  const LABELS = { euria: 'EurIA — Infomaniak', claude: 'Claude — Anthropic' }
  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur-xl border border-white/50 dark:border-white/10 rounded-2xl shadow-2xl p-6 w-full max-w-xs">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mb-1">Rafraîchir le résumé</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">Choisir le fournisseur IA :</p>
        <div className="flex flex-col gap-2">
          {providers.map(p => (
            <button key={p} onClick={() => onPick(p)}
              className="w-full px-4 py-2.5 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors">
              {LABELS[p] ?? p}
            </button>
          ))}
        </div>
        <button onClick={onClose} className="mt-3 w-full text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
          Annuler
        </button>
      </div>
    </div>
  )
}

/** Carte article complète (vue grille / large) — style Liquid Glass. */
function ArticleCard({ article, index, highlight, onEntityClick, onFullReport, annotation, onAnnotate, filePath, availableProviders, isFirstUnread, isLarge }) {
  const [expanded, setExpanded]                   = useState(index < 3)
  const [lightbox, setLightbox]                   = useState(false)
  const [noteOpen, setNoteOpen]                   = useState(false)
  const [refreshing, setRefreshing]               = useState(false)
  const [refreshResume, setRefreshResume]         = useState(null) // résumé mis à jour localement
  const [showIAPicker, setShowIAPicker]           = useState(false)
  const [showContradiction, setShowContradiction] = useState(false)

  const titre    = article['Titre']?.trim() || ''
  const resume   = refreshResume ?? article['Résumé'] ?? ''
  const entities = article.entities ?? null
  const hasEntities = entities && Object.keys(entities).length > 0
  const imgUrl   = firstImage(article['Images'])
  const date     = formatDate(article['Date de publication'])
  const time     = formatTime(article['Date de publication'])
  const count    = useMemo(() => entityCount(article), [article])
  const url      = article['URL'] ?? ''

  const isImportant = annotation?.is_important ?? false
  const isRead      = annotation?.is_read ?? false
  const tags        = annotation?.tags ?? []
  const hasNote     = !!(annotation?.notes?.trim())

  const toggle = useCallback((field) => {
    if (onAnnotate && url) onAnnotate(url, { [field]: !(annotation?.[field] ?? false) })
  }, [onAnnotate, url, annotation])

  // Auto-marquage lu au scroll
  const cardRef = useAutoRead(url, isRead, onAnnotate)

  const handleRefreshResume = useCallback(async (provider) => {
    if (!filePath || !url) return
    setShowIAPicker(false)
    setRefreshing(true)
    try {
      const r = await fetch('/api/article/refresh-resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath, article_url: url, provider }),
      })
      const d = await r.json()
      if (d.ok) setRefreshResume(d.resume)
    } catch { /* silence */ } finally {
      setRefreshing(false)
    }
  }, [filePath, url])

  const triggerRefresh = useCallback(() => {
    if (!availableProviders || availableProviders.length === 0) return
    if (availableProviders.length === 1) {
      handleRefreshResume(availableProviders[0])
    } else {
      setShowIAPicker(true)
    }
  }, [availableProviders, handleRefreshResume])

  return (
    <article ref={cardRef} {...(isFirstUnread ? { 'data-first-unread': '' } : {})} className="bg-white/60 dark:bg-slate-800/50 backdrop-blur-2xl border border-white/70 dark:border-white/10 rounded-3xl overflow-hidden shadow-xl shadow-black/8 dark:shadow-black/30 hover:shadow-2xl hover:shadow-black/12 dark:hover:shadow-black/40 transition-all duration-300">
      {showIAPicker && (
        <IAPickerModal providers={availableProviders} onPick={handleRefreshResume} onClose={() => setShowIAPicker(false)} />
      )}
      {showContradiction && (
        <ContradictionDialog article={article} onClose={() => setShowContradiction(false)} />
      )}
      {imgUrl && (
        <button
          type="button"
          onClick={() => setLightbox(true)}
          className={`group relative w-full ${isLarge ? 'h-[432px] sm:h-[576px]' : 'h-44 sm:h-52'} overflow-hidden bg-slate-100 dark:bg-slate-900 block text-left`}
          title="Agrandir l'image"
        >
          <img src={imgUrl} alt={(titre || article['Sources']) ?? ''} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
            loading="lazy" onError={e => { e.currentTarget.closest('button').style.display = 'none' }} />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/30" />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
            <Maximize2 size={22} className="text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg" />
          </div>
        </button>
      )}
      {lightbox && imgUrl && (
        <ImageLightbox url={imgUrl} alt={(titre || article['Sources']) ?? ''} onClose={() => setLightbox(false)} />
      )}
      <div className="p-5">
        <div className="mb-2">
          {/* Source + date en pill frosted */}
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="inline-flex items-center text-[11px] font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider bg-black/5 dark:bg-white/10 backdrop-blur-sm px-2.5 py-0.5 rounded-full">
              {article['Sources'] ?? '—'}
            </span>
            {date && <span className="text-xs text-slate-400 dark:text-slate-500">{date}{time ? <> · <span>{time}</span></> : ''}</span>}
            {hasEntities && (
              <span className="inline-flex items-center gap-1 text-[10px] text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/30 px-1.5 py-0.5 rounded-full border border-violet-200 dark:border-violet-800">
                <Tag size={9} />{count} entités
              </span>
            )}
            <ReadingTimeBadge article={article} />
          </div>
          <SentimentBadge article={article} />
          {titre && (
            <h3 className="mt-1.5 text-xl font-bold text-slate-800 dark:text-slate-100 leading-tight">
              {titre}
            </h3>
          )}
          {/* Boutons d'action — pleine largeur sous le titre */}
          <div className="flex items-center gap-0.5 mt-2 -ml-1.5">
            {onAnnotate && url && (
              <>
                <button onClick={() => toggle('is_important')}
                  title={isImportant ? 'Retirer des importants' : 'Marquer comme important'}
                  className={`p-1.5 rounded-xl transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center ${isImportant ? 'text-amber-500 bg-amber-50 dark:bg-amber-900/30' : 'text-slate-300 dark:text-slate-600 hover:text-amber-400 dark:hover:text-amber-400 hover:bg-amber-50/50 dark:hover:bg-amber-900/20'}`}>
                  <Star size={14} fill={isImportant ? 'currentColor' : 'none'} />
                </button>
                <button onClick={() => toggle('is_read')}
                  title={isRead ? 'Marquer comme non lu' : 'Marquer comme lu'}
                  className={`p-1.5 rounded-xl transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center ${isRead ? 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30' : 'text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 hover:bg-slate-100/50 dark:hover:bg-slate-700/50'}`}>
                  <Eye size={14} fill={isRead ? 'currentColor' : 'none'} />
                </button>
                <button onClick={() => setNoteOpen(v => !v)}
                  title="Notes et tags"
                  className={`p-1.5 rounded-xl transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center ${(noteOpen || hasNote || tags.length > 0) ? 'text-amber-600 bg-amber-50 dark:bg-amber-900/30' : 'text-slate-300 dark:text-slate-600 hover:text-amber-500 dark:hover:text-amber-400 hover:bg-amber-50/50 dark:hover:bg-amber-900/20'}`}>
                  <Pencil size={14} />
                </button>
              </>
            )}
            {filePath && availableProviders?.length > 0 && (
              <button onClick={triggerRefresh} disabled={refreshing}
                title="Rafraîchir le résumé avec l'IA"
                className="p-1.5 rounded-xl transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center text-slate-300 dark:text-slate-600 hover:text-blue-500 dark:hover:text-blue-400 hover:bg-blue-50/50 dark:hover:bg-blue-900/20 disabled:opacity-40">
                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              </button>
            )}
            {resume && <TTSButton text={resume} size={14} />}
            {url && (
              <button onClick={e => { e.stopPropagation(); setShowContradiction(true) }}
                title="Vérifier les contradictions entre sources"
                className="p-1.5 rounded-xl transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center text-slate-300 dark:text-slate-600 hover:text-violet-500 dark:hover:text-violet-400 hover:bg-violet-50/50 dark:hover:bg-violet-900/20">
                <Scale size={14} />
              </button>
            )}
            {article['URL'] && (
              <a href={article['URL']} target="_blank" rel="noopener noreferrer"
                className="p-1.5 rounded-xl min-w-[32px] min-h-[32px] flex items-center justify-center text-slate-400 hover:text-blue-500 dark:hover:text-blue-400 hover:bg-blue-50/50 dark:hover:bg-blue-900/20 transition-colors" title="Ouvrir l'article">
                <ExternalLink size={14} />
              </a>
            )}
          </div>
        </div>

        {/* Tags affichés inline */}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {tags.map(t => (
              <span key={t} className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                {t}
              </span>
            ))}
          </div>
        )}

        {/* Résumé */}
        <div className={`text-sm leading-relaxed overflow-hidden transition-all ${expanded ? '' : 'max-h-28'}`}>
          {hasEntities
            ? <EntityHighlighter text={resume} entities={entities} onEntityClick={onEntityClick} />
            : <SearchHighlighter text={resume} query={highlight} />
          }
        </div>
        {(url || resume.length > 300) && (
          <div className="mt-2 flex items-center justify-end gap-3">
            {url && (
              <button
                onClick={() => onFullReport?.(article)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-blue-500 dark:hover:text-blue-400 transition-colors"
                title="Générer un rapport complet"
              >
                <FileText size={12} /> Rapport
              </button>
            )}
            {resume.length > 300 && (
              <button onClick={() => setExpanded(v => !v)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
                {expanded ? <><ChevronUp size={12} /> Réduire</> : <><ChevronDown size={12} /> Lire la suite</>}
              </button>
            )}
          </div>
        )}

        {/* Panneau notes/tags (dépliable) */}
        {noteOpen && onAnnotate && url && (
          <AnnotationPanel
            annotation={annotation}
            onSave={changes => onAnnotate(url, changes)}
            onClose={() => setNoteOpen(false)}
          />
        )}

        {/* Affichage note si fermé */}
        {!noteOpen && hasNote && (
          <div className="mt-2 px-3 py-1.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/60">
            <p className="text-xs text-amber-800 dark:text-amber-200 leading-relaxed line-clamp-2">
              {annotation.notes}
            </p>
          </div>
        )}
      </div>
    </article>
  )
}

/** Ligne compacte pour la vue timeline. */
function TimelineItem({ article }) {
  const titre = article['Titre']?.trim() || ''
  const resume = article['Résumé'] ?? ''
  const entities = article.entities ?? null
  const hasEntities = entities && Object.keys(entities).length > 0
  const count = useMemo(() => entityCount(article), [article])
  const date = formatDate(article['Date de publication'])
  const time = formatTime(article['Date de publication'])

  return (
    <div className="flex gap-3 group pb-4 last:pb-0">
      {/* Point + ligne verticale */}
      <div className="flex flex-col items-center shrink-0 w-4">
        <div className={`w-2.5 h-2.5 rounded-full mt-1 ring-2 ring-white dark:ring-slate-950 shrink-0 ${
          hasEntities ? 'bg-violet-400 dark:bg-violet-500' : 'bg-slate-300 dark:bg-slate-600'
        }`} />
        <div className="w-px flex-1 bg-slate-200 dark:bg-slate-700/60 mt-1 group-last:hidden" />
      </div>

      {/* Contenu */}
      <div className="flex-1 min-w-0 pb-1">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">
            {article['Sources'] ?? '—'}
          </span>
          {date && <span className="text-xs text-slate-400 dark:text-slate-500">{date}{time ? <> · <span>{time}</span></> : ''}</span>}
          {hasEntities && (
            <span className="inline-flex items-center gap-1 text-[10px] text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/30 px-1.5 py-0.5 rounded-full border border-violet-200 dark:border-violet-800">
              <Tag size={9} />{count}
            </span>
          )}
          <ReadingTimeBadge article={article} />
          <SentimentBadge article={article} />
          {article['URL'] && (
            <a href={article['URL']} target="_blank" rel="noopener noreferrer"
              className="ml-auto shrink-0 text-slate-300 dark:text-slate-600 hover:text-blue-500 dark:hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all"
              title="Ouvrir l'article">
              <ExternalLink size={12} />
            </a>
          )}
        </div>
        {titre && (
          <p className="text-lg font-medium text-slate-700 dark:text-slate-200 leading-snug line-clamp-1 mb-0.5">
            {titre}
          </p>
        )}
        <p className="text-base text-slate-500 dark:text-slate-400 leading-relaxed line-clamp-2">
          {resume.slice(0, 220)}{resume.length > 220 ? '…' : ''}
        </p>
      </div>
    </div>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function ArticleListViewer({ content, annotations, onAnnotate, filePath, availableProviders, searchInjection = null, focusSignal = 0, onMobileSearchClose }) {
  const [searchQuery, setSearchQuery]         = useState(searchInjection?.query || '')
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const [sortBy, setSortBy]                   = useState('date-desc')
  const [viewStyle, setViewStyle]             = useState('grid') // 'grid' | 'large' | 'timeline'
  const [selectedTypes, setSelectedTypes]     = useState(new Set())
  const [selectedSources, setSelectedSources] = useState(new Set())
  const [selectedEntity, setSelectedEntity]   = useState(null) // { type, value }
  const [reportArticle, setReportArticle]     = useState(null) // article pour le rapport complet
  const [typesOpen, setTypesOpen]             = useState(false)
  const [sourcesOpen, setSourcesOpen]         = useState(false)
  const [annotFilter, setAnnotFilter]         = useState('tous') // 'tous' | 'importants' | 'non-lus'
  const searchRef = useRef(null)
  const mobileSearchRef = useRef(null)

  // ── Injection de la query externe (depuis SearchOverlay) ─────────────────
  useEffect(() => {
    if (searchInjection?.query && searchInjection.version > 0) {
      setSearchQuery(searchInjection.query)
      setTimeout(() => searchRef.current?.focus(), 100)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInjection?.version])

  // ── Signal d’activation de la recherche mobile ────────────────────────
  useEffect(() => {
    if (focusSignal > 0) {
      setMobileSearchOpen(true)
      setTimeout(() => mobileSearchRef.current?.focus(), 100)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSignal])

  // ── Défilement vers le premier article non lu ─────────────────────────────
  const gridRef        = useRef(null)
  const hasScrolledRef = useRef(false)  // a-t-on déjà défilé pour ce fichier ?
  // Capture le snapshot des annotations au moment du chargement du fichier
  const annotationsRef = useRef(annotations)
  useEffect(() => { annotationsRef.current = annotations })

  // Parse JSON
  const articles = useMemo(() => {
    try {
      const data = JSON.parse(content)
      if (!Array.isArray(data)) return null
      if (!data.length || !('Résumé' in data[0])) return null
      return data
    } catch { return null }
  }, [content])

  // Types d'entités disponibles (comptage global)
  const availableTypes = useMemo(() => {
    if (!articles) return []
    const counts = {}
    for (const a of articles) {
      if (!a.entities) continue
      for (const [type, values] of Object.entries(a.entities)) {
        if (Array.isArray(values)) counts[type] = (counts[type] ?? 0) + values.length
      }
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [articles])

  // Sources disponibles (comptage global)
  const availableSources = useMemo(() => {
    if (!articles) return []
    const counts = {}
    for (const a of articles) {
      const src = a['Sources'] ?? '—'
      counts[src] = (counts[src] ?? 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [articles])

  // Pipeline : search → entity filter → source filter → annotation filter → sort
  const displayedArticles = useMemo(() => {
    if (!articles) return []
    const q = searchQuery.trim().toLowerCase()
    let result = articles

    if (q) result = result.filter(a =>
      (a['Résumé'] ?? '').toLowerCase().includes(q) ||
      (a['Titre'] ?? '').toLowerCase().includes(q)
    )

    if (selectedTypes.size > 0) {
      result = result.filter(a => {
        if (!a.entities) return false
        return [...selectedTypes].some(t => (a.entities[t]?.length ?? 0) > 0)
      })
    }

    if (selectedSources.size > 0) {
      result = result.filter(a => selectedSources.has(a['Sources'] ?? '—'))
    }

    // Filtre annotation
    if (annotFilter === 'importants') {
      result = result.filter(a => annotations?.[a['URL']]?.is_important)
    } else if (annotFilter === 'non-lus') {
      result = result.filter(a => !annotations?.[a['URL']]?.is_read)
    }

    result = [...result].sort((a, b) => {
      if (sortBy === 'date-desc') return toTimestamp(b['Date de publication']) - toTimestamp(a['Date de publication'])
      if (sortBy === 'date-asc')  return toTimestamp(a['Date de publication']) - toTimestamp(b['Date de publication'])
      if (sortBy === 'entities')  return entityCount(b) - entityCount(a)
      if (sortBy === 'source')    return (a['Sources'] ?? '').localeCompare(b['Sources'] ?? '', 'fr')
      return 0
    })

    return result
  }, [articles, searchQuery, selectedTypes, selectedSources, sortBy, annotFilter, annotations])

  // Groupes timeline (toujours triés date-desc)
  const timelineGroups = useMemo(() => {
    if (viewStyle !== 'timeline') return null
    const sorted = [...displayedArticles].sort(
      (a, b) => toTimestamp(b['Date de publication']) - toTimestamp(a['Date de publication'])
    )
    const groups = {}
    for (const article of sorted) {
      const bucket = getDateBucket(article['Date de publication'])
      if (!groups[bucket]) groups[bucket] = []
      groups[bucket].push(article)
    }
    return groups
  }, [displayedArticles, viewStyle])

  // Calcule l'URL du premier article non lu à l'ouverture du fichier.
  // Intentionnellement limité à [articles] : on ne recalcule PAS quand les annotations changent
  // pour éviter un nouveau défilement automatique à chaque marque-lu.
  // useMemo (synchrone) garantit que la valeur est disponible dès le rendu courant,
  // ce qui permet à ArticleCard d'appliquer data-first-unread avant que les effets de scroll s'exécutent.
  const firstUnreadUrl = useMemo(() => {
    if (!articles) return null
    const sorted = [...articles].sort(
      (a, b) => toTimestamp(b['Date de publication']) - toTimestamp(a['Date de publication'])
    )
    const first = sorted.find(a => !annotationsRef.current?.[a['URL']]?.is_read)
    return first?.['URL'] ?? null
  }, [articles]) // eslint-disable-line react-hooks/exhaustive-deps

  // Réinitialise le flag de scroll chaque fois qu'un nouveau fichier est ouvert
  useEffect(() => {
    hasScrolledRef.current = false
  }, [articles])

  // Défile vers le premier article non lu après le rendu de la liste
  useEffect(() => {
    if (hasScrolledRef.current || !firstUnreadUrl) return
    const el = gridRef.current?.querySelector('[data-first-unread]')
    if (!el) return
    hasScrolledRef.current = true
    requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [displayedArticles, firstUnreadUrl])

  const toggleType   = type => setSelectedTypes(prev => { const s = new Set(prev); s.has(type) ? s.delete(type) : s.add(type); return s })
  const toggleSource = src  => setSelectedSources(prev => { const s = new Set(prev); s.has(src)  ? s.delete(src)  : s.add(src);  return s })

  const hasActiveFilters = searchQuery.trim() || selectedTypes.size > 0 || selectedSources.size > 0 || annotFilter !== 'tous'

  const clearAll = () => {
    setSearchQuery('')
    setSelectedTypes(new Set())
    setSelectedSources(new Set())
    setAnnotFilter('tous')
    searchRef.current?.focus()
  }

  // Comptage pour les chips annotation
  const importantCount = useMemo(() => {
    if (!articles || !annotations) return 0
    return articles.filter(a => annotations[a['URL']]?.is_important).length
  }, [articles, annotations])

  const handleExport = () => {
    const filename = `articles_${new Date().toISOString().slice(0, 10)}_${displayedArticles.length}.json`
    const blob = new Blob([JSON.stringify(displayedArticles, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    URL.revokeObjectURL(url)
  }

  if (!articles) return null

  const withEntities = articles.filter(a => a.entities && Object.keys(a.entities).length > 0)

  return (
    <div>
      {/* ── Barre de stats ── */}
      <div className="flex items-center gap-3 mb-4 text-xs text-slate-500 dark:text-slate-400">
        <span className="font-medium text-slate-700 dark:text-slate-300">
          {articles.length} article{articles.length > 1 ? 's' : ''}
        </span>
        {hasActiveFilters && (
          <span className="text-slate-500 dark:text-slate-400">
            — <span className="font-medium text-slate-700 dark:text-slate-200">{displayedArticles.length}</span> résultat{displayedArticles.length > 1 ? 's' : ''}
          </span>
        )}
        {withEntities.length > 0 ? (
          <span className="flex items-center gap-1 text-violet-600 dark:text-violet-400">
            <Tag size={11} />{withEntities.length} enrichi{withEntities.length > 1 ? 's' : ''} avec entités
          </span>
        ) : (
          <span className="italic text-slate-400 dark:text-slate-500">
            Aucune entité — lancez <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">enrich_entities.py</code> pour enrichir
          </span>
        )}
        {hasActiveFilters && (
          <button onClick={clearAll}
            className="ml-auto flex items-center gap-1 text-[11px] text-slate-400 hover:text-red-500 dark:hover:text-red-400 transition-colors">
            <X size={10} /> Tout réinitialiser
          </button>
        )}
      </div>

      {/* ── Barre de recherche mobile : fixed dans le viewport ── */}
      {(mobileSearchOpen || searchQuery) && (
        <div className="md:hidden fixed left-0 right-0 z-[60] flex items-center gap-3 px-4 py-3 bg-white dark:bg-slate-900 border-b-2 border-blue-500 shadow-lg"
          style={{ top: 'env(safe-area-inset-top, 0px)' }}
        >
          <Search size={15} className="text-blue-500 shrink-0" />
          <input
            ref={mobileSearchRef}
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Rechercher dans les résumés…"
            className="flex-1 bg-transparent text-base text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none"
            autoFocus
          />
          {searchQuery && (
            <span className="text-xs font-medium text-slate-400 shrink-0">
              {displayedArticles.length} / {articles?.length ?? 0}
            </span>
          )}
          <button
            onClick={() => { setSearchQuery(''); setMobileSearchOpen(false); onMobileSearchClose?.() }}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 shrink-0 p-1"
          >
            <X size={18} />
          </button>
        </div>
      )}

      {/* ── Toolbar : recherche + tri + vue + export — masqué sur mobile ── */}
      <div className="hidden md:flex md:flex-row gap-2 mb-4 sticky top-0 z-10 -mx-6 px-6 py-3 bg-white/60 dark:bg-slate-900/60 backdrop-blur-xl border-b border-white/30 dark:border-slate-700/30">
        {/* Recherche */}
        <div className="relative flex-1">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" />
          <input
            ref={searchRef}
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Rechercher dans les résumés…"
            className="w-full pl-8 pr-8 py-2 text-sm bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-700 dark:text-slate-300 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition-colors"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
              <X size={12} />
            </button>
          )}
        </div>

        {/* Chips filtre annotation (si annotations disponibles) */}
        {onAnnotate && (
          <div className="flex items-center gap-1 shrink-0">
            {[
              { key: 'tous',       label: 'Tous' },
              { key: 'importants', label: `⭐ ${importantCount > 0 ? importantCount : ''}` },
              { key: 'non-lus',    label: '👁 Non lus' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setAnnotFilter(key)}
                className={`px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  annotFilter === key
                    ? 'bg-amber-500 text-white border-amber-600'
                    : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700 hover:border-amber-400 dark:hover:border-amber-600 hover:text-amber-600 dark:hover:text-amber-400'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {/* Tri + vue + export — sur une seule ligne (2e ligne sur mobile) */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="relative shrink-0">
            <ArrowUpDown size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" />
            <select value={sortBy} onChange={e => setSortBy(e.target.value)}
              className="pl-7 pr-3 py-2 text-xs bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-600 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition-colors appearance-none cursor-pointer">
              {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {/* Bascule vue grille / timeline */}
          <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden shrink-0">
            <button onClick={() => setViewStyle('grid')} title="Vue grille"
              className={`px-2.5 py-2 transition-colors ${viewStyle === 'grid' ? 'bg-blue-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>
              <LayoutGrid size={13} />
            </button>
            <button onClick={() => setViewStyle('large')} title="Vue large (1 article / ligne)"
              className={`px-2.5 py-2 transition-colors ${viewStyle === 'large' ? 'bg-blue-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>
              <LayoutList size={13} />
            </button>
            <button onClick={() => setViewStyle('timeline')} title="Vue timeline"
              className={`px-2.5 py-2 transition-colors ${viewStyle === 'timeline' ? 'bg-blue-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>
              <AlignLeft size={13} />
            </button>
          </div>

          {/* Export */}
          <button onClick={handleExport} title={`Exporter ${displayedArticles.length} article(s) en JSON`}
            className="px-2.5 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 hover:border-blue-400 dark:hover:border-blue-500 bg-white dark:bg-slate-800 transition-all shrink-0">
            <Download size={13} />
          </button>
        </div>
      </div>

      {/* ── Panel filtre : types d'entités — masqué sur mobile ── */}
      {availableTypes.length > 0 && (
        <div className="hidden md:block mb-3 bg-white/70 dark:bg-slate-800/40 backdrop-blur-sm border border-white/40 dark:border-slate-700/60 rounded-xl overflow-hidden">
          <button
            onClick={() => setTypesOpen(v => !v)}
            className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors"
          >
            <Filter size={12} className="text-slate-400 dark:text-slate-500 shrink-0" />
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Type d'entité</span>
            {selectedTypes.size > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400">{selectedTypes.size}</span>
            )}
            {selectedTypes.size > 0 && (
              <span
                role="button"
                onClick={e => { e.stopPropagation(); setSelectedTypes(new Set()) }}
                className="ml-auto flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors mr-1"
              >
                <X size={10} /> Effacer
              </span>
            )}
            {selectedTypes.size === 0 && <span className="ml-auto" />}
            {typesOpen ? <ChevronUp size={12} className="text-slate-400 shrink-0" /> : <ChevronDown size={12} className="text-slate-400 shrink-0" />}
          </button>
          {typesOpen && (
            <div className="px-3 pb-3 pt-1 flex flex-wrap gap-1.5">
              {availableTypes.map(([type, count]) => {
                const colors = CHIP_COLORS[type] ?? FALLBACK_CHIP
                const active = selectedTypes.has(type)
                return (
                  <button key={type} onClick={() => toggleType(type)}
                    title={`Filtrer les articles avec des entités de type ${type}`}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all hover:scale-105 active:scale-95 ${active ? colors.on : colors.idle}`}>
                    {type}
                    <span className={`tabular-nums text-[10px] ${active ? 'opacity-80' : 'opacity-55'}`}>{count}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Panel filtre : sources — masqué sur mobile ── */}
      {availableSources.length > 1 && (
        <div className="hidden md:block mb-5 bg-white/70 dark:bg-slate-800/40 backdrop-blur-sm border border-white/40 dark:border-slate-700/60 rounded-xl overflow-hidden">
          <button
            onClick={() => setSourcesOpen(v => !v)}
            className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors"
          >
            <Newspaper size={12} className="text-slate-400 dark:text-slate-500 shrink-0" />
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Source</span>
            {selectedSources.size > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400">{selectedSources.size}</span>
            )}
            {selectedSources.size > 0 && (
              <span
                role="button"
                onClick={e => { e.stopPropagation(); setSelectedSources(new Set()) }}
                className="ml-auto flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors mr-1"
              >
                <X size={10} /> Effacer
              </span>
            )}
            {selectedSources.size === 0 && <span className="ml-auto" />}
            {sourcesOpen ? <ChevronUp size={12} className="text-slate-400 shrink-0" /> : <ChevronDown size={12} className="text-slate-400 shrink-0" />}
          </button>
          {sourcesOpen && (
            <div className="px-3 pb-3 pt-1 flex flex-wrap gap-1.5">
              {availableSources.map(([src, count]) => {
                const active = selectedSources.has(src)
                return (
                  <button key={src} onClick={() => toggleSource(src)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all hover:scale-105 active:scale-95 ${
                      active
                        ? 'bg-slate-700 dark:bg-slate-200 text-white dark:text-slate-800 border-slate-700 dark:border-slate-200'
                        : 'bg-slate-100 dark:bg-slate-700/60 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:border-slate-400 dark:hover:border-slate-400'
                    }`}>
                    {src}
                    <span className={`tabular-nums text-[10px] ${active ? 'opacity-75' : 'opacity-55'}`}>{count}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Contenu : grille ou timeline ── */}
      {displayedArticles.length === 0 ? (
        <div className="text-center py-14 text-slate-400 dark:text-slate-500 text-sm">
          <div className="text-2xl mb-2">🔍</div>
          Aucun article ne correspond aux filtres actifs.
          <br />
          <button onClick={clearAll} className="mt-2 text-blue-500 hover:text-blue-600 dark:hover:text-blue-400 underline text-xs">
            Tout réinitialiser
          </button>
        </div>
      ) : viewStyle === 'timeline' && timelineGroups ? (
        /* Vue timeline */
        <div>
          {BUCKET_ORDER.filter(b => timelineGroups[b]?.length > 0).map(bucket => (
            <div key={bucket} className="mb-7">
              {/* En-tête de groupe */}
              <div className="flex items-center gap-3 mb-4">
                <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider whitespace-nowrap">
                  {bucket}
                </span>
                <div className="flex-1 h-px bg-slate-200 dark:bg-slate-700" />
                <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">
                  {timelineGroups[bucket].length}
                </span>
              </div>
              {/* Items */}
              <div className="ml-1">
                {timelineGroups[bucket].map((article, i) => (
                  <TimelineItem key={article['URL'] ?? i} article={article} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : viewStyle === 'large' ? (
        /* Vue large — 1 article/ligne, centré à 80% */
        <div ref={gridRef} className="flex flex-col items-center gap-6">
          {displayedArticles.map((article, i) => (
            <div key={article['URL'] ?? i} className="w-full" style={{ maxWidth: '80%' }}>
              <ArticleCard article={article} index={i} highlight={searchQuery.trim()}
                onEntityClick={(type, value) => setSelectedEntity({ type, value })}
                onFullReport={a => setReportArticle(a)}
                annotation={annotations?.[article['URL']] ?? null}
                onAnnotate={onAnnotate}
                filePath={filePath}
                availableProviders={availableProviders}
                isFirstUnread={!hasScrolledRef.current && article['URL'] === firstUnreadUrl}
                isLarge
              />
            </div>
          ))}
        </div>
      ) : (
        /* Vue grille */
        <div ref={gridRef} className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {displayedArticles.map((article, i) => (
            <ArticleCard key={article['URL'] ?? i} article={article} index={i} highlight={searchQuery.trim()}
              onEntityClick={(type, value) => setSelectedEntity({ type, value })}
              onFullReport={a => setReportArticle(a)}
              annotation={annotations?.[article['URL']] ?? null}
              onAnnotate={onAnnotate}
              filePath={filePath}
              availableProviders={availableProviders}
              isFirstUnread={!hasScrolledRef.current && article['URL'] === firstUnreadUrl}
            />
          ))}
        </div>
      )}

      {selectedEntity && (
        <EntityArticlePanel
          entityType={selectedEntity.type}
          entityValue={selectedEntity.value}
          onClose={() => setSelectedEntity(null)}
        />
      )}

      {reportArticle && (
        <ArticleFullReportDialog
          article={reportArticle}
          onClose={() => setReportArticle(null)}
        />
      )}
    </div>
  )
}
