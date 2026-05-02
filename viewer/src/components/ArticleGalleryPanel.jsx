import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Images, Loader2, AlertTriangle, ExternalLink } from 'lucide-react'

function ImageViewer({ image, onClose }) {
  if (!image) return null
  return (
    <div className="fixed inset-0 z-[251] bg-black/90 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <img
        src={image.URL}
        alt={image.alt || image.title || 'Image de l’article'}
        className="max-w-full max-h-full object-contain rounded-lg"
        onClick={(e) => e.stopPropagation()}
      />
      <button
        onClick={onClose}
        className="absolute top-4 right-4 w-10 h-10 rounded-full bg-white/15 hover:bg-white/25 text-white flex items-center justify-center"
      >
        <X size={18} />
      </button>
    </div>
  )
}

export default function ArticleGalleryPanel({ article, filePath, onClose }) {
  const [images, setImages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)

  const url = (article?.URL || '').trim()
  const source = article?.Sources || ''
  const hasPersistedGallery = Array.isArray(article?.galerie)
  const existing = useMemo(() => {
    if (Array.isArray(article?.galerie) && article.galerie.length > 0) {
      return article.galerie
    }

    if (!Array.isArray(article?.Images) || article.Images.length === 0) {
      return []
    }

    return article.Images
      .map((img) => {
        const imageUrl = (img?.URL || img?.url || '').trim()
        if (!imageUrl) return null

        const width = Number(img?.width ?? img?.Width ?? 0) || 0
        const height = Number(img?.height ?? img?.Height ?? 0) || 0
        const area = Number(img?.area ?? img?.Area ?? (width * height)) || (width * height)

        return {
          URL: imageUrl,
          width,
          height,
          area,
          title: (img?.title || '').trim(),
          alt: (img?.alt || '').trim(),
          copyright: (img?.copyright || '').trim(),
        }
      })
      .filter(Boolean)
  }, [article?.galerie, article?.Images])

  useEffect(() => {
    if (!url) {
      setLoading(false)
      setError('URL article manquante')
      return
    }

    if (hasPersistedGallery) {
      setImages(existing)
      setLoading(false)
      return
    }

    if (existing.length > 0) {
      setImages(existing)
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')

    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 9000)

    fetch('/api/article/gallery', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({ article_url: url, file_path: filePath, max: 12 }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error)
        setImages(Array.isArray(d.gallery) ? d.gallery : [])
      })
      .catch((e) => {
        if (e?.name === 'AbortError') {
          setError('Chargement trop long (timeout). Réessayez dans quelques secondes.')
          return
        }
        setError(e.message || 'Erreur lors du chargement de la galerie')
      })
      .finally(() => {
        window.clearTimeout(timeoutId)
        setLoading(false)
      })

    return () => {
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [url, filePath, existing, hasPersistedGallery])

  useEffect(() => {
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return createPortal(
    <>
      <div className="fixed inset-0 z-[240] bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-[241] bg-slate-950/95 text-slate-100 flex flex-col" style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
        <div className="shrink-0 px-4 py-3 border-b border-white/10 flex items-center gap-3">
          <Images size={18} className="text-cyan-300" />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold truncate">Galerie d’images</h3>
            {source && <p className="text-xs text-slate-400 truncate">{source}</p>}
          </div>
          <button
            onClick={onClose}
            className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center"
            title="Fermer"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="h-full flex items-center justify-center gap-2 text-slate-300">
              <Loader2 size={16} className="animate-spin" /> Chargement de la galerie…
            </div>
          )}

          {!loading && error && (
            <div className="max-w-xl mx-auto mt-10 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-rose-100 text-sm flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && images.length === 0 && (
            <p className="text-center text-sm text-slate-400 mt-16">Aucune image trouvée.</p>
          )}

          {!loading && !error && images.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {images.map((img, idx) => (
                <article key={`${img.URL || 'img'}-${idx}`} className="rounded-xl border border-white/10 bg-white/5 overflow-hidden">
                  <button className="w-full text-left" onClick={() => setSelected(img)}>
                    <div className="aspect-video bg-black/50 overflow-hidden">
                      <img src={img.URL} alt={img.alt || img.title || 'Image de l’article'} className="w-full h-full object-cover hover:scale-[1.02] transition-transform" loading="lazy" />
                    </div>
                  </button>
                  <div className="p-3 space-y-1 text-xs text-slate-300">
                    <p className="truncate" title={img.title || img.alt || ''}>{img.title || img.alt || 'Image'}</p>
                    <p>Dimensions : {img.width || '?'}×{img.height || '?'}</p>
                    <p>Surface : {img.area || 0}</p>
                    <p className="truncate" title={img.copyright || ''}>Copyright : {img.copyright || 'non renseigné'}</p>
                    <a
                      href={img.URL}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200"
                    >
                      <ExternalLink size={12} /> Ouvrir l’image
                    </a>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>

      <ImageViewer image={selected} onClose={() => setSelected(null)} />
    </>,
    document.body,
  )
}
