/**
 * TopArticlesPanel — Affiche les N articles les mieux scorés (Feature 1)
 * Style : cartes article identiques à la vue JSON, grille 2 colonnes, modal large.
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { X, Star, ExternalLink, RefreshCw, Clock, Tag, ChevronDown, ChevronUp, Maximize2, PlayCircle, Pause, Volume2, Eye, Pencil, Check, FileText, Radio } from 'lucide-react'
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

// ── Mode Direct ───────────────────────────────────────────────────────────────

const DIRECT_INTERVALS = [
  { label: '5s',  value: 5   },
  { label: '15s', value: 15  },
  { label: '30s', value: 30  },
  { label: '1m',  value: 60  },
  { label: '5m',  value: 300 },
]

function DirectMode({ onReport }) {
  const [logEntries,     setLogEntries]     = useState([])
  const [scanning,       setScanning]       = useState(null)   // {feedTitle}
  const [selectedEntry,  setSelectedEntry]  = useState(null)
  const [interval,       setIntervalVal]    = useState(30)
  const [paused,         setPaused]         = useState(false)
  const [loadingArticle, setLoadingArticle] = useState(false)
  const esRef         = useRef(null)
  const logRef        = useRef(null)
  const autoScrollRef = useRef(true)

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
            const next  = [...prev, entry]
            return next.slice(-200) // garde les 200 dernières entrées
          })
        }
      } catch { /* json parse silencieux */ }
    }
    // EventSource gère la reconnexion automatiquement — pas de handler onerror

    return () => es.close()
  }, [interval, paused]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll vers le bas
  useEffect(() => {
    if (autoScrollRef.current && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logEntries, scanning])

  const handleLogScroll = () => {
    if (!logRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = logRef.current
    autoScrollRef.current = scrollTop + clientHeight >= scrollHeight - 20
  }

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

  const fmtTime = (iso) => {
    if (!iso) return '--:--'
    try {
      const d = new Date(iso)
      return d.toLocaleString('fr-FR', {
        day:    '2-digit', month: '2-digit',
        hour:   '2-digit', minute: '2-digit',
      })
    } catch { return '' }
  }

  return (
    <div className="flex flex-col h-full" style={{ background: '#0d1117' }}>

      {/* ── En-tête : statut + sélecteur vitesse + pause ── */}
      <div className="flex items-center gap-2 px-4 py-2 shrink-0" style={{ borderBottom: '1px solid #30363d' }}>
        <span className={`w-2 h-2 rounded-full shrink-0 ${paused ? 'bg-slate-500' : 'bg-emerald-400 animate-pulse'}`} />
        <span className="text-xs font-mono truncate max-w-[160px]" style={{ color: '#3fb950' }}>
          {paused ? 'EN PAUSE' : scanning ? `[${scanning.feedTitle}]` : 'Connexion…'}
        </span>

        <div className="flex items-center gap-1 ml-auto flex-wrap">
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
        </div>
      </div>

      {/* ── Log ── */}
      <div ref={logRef} onScroll={handleLogScroll}
        className="flex-1 overflow-y-auto p-3 pb-2"
        style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace', fontSize: '12px' }}>
        {logEntries.length === 0 && !scanning && (
          <div className="py-6 text-center text-xs" style={{ color: '#8b949e' }}>
            Initialisation du Direct — les nouveaux articles apparaîtront ici
          </div>
        )}
        {logEntries.map((entry, i) => (
          <div key={entry._id ?? i}
            onClick={() => setSelectedEntry(e => e?.url === entry.url ? null : entry)}
            className="flex items-start gap-2 px-2 py-[3px] rounded cursor-pointer select-none"
            style={{
              background: selectedEntry?.url === entry.url ? 'rgba(63,185,80,0.12)' : 'transparent',
              border:     selectedEntry?.url === entry.url ? '1px solid rgba(63,185,80,0.35)' : '1px solid transparent',
              marginBottom: '1px',
            }}>
            <span className="shrink-0 tabular-nums w-28 text-right" style={{ color: '#8b949e' }}>
              {fmtTime(entry.pubDateParsed)}
            </span>
            <span className="shrink-0 w-28 truncate" title={entry.feedTitle} style={{ color: '#58a6ff' }}>
              {entry.feedTitle}
            </span>
            <span className="flex-1 leading-snug" style={{ color: selectedEntry?.url === entry.url ? '#e6edf3' : '#c9d1d9' }}>
              {entry.title}
            </span>
          </div>
        ))}
        {/* Curseur clignotant */}
        {!paused && (
          <div className="flex items-center gap-2 px-2 py-[3px]" style={{ color: '#3fb950', opacity: 0.5 }}>
            <span className="w-28" />
            <span className="animate-pulse">▋</span>
          </div>
        )}
      </div>

      {/* ── Barre inférieure : article sélectionné + bouton ── */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-3" style={{ borderTop: '1px solid #30363d' }}>
        <div className="flex-1 min-w-0">
          {selectedEntry ? (
            <>
              <p className="text-[10px] truncate font-mono" style={{ color: '#8b949e' }}>{selectedEntry.feedTitle}</p>
              <p className="text-xs truncate font-mono" style={{ color: '#c9d1d9' }}>{selectedEntry.title}</p>
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
  const [isMaximized, setIsMaximized] = useState(false)
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
          <div className="flex-1 min-h-0">
            <DirectMode onReport={a => setReportArticle(a)} />
          </div>
        )}

        {/* ── Tab-bar ── */}
        <div className="shrink-0 flex border-t border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-800/80 backdrop-blur-xl overflow-hidden rounded-b-2xl">
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
        {/* Ligne 1 : filtres + rafraîchir + fermer */}
        <div className="flex items-center gap-2">
          <label className="text-slate-500 dark:text-slate-400 text-xs shrink-0">Fenêtre</label>
          <select value={hours} onChange={e => setHours(Number(e.target.value))}
            className="flex-1 min-w-0 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-200">
            <option value="6">6h</option>
            <option value="24">24h</option>
            <option value="48">48h</option>
            <option value="168">7j</option>
            <option value="0">Tout</option>
          </select>
          <label className="text-slate-500 dark:text-slate-400 text-xs shrink-0">Top</label>
          <select value={topN} onChange={e => setTopN(Number(e.target.value))}
            className="flex-1 min-w-0 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-200">
            <option value="5">5</option>
            <option value="10">10</option>
            <option value="20">20</option>
            <option value="50">50</option>
          </select>
          <button onClick={load} title="Actualiser"
            className="w-9 h-9 rounded-full bg-amber-500 hover:bg-amber-600 text-white flex items-center justify-center shrink-0 transition-colors">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
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
