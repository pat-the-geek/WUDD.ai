/**
 * YouTubePanel — Drawer latéral droit : vidéos YouTube liées à un article.
 *
 * - Plein écran sur mobile, drawer 420px sur desktop
 * - Filtre langue (Toutes / FR / EN) + slider pertinence min.
 * - Cartes vidéo compactes avec thumbnail, score couleur, chaîne, durée, vues
 * - Lecture inline sous la carte au clic (youtube-nocookie.com — évite l'erreur 413)
 * - Fallback visuel si la vidéo bloque l'intégration (embeddable: false)
 * - Props : article {titre, entities, Résumé, Sources} + onClose
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { X, PlayCircle, Loader2, AlertTriangle, ExternalLink, SlidersHorizontal } from 'lucide-react'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatViews(n) {
  if (!n) return ''
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M vues`
  if (n >= 1_000)     return `${Math.round(n / 1_000)}K vues`
  return `${n} vues`
}

function scoreColor(score) {
  if (score >= 70) return '#34C759'   // vert iOS
  if (score >= 40) return '#FF9500'   // orange iOS
  return '#FF3B30'                    // rouge iOS
}

function langFlag(lang) {
  if (lang === 'fr') return '🇫🇷'
  if (lang === 'en') return '🇬🇧'
  return '🌐'
}

// ── Composant carte vidéo ─────────────────────────────────────────────────────

function VideoCard({ video, onPlay, isPlaying }) {
  const { id, title, channel, published, description, thumbnail,
          duration, views, language, embeddable, score } = video

  const color = scoreColor(score)
  const hors_sujet = score < 40

  return (
    <div className={`rounded-xl border transition-all overflow-hidden ${
      hors_sujet
        ? 'border-slate-200 dark:border-slate-700 opacity-60'
        : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
    } bg-white dark:bg-slate-800`}>

      {/* ── En-tête cliquable ── */}
      <button
        className="w-full text-left p-3 flex gap-3 items-start"
        onClick={() => onPlay(video)}
        disabled={!embeddable && hors_sujet}
        title={!embeddable ? 'Intégration désactivée par la chaîne' : title}
      >
        {/* Thumbnail */}
        <div className="relative shrink-0 w-24 h-[54px] rounded-lg overflow-hidden bg-slate-900">
          {thumbnail ? (
            <img src={thumbnail} alt="" className="w-full h-full object-cover" loading="lazy" />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <PlayCircle size={20} className="text-slate-600" />
            </div>
          )}
          {duration && (
            <span className="absolute bottom-1 right-1 text-[10px] font-semibold bg-black/80 text-white px-1 rounded">
              {duration}
            </span>
          )}
          {!embeddable && (
            <span className="absolute inset-0 flex items-center justify-center bg-black/60">
              <span className="text-[18px]">🔒</span>
            </span>
          )}
        </div>

        {/* Infos */}
        <div className="flex-1 min-w-0">
          <p className={`text-[13px] font-medium leading-tight line-clamp-2 ${
            hors_sujet ? 'text-slate-400 dark:text-slate-500' : 'text-slate-800 dark:text-slate-200'
          }`}>
            {langFlag(language)} {title}
          </p>
          <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5 truncate">{channel}</p>
          <div className="flex items-center gap-2 mt-0.5">
            {views > 0 && (
              <span className="text-[10px] text-slate-400">{formatViews(views)}</span>
            )}
            {published && (
              <span className="text-[10px] text-slate-400">· {published}</span>
            )}
          </div>
        </div>
      </button>

      {/* ── Barre de pertinence ── */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${score}%`, background: color }}
            />
          </div>
          <span className="text-[10px] font-semibold shrink-0" style={{ color }}>
            {score}%
          </span>
          {hors_sujet && (
            <span className="text-[10px] text-rose-500 font-medium shrink-0">hors sujet</span>
          )}
        </div>
      </div>

      {/* ── Player inline ── */}
      {isPlaying && (
        <div className="px-3 pb-3">
          {embeddable ? (
            <div className="relative w-full" style={{ paddingBottom: '56.25%' }}>
              <iframe
                className="absolute inset-0 w-full h-full rounded-lg"
                src={`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                title={title}
              />
            </div>
          ) : (
            <div
              className="relative w-full rounded-lg overflow-hidden flex flex-col items-center justify-center gap-2 py-6"
              style={{
                background: thumbnail ? `url(${thumbnail}) center/cover` : '#0f172a',
              }}
            >
              <div className="absolute inset-0 bg-black/70 backdrop-blur-sm rounded-lg" />
              <span className="relative text-2xl">🔒</span>
              <p className="relative text-[12px] text-white/80 text-center px-4">
                Intégration désactivée par la chaîne
              </p>
              <a
                href={`https://www.youtube.com/watch?v=${id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="relative flex items-center gap-1.5 text-[12px] font-medium text-white bg-[var(--color-danger)]/90 hover:bg-[var(--color-danger)] px-3 py-1.5 rounded-full transition-colors"
              >
                <ExternalLink size={12} /> Voir sur YouTube
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function YouTubePanel({ article, onClose }) {
  const [videos,    setVideos]    = useState([])
  const [query,     setQuery]     = useState('')
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [lang,      setLang]      = useState('all')   // 'all' | 'fr' | 'en'
  const [minScore,  setMinScore]  = useState(0)
  const [playingId, setPlayingId] = useState(null)

  const titre    = article?.titre    ?? article?.['titre']    ?? ''
  const entities = article?.entities ?? {}
  const source   = article?.['Sources'] ?? article?.source ?? ''

  // ── Clé stable — ne change que si le contenu réel change (pas la référence objet) ──
  const stableKey = useMemo(
    () => JSON.stringify({ titre, entities }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [titre, JSON.stringify(entities)]
  )

  // ── Chargement des vidéos ──────────────────────────────────────────────────
  useEffect(() => {
    if (!titre && !Object.keys(entities).length) return
    setLoading(true)
    setError(null)
    setVideos([])
    setPlayingId(null)

    fetch('/api/youtube/videos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ titre, entities, max: 6 }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error)
        setQuery(d.query ?? '')
        setVideos(d.videos ?? [])
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [stableKey])  // ← dépend du contenu, pas de la référence objet

  // ── Fermeture Échap ────────────────────────────────────────────────────────
  useEffect(() => {
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // ── Filtre actif ───────────────────────────────────────────────────────────
  const visible = videos.filter(v => {
    if (lang !== 'all' && v.language && v.language !== lang) return false
    if (v.score < minScore) return false
    return true
  })

  const masked = videos.length - visible.length

  const handlePlay = useCallback((video) => {
    setPlayingId(prev => prev === video.id ? null : video.id)
  }, [])

  // ── Nombre de hors-sujet parmi les vidéos visibles ─────────────────────────
  const horsSupjetCount = visible.filter(v => v.score < 40).length

  // ── Render (portal pour passer au-dessus de tous les modals) ───────────────
  return createPortal(
    <>
      {/* Fond semi-transparent */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-[2px] z-[230]"
        onClick={onClose}
      />

      {/* Drawer latéral droit */}
      <div
        className="fixed inset-y-0 right-0 z-[231] flex flex-col w-full md:w-[420px] shadow-2xl"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 overflow-hidden">

          {/* ── Header ─────────────────────────────────────────────────── */}
          <div className="shrink-0 flex items-center gap-3 px-4 py-3 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
            <PlayCircle size={18} className="text-[var(--color-danger)] shrink-0" />
            <div className="flex-1 min-w-0">
              <h3 className="text-[13px] font-semibold text-slate-800 dark:text-slate-200 truncate">
                Vidéos liées
              </h3>
              {source && (
                <p className="text-[11px] text-slate-400 dark:text-slate-500 truncate">{source}</p>
              )}
            </div>
            {query && (
              <span className="hidden sm:block text-[10px] text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-700 px-2 py-0.5 rounded-full truncate max-w-[140px]" title={query}>
                🔍 {query}
              </span>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors shrink-0"
              title="Fermer"
            >
              <X size={16} />
            </button>
          </div>

          {/* ── Filtres ─────────────────────────────────────────────────── */}
          <div className="shrink-0 px-4 py-2.5 bg-white dark:bg-slate-800 border-b border-slate-100 dark:border-slate-700/50 flex flex-col gap-2">
            {/* Langue */}
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">Langue</span>
              <div className="flex gap-1">
                {[['all', 'Toutes'], ['fr', '🇫🇷 FR'], ['en', '🇬🇧 EN']].map(([val, label]) => (
                  <button
                    key={val}
                    onClick={() => setLang(val)}
                    className={`text-[11px] font-medium px-2 py-0.5 rounded-full border transition-colors ${
                      lang === val
                        ? 'bg-[#007AFF] border-[#007AFF] text-white'
                        : 'border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:border-slate-400'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Pertinence min */}
            <div className="flex items-center gap-2">
              <SlidersHorizontal size={11} className="text-slate-400 shrink-0" />
              <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">Pertinence min.</span>
              <input
                type="range" min="0" max="100" step="5"
                value={minScore}
                onChange={e => { setMinScore(Number(e.target.value)); setPlayingId(null) }}
                className="flex-1 accent-[#007AFF]"
              />
              <span className="text-[11px] font-semibold text-[#007AFF] w-7 text-right shrink-0">
                {minScore}%
              </span>
            </div>
          </div>

          {/* ── Résumé compteur ─────────────────────────────────────────── */}
          {!loading && !error && videos.length > 0 && (
            <div className="shrink-0 px-4 py-1.5 flex items-center gap-2">
              <span className="text-[11px] text-slate-400 dark:text-slate-500">
                {visible.length} vidéo{visible.length !== 1 ? 's' : ''}
                {masked > 0 && ` · ${masked} masquée${masked !== 1 ? 's' : ''}`}
              </span>
              {horsSupjetCount > 0 && (
                <span className="flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                  <AlertTriangle size={10} />
                  {horsSupjetCount} hors sujet
                </span>
              )}
            </div>
          )}

          {/* ── Corps scrollable ─────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">

            {/* Chargement */}
            {loading && (
              <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400">
                <Loader2 size={28} className="animate-spin text-[var(--color-danger)]" />
                <p className="text-[13px]">Recherche en cours…</p>
              </div>
            )}

            {/* Erreur */}
            {error && (
              <div className="flex flex-col items-center justify-center gap-2 py-10 text-center px-4">
                <AlertTriangle size={24} className="text-amber-500" />
                <p className="text-[13px] text-slate-500 dark:text-slate-400">{error}</p>
              </div>
            )}

            {/* Pas de résultat */}
            {!loading && !error && videos.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-2 py-16 text-slate-400">
                <PlayCircle size={32} className="opacity-30" />
                <p className="text-[13px]">Aucune vidéo trouvée</p>
              </div>
            )}

            {/* Vidéos filtrées */}
            {!loading && !error && visible.map(video => (
              <VideoCard
                key={video.id}
                video={video}
                isPlaying={playingId === video.id}
                onPlay={handlePlay}
              />
            ))}

            {/* Vidéos masquées (résidu sous le seuil) */}
            {!loading && !error && masked > 0 && (
              <p className="text-center text-[11px] text-slate-400 py-2">
                {masked} vidéo{masked !== 1 ? 's' : ''} masquée{masked !== 1 ? 's' : ''} par le filtre
              </p>
            )}
          </div>

          {/* ── Footer — lien YouTube direct ─────────────────────────────── */}
          {!loading && !error && query && (
            <div className="shrink-0 px-4 py-3 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
              <a
                href={`https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1.5 text-[12px] text-slate-400 hover:text-[var(--color-danger)] transition-colors"
              >
                <ExternalLink size={11} /> Voir plus sur YouTube
              </a>
            </div>
          )}
        </div>
      </div>
    </>,
    document.body
  )
}
