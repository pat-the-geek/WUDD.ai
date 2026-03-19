import { useMemo, useState, useEffect, useRef } from 'react'
import { Download, FileText, Calendar, HardDrive, ChevronRight, ChevronDown, Images, ArrowUp, Tag, Braces, LayoutList, Trash2, AlertTriangle, Printer } from 'lucide-react'
import JsonViewer from './JsonViewer'
import MarkdownViewer from './MarkdownViewer'
import EntityPanel from './EntityPanel'
import ArticleListViewer from './ArticleListViewer'

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`
}

function formatDate(timestamp) {
  return new Date(timestamp * 1000).toLocaleString('fr-FR', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/** Extrait toutes les images des articles JSON (champ Images[].URL). */
function extractImages(jsonContent) {
  try {
    const data = JSON.parse(jsonContent)
    const articles = Array.isArray(data) ? data : [data]
    const images = []
    articles.forEach(article => {
      if (!Array.isArray(article?.Images)) return
      article.Images.forEach(img => {
        if (img?.url) {
          images.push({
            url: img.url,
            width: img.width ?? null,
            source: article['Sources'] ?? '',
            date: article['Date de publication'] ?? '',
            articleUrl: article['URL'] ?? '',
          })
        }
      })
    })
    return images
  } catch {
    return []
  }
}

function ImageGallery({ content }) {
  const images = useMemo(() => extractImages(content), [content])
  const [failedUrls, setFailedUrls] = useState(new Set())
  const [lightbox, setLightbox] = useState(null) // index de l'image agrandie

  const visible = images.filter(img => !failedUrls.has(img.url))
  if (!visible.length) return null

  const handleError = (url) =>
    setFailedUrls(prev => new Set([...prev, url]))

  return (
    <div className="mt-6">
      {/* En-tête section */}
      <div className="flex items-center gap-2 mb-3">
        <Images size={14} className="text-slate-500 dark:text-slate-400" />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Images
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-600 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded-full">
          {visible.length}
        </span>
      </div>

      {/* Grille */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {visible.map((img, i) => (
          <button
            key={i}
            onClick={() => setLightbox(i)}
            className="group text-left rounded-xl overflow-hidden bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:border-blue-500/60 transition-all hover:shadow-lg hover:shadow-blue-500/10 dark:hover:shadow-blue-900/20 focus:outline-none focus:border-blue-500"
          >
            {/* Vignette */}
            <div className="aspect-video overflow-hidden bg-slate-100 dark:bg-slate-900 relative">
              <img
                src={img.url}
                alt={img.source}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                loading="lazy"
                onError={() => handleError(img.url)}
              />
              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
            </div>
            {/* Méta */}
            {(img.source || img.date) && (
              <div className="px-2.5 py-2">
                {img.source && (
                  <div className="text-[11px] text-slate-700 dark:text-slate-300 truncate font-medium">{img.source}</div>
                )}
                {img.date && (
                  <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">{img.date}</div>
                )}
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Lightbox */}
      {lightbox !== null && (
        <Lightbox
          images={visible}
          index={lightbox}
          onClose={() => setLightbox(null)}
          onNav={(idx) => setLightbox(idx)}
        />
      )}
    </div>
  )
}

function Lightbox({ images, index, onClose, onNav }) {
  const img = images[index]

  // Navigation clavier
  useMemo(() => {
    const handler = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') onNav(Math.min(index + 1, images.length - 1))
      if (e.key === 'ArrowLeft') onNav(Math.max(index - 1, 0))
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [index, images.length, onClose, onNav])

  return (
    <div
      className="fixed inset-0 bg-black/85 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="relative max-w-5xl max-h-[90vh] flex flex-col items-center gap-3">
        {/* Image */}
        <img
          src={img.url}
          alt={img.source}
          className="max-w-full max-h-[80vh] rounded-xl object-contain shadow-2xl"
        />

        {/* Méta + actions */}
        <div className="flex items-center gap-4 text-sm text-slate-300">
          {img.source && <span className="font-medium">{img.source}</span>}
          {img.date && <span className="text-slate-500">{img.date}</span>}
          {img.width && <span className="text-slate-600 text-xs">{img.width}px</span>}
          <a
            href={img.url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-2 text-xs text-blue-400 hover:text-blue-300 underline"
            onClick={e => e.stopPropagation()}
          >
            Ouvrir l'original ↗
          </a>
        </div>

        {/* Compteur */}
        <div className="text-xs text-slate-600 select-none">
          {index + 1} / {images.length}
        </div>

        {/* Bouton fermer */}
        <button
          onClick={onClose}
          className="absolute -top-2 -right-2 w-8 h-8 bg-slate-700 hover:bg-slate-600 rounded-full flex items-center justify-center text-slate-300 transition-colors"
        >
          ✕
        </button>

        {/* Flèches de navigation */}
        {index > 0 && (
          <button
            onClick={() => onNav(index - 1)}
            className="absolute left-2 top-1/2 -translate-y-1/2 w-9 h-9 bg-black/50 hover:bg-black/70 rounded-full flex items-center justify-center text-white transition-colors"
          >
            ‹
          </button>
        )}
        {index < images.length - 1 && (
          <button
            onClick={() => onNav(index + 1)}
            className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 bg-black/50 hover:bg-black/70 rounded-full flex items-center justify-center text-white transition-colors"
          >
            ›
          </button>
        )}
      </div>
    </div>
  )
}

export default function FileViewer({ file, content, loading, loadingProgress, onDownload, onContentSaved, onEntitySearch, onDelete, annotations, onAnnotate, sidebarOpen, availableProviders = [], articleSearchQuery = null, articleFocusSignal = 0, onMobileSearchClose, mobileFilterSignal = null, onMobileFilterClose, onMerged }) {
  const scrollRef = useRef(null)
  const entitiesRef = useRef(null)
  const imagesRef = useRef(null)
  const exportRef = useRef(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewMode, setViewMode] = useState('articles') // 'json' | 'articles'
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [deleteError, setDeleteError]     = useState(null)
  const [exportOpen, setExportOpen]       = useState(false)

  // Écoute le scroll du conteneur principal (re-attaché à chaque changement de fichier)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => setScrollTop(el.scrollTop)
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [file])

  // Remet le scroll à 0 et la vue JSON lors d'un changement de fichier
  useEffect(() => { setScrollTop(0); setViewMode('articles'); setExportOpen(false) }, [file])

  // Garde une référence du fichier courant accessible depuis beforeprint
  const fileRef = useRef(file)
  useEffect(() => { fileRef.current = file }, [file])

  // Déplace #print-area dans <body> avant impression pour éviter
  // les contraintes flex/overflow qui tronquent et créent des pages vides
  useEffect(() => {
    function beforePrint() {
      const el = document.getElementById('print-area')
      if (!el) return
      el._printParent      = el.parentNode
      el._printNextSibling = el.nextSibling || null
      // Injecte le footer filename directement en DOM (inline styles — sans dépendance CSS)
      const filename = fileRef.current?.path?.split('/').pop() || ''
      if (filename) {
        const footer = document.createElement('div')
        footer.style.cssText = 'display:block;text-align:center;font-size:8pt;color:#555;margin-top:24pt;padding-top:6pt;border-top:0.5pt solid #bbb;font-family:sans-serif;'
        footer.textContent = filename
        el._injectedFooter = footer
        el.appendChild(footer)
      }
      document.body.appendChild(el)
    }
    function afterPrint() {
      const el = document.getElementById('print-area')
      if (!el || !el._printParent) return
      if (el._injectedFooter) {
        try { el.removeChild(el._injectedFooter) } catch (e) {}
        delete el._injectedFooter
      }
      el._printParent.insertBefore(el, el._printNextSibling)
      delete el._printParent
      delete el._printNextSibling
    }
    window.addEventListener('beforeprint', beforePrint)
    window.addEventListener('afterprint',  afterPrint)
    return () => {
      window.removeEventListener('beforeprint', beforePrint)
      window.removeEventListener('afterprint',  afterPrint)
    }
  }, [])

  // Ferme le dropdown export au clic extérieur
  useEffect(() => {
    if (!exportOpen) return
    const handler = (e) => {
      if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [exportOpen])

  // Détecte si le JSON contient des images
  const hasImages = useMemo(() => {
    if (!content || file?.type !== 'json') return false
    return extractImages(content).length > 0
  }, [content, file])

  // Détecte si le JSON contient des entités nommées
  const hasEntities = useMemo(() => {
    if (!content || file?.type !== 'json') return false
    try {
      const data = JSON.parse(content)
      const articles = Array.isArray(data) ? data : [data]
      return articles.some(a => a?.entities && Object.keys(a.entities).length > 0)
    } catch { return false }
  }, [content, file])

  // Détecte si le JSON est un tableau d'articles (champ "Résumé" présent)
  const isArticleArray = useMemo(() => {
    if (!content || file?.type !== 'json') return false
    try {
      const data = JSON.parse(content)
      return Array.isArray(data) && data.length > 0 && 'Résumé' in data[0]
    } catch { return false }
  }, [content, file])

  const scrollToTop = () => scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  const scrollToEntities = () => entitiesRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const scrollToImages = () => imagesRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  const handleDelete = async () => {
    setDeleteError(null)
    try {
      await onDelete(file)
      setDeleteConfirm(false)
    } catch (e) {
      setDeleteError(e.message)
    }
  }

  if (!file) {
    return (
      <main className="flex-1 flex items-center justify-center bg-slate-50 dark:bg-slate-900 select-none">
        <div className="text-center">
          <div className="w-16 h-16 rounded-2xl bg-white dark:bg-slate-800 flex items-center justify-center mx-auto mb-4 border border-slate-200 dark:border-slate-700">
            <FileText size={28} className="text-slate-400 dark:text-slate-600" />
          </div>
          <p className="text-slate-500 dark:text-slate-400 font-medium mb-1">Aucun fichier sélectionné</p>
          <p className="text-slate-400 dark:text-slate-600 text-sm">Choisissez un fichier dans la liste de gauche</p>
        </div>
      </main>
    )
  }

  const pathParts = file.path.split('/')

  return (
    <main className="flex-1 flex flex-col overflow-hidden bg-slate-50 dark:bg-slate-900 relative">
      {/* ── Barre de fichier ── */}
      <div
        className={`flex items-center gap-2 px-3 py-2 backdrop-blur-xl border-t border-white/30 dark:border-slate-700/40 md:border-t-0 md:border-b shrink-0 fixed left-0 right-0 md:static md:z-auto transition-all duration-200 ${
          sidebarOpen
            ? 'z-[15] bg-white/25 dark:bg-slate-800/25'
            : 'z-40 bg-white/60 dark:bg-slate-800/60'
        }`}
        style={{ bottom: 'calc(4rem + env(safe-area-inset-bottom))' }}
      >
        {/* Fil d'Ariane — desktop uniquement */}
        <div className="hidden md:flex items-center gap-0.5 min-w-0 flex-1 text-xs text-slate-400 dark:text-slate-500 overflow-hidden">
          {pathParts.map((part, i) => (
            <span key={i} className="flex items-center gap-0.5 shrink-0">
              {i > 0 && <ChevronRight size={10} className="text-slate-300 dark:text-slate-700" />}
              <span className={i === pathParts.length - 1 ? 'text-slate-700 dark:text-slate-300 font-medium' : ''}>
                {part}
              </span>
            </span>
          ))}
        </div>

        {/* Méta — large desktop uniquement */}
        <div className="hidden lg:flex items-center gap-4 text-xs text-slate-400 dark:text-slate-500 shrink-0">
          <span className="flex items-center gap-1">
            <Calendar size={11} />
            {formatDate(file.modified)}
          </span>
          <span className="flex items-center gap-1">
            <HardDrive size={11} />
            {formatSize(file.size)}
          </span>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
            file.type === 'json'
              ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400'
              : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400'
          }`}>
            {file.type === 'json' ? 'JSON' : 'MD'}
          </span>
        </div>

        {/* ── Spacer mobile : pousse les boutons à droite ── */}
        <div className="flex-1 md:hidden" />

        {/* Toggle Articles / JSON (uniquement pour les tableaux d'articles) */}
        {isArticleArray && (
          <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden shrink-0">
            <button
              onClick={() => setViewMode('articles')}
              title="Vue articles annotés"
              className={`flex items-center gap-1 px-2 py-1.5 text-xs transition-colors ${
                viewMode === 'articles'
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              <LayoutList size={12} />
              <span className="hidden sm:inline">Articles</span>
            </button>
            <button
              onClick={() => setViewMode('json')}
              title="Vue JSON brut"
              className={`flex items-center gap-1 px-2 py-1.5 text-xs transition-colors ${
                viewMode === 'json'
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              <Braces size={12} />
              <span className="hidden sm:inline">JSON</span>
            </button>
          </div>
        )}

        {/* ── Export : dropdown sur mobile, boutons séparés sur desktop ── */}

        {/* Mobile : dropdown unique regroupant tous les exports — masqué sur mobile */}
        <div ref={exportRef} className="hidden shrink-0">
          <button
            onClick={() => setExportOpen(v => !v)}
            className={`flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              exportOpen
                ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300'
                : 'bg-slate-100 dark:bg-slate-700/70 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300'
            }`}
          >
            <Download size={13} />
            <span>Export</span>
            <ChevronDown size={10} className={`transition-transform duration-150 ${exportOpen ? 'rotate-180' : ''}`} />
          </button>

          {exportOpen && (
            <div className="absolute bottom-full mb-2 right-0 glass-panel rounded-xl border border-white/40 dark:border-slate-700/60 shadow-2xl z-[200] py-1.5 min-w-[9.5rem] overflow-hidden">
              {/* JSON brut */}
              <button
                onClick={() => { onDownload(); setExportOpen(false) }}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100/70 dark:hover:bg-slate-700/70 active:bg-slate-200/70 transition-colors"
              >
                <Download size={13} className="text-blue-500 shrink-0" />
                <span>JSON</span>
              </button>

              {/* CSV — uniquement si tableau d'articles */}
              {isArticleArray && (
                <a
                  href={`/api/export/csv?path=${encodeURIComponent(file.path)}`}
                  download
                  onClick={() => setExportOpen(false)}
                  className="flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100/70 dark:hover:bg-slate-700/70 active:bg-slate-200/70 transition-colors"
                >
                  <Download size={13} className="text-green-500 shrink-0" />
                  <span>CSV</span>
                </a>
              )}

              {/* XLSX — uniquement si tableau d'articles */}
              {isArticleArray && (
                <a
                  href={`/api/export/xlsx?path=${encodeURIComponent(file.path)}`}
                  download
                  onClick={() => setExportOpen(false)}
                  className="flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100/70 dark:hover:bg-slate-700/70 active:bg-slate-200/70 transition-colors"
                >
                  <Download size={13} className="text-emerald-500 shrink-0" />
                  <span>XLSX</span>
                </a>
              )}

              {/* PDF / impression */}
              <button
                onClick={() => { window.print(); setExportOpen(false) }}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100/70 dark:hover:bg-slate-700/70 active:bg-slate-200/70 transition-colors"
              >
                <Printer size={13} className="text-purple-500 shrink-0" />
                <span>PDF</span>
              </button>
            </div>
          )}
        </div>

        {/* Desktop : boutons séparés */}
        <button
          onClick={onDownload}
          title="Télécharger le fichier JSON"
          className="hidden md:flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
        >
          <Download size={12} />
          JSON
        </button>

        {isArticleArray && (
          <>
            <a
              href={`/api/export/csv?path=${encodeURIComponent(file.path)}`}
              download
              title="Exporter en CSV"
              className="hidden md:flex items-center gap-1.5 px-3 py-1.5 bg-green-700 hover:bg-green-600 active:bg-green-800 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
            >
              <Download size={12} /> CSV
            </a>
            <a
              href={`/api/export/xlsx?path=${encodeURIComponent(file.path)}`}
              download
              title="Exporter en Excel (XLSX)"
              className="hidden md:flex items-center gap-1.5 px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 active:bg-emerald-800 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
            >
              <Download size={12} /> XLSX
            </a>
          </>
        )}

        {/* Bouton PDF / impression — disponible pour tous les fichiers */}
        <button
          onClick={() => window.print()}
          title="Imprimer / Exporter en PDF"
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 active:bg-purple-700 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
        >
          <Printer size={12} />
          <span className="hidden sm:inline">PDF</span>
        </button>

        {/* Bouton supprimer (uniquement pour les fichiers non-JSON) */}
        {onDelete && file?.type !== 'json' && (
          <button
            onClick={() => { setDeleteConfirm(true); setDeleteError(null) }}
            title="Supprimer ce fichier"
            className="flex items-center justify-center p-2 bg-red-100 dark:bg-red-900/30 hover:bg-red-200 dark:hover:bg-red-900/60 text-red-600 dark:text-red-400 rounded-lg transition-colors shrink-0"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      {/* ── Contenu ── */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-6 pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:p-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-400 dark:text-slate-500">
            <div className="w-5 h-5 border-2 border-slate-300 dark:border-slate-600 border-t-blue-500 rounded-full animate-spin" />
            {loadingProgress > 0 ? (
              <>
                <div className="w-48 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all duration-200"
                    style={{ width: `${loadingProgress}%` }}
                  />
                </div>
                <span className="text-xs">{loadingProgress} % chargé</span>
              </>
            ) : (
              <span className="text-sm">Chargement…</span>
            )}
          </div>
        ) : content === null ? (
          <div className="text-slate-400 dark:text-slate-500 text-sm">Contenu indisponible</div>
        ) : file.type === 'json' ? (
          viewMode === 'articles' && isArticleArray ? (
            <ArticleListViewer content={content} annotations={annotations} onAnnotate={onAnnotate} filePath={file?.path} availableProviders={availableProviders} searchInjection={articleSearchQuery} focusSignal={articleFocusSignal} onMobileSearchClose={onMobileSearchClose} mobileFilterSignal={mobileFilterSignal} onMobileFilterClose={onMobileFilterClose} onMerged={onMerged} />
          ) : (
            <>
              <div className="bg-slate-100 dark:bg-slate-950 rounded-xl p-6 border border-slate-200 dark:border-slate-800/60">
                <JsonViewer
                  content={content}
                  onSave={onContentSaved ? (newContent) => onContentSaved(file.path, newContent) : undefined}
                />
              </div>
              <div ref={entitiesRef}><EntityPanel content={content} onEntitySearch={onEntitySearch} /></div>
              <div ref={imagesRef}><ImageGallery content={content} /></div>
            </>
          )
        ) : (
          <div id="print-area">
            <MarkdownViewer content={content} />
          </div>
        )}
      </div>
      {/* ── Boutons de navigation flottants ── */}
      {/* ── Dialog de confirmation suppression ── */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="glass-panel rounded-2xl shadow-2xl w-full max-w-sm border border-white/45 dark:border-white/[0.09] p-6">
            <div className="flex items-start gap-3 mb-4">
              <div className="w-9 h-9 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center shrink-0">
                <AlertTriangle size={16} className="text-red-600 dark:text-red-400" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-800 dark:text-slate-100 text-sm mb-1">
                  Supprimer ce fichier ?
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 break-all leading-relaxed">
                  {file.path}
                </p>
                <p className="text-xs text-red-500 dark:text-red-400 mt-1.5">
                  Cette action est irréversible.
                </p>
              </div>
            </div>
            {deleteError && (
              <p className="text-xs text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2 mb-4">
                {deleteError}
              </p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setDeleteConfirm(false); setDeleteError(null) }}
                className="px-4 py-2 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
              >
                Annuler
              </button>
              <button
                onClick={handleDelete}
                className="px-4 py-2 rounded-lg text-xs font-medium text-white bg-red-600 hover:bg-red-500 active:bg-red-700 transition-colors"
              >
                Supprimer
              </button>
            </div>
          </div>
        </div>
      )}

      {scrollTop > 50 && (
        <div className="fixed bottom-[calc(11rem+env(safe-area-inset-bottom))] md:bottom-5 right-5 flex flex-col gap-2 z-50">
          {hasImages && (
            <button
              onClick={scrollToImages}
              title="Aller aux images"
              className="w-10 h-10 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-blue-500/20 transition-all"
            >
              <Images size={16} />
            </button>
          )}
          {hasEntities && (
            <button
              onClick={scrollToEntities}
              title="Aller aux entités nommées"
              className="w-10 h-10 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-violet-600 dark:hover:text-violet-400 hover:border-violet-400 dark:hover:border-violet-500 hover:shadow-violet-500/20 transition-all"
            >
              <Tag size={16} />
            </button>
          )}
          <button
            onClick={scrollToTop}
            title="Retour en haut"
            className="w-10 h-10 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-blue-500/20 transition-all"
          >
            <ArrowUp size={16} />
          </button>
        </div>
      )}
    </main>
  )
}
