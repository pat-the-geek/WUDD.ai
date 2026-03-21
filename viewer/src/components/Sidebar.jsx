import { Search, FileJson, FileText, X, Folder, RefreshCw } from 'lucide-react'
import { useMemo } from 'react'

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`
}

function formatDate(timestamp) {
  return new Date(timestamp * 1000).toLocaleDateString('fr-FR', {
    day: '2-digit', month: '2-digit', year: '2-digit',
  })
}

function formatTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString('fr-FR', {
    hour: '2-digit', minute: '2-digit',
  })
}

function isToday(timestamp) {
  const d = new Date(timestamp * 1000)
  const now = new Date()
  return d.getFullYear() === now.getFullYear()
    && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate()
}

export default function Sidebar({
  files, selectedFile, onSelect,
  typeFilter, onTypeFilterChange,
  nameSearch, onNameSearchChange,
  isOpen, onClose,
  onRefresh, isRefreshing,
}) {
  // Grouper par flux
  const grouped = useMemo(() => {
    const groups = {}
    files.forEach(f => {
      const key = f.flux || 'Racine'
      if (!groups[key]) groups[key] = []
      groups[key].push(f)
    })
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b, 'fr'))
  }, [files])

  return (
    <aside className={[
      'w-72 flex flex-col glass-sidebar border-r border-white/40 dark:border-white/[0.07] shrink-0',
      // Desktop : position normale dans le flux
      'md:relative md:translate-x-0 md:z-auto md:shadow-none',
      // Mobile : drawer fixe qui slide depuis la gauche
      'fixed top-0 left-0 h-full z-40 shadow-xl transition-transform duration-200',
      isOpen ? 'translate-x-0' : '-translate-x-full',
    ].join(' ')}>
      {/* Barre mobile uniquement : titre + bouton fermer */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-slate-200 dark:border-slate-700 md:hidden">
        <span className="text-hig-subheadline font-semibold text-slate-700 dark:text-slate-200">Fichiers</span>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-400 dark:text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors touch-target"
        >
          <X size={18} />
        </button>
      </div>
      {/* ── Filtres ── visibles sur mobile et desktop */}
      <div className="p-3 border-b border-slate-200 dark:border-slate-700 space-y-2.5">
        {/* Boutons type */}
        <div className="flex gap-1">
          {[
            { key: 'all', label: 'Tous' },
            { key: 'json', label: 'JSON' },
            { key: 'markdown', label: 'Markdown' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => onTypeFilterChange(key)}
              className={`flex-1 py-1.5 text-hig-caption1 font-medium rounded transition-colors ${
                typeFilter === key
                  ? 'bg-[#007AFF] dark:bg-[#0A84FF] text-white'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Recherche par nom */}
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={nameSearch}
            onChange={e => onNameSearchChange(e.target.value)}
            placeholder="Filtrer par nom…"
            className="w-full pl-8 pr-7 py-1.5 bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-sm text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
          {nameSearch && (
            <button
              onClick={() => onNameSearchChange('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
            >
              <X size={12} />
            </button>
          )}
        </div>

        <div className="flex items-center justify-between">
          <div className="text-xs text-slate-400 dark:text-slate-600">
            {files.length} fichier{files.length !== 1 ? 's' : ''}
          </div>
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              title="Actualiser la liste des fichiers"
              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 transition-colors disabled:opacity-50"
            >
              <RefreshCw size={11} className={isRefreshing ? 'animate-spin' : ''} />
              Actualiser
            </button>
          )}
        </div>
      </div>

      {/* ── Liste des fichiers ── */}
      <div className="flex-1 overflow-y-auto">
        {grouped.map(([flux, fluxFiles]) => (
          <div key={flux}>
            {/* En-tête de groupe */}
            <div className="sticky top-0 z-10 bg-white/95 dark:bg-slate-800/95 px-3 py-1.5 flex items-center gap-1.5 border-b border-slate-200/60 dark:border-slate-700/60 backdrop-blur-sm">
              <Folder size={11} className="text-slate-400 dark:text-slate-500" />
              <span className="text-hig-caption2 font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider truncate">
                {flux}
              </span>
              <span className="ml-auto text-hig-caption2 text-slate-500 dark:text-slate-500 shrink-0">{fluxFiles.length}</span>
            </div>

            {/* Items */}
            {fluxFiles.map(file => {
              const isSelected = selectedFile?.path === file.path
              return (
                <button
                  key={file.path}
                  onClick={() => onSelect(file)}
                  className={`w-full text-left px-3 py-2.5 flex items-start gap-2.5 border-b border-slate-200/30 dark:border-slate-700/30 transition-colors ${
                    isSelected
                      ? 'bg-[#007AFF]/10 dark:bg-[#0A84FF]/15 border-l-2 border-l-[#007AFF] dark:border-l-[#0A84FF] pl-[10px]'
                      : 'hover:bg-slate-100/50 dark:hover:bg-slate-700/50'
                  }`}
                >
                  {file.type === 'json'
                    ? <FileJson size={14} className="shrink-0 mt-0.5 text-amber-500 dark:text-amber-400" />
                    : <FileText size={14} className="shrink-0 mt-0.5 text-blue-500 dark:text-blue-400" />
                  }
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-slate-800 dark:text-slate-200 truncate leading-snug flex items-center gap-1.5">
                      <span className="truncate">{file.name}</span>
                      {isToday(file.modified) && (
                        <span className="shrink-0 text-[11px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-orange-500 text-white leading-none">
                          new
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`text-[11px] px-1.5 rounded font-mono leading-4 ${
                        file.type === 'json'
                          ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400'
                          : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400'
                      }`}>
                        {file.type === 'json' ? 'JSON' : 'MD'}
                      </span>
                      <span className="text-[11px] text-slate-400 dark:text-slate-500">{formatSize(file.size)}</span>
                      <span className="text-[11px] text-slate-400 dark:text-slate-600 ml-auto">{formatDate(file.modified)} {formatTime(file.modified)}</span>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        ))}

        {files.length === 0 && (
          <div className="p-8 text-center text-slate-400 dark:text-slate-500 text-sm">
            Aucun fichier trouvé
          </div>
        )}
      </div>
    </aside>
  )
}
