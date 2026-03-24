/**
 * TopArticlesPanel — Affiche les N articles les mieux scorés (Feature 1)
 * Style : cartes article identiques à la vue JSON, grille 2 colonnes, modal large.
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { X, Star, ExternalLink, RefreshCw, Clock, Tag, ChevronDown, ChevronUp, Maximize2, PlayCircle, Pause, Volume2, VolumeX, Eye, Pencil, Check, FileText, Radio, ZoomIn, ZoomOut, Terminal } from 'lucide-react'
import { MapContainer, TileLayer, Marker, Tooltip as LeafletTooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import EntityHighlighter from './EntityHighlighter'
import EntityArticlePanel from './EntityArticlePanel'
import ArticleFullReportDialog from './ArticleFullReportDialog'
import TTSButton, { stopAll } from './TTSButton'

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseArticleDate(raw) {
  if (!raw) return new Date(NaN)
  const m = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (m) return new Date(parseInt(m[3]), parseInt(m[2]) - 1, parseInt(m[1]))
  return new Date(raw)
}

function formatDate(raw) {
  if (!raw) return ''
  try {
    return parseArticleDate(raw).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch { return raw }
}

function formatTime(raw) {
  if (!raw || (!/T\d{2}:\d{2}/.test(raw) && !/\d{2}:\d{2}:\d{2}/.test(raw))) return ''
  try {
    return parseArticleDate(raw).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

function firstImage(images) {
  if (!Array.isArray(images)) return null
  return images.find(i => i?.URL || i?.url)?.URL ?? images.find(i => i?.url)?.url ?? null
}

function entityCount(article) {
  if (!article.entities) return 0
  return Object.values(article.entities).reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0)
}

// ── Badges ────────────────────────────────────────────────────────────────────

// Couleurs HIG : systemGreen #34C759 / systemRed #FF3B30 / slate pour neutre
const SENTIMENT_CFG = {
  positif: { label: 'Positif', dot: 'bg-[#34C759] dark:bg-[#30D158]', text: 'text-[#1a7a34] dark:text-[#30D158]', bg: 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800' },
  neutre:  { label: 'Neutre',  dot: 'bg-slate-400',                   text: 'text-slate-600 dark:text-slate-400', bg: 'bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600' },
  négatif: { label: 'Négatif', dot: 'bg-[#FF3B30] dark:bg-[#FF453A]', text: 'text-[#c0392b] dark:text-[#FF453A]', bg: 'bg-rose-50 dark:bg-rose-900/30 border-rose-200 dark:border-rose-800' },
}
const TON_LABELS = { factuel: 'Factuel', alarmiste: 'Alarmiste', promotionnel: 'Promo', critique: 'Critique', analytique: 'Analytique' }

function SentimentBadge({ article }) {
  const sentiment = article.sentiment
  const scoreSent = article.score_sentiment
  const ton       = article.ton_editorial
  const scoreTon  = article.score_ton
  if (!sentiment) return null
  const cfg = SENTIMENT_CFG[sentiment] ?? SENTIMENT_CFG.neutre
  return (
    <div className="flex items-center gap-1.5 flex-wrap mt-1">
      <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full border ${cfg.bg} ${cfg.text}`}>
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
        {cfg.label}{scoreSent ? ` ${scoreSent}/5` : ''}
      </span>
      {ton && (
        <span className="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded-full border bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400">
          {TON_LABELS[ton] ?? ton}{scoreTon ? ` ${scoreTon}/5` : ''}
        </span>
      )}
    </div>
  )
}

function ReadingTimeBadge({ article }) {
  const label = article.temps_lecture_label
  if (!label) return null
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full border bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400">
      <Clock size={9} className="shrink-0" />
      {label}
    </span>
  )
}

// ── Barre de score ────────────────────────────────────────────────────────────

function ScoreBar({ score }) {
  const pct = Math.round(score)
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-slate-400'
  return (
    <div className="flex items-center gap-2 mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/50">
      <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">Score</span>
      <div className="flex-1 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums font-semibold text-slate-500 dark:text-slate-400 shrink-0 w-10 text-right">{score}</span>
    </div>
  )
}

// ── Lightbox ──────────────────────────────────────────────────────────────────

function ImageLightbox({ url, alt, onClose }) {
  return (
    <div
      className="hig-overlay-enter fixed inset-0 bg-black/90 backdrop-blur-sm z-[60] flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <img src={url} alt={alt} className="max-w-full max-h-[90vh] rounded-xl object-contain shadow-2xl" />
      <button onClick={onClose}
        className="absolute top-4 right-4 w-9 h-9 bg-slate-700/80 hover:bg-slate-600 rounded-full flex items-center justify-center text-slate-300 hover:text-white transition-colors">
        <X size={16} />
      </button>
    </div>
  )
}

// ── Hook lecture podcast ───────────────────────────────────────────────────────

function usePodcast(articles) {
  const [playing, setPlaying]       = useState(false)
  const [currentIdx, setCurrentIdx] = useState(-1)
  const playingRef = useRef(false)

  const speakAt = useCallback((idx) => {
    if (!playingRef.current || idx >= articles.length) {
      setPlaying(false)
      setCurrentIdx(-1)
      playingRef.current = false
      return
    }
    const art    = articles[idx]
    const titre  = art['Titre']?.trim() || ''
    const resume = art['Résumé'] || ''
    const source = art['Sources'] || ''
    let text = `Article ${idx + 1} sur ${articles.length}. `
    if (source) text += `${source}. `
    if (titre)  text += `${titre}. `
    if (resume) text += resume
    text = text.replace(/\n+/g, ' ').replace(/\s{2,}/g, ' ').trim()

    const utt = new SpeechSynthesisUtterance(text)
    utt.lang    = 'fr-FR'
    utt.rate    = 0.92
    utt.onend   = () => speakAt(idx + 1)
    utt.onerror = () => { setPlaying(false); setCurrentIdx(-1); playingRef.current = false }
    setCurrentIdx(idx)
    window.speechSynthesis.speak(utt)
  }, [articles]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(() => {
    if (!window.speechSynthesis || articles.length === 0) return
    stopAll()
    playingRef.current = true
    setPlaying(true)
    speakAt(0)
  }, [speakAt, articles.length])

  const stop = useCallback(() => {
    playingRef.current = false
    window.speechSynthesis?.cancel()
    setPlaying(false)
    setCurrentIdx(-1)
  }, [])

  useEffect(() => () => { playingRef.current = false; window.speechSynthesis?.cancel() }, [])

  return { playing, currentIdx, start, stop }
}

// ── Bouton podcast — composant stable (hors du parent) ────────────────────────

function PodcastBtn({ playing, currentIdx, total, onStart, onStop, disabled, mobile }) {
  const hasTTS = typeof window !== 'undefined' && !!window.speechSynthesis
  if (!hasTTS) return null
  return (
    <button
      onClick={playing ? onStop : onStart}
      disabled={disabled}
      title={disabled ? 'Chargement…' : playing ? 'Arrêter le podcast' : 'Écouter tous les articles en séquence'}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        playing
          ? 'bg-violet-600 hover:bg-violet-700 text-white'
          : 'bg-violet-100 dark:bg-violet-900/40 hover:bg-violet-200 dark:hover:bg-violet-800/60 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800'
      } ${mobile ? 'flex-1 justify-center' : ''}`}
    >
      {playing
        ? <><Pause size={12} /> {currentIdx + 1}/{total}</>
        : <><PlayCircle size={12} /> Écouter</>
      }
    </button>
  )
}

// ── Hook auto-read ────────────────────────────────────────────────────────────

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

// ── Panneau annotation ────────────────────────────────────────────────────────

function AnnotationPanel({ annotation, onSave, onClose }) {
  const [notes, setNotes]       = useState(annotation?.notes ?? '')
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags]         = useState(annotation?.tags ?? [])

  const addTag = () => {
    const t = tagInput.trim()
    if (t && !tags.includes(t) && tags.length < 20) { setTags(prev => [...prev, t]); setTagInput('') }
  }
  const removeTag = t => setTags(prev => prev.filter(x => x !== t))

  return (
    <div className="mt-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/60">
      <div className="flex flex-wrap gap-1.5 mb-2">
        {tags.map(t => (
          <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-100 dark:bg-amber-800/50 text-amber-800 dark:text-amber-200 border border-amber-300 dark:border-amber-700">
            {t}
            <button onClick={() => removeTag(t)} className="hover:text-red-500 transition-colors"><X size={9} /></button>
          </span>
        ))}
        <div className="flex items-center gap-1">
          <input value={tagInput} onChange={e => setTagInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
            placeholder="+ tag"
            className="text-[11px] px-2 py-0.5 rounded-full border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-amber-400 w-16" />
        </div>
      </div>
      <textarea value={notes} onChange={e => setNotes(e.target.value)}
        placeholder="Notes personnelles…" maxLength={5000} rows={2}
        className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-amber-400 resize-none" />
      <div className="flex items-center justify-end gap-2 mt-1.5">
        <button onClick={onClose} className="text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">Annuler</button>
        <button onClick={() => { const t = tagInput.trim(); const finalTags = t && !tags.includes(t) ? [...tags, t] : tags; onSave({ notes, tags: finalTags }); onClose() }}
          className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white font-medium transition-colors">
          <Check size={10} /> Enregistrer
        </button>
      </div>
    </div>
  )
}

// ── Modal choix fournisseur IA ────────────────────────────────────────────────

function IAPickerModal({ providers, onPick, onClose }) {
  const LABELS = { euria: 'EurIA — Infomaniak', claude: 'Claude — Anthropic' }
  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[70] flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur-xl border border-white/50 dark:border-white/10 rounded-2xl shadow-2xl p-6 w-full max-w-xs">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mb-1">Enrichir l'article</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">Choisir le fournisseur IA :</p>
        <div className="flex flex-col gap-2">
          {providers.map(p => (
            <button key={p} onClick={() => onPick(p)}
              className="w-full px-4 py-2.5 rounded-xl text-sm font-medium bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white transition-colors">
              {LABELS[p] ?? p}
            </button>
          ))}
        </div>
        <button onClick={onClose} className="mt-3 w-full text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">Annuler</button>
      </div>
    </div>
  )
}

// ── Carte article ─────────────────────────────────────────────────────────────

function ArticleCard({ article, rank, onEntityClick, isCurrentPodcast, annotation, onAnnotate, filePath, availableProviders, onReport }) {
  const [expanded, setExpanded]           = useState(rank <= 3)
  const [lightbox, setLightbox]           = useState(false)
  const [noteOpen, setNoteOpen]           = useState(false)
  const [refreshing, setRefreshing]       = useState(false)
  const [localEnrichment, setLocalEnrichment] = useState(null)
  const [showIAPicker, setShowIAPicker]   = useState(false)

  const displayArticle = localEnrichment ? { ...article, ...localEnrichment } : article

  const resume      = displayArticle['Résumé'] ?? ''
  const entities    = displayArticle.entities ?? null
  const hasEntities = entities && Object.keys(entities).length > 0
  const count       = useMemo(() => entityCount(displayArticle), [displayArticle])
  const imgUrl      = firstImage(article['Images'])
  const date        = formatDate(article['Date de publication'])
  const time        = formatTime(article['Date de publication'])
  const url         = article['URL'] || article['url'] || '#'
  const titre       = article['Titre']?.trim() || ''

  const isImportant = annotation?.is_important ?? false
  const isRead      = annotation?.is_read ?? false
  const tags        = annotation?.tags ?? []
  const hasNote     = !!(annotation?.notes?.trim())

  const toggle = useCallback((field) => {
    if (onAnnotate && url && url !== '#') onAnnotate(url, { [field]: !(annotation?.[field] ?? false) })
  }, [onAnnotate, url, annotation])

  const cardRef = useAutoRead(url !== '#' ? url : null, isRead, onAnnotate)

  const handleRefreshResume = useCallback(async (provider) => {
    if (!filePath || !url || url === '#') return
    setShowIAPicker(false)
    setRefreshing(true)
    try {
      const r = await fetch('/api/article/refresh-resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath, article_url: url, provider }),
      })
      const d = await r.json()
      if (d.ok) {
        const enriched = { 'Résumé': d.resume }
        if (d.entities && Object.keys(d.entities).length > 0) enriched.entities = d.entities
        if (d.sentiment)               enriched.sentiment              = d.sentiment
        if (d.score_sentiment != null) enriched.score_sentiment        = d.score_sentiment
        if (d.ton_editorial)           enriched.ton_editorial          = d.ton_editorial
        if (d.score_ton != null)       enriched.score_ton              = d.score_ton
        if (d.temps_lecture_minutes != null) {
          enriched.temps_lecture_minutes = d.temps_lecture_minutes
          enriched.temps_lecture_label   = d.temps_lecture_label
        }
        setLocalEnrichment(enriched)
      }
    } catch { /* silence */ } finally {
      setRefreshing(false)
    }
  }, [filePath, url])

  const triggerRefresh = useCallback(() => {
    if (!availableProviders || availableProviders.length === 0) return
    if (availableProviders.length === 1) handleRefreshResume(availableProviders[0])
    else setShowIAPicker(true)
  }, [availableProviders, handleRefreshResume])

  return (
    <article ref={cardRef} className={`bg-white/60 dark:bg-slate-800/50 backdrop-blur-2xl border rounded-3xl overflow-hidden shadow-xl shadow-black/8 dark:shadow-black/30 hover:shadow-2xl hover:shadow-black/12 dark:hover:shadow-black/40 transition-all duration-300 flex flex-col ${
      isCurrentPodcast
        ? 'border-violet-400 dark:border-violet-500 ring-2 ring-violet-300/50 dark:ring-violet-700/50'
        : 'border-white/70 dark:border-white/10'
    }`}>

      {showIAPicker && (
        <IAPickerModal providers={availableProviders} onPick={handleRefreshResume} onClose={() => setShowIAPicker(false)} />
      )}

      {imgUrl && (
        <button type="button" onClick={() => setLightbox(true)}
          className="group relative w-full h-44 sm:h-52 overflow-hidden bg-slate-100 dark:bg-slate-900 block text-left shrink-0"
          title="Agrandir l'image">
          {/* Badge rang en haut-gauche */}
          <span className={`absolute top-2 left-2 z-10 flex items-center justify-center rounded-full font-bold text-white shadow-lg text-[11px] w-7 h-7 ${
            rank === 1 ? 'bg-amber-400' : rank === 2 ? 'bg-slate-400' : rank === 3 ? 'bg-orange-400' : 'bg-slate-600/70'
          }`}>
            {rank <= 3 ? ['🥇','🥈','🥉'][rank-1] : rank}
          </span>
          <img src={imgUrl} alt={titre || article['Sources'] || ''}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
            loading="lazy" onError={e => { e.currentTarget.closest('button').style.display = 'none' }} />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/30" />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
            <Maximize2 size={22} className="text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg" />
          </div>
        </button>
      )}
      {lightbox && imgUrl && (
        <ImageLightbox url={imgUrl} alt={titre || article['Sources'] || ''} onClose={() => setLightbox(false)} />
      )}

      <div className="p-5 flex flex-col flex-1">

        {/* Badge rang quand pas d'image */}
        {!imgUrl && (
          <div className="flex items-center gap-2 mb-3">
            <span className={`flex items-center justify-center rounded-full font-bold text-white shadow-md text-xs w-8 h-8 shrink-0 ${
              rank === 1 ? 'bg-amber-400 ring-2 ring-amber-200 dark:ring-amber-800' :
              rank === 2 ? 'bg-slate-400 ring-2 ring-slate-200 dark:ring-slate-700' :
              rank === 3 ? 'bg-orange-400 ring-2 ring-orange-200 dark:ring-orange-800' : 'bg-slate-500/70'
            }`}>
              {rank <= 3 ? ['🥇','🥈','🥉'][rank-1] : rank}
            </span>
          </div>
        )}

        {/* En-tête — pleine largeur */}
        <div className="mb-2">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="inline-flex items-center text-[11px] font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider bg-black/5 dark:bg-white/10 backdrop-blur-sm px-2.5 py-0.5 rounded-full">
              {article['Sources'] ?? '—'}
            </span>
            {date && <span className="text-xs text-slate-400 dark:text-slate-500">{date}{time ? <> · <span>{time}</span></> : ''}</span>}
            {hasEntities && (
              <span className="inline-flex items-center gap-1 text-[11px] text-[#5856D6] dark:text-[#5E5CE6] bg-violet-50 dark:bg-violet-900/30 px-1.5 py-0.5 rounded-full border border-violet-200 dark:border-violet-800">
                <Tag size={9} />{count} entités
              </span>
            )}
            <ReadingTimeBadge article={displayArticle} />
          </div>
          <SentimentBadge article={displayArticle} />
          {titre && (
            <h3 className="mt-1.5 text-xl font-bold text-slate-800 dark:text-slate-100 leading-tight">
              {titre}
            </h3>
          )}
          {/* Boutons d'action — pleine largeur sous le titre */}
          <div className="flex items-center gap-0.5 mt-2 -ml-1.5">
            {onAnnotate && url && url !== '#' && (
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
                title="Enrichir l'article avec l'IA"
                className="p-1.5 rounded-xl transition-colors min-w-[32px] min-h-[32px] flex items-center justify-center text-slate-300 dark:text-slate-600 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-blue-50/50 dark:hover:bg-blue-900/20 disabled:opacity-40">
                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
              </button>
            )}
            {resume && <TTSButton text={resume || titre} size={14} />}
            {url && url !== '#' && (
              <a href={url} target="_blank" rel="noopener noreferrer"
                className="p-1.5 rounded-xl min-w-[32px] min-h-[32px] flex items-center justify-center text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-blue-50/50 dark:hover:bg-blue-900/20 transition-colors" title="Ouvrir l'article">
                <ExternalLink size={14} />
              </a>
            )}
          </div>
        </div>

        {/* Tags inline */}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {tags.map(t => (
              <span key={t} className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800">{t}</span>
            ))}
          </div>
        )}

        {/* Résumé */}
        <div className={`text-sm leading-relaxed overflow-hidden transition-all ${expanded ? '' : 'max-h-24'}`}>
          {hasEntities
            ? <EntityHighlighter text={resume} entities={entities} onEntityClick={(type, value) => onEntityClick?.(type, value)} />
            : <p className="text-slate-700 dark:text-slate-300">{resume}</p>
          }
        </div>
        {(url !== '#' || resume.length > 280) && (
          <div className="mt-1.5 flex items-center justify-end gap-3">
            {url && url !== '#' && (
              <button
                onClick={() => onReport?.(article)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] transition-colors"
                title="Générer un rapport complet">
                <FileText size={12} /> Rapport
              </button>
            )}
            {resume.length > 280 && (
              <button onClick={() => setExpanded(v => !v)}
                className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors">
                {expanded ? <><ChevronUp size={12} /> Réduire</> : <><ChevronDown size={12} /> Lire la suite</>}
              </button>
            )}
          </div>
        )}

        {/* Panneau notes */}
        {noteOpen && onAnnotate && url && url !== '#' && (
          <AnnotationPanel annotation={annotation} onSave={changes => onAnnotate(url, changes)} onClose={() => setNoteOpen(false)} />
        )}
        {!noteOpen && hasNote && (
          <div className="mt-2 px-3 py-1.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/60">
            <p className="text-xs text-amber-800 dark:text-amber-200 leading-relaxed line-clamp-2">{annotation.notes}</p>
          </div>
        )}

        {/* Barre score + podcast */}
        <div className="mt-3 pt-3 border-t border-white/40 dark:border-white/5 flex items-center gap-2">
          {isCurrentPodcast && (
            <span className="flex items-center gap-1 text-[11px] text-[#5856D6] dark:text-[#5E5CE6] font-medium">
              <Volume2 size={11} className="animate-pulse" />En cours…
            </span>
          )}
          <div className="ml-auto flex items-center gap-2 flex-1 min-w-0">
            <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">Score</span>
            <div className="flex-1 h-1.5 bg-slate-200/60 dark:bg-slate-700/50 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${
                (article.score_pertinence ?? 0) >= 70 ? 'bg-emerald-500' :
                (article.score_pertinence ?? 0) >= 40 ? 'bg-amber-500' : 'bg-slate-400'
              }`} style={{ width: `${article.score_pertinence ?? 0}%` }} />
            </div>
            <span className="text-xs tabular-nums font-semibold text-slate-500 dark:text-slate-400 shrink-0">{article.score_pertinence ?? 0}</span>
          </div>
        </div>
      </div>
    </article>
  )
}

// ── DirectMapOverlay — carte monde avec vignettes d'entités ───────────────────

function MapInvalidator({ containerRef }) {
  const map = useMap()
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(() => setTimeout(() => map.invalidateSize(), 0))
    obs.observe(el)
    return () => obs.disconnect()
  }, [map, containerRef])
  return null
}

function MapRefGetter({ mapRef }) {
  const map = useMap()
  useEffect(() => { mapRef.current = map }, [map, mapRef])
  return null
}

function makeThumbIcon(images, zIndexBase, thumbSize) {
  const n = images.length
  const offset = 5
  const totalW = thumbSize + (n - 1) * offset
  const totalH = thumbSize + (n - 1) * offset
  // Les premières images (index 0) sont les plus importantes → au-dessus
  const html = images.map((img, i) => {
    const depth = n - 1 - i // i=0 → sur le dessus (z élevé)
    if (img.url) {
      // Fallback : si l'image ne charge pas, affiche les initiales de l'entité
      const initials = (img.name || '?').slice(0, 2).toUpperCase()
      return `<div style="position:absolute;top:${depth * offset}px;left:${depth * offset}px;
        width:${thumbSize}px;height:${thumbSize}px;border-radius:6px;
        border:2px solid rgba(255,255,255,0.75);box-shadow:0 2px 10px rgba(0,0,0,0.7);
        background:#1c2128;z-index:${n - depth};overflow:hidden;">
        <img src="${img.url.replace(/"/g, '%22')}"
          title="${img.name.replace(/"/g, '')}"
          style="width:100%;height:100%;object-fit:cover;display:block;"
          onerror="this.style.display='none';this.nextSibling.style.display='flex'"/>
        <div style="display:none;width:100%;height:100%;align-items:center;justify-content:center;
          font-size:${Math.round(thumbSize * 0.35)}px;font-weight:700;color:#58a6ff;
          font-family:monospace;">${initials}</div>
      </div>`
    }
    // Pas d'URL : icône texte pure
    const initials = (img.name || '?').slice(0, 2).toUpperCase()
    return `<div style="position:absolute;top:${depth * offset}px;left:${depth * offset}px;
      width:${thumbSize}px;height:${thumbSize}px;border-radius:6px;
      border:2px solid rgba(255,255,255,0.75);box-shadow:0 2px 10px rgba(0,0,0,0.7);
      background:#1c2128;z-index:${n - depth};
      display:flex;align-items:center;justify-content:center;
      font-size:${Math.round(thumbSize * 0.35)}px;font-weight:700;color:#58a6ff;
      font-family:monospace;">${initials}</div>`
  }).join('')
  return L.divIcon({
    html: `<div style="position:relative;width:${totalW}px;height:${totalH}px;">${html}</div>`,
    className: '',
    iconSize:   [totalW, totalH],
    iconAnchor: [totalW / 2, totalH / 2],
  })
}

const MAP_CENTER = [20, 10]
const MAP_ZOOM   = 2

const mapBtnStyle = {
  background: 'rgba(22,27,34,0.92)',
  border:     '1px solid #30363d',
  color:      '#c9d1d9',
  borderRadius: 6,
  width: 28, height: 28,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  cursor: 'pointer',
  fontSize: 16,
  lineHeight: 1,
  userSelect: 'none',
}

function DirectMapOverlay({ markers, onEntityClick, thumbSize = 44 }) {
  const containerRef = useRef(null)
  const mapRef       = useRef(null)

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <MapContainer
        center={MAP_CENTER} zoom={MAP_ZOOM} minZoom={1} maxZoom={6}
        scrollWheelZoom={true} zoomControl={false}
        style={{ height: '100%', width: '100%' }}
      >
        <MapInvalidator containerRef={containerRef} />
        <MapRefGetter mapRef={mapRef} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {markers.map((m) => {
          const { entity } = m
          const icon = makeThumbIcon([{ url: entity.url, name: entity.name }], m.zIndex, thumbSize)
          return (
            <Marker key={m.articleId} position={[m.lat, m.lon]}
              icon={icon} zIndexOffset={m.zIndex * 100}
              eventHandlers={{ click: () => onEntityClick?.(entity.type, entity.name, m.articleId) }}>
              <LeafletTooltip direction="top" opacity={0.97}>
                <div style={{ minWidth: 260, maxWidth: 420 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'nowrap' }}>
                    <span style={{ fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap', color: '#58a6ff', flexShrink: 0 }}>{m.entity.name}</span>
                    <span style={{ fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 1, minWidth: 0 }}>{m.title}</span>
                  </div>
                  {m.description && (
                    <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {m.description.length > 120 ? m.description.slice(0, 120) + '…' : m.description}
                    </div>
                  )}
                </div>
              </LeafletTooltip>
            </Marker>
          )
        })}
      </MapContainer>

      {/* Boutons zoom + recentrage — ancrés en haut-gauche pour éviter l'overflow
           vers le header du panel (close button en haut-droite) */}
      <div className="absolute top-2 left-3 z-[1000] flex flex-col gap-1">
        <button title="Zoom +" style={mapBtnStyle} onClick={() => mapRef.current?.zoomIn()}>+</button>
        <button title="Zoom −" style={mapBtnStyle} onClick={() => mapRef.current?.zoomOut()}>−</button>
        <button title="Recentrer" style={{ ...mapBtnStyle, fontSize: 13 }} onClick={() => mapRef.current?.setView(MAP_CENTER, MAP_ZOOM)}>⌖</button>
      </div>

      {/* Indicateur de progression NER */}
      <div className="absolute top-2 right-2 z-[1000] pointer-events-none">
        {markers.length === 0 && (
          <span className="text-[9px] font-mono px-2 py-0.5 rounded"
            style={{ background: 'rgba(13,17,23,0.8)', color: '#3fb950' }}>
            Analyse NER…
          </span>
        )}
      </div>
    </div>
  )
}

// ── Mode Direct ───────────────────────────────────────────────────────────────

const DIRECT_INTERVALS = [
  { label: '5s',  value: 5   },
  { label: '15s', value: 15  },
  { label: '30s', value: 30  },
  { label: '1m',  value: 60  },
  { label: '5m',  value: 300 },
]

function matchesKeywords(title, keywords) {
  if (!title || !keywords?.length) return false
  const t = title.toLowerCase()
  return keywords.some(({ keyword, or: orTerms = [], and: andTerms = [] }) => {
    const primary = keyword ? t.includes(keyword.toLowerCase()) : false
    const orMatch = orTerms.some(w => t.includes(w.toLowerCase()))
    if (!primary && !orMatch) return false
    if (andTerms.length === 0) return true
    return andTerms.every(w => t.includes(w.toLowerCase()))
  })
}

function DirectMode({ onReport }) {
  const [logEntries,     setLogEntries]     = useState([])
  const [scanning,       setScanning]       = useState(null)   // {feedTitle}
  const [cycleStats,     setCycleStats]     = useState(null)   // {total, success}
  const [selectedEntry,  setSelectedEntry]  = useState(null)
  const [interval,       setIntervalVal]    = useState(30)
  const [paused,         setPaused]         = useState(false)
  const [loadingArticle, setLoadingArticle] = useState(false)
  const [keywords,       setKeywords]       = useState([])
  const [filterText,     setFilterText]     = useState('')
  const [thumbSize,      setThumbSize]      = useState(44)
  const [soundEnabled,   setSoundEnabled]   = useState(() => {
    try { return localStorage.getItem('direct_sound') !== 'off' } catch { return true }
  })
  // ── Carte (mobile + desktop) ──
  const [mapVisible,            setMapVisible]           = useState(true)
  const [mapHeightPct,          setMapHeightPct]         = useState(50)
  const directContainerRef = useRef(null)
  const [selectedEntityFromMap, setSelectedEntityFromMap] = useState(null)
  const [enrichingFromMap,      setEnrichingFromMap]     = useState(false) // enrichissement en cours
  const [articleEntities, setArticleEntities] = useState({}) // {_id: {entities, coords, images}}
  const nerQueueRef      = useRef([])   // [{_id, title, description}]
  const nerProcessingRef = useRef(false)
  const nerTimerRef      = useRef(null)
  const esRef         = useRef(null)
  const logRef = useRef(null)
  const endRef = useRef(null)
  const prevCountRef      = useRef(0)     // suivi du nombre d'articles pour détecter les nouveaux
  const audioCtxRef       = useRef(null)
  const audioUnlockedRef  = useRef(false) // true après déverrouillage iOS (geste utilisateur requis)
  const firstCycleDoneRef = useRef(false) // vrai après le 1er cycle_end (évite 100 dings au chargement)
  const enrichedArticlesRef = useRef(new Set()) // IDs articles déjà préparés côté backend — évite double fetch

  // ── Déverrouillage iOS : l'AudioContext doit être créé + unpausé lors d'un
  // geste utilisateur, sinon Safari mobile bloque silencieusement tous les sons.
  // On écoute le premier click/touchstart sur le document (one-shot).
  useEffect(() => {
    function unlock() {
      try {
        const AC = window.AudioContext || window.webkitAudioContext
        if (!AC) return
        if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
          audioCtxRef.current = new AC()
        }
        const ctx = audioCtxRef.current
        // Jouer un buffer silencieux (1 sample) pour "débloquer" iOS
        const buf = ctx.createBuffer(1, 1, ctx.sampleRate)
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.connect(ctx.destination)
        src.start(0)
        ctx.resume().then(() => { audioUnlockedRef.current = true })
      } catch { /* pas d'AudioContext disponible */ }
    }
    document.addEventListener('click',      unlock, { once: true, passive: true })
    document.addEventListener('touchstart', unlock, { once: true, passive: true })
    return () => {
      document.removeEventListener('click',      unlock)
      document.removeEventListener('touchstart', unlock)
    }
  }, [])

  // Son de notification — ding synthétisé via Web Audio API
  const playNotification = useCallback(() => {
    // Sur iOS, l'AudioContext doit avoir été déverrouillé par un geste utilisateur
    if (!audioUnlockedRef.current) return
    try {
      const ctx = audioCtxRef.current
      if (!ctx || ctx.state === 'closed') return
      if (ctx.state === 'suspended') return // pas encore déverrouillé, ignorer
      const osc  = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(880, ctx.currentTime)           // La5
      osc.frequency.exponentialRampToValueAtTime(660, ctx.currentTime + 0.12) // descend
      gain.gain.setValueAtTime(0.18, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35)
      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 0.35)
    } catch { /* AudioContext non disponible — silencieux */ }
  }, [])

  // Persistance de la préférence son
  const toggleSound = useCallback(() => {
    setSoundEnabled(prev => {
      const next = !prev
      try { localStorage.setItem('direct_sound', next ? 'on' : 'off') } catch { /* */ }
      return next
    })
  }, [])

  // Chargement des mots-clés une seule fois
  useEffect(() => {
    fetch('/api/keywords')
      .then(r => r.json())
      .then(data => Array.isArray(data) ? setKeywords(data) : null)
      .catch(() => null)
  }, [])

  // Tri chronologique des entrées (null pubDateParsed → fin de liste)
  const sortedEntries = useMemo(() =>
    [...logEntries].sort((a, b) => {
      if (!a.pubDateParsed && !b.pubDateParsed) return 0
      if (!a.pubDateParsed) return 1
      if (!b.pubDateParsed) return -1
      return a.pubDateParsed.localeCompare(b.pubDateParsed)
    }),
  [logEntries])

  // Filtrage par texte libre (titre ou source)
  const filteredEntries = useMemo(() => {
    if (!filterText.trim()) return sortedEntries
    const q = filterText.toLowerCase()
    return sortedEntries.filter(e =>
      e.title?.toLowerCase().includes(q) || e.feedTitle?.toLowerCase().includes(q)
    )
  }, [sortedEntries, filterText])

  // Démarrer / arrêter le flux SSE
  useEffect(() => {
    esRef.current?.close()
    if (paused) return

    const es = new EventSource(`/api/rss/direct/stream?interval=${interval}`)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'scanning') {
          setScanning({ feedTitle: msg.feedTitle, feedUrl: msg.feedUrl })
        } else if (msg.type === 'article') {
          setLogEntries(prev => {
            const entry = { ...msg, _id: msg.url + '|' + msg.pubDateParsed }
            if (prev.some(e => e._id === entry._id)) return prev // dédupliquer
            const next = [...prev, entry].slice(-500)
            return next
          })
        } else if (msg.type === 'cycle_start') {
          setCycleStats({ total: msg.total, success: null })
          setScanning(null)
        } else if (msg.type === 'cycle_end') {
          firstCycleDoneRef.current = true
          setCycleStats({ total: msg.total, success: msg.success })
          setScanning(null)
        }
      } catch { /* json parse silencieux */ }
    }
    // EventSource gère la reconnexion automatiquement — pas de handler onerror

    return () => es.close()
  }, [interval, paused]) // eslint-disable-line react-hooks/exhaustive-deps

  // Son : déclencher un ding quand un nouvel article arrive APRÈS le 1er cycle
  useEffect(() => {
    if (soundEnabled && !paused && firstCycleDoneRef.current && logEntries.length > prevCountRef.current) {
      playNotification()
    }
    prevCountRef.current = logEntries.length
  }, [logEntries.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll toujours forcé vers la sentinelle de fin à chaque nouvel article
  useEffect(() => {
    if (endRef.current) {
      endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [logEntries])


  // ── NER queue processing ──────────────────────────────────────────────────
  const processNerQueue = useCallback(async () => {
    if (nerQueueRef.current.length === 0) {
      nerProcessingRef.current = false
      return
    }
    nerProcessingRef.current = true
    const item = nerQueueRef.current.shift()
    try {
      const r1 = await fetch('/api/rss/direct/ner', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: item.title, description: item.description }),
      })
      const entities = await r1.json()
      if (entities.error) throw new Error(entities.error)

      const gpeNames = [...(entities.GPE || []), ...(entities.LOC || [])]
      let coords = {}
      if (gpeNames.length) {
        try {
          const r2 = await fetch('/api/entities/geocode', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(gpeNames),
          })
          coords = await r2.json()
        } catch { /* géocodage optionnel */ }
      }

      const imgEntities = [
        ...(entities.PERSON  || []).map(n => ({ name: n, type: 'PERSON'  })),
        ...(entities.ORG     || []).map(n => ({ name: n, type: 'ORG'     })),
        ...(entities.PRODUCT || []).map(n => ({ name: n, type: 'PRODUCT' })),
      ]
      let images = {}
      if (imgEntities.length) {
        try {
          const r3 = await fetch('/api/entities/images', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(imgEntities),
          })
          images = await r3.json()
        } catch { /* images optionnelles */ }
      }
      setArticleEntities(prev => ({ ...prev, [item._id]: { entities, coords, images } }))
    } catch {
      // NER échoué : remettre en fin de queue pour retry (si pas déjà retried)
      if (!item._retried) {
        nerQueueRef.current.push({ ...item, _retried: true })
      }
    }
    nerTimerRef.current = setTimeout(processNerQueue, 2000)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Quand de nouveaux articles arrivent → les enqueue (plus récent en premier)
  useEffect(() => {
    if (!mapVisible) return
    const processed = new Set(Object.keys(articleEntities))
    const queued    = new Set(nerQueueRef.current.map(q => q._id))
    const toAdd = [...sortedEntries]
      .reverse() // plus récent en tête
      .filter(e => !processed.has(e._id) && !queued.has(e._id))
      .map(e => ({ _id: e._id, title: e.title || '', description: e.description || '' }))
    if (toAdd.length) {
      nerQueueRef.current.unshift(...toAdd)
      if (!nerProcessingRef.current) processNerQueue()
    }
  }, [sortedEntries, mapVisible]) // eslint-disable-line react-hooks/exhaustive-deps

  // Nettoyage timer NER à l'unmount
  useEffect(() => () => { clearTimeout(nerTimerRef.current) }, [])

  // Marqueurs carte : une entrée par position géocodée, image optionnelle de l'entité principale
  const mapMarkers = useMemo(() => {
    const markers = []
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000 // 7 jours
    sortedEntries.forEach((entry, idx) => {
      // Filtrer les articles sans date détectable ou de plus de 7 jours
      const pubTs = entry.pubDateParsed ? new Date(entry.pubDateParsed).getTime() : NaN
      if (isNaN(pubTs) || pubTs < cutoff) return

      const data = articleEntities[entry._id]
      if (!data) return
      const gpeNames = [...(data.entities.GPE || []), ...(data.entities.LOC || [])]
      const pos = gpeNames.map(n => data.coords[n]).find(c => c?.lat != null)
      if (!pos) return
      // Priorité : entité avec image → entité sans image → titre de l'article
      const allEntities = [
        ...(data.entities.PERSON  || []).map(n => ({ name: n, type: 'PERSON',  img: data.images[n] })),
        ...(data.entities.ORG     || []).map(n => ({ name: n, type: 'ORG',     img: data.images[n] })),
        ...(data.entities.PRODUCT || []).map(n => ({ name: n, type: 'PRODUCT', img: data.images[n] })),
      ]
      const topEntity = allEntities.find(e => e.img?.url) || allEntities[0]
      const entityName = topEntity?.name || (entry.feedTitle || entry.title || '?').slice(0, 20)
      const entityType = topEntity?.type || 'GPE'
      const entityUrl  = topEntity?.img?.url || null
      markers.push({
        articleId:   entry._id,
        lat: pos.lat, lon: pos.lon,
        zIndex:      idx,
        entity:      { name: entityName, type: entityType, url: entityUrl },
        title:       entry.title       || '',
        description: entry.description || '',
      })
    })
    return markers
  }, [articleEntities, sortedEntries])

  const openArticle = async () => {
    if (!selectedEntry || loadingArticle) return
    setLoadingArticle(true)
    try {
      const r = await fetch('/api/rss/direct/article', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          url:         selectedEntry.url,
          title:       selectedEntry.title,
          source:      selectedEntry.feedTitle,
          pub_date:    selectedEntry.pubDate,
          description: selectedEntry.description ?? '',
        }),
      })
      const article = await r.json()
      if (!article.error) onReport(article)
    } catch { /* erreur réseau silencieuse */ }
    setLoadingArticle(false)
  }

  // Enrichissement complet au clic sur un marqueur de la carte
  const handleEntityClickFromMap = async (type, name, articleId) => {
    if (enrichingFromMap) return
    // Retrouver l'entry complète dans le log
    const entry = sortedEntries.find(e => e._id === articleId)
    if (!entry) {
      // Fallback : ouvrir directement sans enrichissement
      setSelectedEntityFromMap({ type, value: name })
      return
    }

    // Cache : si cet article a déjà été préparé côté backend, ne pas rappeler l'API
    if (enrichedArticlesRef.current.has(entry._id)) {
      setSelectedEntityFromMap({ type, value: name })
      return
    }

    setEnrichingFromMap(true)
    try {
      await fetch('/api/rss/direct/article', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url:          entry.url,
          title:        entry.title,
          source:       entry.feedTitle,
          pub_date:     entry.pubDate,
          description:  entry.description ?? '',
          entity_type:  type,
          entity_value: name,
        }),
      })
      enrichedArticlesRef.current.add(entry._id)
    } catch { /* non bloquant */ }
    setEnrichingFromMap(false)
    setSelectedEntityFromMap({ type, value: name })
  }

  const fmtTime = (iso) => {
    if (!iso) return '--:--'
    try {
      const d = new Date(iso)
      if (isNaN(d.getTime()) || d.getFullYear() < 2000) return '--:--'
      return d.toLocaleString('fr-FR', {
        day:    '2-digit', month: '2-digit', year: '2-digit',
        hour:   '2-digit', minute: '2-digit',
      })
    } catch { return '--:--' }
  }

  function startMapDrag(startClientY) {
    const container = directContainerRef.current
    if (!container) return
    const startH = container.querySelector('[data-map-pane]')?.getBoundingClientRect().height ?? 0
    const totalH = container.getBoundingClientRect().height
    function onMove(e) {
      const clientY = e.clientY ?? e.touches?.[0]?.clientY
      if (clientY == null) return
      const newH = Math.max(80, Math.min(totalH - 120, startH + (clientY - startClientY)))
      setMapHeightPct(newH / totalH * 100)
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend',  onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)
    window.addEventListener('touchmove', onMove, { passive: false })
    window.addEventListener('touchend',  onUp)
  }

  return (
    <div ref={directContainerRef} className="flex flex-col flex-1 min-h-0" style={{ background: '#0d1117' }}>

      {/* ── En-tête : statut + sélecteur vitesse + pause ── */}
      <div className="flex items-center gap-2 px-4 py-2 shrink-0" style={{ borderBottom: '1px solid #30363d' }}>
        <span className={`w-2 h-2 rounded-full shrink-0 ${paused ? 'bg-slate-500' : 'bg-emerald-400 animate-pulse'}`} />
        <span className="text-xs font-mono truncate max-w-[160px]" style={{ color: '#3fb950' }}>
          {paused ? 'EN PAUSE' : scanning ? `[${scanning.feedTitle}]` : 'Connexion…'}
          {!paused && <span className="animate-pulse ml-1">▋</span>}
        </span>
        {cycleStats && (
          <span className="text-[10px] font-mono ml-1 shrink-0" style={{
            color: cycleStats.success === null ? '#8b949e' : cycleStats.success < cycleStats.total * 0.3 ? '#f85149' : '#3fb950'
          }}>
            {cycleStats.success === null
              ? `⟳ ${cycleStats.total} flux…`
              : `${cycleStats.success}/${cycleStats.total}`}
          </span>
        )}

        <div className="flex items-center gap-1 ml-auto flex-wrap">
          {/* ── Slider taille vignettes — desktop uniquement ── */}
          <div className="hidden md:flex items-center gap-2 mr-2" style={{ minWidth: 140 }}>
            <ZoomOut size={13} style={{ color: '#8b949e', flexShrink: 0 }} />
            <input
              type="range"
              min="20"
              max="135"
              value={thumbSize}
              onChange={e => setThumbSize(Number(e.target.value))}
              title={`Taille des vignettes : ${thumbSize}px`}
              className="w-24 accent-emerald-500"
              style={{ cursor: 'pointer' }}
            />
            <ZoomIn size={13} style={{ color: '#8b949e', flexShrink: 0 }} />
          </div>
          {/* Bouton son */}
          <button
            onClick={toggleSound}
            title={soundEnabled ? 'Désactiver le son' : 'Activer le son'}
            className="flex items-center justify-center w-6 h-6 rounded transition-colors mr-1"
            style={{
              background: soundEnabled ? '#1a4731' : '#161b22',
              border:     soundEnabled ? '1px solid #3fb950' : '1px solid #30363d',
              color:      soundEnabled ? '#3fb950' : '#8b949e',
            }}
          >
            {soundEnabled ? <Volume2 size={11} /> : <VolumeX size={11} />}
          </button>
          <span className="text-[10px] font-mono mr-0.5" style={{ color: '#8b949e' }}>Intervalle</span>
          {DIRECT_INTERVALS.map(({ label, value }) => (
            <button key={value} onClick={() => setIntervalVal(value)}
              className="px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors"
              style={{
                background: interval === value ? '#1a4731' : '#161b22',
                color:      interval === value ? '#3fb950' : '#8b949e',
                border:     interval === value ? '1px solid #3fb950' : '1px solid #30363d',
              }}>
              {label}
            </button>
          ))}
          <button onClick={() => setPaused(p => !p)}
            className="ml-1 px-2 py-0.5 rounded text-[10px] font-mono transition-colors"
            style={{
              background: paused ? '#1a4731' : '#161b22',
              color:      paused ? '#3fb950' : '#8b949e',
              border:     '1px solid #30363d',
            }}>
            {paused ? '▶ Reprendre' : '⏸ Pause'}
          </button>
          {/* Bouton Terminal IA */}
          <button
            onClick={() => {
              if (!logEntries.length) return
              const articles = logEntries.map(e => ({
                'Date de publication': e.pubDateParsed || '',
                'Sources': e.feedTitle || '',
                'URL': e.url || '',
                'Résumé': e.description || e.title || '',
                ...(articleEntities[e._id]?.entities ? { entities: articleEntities[e._id].entities } : {}),
              }))
              window.dispatchEvent(new CustomEvent('wudd:openFluxChatbot', {
                detail: { articles, filePath: 'Direct RSS', count: articles.length }
              }))
            }}
            disabled={!logEntries.length}
            title={`Terminal IA — analyser les ${logEntries.length} articles en direct`}
            className="ml-1 flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: '#1a3a2a',
              color:      '#3fb950',
              border:     '1px solid #2ea043',
            }}>
            <Terminal size={10} />
            Terminal IA
          </button>
        </div>
      </div>

      {/* ── Carte monde (mobile + desktop) ── */}
      {mapVisible && (
        <>
          <div data-map-pane className="shrink-0" style={{ height: `${mapHeightPct}%`, minHeight: 80, isolation: 'isolate', position: 'relative' }}>
            <DirectMapOverlay markers={mapMarkers} onEntityClick={handleEntityClickFromMap} thumbSize={thumbSize} />
            {/* Overlay spinner pendant l'enrichissement */}
            {enrichingFromMap && (
              <div style={{
                position: 'absolute', inset: 0, zIndex: 2000,
                background: 'rgba(13,17,23,0.65)', backdropFilter: 'blur(2px)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10,
              }}>
                <div className="animate-spin" style={{
                  width: 28, height: 28, borderRadius: '50%',
                  border: '3px solid #30363d', borderTopColor: '#3fb950',
                }} />
                <span style={{ fontSize: 11, color: '#8b949e', fontFamily: 'monospace' }}>Enrichissement en cours…</span>
              </div>
            )}
          </div>
          {/* Séparateur redimensionnable */}
          <div
            onMouseDown={e => { e.preventDefault(); startMapDrag(e.clientY) }}
            onTouchStart={e => { startMapDrag(e.touches[0].clientY) }}
            title="Glisser pour redimensionner"
            style={{
              height: 8, flexShrink: 0, cursor: 'row-resize',
              background: '#161b22',
              borderTop: '1px solid #30363d', borderBottom: '1px solid #30363d',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              userSelect: 'none',
            }}
          >
            <div style={{ width: 36, height: 3, borderRadius: 99, background: '#444c56' }} />
          </div>
        </>
      )}
      {selectedEntityFromMap && (
        <EntityArticlePanel
          entityType={selectedEntityFromMap.type}
          entityValue={selectedEntityFromMap.value}
          onClose={() => setSelectedEntityFromMap(null)}
        />
      )}

      {/* ── Filtre texte ── */}
      <div className="px-3 py-1.5 shrink-0" style={{ borderBottom: '1px solid #21262d' }}>
        <input
          type="text"
          value={filterText}
          onChange={e => setFilterText(e.target.value)}
          placeholder="Filtrer les lignes…"
          className="w-full rounded px-2 py-1 text-xs font-mono outline-none"
          style={{
            background:   '#161b22',
            border:       '1px solid #30363d',
            color:        '#c9d1d9',
            caretColor:   '#3fb950',
          }}
        />
      </div>

      {/* ── Log ── */}
      <div ref={logRef}
        className="flex-1 overflow-y-scroll p-3 pb-2"
        style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace', fontSize: '12px', WebkitOverflowScrolling: 'touch' }}>
        {logEntries.length === 0 && !scanning && (
          <div className="py-6 text-center text-xs" style={{ color: '#8b949e' }}>
            Initialisation du Direct — les nouveaux articles apparaîtront ici
          </div>
        )}
        {filteredEntries.length === 0 && logEntries.length > 0 && (
          <div className="py-4 text-center text-xs" style={{ color: '#8b949e' }}>
            Aucune ligne ne correspond à « {filterText} »
          </div>
        )}
        {filteredEntries.map((entry) => {
          const isKw = matchesKeywords(entry.title, keywords)
          return (
          <div key={entry._id}
            onClick={() => setSelectedEntry(e => e?._id === entry._id ? null : entry)}
            className="flex items-start gap-2 px-2 py-[3px] rounded cursor-pointer select-none"
            style={{
              background: selectedEntry?._id === entry._id ? 'rgba(63,185,80,0.12)' : 'transparent',
              border:     selectedEntry?._id === entry._id ? '1px solid rgba(63,185,80,0.35)' : '1px solid transparent',
              marginBottom: '1px',
              fontWeight:   isKw ? '600' : undefined,
            }}>
            <span className="shrink-0 tabular-nums w-28 text-right" style={{ color: '#8b949e' }}>
              {fmtTime(entry.pubDateParsed)}
            </span>
            <span className="shrink-0 w-28 truncate" title={entry.feedTitle} style={{ color: isKw ? '#3fb950' : '#58a6ff' }}>
              {entry.feedTitle}
            </span>
            <span className="flex-1 leading-snug" style={{ color: selectedEntry?._id === entry._id ? '#e6edf3' : isKw ? '#e6edf3' : '#c9d1d9' }}>
              {entry.title}
            </span>
          </div>
          )
        })}
        {/* Sentinelle : cible du scroll automatique après chaque nouvel article */}
        <div ref={endRef} />
      </div>

      {/* ── Barre inférieure : article sélectionné + bouton ── */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-3" style={{ borderTop: '1px solid #30363d', paddingBottom: 'max(12px, env(safe-area-inset-bottom))' }}>
        <div className="flex-1 min-w-0">
          {selectedEntry ? (
            <>
              <p className="text-[10px] truncate font-mono" style={{ color: '#8b949e' }}>{selectedEntry.feedTitle}</p>
              <div className="overflow-hidden w-full">
                <span className="marquee-scroll text-xs font-mono" style={{ color: '#c9d1d9' }}>
                  {selectedEntry.title}&nbsp;&nbsp;&nbsp;&nbsp;{selectedEntry.title}
                </span>
              </div>
            </>
          ) : (
            <p className="text-[10px] font-mono" style={{ color: '#8b949e' }}>Cliquer sur une ligne pour sélectionner</p>
          )}
        </div>
        <button onClick={openArticle}
          disabled={!selectedEntry || loadingArticle}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-mono font-medium transition-colors shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ background: '#1a4731', color: '#3fb950', border: '1px solid #3fb950' }}>
          {loadingArticle
            ? <><RefreshCw size={11} className="animate-spin" /> Génération IA…</>
            : <>◆ Article</>
          }
        </button>
      </div>
    </div>
  )
}


// ── Panel principal ───────────────────────────────────────────────────────────

export default function TopArticlesPanel({ onClose, annotations = {}, onAnnotate, availableProviders = [] }) {
  const [activeTab, setActiveTab] = useState('top') // 'top' | 'direct'
  const [articles, setArticles] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [hours, setHours]       = useState(48)
  const [topN, setTopN]         = useState(10)
  const [isMaximized, setIsMaximized] = useState(() => window.innerWidth < 768)
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [reportArticle, setReportArticle] = useState(null)

  const { playing, currentIdx, start: podcastStart, stop: podcastStop } = usePodcast(articles)

  const load = () => {
    podcastStop()
    setLoading(true)
    setError(null)
    fetch(`/api/articles/top?n=${topN}&hours=${hours}`)
      .then(r => r.json())
      .then(data => { setArticles(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { load() }, [hours, topN])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <>
    <div
      className={`hig-overlay-enter fixed inset-0 z-50 flex bg-black/60 backdrop-blur-sm ${isMaximized ? 'items-stretch' : 'items-start justify-center p-4 overflow-y-auto'}`}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className={`hig-modal-enter flex flex-col glass-panel shadow-2xl border border-white/45 dark:border-white/[0.09] overflow-hidden w-full ${isMaximized ? '' : 'max-w-5xl rounded-2xl my-4 max-h-[calc(100dvh-4rem)]'}`}>

        {/* ── En-tête ── */}
        <div className="flex items-center gap-3 px-5 py-3.5 border-b border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0">
          {activeTab === 'top'
            ? <Star size={18} className="text-amber-500 shrink-0" />
            : <Radio size={18} className="text-emerald-500 shrink-0" />
          }
          <span className="font-semibold text-slate-900 dark:text-slate-100">
            {activeTab === 'top' ? 'Top articles' : 'Direct'}
          </span>
          {activeTab === 'top' && !loading && articles.length > 0 && (
            <span className="text-xs text-slate-400 dark:text-slate-500">— {articles.length} article{articles.length > 1 ? 's' : ''}</span>
          )}

          {/* Contrôles desktop — visibles uniquement en mode Top */}
          {activeTab === 'top' && (
            <div className="hidden md:flex flex-wrap items-center gap-3 ml-auto">
              <PodcastBtn
                playing={playing}
                currentIdx={currentIdx}
                total={articles.length}
                onStart={podcastStart}
                onStop={podcastStop}
                disabled={loading || articles.length === 0}
              />
              <div className="flex items-center gap-2 text-sm">
                <label className="text-slate-500 dark:text-slate-400 text-xs">Fenêtre :</label>
                <select value={hours} onChange={e => setHours(Number(e.target.value))}
                  className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-200">
                  <option value="6">6h</option>
                  <option value="24">24h</option>
                  <option value="48">48h</option>
                  <option value="168">7j</option>
                  <option value="0">Tout</option>
                </select>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <label className="text-slate-500 dark:text-slate-400 text-xs">Top :</label>
                <select value={topN} onChange={e => setTopN(Number(e.target.value))}
                  className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-200">
                  <option value="5">5</option>
                  <option value="10">10</option>
                  <option value="20">20</option>
                  <option value="50">50</option>
                </select>
              </div>
              <button onClick={load} title="Actualiser"
                className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs rounded-lg transition-colors">
                <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                Actualiser
              </button>
              <button onClick={() => setIsMaximized(m => !m)} title={isMaximized ? 'Réduire' : 'Plein écran'}
                className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors">
                <Maximize2 size={14} />
              </button>
              <button onClick={onClose}
                className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors">
                <X size={14} />
              </button>
            </div>
          )}

          {/* Boutons plein écran + fermer (toujours visibles à droite) */}
          {activeTab === 'direct' && (
            <div className="flex items-center gap-2 ml-auto">
              <button onClick={() => setIsMaximized(m => !m)} title={isMaximized ? 'Réduire' : 'Plein écran'}
                className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors">
                <Maximize2 size={14} />
              </button>
              <button onClick={onClose}
                className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors">
                <X size={14} />
              </button>
            </div>
          )}

          {/* Mobile : plein écran uniquement (en mode Top sans contrôles desktop) */}
          {activeTab === 'top' && (
            <div className="flex md:hidden items-center gap-2 ml-auto">
              <button onClick={() => setIsMaximized(m => !m)}
                className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 flex items-center justify-center text-slate-500 dark:text-slate-400">
                <Maximize2 size={14} />
              </button>
            </div>
          )}
        </div>

        {/* ── Corps ── */}
        {activeTab === 'top' ? (
          <div className="flex-1 overflow-y-auto p-5 pb-36 md:pb-5">
            {error && (
              <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm">{error}</div>
            )}

            {loading ? (
              <div className="flex items-center justify-center py-20 gap-2 text-slate-400 dark:text-slate-500">
                <RefreshCw size={20} className="animate-spin" />
                <span className="text-sm">Chargement…</span>
              </div>
            ) : articles.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500 gap-3">
                <Star size={36} className="opacity-30" />
                <p className="text-sm">Aucun article trouvé dans cette fenêtre</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {articles.map((article, i) => {
                  const artUrl = article['URL'] ?? article['url'] ?? ''
                  return (
                    <ArticleCard
                      key={artUrl || i}
                      article={article}
                      rank={i + 1}
                      isCurrentPodcast={playing && currentIdx === i}
                      onEntityClick={(type, value) => setSelectedEntity({ type, value })}
                      annotation={artUrl ? annotations?.[artUrl] : undefined}
                      onAnnotate={onAnnotate}
                      availableProviders={availableProviders}
                      onReport={a => setReportArticle(a)}
                    />
                  )
                })}
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col">
            <DirectMode onReport={a => setReportArticle(a)} />
          </div>
        )}

        {/* ── Tab-bar ── */}
        <div className="shrink-0 flex border-t border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-800/80 backdrop-blur-xl overflow-hidden rounded-b-2xl"
          style={isMaximized ? { paddingBottom: 'env(safe-area-inset-bottom)' } : {}}>
          <button
            onClick={() => setActiveTab('top')}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors ${
              activeTab === 'top'
                ? 'text-amber-600 dark:text-amber-400 bg-amber-50/60 dark:bg-amber-900/20 border-t-2 border-amber-500'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 border-t-2 border-transparent'
            }`}>
            <Star size={13} />
            Top articles
          </button>
          <button
            onClick={() => setActiveTab('direct')}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-xs font-medium transition-colors ${
              activeTab === 'direct'
                ? 'text-emerald-600 dark:text-emerald-400 bg-emerald-50/60 dark:bg-emerald-900/20 border-t-2 border-emerald-500'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 border-t-2 border-transparent'
            }`}>
            <Radio size={13} />
            Direct
          </button>
        </div>
      </div>
    </div>

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
        filePath={reportArticle._source_file ?? null}
        onClose={() => setReportArticle(null)}
      />
    )}

    {/* ── Toolbar mobile (Top uniquement) ── */}
    {activeTab === 'top' && (
      <div
        className="hig-sheet-enter md:hidden fixed bottom-0 left-0 right-0 z-[60] bg-white/80 dark:bg-slate-800/80 backdrop-blur-xl border-t border-slate-200/60 dark:border-slate-700/60 px-4 pt-2 flex flex-col gap-2"
        style={{ paddingBottom: 'max(10px, env(safe-area-inset-bottom))' }}
      >
        {/* Ligne 1 : filtres + rafraîchir + direct + fermer */}
        <div className="flex items-center gap-2">
          <select aria-label="Fenêtre temporelle" value={hours} onChange={e => setHours(Number(e.target.value))}
            className="flex-1 min-w-0 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-200">
            <option value="6">6h</option>
            <option value="24">24h</option>
            <option value="48">48h</option>
            <option value="168">7j</option>
            <option value="0">Tout</option>
          </select>
          <select aria-label="Nombre d'articles" value={topN} onChange={e => setTopN(Number(e.target.value))}
            className="flex-1 min-w-0 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-200">
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
            <option value="50">Top 50</option>
          </select>
          <button onClick={load} title="Actualiser"
            className="w-9 h-9 rounded-full bg-amber-500 hover:bg-amber-600 text-white flex items-center justify-center shrink-0 transition-colors">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => setActiveTab('direct')} title="Direct"
            className="w-9 h-9 rounded-full bg-emerald-100 dark:bg-emerald-900/40 hover:bg-emerald-200 dark:hover:bg-emerald-800/60 flex items-center justify-center text-emerald-600 dark:text-emerald-400 shrink-0 transition-colors">
            <Radio size={16} />
          </button>
          <button onClick={onClose} title="Fermer"
            className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 transition-colors">
            <X size={16} />
          </button>
        </div>
        {/* Ligne 2 : podcast */}
        <PodcastBtn
          playing={playing}
          currentIdx={currentIdx}
          total={articles.length}
          onStart={podcastStart}
          onStop={podcastStop}
          disabled={loading || articles.length === 0}
          mobile
        />
      </div>
    )}
  </>
  )
}
