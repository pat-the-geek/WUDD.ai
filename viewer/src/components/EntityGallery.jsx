import { useEffect, useState } from 'react'
import { Loader2, ZoomIn, ZoomOut } from 'lucide-react'

const SECTIONS = [
  { type: 'PERSON',  label: 'Personnes',       shape: 'portrait' },
  { type: 'ORG',     label: 'Organisations',    shape: 'square'   },
  { type: 'PRODUCT', label: 'Produits / Tech',  shape: 'square'   },
]

const TYPE_COLORS = {
  PERSON:  'bg-violet-500',
  ORG:     'bg-blue-500',
  PRODUCT: 'bg-orange-500',
}

const PLACEHOLDER_COLORS = {
  PERSON:  { bg: 'bg-violet-100 dark:bg-violet-900/30', text: 'text-violet-500 dark:text-violet-300' },
  ORG:     { bg: 'bg-blue-100 dark:bg-blue-900/30',     text: 'text-blue-500 dark:text-blue-300'    },
  PRODUCT: { bg: 'bg-orange-100 dark:bg-orange-900/30', text: 'text-orange-500 dark:text-orange-300' },
}

function portraitHeight(zoom) {
  return Math.max(55, 220 - zoom * 11)
}

function initials(name) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')
}

function GalleryTile({ name, img, type, shape, h, onClick }) {
  const [imgError, setImgError] = useState(false)

  const isSquare = shape === 'square'
  const hasImage = img != null && !imgError
  const ph = PLACEHOLDER_COLORS[type] ?? { bg: 'bg-slate-100 dark:bg-slate-800', text: 'text-slate-400' }

  return (
    <button
      onClick={() => onClick(type, name)}
      title={name}
      className="group flex flex-col items-center gap-1 focus:outline-none"
    >
      <div
        className={[
          'w-full overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700',
          'transition-all group-hover:ring-2 group-hover:ring-violet-400',
          'group-hover:scale-[1.03] group-active:scale-95',
          hasImage
            ? (isSquare ? 'bg-white dark:bg-slate-100' : 'bg-slate-100 dark:bg-slate-800')
            : ph.bg,
        ].join(' ')}
        style={isSquare ? { aspectRatio: '1', width: '100%' } : { height: h + 'px' }}
      >
        {hasImage ? (
          <img
            src={img.url}
            alt={name}
            onError={() => setImgError(true)}
            className={['w-full h-full', isSquare ? 'object-contain p-1.5' : 'object-cover'].join(' ')}
            loading="lazy"
          />
        ) : (
          <div className={`w-full h-full flex items-center justify-center ${ph.text}`}>
            <span className="font-semibold text-lg select-none leading-none">
              {initials(name)}
            </span>
          </div>
        )}
      </div>
      <span className="text-[11px] leading-tight text-center text-slate-600 dark:text-slate-400 max-w-full truncate px-0.5 w-full">
        {name}
      </span>
    </button>
  )
}

function SectionBlock({ section, images, zoom, onEntityClick }) {
  const items = section.entities
    .sort((a, b) => a.name.localeCompare(b.name, 'fr'))

  if (items.length === 0) return null

  const h = portraitHeight(zoom)
  const color = TYPE_COLORS[section.type] ?? 'bg-slate-500'
  const withImage = items.filter(e => images[e.name] != null).length

  return (
    <div className="mb-8">
      {/* En-tête de section */}
      <div className="flex items-center gap-2 mb-3">
        <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${color}`} />
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          {section.label}
        </span>
        <span className="text-xs text-slate-400 dark:text-slate-500">
          · {withImage} image{withImage > 1 ? 's' : ''} / {items.length}
        </span>
      </div>

      {/* Grille */}
      <div
        className="grid gap-2"
        style={{ gridTemplateColumns: `repeat(${zoom}, minmax(0, 1fr))` }}
      >
        {items.map(e => (
          <GalleryTile
            key={e.name}
            name={e.name}
            img={images[e.name]}
            type={section.type}
            shape={section.shape}
            h={h}
            onClick={onEntityClick}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * EntityGallery — galerie d'images Wikipedia pour PERSON / ORG / PRODUCT.
 *
 * Props:
 *   entities      [{name, type, count}]   — entités à afficher
 *   onEntityClick fn(type, name)          — ouvre EntityArticlePanel
 */
export default function EntityGallery({ entities, onEntityClick }) {
  const [images, setImages] = useState({})
  const [loading, setLoading] = useState(true)
  const [zoom, setZoom] = useState(10)

  useEffect(() => {
    if (!entities || entities.length === 0) {
      setLoading(false)
      return
    }

    // Envoie {name, type} pour que le backend choisisse la bonne stratégie
    fetch('/api/entities/images', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entities.map(e => ({ name: e.name, type: e.type }))),
    })
      .then(r => r.json())
      .then(data => { setImages(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [entities])

  // Grouper les entités par type pour chaque section
  const entitiesByType = {}
  for (const e of entities) {
    if (!entitiesByType[e.type]) entitiesByType[e.type] = []
    entitiesByType[e.type].push(e)
  }

  const sections = SECTIONS
    .map(s => ({ ...s, entities: entitiesByType[s.type] ?? [] }))
    .filter(s => s.entities.length > 0)

  const totalWithImage = entities.filter(e => images[e.name] != null).length
  const totalEntities = entities.length

  return (
    <div>
      {/* Barre de contrôle zoom */}
      <div className="flex items-center gap-3 mb-6 px-1">
        <ZoomOut size={14} className="text-slate-400 shrink-0" />
        <input
          type="range"
          min="2"
          max="15"
          value={zoom}
          onChange={e => setZoom(Number(e.target.value))}
          className="flex-1 accent-violet-500"
        />
        <ZoomIn size={14} className="text-slate-400 shrink-0" />
        <span className="text-xs text-slate-500 dark:text-slate-400 w-20 text-right shrink-0">
          {zoom} col.
        </span>
        {!loading && (
          <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">
            {totalWithImage} / {totalEntities} avec image
          </span>
        )}
      </div>

      {/* Contenu */}
      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-slate-400 dark:text-slate-500">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Recherche des images Wikipedia…</span>
        </div>
      ) : sections.length === 0 ? (
        <div className="text-center py-16 text-slate-400 dark:text-slate-500 text-sm">
          Aucune entité à afficher.
        </div>
      ) : (
        sections.map(section => (
          <SectionBlock
            key={section.type}
            section={section}
            images={images}
            zoom={zoom}
            onEntityClick={onEntityClick}
          />
        ))
      )}
    </div>
  )
}
