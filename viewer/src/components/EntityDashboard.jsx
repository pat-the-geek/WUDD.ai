import { useEffect, useState, useRef } from 'react'
import { useFetchCache } from '../hooks/useFetchCache'
import { X, Tag, Loader2, BarChart2, FileText, Newspaper, List, Map, Images, Maximize2, Minimize2, TrendingUp, Search } from 'lucide-react'
import EntityArticlePanel from './EntityArticlePanel'
import EntityWorldMap from './EntityWorldMap'
import EntityGallery from './EntityGallery'
import EntityTimeline from './EntityTimeline'
import { getEntityConfig } from '../lib/entity-config'

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
  const cfg = getEntityConfig(section.type)
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
  const [includeStructural, setIncludeStructural] = useState(false)
  const dashboardUrl = includeStructural
    ? '/api/entities/dashboard?include_structural=1'
    : '/api/entities/dashboard'
  const { data, loading } = useFetchCache(dashboardUrl)
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [viewMode, setViewMode] = useState('list') // 'list' | 'map'
  const [isMaximized, setIsMaximized] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null) // null = pas de recherche active
  const [searchLoading, setSearchLoading] = useState(false)
  const searchDebounceRef = useRef(null)


  // Recherche débouncée (300ms) via l'API backend
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults(null)
      setSearchLoading(false)
      return
    }
    setSearchLoading(true)
    searchDebounceRef.current = setTimeout(() => {
      const params = new URLSearchParams({ q: searchQuery })
      if (includeStructural) params.set('include_structural', '1')
      fetch(`/api/entities/search?${params.toString()}`)
        .then(r => r.json())
        .then(d => { setSearchResults(d.by_type ?? []); setSearchLoading(false) })
        .catch(() => { setSearchResults([]); setSearchLoading(false) })
    }, 300)
    return () => { if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current) }
  }, [searchQuery, includeStructural])

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
        className={`hig-overlay-enter fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex justify-center ${isMaximized ? 'items-stretch' : 'items-stretch md:items-start md:p-4 md:overflow-y-auto'}`}
        onClick={e => e.target === e.currentTarget && onClose()}
      >
        <div className={`hig-modal-enter glass-panel shadow-2xl w-full border border-white/45 dark:border-white/[0.09] overflow-hidden flex flex-col relative ${isMaximized ? '' : 'md:max-w-4xl md:rounded-2xl md:my-4 md:max-h-[calc(100dvh-4rem)]'}`}>

          {/* ── En-tête desktop ── */}
          <div className="hidden md:flex items-center gap-2 px-4 py-3 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl border-b border-white/30 dark:border-slate-700/40 shrink-0">
            <BarChart2 size={18} className="text-accent" />
            <span className="font-semibold text-slate-800 dark:text-slate-100 text-base">
              Dashboard entités
            </span>
            {!loading && data && (
              <span className="text-xs text-slate-400 dark:text-slate-500 ml-1">
                — {data.by_type.length} types
              </span>
            )}
            {!loading && data && data.by_type.length > 0 && (
              <div className="ml-auto mr-2 flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                <button onClick={() => setViewMode('list')} title="Vue liste" className={`flex items-center justify-center gap-2 px-3 py-1.5 text-xs font-medium transition-colors ${viewMode === 'list' ? 'btn-accent text-white' : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}><List size={14} /><span>Liste</span></button>
                <button onClick={() => setViewMode('map')} title="Vue carte" className={`flex items-center justify-center gap-2 px-3 py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${viewMode === 'map' ? 'btn-accent text-white' : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}><Map size={14} /><span>Carte</span></button>
                <button onClick={() => setViewMode('gallery')} title="Galerie" className={`flex items-center justify-center gap-2 px-3 py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${viewMode === 'gallery' ? 'btn-accent text-white' : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}><Images size={14} /><span>Galerie</span></button>
                <button onClick={() => setViewMode('timeline')} title="Timeline" className={`flex items-center justify-center gap-2 px-3 py-1.5 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 ${viewMode === 'timeline' ? 'btn-accent text-white' : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'}`}><TrendingUp size={14} /><span>Timeline</span></button>
              </div>
            )}
            <button onClick={() => setIsMaximized(m => !m)} title={isMaximized ? 'Réduire' : 'Agrandir'} className="shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors">{isMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</button>
            <button onClick={onClose} className="shrink-0 w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 flex items-center justify-center text-slate-500 dark:text-slate-400 transition-colors"><X size={14} /></button>
          </div>

          {/* ── Tab bar mobile — floating pill transparent ── */}
          <div
            className="md:hidden absolute bottom-0 left-0 right-0 z-[1100] flex flex-col"
            style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
          >
            <div className="flex items-stretch mx-3 mb-3 h-[49px] rounded-2xl overflow-hidden glass-nav">
              <button onClick={() => setViewMode('list')} className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${viewMode === 'list' ? 'text-accent' : 'text-slate-400 dark:text-slate-500'}`}>{viewMode === 'list' && <span className="nav-active-pill" />}<List size={20} strokeWidth={viewMode === 'list' ? 2.2 : 1.8} /><span className="text-[11px] font-medium leading-none">Liste</span></button>
              <button onClick={() => setViewMode('map')} className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${viewMode === 'map' ? 'text-accent' : 'text-slate-400 dark:text-slate-500'}`}>{viewMode === 'map' && <span className="nav-active-pill" />}<Map size={20} strokeWidth={viewMode === 'map' ? 2.2 : 1.8} /><span className="text-[11px] font-medium leading-none">Carte</span></button>
              <button onClick={() => setViewMode('gallery')} className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${viewMode === 'gallery' ? 'text-accent' : 'text-slate-400 dark:text-slate-500'}`}>{viewMode === 'gallery' && <span className="nav-active-pill" />}<Images size={20} strokeWidth={viewMode === 'gallery' ? 2.2 : 1.8} /><span className="text-[11px] font-medium leading-none">Galerie</span></button>
              <button onClick={() => setViewMode('timeline')} className={`relative flex flex-1 flex-col items-center justify-center gap-[2px] transition-colors active:opacity-60 ${viewMode === 'timeline' ? 'text-accent' : 'text-slate-400 dark:text-slate-500'}`}>{viewMode === 'timeline' && <span className="nav-active-pill" />}<TrendingUp size={20} strokeWidth={viewMode === 'timeline' ? 2.2 : 1.8} /><span className="text-[11px] font-medium leading-none">Timeline</span></button>
              <button onClick={onClose} aria-label="Fermer" className="flex items-center justify-center px-4 text-slate-400 dark:text-slate-500 border-l border-slate-200/60 dark:border-slate-700/50 active:opacity-60 transition-colors"><X size={20} /></button>
            </div>
          </div>

          {/* ── Corps ── */}
          <div className={`p-4 sm:p-6 flex-1 min-h-0 entity-tabs-content ${viewMode === 'map' ? 'flex flex-col overflow-hidden' : 'overflow-y-auto'}`}>
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
                <div className={`grid grid-cols-2 sm:grid-cols-3 gap-3 mb-8 ${viewMode === 'map' ? 'shrink-0' : ''}`}>
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
                    style={isMaximized ? { flex: 1, minHeight: 0 } : { height: 'clamp(220px, calc(100dvh - 22rem), 520px)' }}
                  />
                ) : viewMode === 'gallery' ? (
                  /* ── Vue Galerie ── */
                  <EntityGallery
                    entities={galleryEntities}
                    onEntityClick={(type, value) => setSelectedEntity({ type, value })}
                  />
                ) : viewMode === 'timeline' ? (
                  /* ── Vue Timeline ── */
                  <EntityTimeline
                    includeStructuralDefault={includeStructural}
                    onEntitySearch={(value, type) => setSelectedEntity({ type, value })}
                  />
                ) : (
                  /* ── Vue Liste ── */
                  <>
                    {/* Barre de recherche */}
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                      <label className="inline-flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={includeStructural}
                          onChange={e => setIncludeStructural(e.target.checked)}
                          className="rounded border-slate-300 dark:border-slate-600 text-accent focus:ring-[var(--color-accent-subtle)]"
                        />
                        Inclure types structurels (DATE, MONEY…)
                      </label>
                      <span className="text-[11px] text-slate-400 dark:text-slate-500">
                        Active aussi les types avancés comme LAW/WORK_OF_ART dans les recherches et le dashboard.
                      </span>
                    </div>
                    <div className="mb-4 relative">
                      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" />
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        placeholder="Rechercher une entité…"
                        className="w-full pl-9 pr-8 py-2 text-sm bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-subtle)]"
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
                      if (searchLoading) {
                        return (
                          <div className="flex items-center justify-center py-12 gap-2 text-slate-400 dark:text-slate-500 text-sm">
                            <Loader2 size={16} className="animate-spin" /> Recherche…
                          </div>
                        )
                      }
                      const displayList = searchResults !== null ? searchResults : data.by_type
                      const searchMax = displayList[0]?.mention_count ?? 1
                      return displayList.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {displayList.map(section => (
                            <TypeSection
                              key={section.type}
                              section={section}
                              maxMentions={searchResults !== null ? searchMax : maxMentions}
                              onEntitySearch={(value, type) => setSelectedEntity({ type, value })}
                            />
                          ))}
                        </div>
                      ) : (
                        <div className="text-center py-12 text-slate-400 dark:text-slate-500 text-sm">
                          Aucune entité trouvée pour « {searchQuery} »
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
