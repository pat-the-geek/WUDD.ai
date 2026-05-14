/**
 * GraphArticlePanel.jsx — Panel flottant d'article pour le Graphe de connaissances.
 *
 * Charge l'article COMPLET depuis /api/graph/article au montage pour afficher :
 * image, NER colorés, sentiment, titre, badges, résumé enrichi.
 *
 * Props :
 *   article  — données partielles du nœud graphe { URL/url, Sources/source, … }
 *   filePath — chemin relatif du fichier JSON source
 *   onClose  — () => void
 */
import { useState, useEffect } from 'react'
import {
  X, Tag, Clock, ExternalLink, FileText, Maximize2, ChevronUp, ChevronDown, Loader2, PlayCircle, Images,
} from 'lucide-react'
import EntityHighlighter from './EntityHighlighter'
import ArticleFullReportDialog from './ArticleFullReportDialog'
import YouTubePanel from './YouTubePanel'
import ArticleGalleryPanel from './ArticleGalleryPanel'

// ── Utilitaires date ──────────────────────────────────────────────────────────
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
  if (!article?.entities) return 0
  return Object.values(article.entities).reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0)
}

// ── Badges sentiment / ton ────────────────────────────────────────────────────
const SENTIMENT_CFG = {
  positif: { label: 'Positif', dot: 'bg-[var(--color-success)]', text: 'text-[var(--color-success)]', bg: 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800' },
  neutre:  { label: 'Neutre',  dot: 'bg-slate-400',                   text: 'text-slate-600 dark:text-slate-400',  bg: 'bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600' },
  négatif: { label: 'Négatif', dot: 'bg-[var(--color-danger)]', text: 'text-[var(--color-danger)]', bg: 'bg-rose-50 dark:bg-rose-900/30 border-rose-200 dark:border-rose-800' },
}
const TON_LABELS = { factuel: 'Factuel', alarmiste: 'Alarmiste', promotionnel: 'Promo', critique: 'Critique', analytique: 'Analytique' }

function SentimentBadge({ article }) {
  const { sentiment, score_sentiment: scoreSent, ton_editorial: ton, score_ton: scoreTon } = article
  if (!sentiment) return null
  const cfg = SENTIMENT_CFG[sentiment] ?? SENTIMENT_CFG.neutre
  return (
    <div className="flex items-center gap-2 flex-wrap mt-1">
      <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full border ${cfg.bg} ${cfg.text}`}>
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
        {cfg.label}{scoreSent ? ` ${scoreSent}/5` : ''}
      </span>
      {ton && (
        <span className="inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-full border bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400">
          {TON_LABELS[ton] ?? ton}{scoreTon ? ` ${scoreTon}/5` : ''}
        </span>
      )}
    </div>
  )
}

// ── Lightbox image ────────────────────────────────────────────────────────────
function ImageLightbox({ url, alt, onClose }) {
  return (
    <div
      className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[200] flex items-center justify-center p-4"
      onClick={onClose}
    >
      <img src={url} alt={alt} className="max-w-full max-h-full object-contain rounded-lg shadow-2xl" />
      <button onClick={onClose} className="absolute top-4 right-4 p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
        <X size={20} />
      </button>
    </div>
  )
}

// ── Chip entité coloré ────────────────────────────────────────────────────────
const ENTITY_COLORS = {
  PERSON:      'bg-violet-100 dark:bg-violet-900/50 text-violet-800 dark:text-violet-200 ring-violet-300 dark:ring-violet-700',
  ORG:         'bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200 ring-blue-300 dark:ring-blue-700',
  GPE:         'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-800 dark:text-emerald-200 ring-emerald-300 dark:ring-emerald-700',
  PRODUCT:     'bg-orange-100 dark:bg-orange-900/50 text-orange-800 dark:text-orange-200 ring-orange-300 dark:ring-orange-700',
  EVENT:       'bg-amber-100 dark:bg-amber-900/50 text-amber-800 dark:text-amber-200 ring-amber-300 dark:ring-amber-700',
  LAW:         'bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-200 ring-red-300 dark:ring-red-700',
  LOC:         'bg-teal-100 dark:bg-teal-900/50 text-teal-800 dark:text-teal-200 ring-teal-300 dark:ring-teal-700',
  NORP:        'bg-fuchsia-100 dark:bg-fuchsia-900/50 text-fuchsia-800 dark:text-fuchsia-200 ring-fuchsia-300 dark:ring-fuchsia-700',
  MONEY:       'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-800 dark:text-yellow-200 ring-yellow-300 dark:ring-yellow-700',
  PERCENT:     'bg-lime-100 dark:bg-lime-900/50 text-lime-800 dark:text-lime-200 ring-lime-300 dark:ring-lime-700',
}
const FALLBACK_ENTITY = 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 ring-slate-300 dark:ring-slate-600'

function EntityChip({ type, value }) {
  const cls = ENTITY_COLORS[type] ?? FALLBACK_ENTITY
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full ring-1 ring-inset ${cls}`}>
      <span className="opacity-60 uppercase tracking-wide text-[9px]">{type}</span>
      {value}
    </span>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────
export default function GraphArticlePanel({ article: partialArticle, filePath, onClose }) {
  const [article,    setArticle]    = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [lightbox,   setLightbox]   = useState(false)
  const [expanded,   setExpanded]   = useState(true)
  const [reportOpen, setReportOpen] = useState(false)
  const [youtubeOpen, setYoutubeOpen] = useState(false)
  const [galleryOpen, setGalleryOpen] = useState(false)

  // URL canonique : le nœud graphe envoie soit la clé française 'URL' soit 'url'
  const canonicalUrl = partialArticle?.['URL'] ?? partialArticle?.url ?? ''

  // ── Fetch article complet ─────────────────────────────────────────────────
  useEffect(() => {
    const fallback = {
      'URL':                 canonicalUrl,
      'Sources':             partialArticle?.['Sources'] ?? partialArticle?.source ?? '',
      'Date de publication': partialArticle?.['Date de publication'] ?? partialArticle?.date ?? '',
      'Résumé':              partialArticle?.['Résumé'] ?? partialArticle?.resume ?? '',
    }

    if (!filePath || !canonicalUrl) {
      setArticle(fallback)
      setLoading(false)
      return
    }

    const params = new URLSearchParams({ file_path: filePath, url: canonicalUrl })
    fetch(`/api/graph/article?${params}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => {
        if (data?.error) throw new Error(data.error)
        setArticle(data)
      })
      .catch(() => setArticle(fallback))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filePath, canonicalUrl])

  // ── Données dérivées ─────────────────────────────────────────────────────
  const titre      = article?.['Titre']?.trim() || ''
  const resume     = article?.['Résumé'] ?? ''
  const entities   = article?.entities ?? null
  const hasEntities = entities && Object.keys(entities).length > 0
  const imgUrl     = firstImage(article?.['Images'])
  const date       = formatDate(article?.['Date de publication'])
  const time       = formatTime(article?.['Date de publication'])
  const count      = entityCount(article)
  const url        = article?.['URL'] ?? canonicalUrl

  return (
    <>
    {/* Overlay semi-transparent — clic pour fermer */}
    <div
      className="fixed inset-0 z-[110] bg-black/30 backdrop-blur-[2px]"
      onClick={onClose}
    />

    {/* Panel centré */}
    <div className="fixed inset-x-4 bottom-4 top-16 z-[120] flex items-start justify-center pointer-events-none">
      <div
        className="relative w-full max-w-2xl max-h-full overflow-y-auto pointer-events-auto bg-white/95 dark:bg-slate-800/95 backdrop-blur-2xl border border-white/70 dark:border-white/10 rounded-3xl shadow-2xl shadow-black/20 dark:shadow-black/50"
        onClick={e => e.stopPropagation()}
      >
        {/* Bouton fermer */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 p-2 bg-black/10 dark:bg-white/10 hover:bg-black/20 dark:hover:bg-white/20 rounded-full text-slate-600 dark:text-slate-300 transition-colors"
          aria-label="Fermer"
        >
          <X size={16} />
        </button>

        {/* Chargement */}
        {loading && (
          <div className="flex items-center justify-center h-48 gap-3 text-slate-400 dark:text-slate-500">
            <Loader2 size={20} className="animate-spin" />
            <span className="text-sm">Chargement de l'article…</span>
          </div>
        )}

        {/* Contenu */}
        {!loading && article && (
          <>
            {/* Image hero */}
            {imgUrl && (
              <button
                type="button"
                onClick={() => setLightbox(true)}
                className="group relative w-full h-52 sm:h-64 overflow-hidden rounded-t-3xl bg-slate-100 dark:bg-slate-900 block text-left"
                title="Agrandir l'image"
              >
                <img
                  src={imgUrl}
                  alt={titre || article['Sources'] || ''}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                  loading="lazy"
                  onError={e => { e.currentTarget.closest('button').style.display = 'none' }}
                />
                <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/30" />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
                  <Maximize2 size={22} className="text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg" />
                </div>
              </button>
            )}
            {lightbox && imgUrl && (
              <ImageLightbox
                url={imgUrl}
                alt={titre || article['Sources'] || ''}
                onClose={() => setLightbox(false)}
              />
            )}

            {/* Corps */}
            <div className="p-5">
              {/* Badges source · date · entités · lecture */}
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span className="inline-flex items-center text-[11px] font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider bg-black/5 dark:bg-white/10 backdrop-blur-sm px-3 py-0.5 rounded-full">
                  {article['Sources'] ?? '—'}
                </span>
                {date && (
                  <span className="text-xs text-slate-400 dark:text-slate-500">
                    {date}{time ? <> · <span>{time}</span></> : ''}
                  </span>
                )}
                {hasEntities && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-[#5856D6] dark:text-[#5E5CE6] bg-violet-50 dark:bg-violet-900/30 px-2 py-0.5 rounded-full border border-violet-200 dark:border-violet-800">
                    <Tag size={9} />{count} entité{count > 1 ? 's' : ''}
                  </span>
                )}
                {article.temps_lecture_label && (
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full border bg-slate-100 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400">
                    <Clock size={9} className="shrink-0" />{article.temps_lecture_label}
                  </span>
                )}
              </div>

              {/* Sentiment + ton éditorial */}
              <SentimentBadge article={article} />

              {/* Titre */}
              {titre && (
                <h3 className="mt-2 text-xl font-bold text-slate-800 dark:text-slate-100 leading-tight pr-8">
                  {titre}
                </h3>
              )}

              {/* Barre d'actions */}
              <div className="flex items-center gap-1 mt-2 -ml-2 mb-3">
                {url && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1.5 rounded-xl min-w-[32px] min-h-[32px] flex items-center justify-center text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-blue-50/50 dark:hover:bg-blue-900/20 transition-colors"
                    title="Ouvrir l'article original"
                  >
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>

              {/* Résumé avec NER colorés */}
              {resume && (
                <div className={`text-sm leading-relaxed overflow-hidden transition-all ${expanded ? '' : 'max-h-28'}`}>
                  {hasEntities
                    ? <EntityHighlighter text={resume} entities={entities} />
                    : <p className="leading-7 text-slate-700 dark:text-slate-300">{resume}</p>
                  }
                </div>
              )}

              {/* Chips entités par type */}
              {hasEntities && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {Object.entries(entities).flatMap(([type, values]) =>
                    (Array.isArray(values) ? values : []).map(v => (
                      <EntityChip key={`${type}:${v}`} type={type} value={v} />
                    ))
                  )}
                </div>
              )}

              {/* Pied de carte */}
              <div className="mt-3 flex items-center justify-end gap-3 border-t border-slate-100 dark:border-slate-700 pt-3">
                {url && (
                  <>
                    <button
                      onClick={() => setGalleryOpen(true)}
                      className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
                    >
                      <Images size={13} /> Galerie
                    </button>
                    <button
                      onClick={() => setYoutubeOpen(true)}
                      className="flex items-center gap-1 text-xs text-rose-400 hover:text-[var(--color-danger)] dark:hover:text-[#FF453A] transition-colors"
                    >
                      <PlayCircle size={13} /> Vidéos
                    </button>
                    <button
                      onClick={() => setReportOpen(true)}
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-[#007AFF] dark:hover:text-[#0A84FF] transition-colors"
                    >
                      <FileText size={13} /> Rapport
                    </button>
                  </>
                )}
                {resume.length > 300 && (
                  <button
                    onClick={() => setExpanded(v => !v)}
                    className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
                  >
                    {expanded
                      ? <><ChevronUp size={13} /> Réduire</>
                      : <><ChevronDown size={13} /> Lire la suite</>
                    }
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>

    {/* Dialog rapport complet */}
    {reportOpen && (
      <ArticleFullReportDialog
        article={article ?? partialArticle}
        filePath={filePath}
        onClose={() => setReportOpen(false)}
      />
    )}

    {/* Panel YouTube */}
    {youtubeOpen && (
      <YouTubePanel
        article={{
          titre:    (article ?? partialArticle)?.['Titre'] ?? (article ?? partialArticle)?.['Sources'] ?? '',
          entities: (article ?? partialArticle)?.entities ?? {},
          Sources:  (article ?? partialArticle)?.['Sources'] ?? '',
        }}
        onClose={() => setYoutubeOpen(false)}
      />
    )}
    {galleryOpen && (
      <ArticleGalleryPanel
        article={article ?? partialArticle}
        filePath={filePath}
        onClose={() => setGalleryOpen(false)}
      />
    )}
    </>
  )
}
