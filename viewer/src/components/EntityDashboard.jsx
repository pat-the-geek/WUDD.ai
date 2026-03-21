import { useEffect, useState } from 'react'
import { X, Tag, Loader2, BarChart2, FileText, Newspaper, List, Map, Images, Maximize2, Minimize2, TrendingUp, Search } from 'lucide-react'
import EntityArticlePanel from './EntityArticlePanel'
import EntityWorldMap from './EntityWorldMap'
import EntityGallery from './EntityGallery'
import EntityTimeline from './EntityTimeline'

/**
 * Configuration des types NER (cohérente avec EntityPanel).
 * Couleurs écrites en dur pour éviter la purge Tailwind.
 */
const TYPE_CONFIG = {
  PERSON:      { label: 'Personnes',          bar: 'bg-violet-400 dark:bg-violet-500',  text: 'text-violet-700 dark:text-violet-300',  badge: 'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-800' },
  ORG:         { label: 'Organisations',      bar: 'bg-blue-400 dark:bg-blue-500',      text: 'text-blue-700 dark:text-blue-300',      badge: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800' },
  GPE:         { label: 'Lieux géopolitiques',bar: 'bg-emerald-400 dark:bg-emerald-500',text: 'text-emerald-700 dark:text-emerald-300',badge: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800' },
  PRODUCT:     { label: 'Produits / Tech',    bar: 'bg-orange-400 dark:bg-orange-500',  text: 'text-orange-700 dark:text-orange-300',  badge: 'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-800' },
  EVENT:       { label: 'Événements',         bar: 'bg-amber-400 dark:bg-amber-500',    text: 'text-amber-700 dark:text-amber-300',    badge: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800' },
  LAW:         { label: 'Lois / Règlements',  bar: 'bg-red-400 dark:bg-red-500',        text: 'text-red-700 dark:text-red-300',        badge: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800' },
  LOC:         { label: 'Lieux',              bar: 'bg-teal-400 dark:bg-teal-500',      text: 'text-teal-700 dark:text-teal-300',      badge: 'bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800' },
  NORP:        { label: 'Groupes',            bar: 'bg-fuchsia-400 dark:bg-fuchsia-500',text: 'text-fuchsia-700 dark:text-fuchsia-300',badge: 'bg-fuchsia-100 dark:bg-fuchsia-900/40 text-fuchsia-700 dark:text-fuchsia-300 border-fuchsia-200 dark:border-fuchsia-800' },
  FAC:         { label: 'Sites / Bâtiments',  bar: 'bg-cyan-400 dark:bg-cyan-500',      text: 'text-cyan-700 dark:text-cyan-300',      badge: 'bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-800' },
  WORK_OF_ART: { label: 'Œuvres',             bar: 'bg-rose-400 dark:bg-rose-500',      text: 'text-rose-700 dark:text-rose-300',      badge: 'bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800' },
  MONEY:       { label: 'Montants',           bar: 'bg-yellow-400 dark:bg-yellow-500',  text: 'text-yellow-700 dark:text-yellow-300',  badge: 'bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800' },
  PERCENT:     { label: 'Pourcentages',       bar: 'bg-lime-400 dark:bg-lime-500',      text: 'text-lime-700 dark:text-lime-300',      badge: 'bg-lime-100 dark:bg-lime-900/40 text-lime-700 dark:text-lime-300 border-lime-200 dark:border-lime-800' },
  LANGUAGE:    { label: 'Langues',            bar: 'bg-indigo-400 dark:bg-indigo-500',  text: 'text-indigo-700 dark:text-indigo-300',  badge: 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800' },
  DATE:        { label: 'Dates',              bar: 'bg-slate-400 dark:bg-slate-500',    text: 'text-slate-600 dark:text-slate-400',    badge: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' },
  TIME:        { label: 'Heures',             bar: 'bg-slate-400 dark:bg-slate-500',    text: 'text-slate-600 dark:text-slate-400',    badge: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' },
  QUANTITY:    { label: 'Quantités',          bar: 'bg-stone-400 dark:bg-stone-500',    text: 'text-stone-600 dark:text-stone-400',    badge: 'bg-stone-100 dark:bg-stone-800/60 text-stone-600 dark:text-stone-400 border-stone-200 dark:border-stone-700' },
  CARDINAL:    { label: 'Nombres',            bar: 'bg-zinc-400 dark:bg-zinc-500',      text: 'text-zinc-600 dark:text-zinc-400',      badge: 'bg-zinc-100 dark:bg-zinc-800/60 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-700' },
  ORDINAL:     { label: 'Ordinaux',           bar: 'bg-gray-400 dark:bg-gray-500',      text: 'text-gray-600 dark:text-gray-400',      badge: 'bg-gray-100 dark:bg-gray-800/60 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700' },
}
const FALLBACK_CFG = {
  label: '',
  bar: 'bg-slate-400 dark:bg-slate-500',
  text: 'text-slate-600 dark:text-slate-400',
  badge: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
}

function StatCard({ icon: Icon, value, label, sub }) {
  return (
    <div className="flex flex-col items-center gap-1 px-5 py-4 bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-2xl text-center">
      <Icon size={18} className="text-slate-400 dark:text-slate-500 mb-1" />
      <span className="text-xl sm:text-2xl font-bold tabular-nums text-slate-800 dark:text-slate-100">{value.toLocaleString('fr-FR')}</span>
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</span>
      {sub && <span className="text-[11px] text-slate-400 dark:text-slate-500">{sub}</span>}
    </div>
  )
}

function TypeSection({ section, maxMentions, onEntitySearch }) {
  const cfg = TYPE_CONFIG[section.type] ?? { ...FALLBACK_CFG, label: section.type }
  const pct = maxMentions > 0 ? Math.round((section.mention_count / maxMentions) * 100) : 0

  return (
    <div className="bg-white dark:bg-slate-800/40 border border-slate-200 dark:border-slate-700/60 rounded-2xl overflow-hidden">
      {/* En-tête */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-700/40">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-sm font-semibold ${cfg.text}`}>
              {cfg.label || section.type}
            </span>
            <span className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500">
              {section.type}
            </span>
          </div>
          {/* Barre de proportion */}
          <div className="mt-1.5 h-1.5 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden w-full">
            <div className={`h-full rounded-full transition-all ${cfg.bar}`} style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-sm font-bold tabular-nums text-slate-700 dark:text-slate-300">
            {section.mention_count.toLocaleString('fr-FR')}
          </div>
          <div className="text-[11px] text-slate-400 dark:text-slate-500">
            {section.unique_count} uniques
          </div>
        </div>
      </div>

      {/* Top entités */}
      <div className="px-4 py-3 flex flex-wrap gap-1.5">
        {section.top.map(({ value, count }) => (
          <button
            key={value}
            onClick={() => onEntitySearch?.(value, section.type)}
            title={`Rechercher «${value}» dans tous les fichiers`}
            className={`group inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border transition-all hover:ring-2 hover:ring-offset-1 hover:ring-slate-400/40 hover:scale-105 active:scale-95 ${cfg.badge}`}
          >
            {value}
            {count > 1 && (
              <span className="opacity-55 font-semibold tabular-nums">×{count}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * EntityDashboard — vue agrégée cross-fichiers de toutes les entités nommées.
 *
 * Props:
 *   onClose         {fn}           — ferme le dashboard
 *   onEntitySearch  {fn(val,type)} — ouvre EntitySearchModal pour une entité
 */
export default function EntityDashboard({ onClose, onEntitySearch }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [viewMode, setViewMode] = useState('list') // 'list' | 'map'
  const [isMaximized, setIsMaximized] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    fetch('/api/entities/dashboard')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const maxMentions = data?.by_type?.[0]?.mention_count ?? 1

  // Entités GPE + LOC pour la carte (top 150 par occurrence)
  const geoEntities = data
    ? data.by_type
        .filter(s => s.type === 'GPE' || s.type === 'LOC')
        .flatMap(s => s.top.map(({ value, count }) => ({ name: value, type: s.type, count })))
        .sort((a, b) => b.count - a.count)
        .slice(0, 150)
    : []

  // Entités PERSON + ORG + PRODUCT pour la galerie (top 50 de chaque type)
  const galleryEntities = data
    ? data.by_type
        .filter(s => s.type === 'PERSON' || s.type === 'ORG' || s.type === 'PRODUCT')
        .flatMap(s => s.top.map(({ value, count }) => ({ name: value, type: s.type, count })))
    : []

  return (
    <>
      <div
        className={`hig-overlay-enter fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex justify-center ${isMaximized ? 'items-stretch' : 'items-start p-4 overflow-y-auto'}`}
        onClick={e => e.target === e.currentTarget && onClose()}
      >
        <div className={`hig-modal-enter glass-panel shadow-2xl w-full border border-white/45 dark:border-white/[0.09] overflow-hidden flex flex-col ${isMaximized ? '' : 'max-w-4xl rounded-2xl my-4 max-h-[calc(100dvh-4rem)]'}`}>

          {/* ── En-tête ── */}
          <div className="flex items-center gap-2 sm:gap-3 px-4 sm:px-6 py-3 sm:py-4 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl border-t border-white/30 dark:border-slate-700/40 md:border-t-0 md:border-b shrink-0 order-last md:order-first" style={isMaximized ? { paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))' } : undefined}>
            <BarChart2 size={18} className="hidden md:block text-violet-500" />
            <span className="hidden md:block font-semibold text-slate-800 dark:text-slate-100 text-base">
              Dashboard entités
            </span>
            {!loading && data && (
              <span className="hidden md:inline text-xs text-slate-400 dark:text-slate-500 ml-1">
                — {data.by_type.length} types
              </span>
            )}

            {/* Toggle Liste / Carte */}
            {!loading && data && data.by_type.length > 0 && (
              <div className="flex-1 md:flex-none md:ml-auto md:mr-2 flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                <button
                  onClick={() => setViewMode('list')}
                  title="Vue liste"
                  className={`flex-1 flex items-center justify-center gap-2 px-4 sm:px-3 py-3 sm:py-1.5 text-sm sm:text-xs font-medium transition-colors ${
                    viewMode === 'list'
                      ? 'bg-violet-500 text-white'
                      : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <List size={16} />
                  <span>Liste</span>
                </button>
                <button
                  onClick={() => setViewMode('map')}
                  title="Vue carte du monde"
                  className={`flex-1 flex items-center justify-center gap-2 px-4 sm:px-3 py-3 sm:py-1.5 text-sm sm:text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                    viewMode === 'map'
                      ? 'bg-violet-500 text-white'
                      : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <Map size={16} />
                  <span>Carte</span>
                </button>
                <button
                  onClick={() => setViewMode('gallery')}
                  title="Galerie d'images Wikipedia"
                  className={`flex-1 flex items-center justify-center gap-2 px-4 sm:px-3 py-3 sm:py-1.5 text-sm sm:text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                    viewMode === 'gallery'
                      ? 'bg-violet-500 text-white'
                      : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <Images size={16} />
                  <span>Galerie</span>
                </button>
                <button
                  onClick={() => setViewMode('timeline')}
                  title="Évolution temporelle des entités"
                  className={`flex-1 flex items-center justify-center gap-2 px-4 sm:px-3 py-3 sm:py-1.5 text-sm sm:text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${
                    viewMode === 'timeline'
                      ? 'bg-violet-500 text-white'
                      : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <TrendingUp size={16} />
                  <span>Timeline</span>
                </button>
              </div>
            )}

            <button
              onClick={() => setIsMaximized(m => !m)}
              title={isMaximized ? 'Réduire la fenêtre' : 'Agrandir à la taille de l\'écran'}
              className="shrink-0 w-10 h-10 sm:w-8 sm:h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
            >
              {isMaximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
            <button
              onClick={onClose}
              className="shrink-0 w-10 h-10 sm:w-8 sm:h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* ── Corps ── */}
          <div className={`p-4 sm:p-6 flex-1 min-h-0 ${viewMode === 'map' ? 'flex flex-col overflow-hidden' : 'overflow-y-auto'}`}>
            {loading ? (
              <div className="flex items-center justify-center py-20 gap-2 text-slate-400 dark:text-slate-500">
                <Loader2 size={20} className="animate-spin" />
                <span className="text-sm">Agrégation en cours…</span>
              </div>
            ) : !data || data.by_type.length === 0 ? (
              <div className="text-center py-20 text-slate-400 dark:text-slate-500 text-sm">
                <div className="text-4xl mb-3">📊</div>
                Aucune entité trouvée.
                <br />
                <span className="text-xs">
                  Lancez <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded-full">enrich_entities.py</code> pour enrichir vos données.
                </span>
              </div>
            ) : (
              <>
                {/* Statistiques globales */}
                <div className={`grid grid-cols-2 sm:grid-cols-3 gap-3 mb-8 ${isMaximized && viewMode === 'map' ? 'shrink-0' : ''}`}>
                  <StatCard icon={FileText}  value={data.total_files}          label="Fichiers analysés" />
                  <StatCard icon={Newspaper} value={data.total_articles}        label="Articles au total" />
                  <StatCard
                    icon={Tag}
                    value={data.total_with_entities}
                    label="Articles enrichis"
                    sub={data.total_articles > 0
                      ? `${Math.round(data.total_with_entities / data.total_articles * 100)} %`
                      : ''}
                  />
                </div>

                {viewMode === 'map' ? (
                  /* ── Vue Carte ── */
                  <EntityWorldMap
                    entities={geoEntities}
                    onEntityClick={(type, value) => setSelectedEntity({ type, value })}
                    style={isMaximized ? { flex: 1, minHeight: 0 } : undefined}
                  />
                ) : viewMode === 'gallery' ? (
                  /* ── Vue Galerie ── */
                  <EntityGallery
                    entities={galleryEntities}
                    onEntityClick={(type, value) => setSelectedEntity({ type, value })}
                  />
                ) : viewMode === 'timeline' ? (
                  /* ── Vue Timeline ── */
                  <EntityTimeline onEntitySearch={(value, type) => setSelectedEntity({ type, value })} />
                ) : (
                  /* ── Vue Liste ── */
                  <>
                    {/* Barre de recherche */}
                    <div className="mb-4 relative">
                      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" />
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        placeholder="Rechercher une entité…"
                        className="w-full pl-9 pr-8 py-2 text-sm bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-400/60 dark:focus:ring-violet-500/50"
                      />
                      {searchQuery && (
                        <button
                          onClick={() => setSearchQuery('')}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>

                    {/* Grille des types */}
                    {(() => {
                      const filtered = searchQuery
                        ? data.by_type
                            .map(s => ({ ...s, top: s.top.filter(({ value }) => value.toLowerCase().startsWith(searchQuery.toLowerCase())) }))
                            .filter(s => s.top.length > 0)
                        : data.by_type
                      return filtered.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {filtered.map(section => (
                            <TypeSection
                              key={section.type}
                              section={section}
                              maxMentions={maxMentions}
                              onEntitySearch={(value, type) => setSelectedEntity({ type, value })}
                            />
                          ))}
                        </div>
                      ) : (
                        <div className="text-center py-12 text-slate-400 dark:text-slate-500 text-sm">
                          Aucune entité ne commence par « {searchQuery} »
                        </div>
                      )
                    })()}
                  </>
                )}
              </>
            )}
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
    </>
  )
}
