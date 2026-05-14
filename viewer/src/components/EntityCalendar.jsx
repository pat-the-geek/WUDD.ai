import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react'

// ── Parsing de date robuste (ISO 8601, DD/MM/YYYY ou RFC822) ─────────────────
function parseArticleDate(raw) {
  if (!raw) return null
  // ISO 8601 : "2026-01-23T10:00:00Z" ou "2026-01-23"
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const d = new Date(raw)
    return isNaN(d) ? null : d
  }
  // DD/MM/YYYY : "23/01/2026"
  const m = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})/)
  if (m) {
    const d = new Date(parseInt(m[3]), parseInt(m[2]) - 1, parseInt(m[1]))
    return isNaN(d) ? null : d
  }
  // RFC822 et autres formats reconnus nativement par JS
  // ex. "Mon, 03 Mar 2026 09:00:00 +0000"
  const d = new Date(raw)
  return isNaN(d) ? null : d
}

// Extrait la première phrase du résumé comme titre de l'article
function articleTitle(art) {
  const resume = art['Résumé'] || ''
  const dot = resume.search(/[.!?]\s/)
  const raw = dot > 0 && dot < 120 ? resume.slice(0, dot + 1) : resume.slice(0, 80)
  return raw.trim() || art['Sources'] || 'Article'
}

function dayKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const MONTHS_FR = [
  'Janvier','Février','Mars','Avril','Mai','Juin',
  'Juillet','Août','Septembre','Octobre','Novembre','Décembre',
]
const DAYS_FR = ['lun.','mar.','mer.','jeu.','ven.','sam.','dim.']

// ── Couleur par source (hash stable) ────────────────────────────────────────
const PILL_COLORS = [
  'bg-violet-500 dark:bg-violet-600',
  'bg-blue-500 dark:bg-blue-600',
  'bg-emerald-500 dark:bg-emerald-600',
  'bg-amber-500 dark:bg-amber-600',
  'bg-rose-500 dark:bg-rose-600',
  'bg-cyan-600 dark:bg-cyan-700',
  'bg-indigo-500 dark:bg-indigo-600',
  'bg-teal-500 dark:bg-teal-600',
]

function sourceColor(source) {
  if (!source) return PILL_COLORS[0]
  let h = 0
  for (const c of source) h = (h * 31 + c.charCodeAt(0)) & 0xffff
  return PILL_COLORS[h % PILL_COLORS.length]
}

// ── Barre de navigation commune ──────────────────────────────────────────────
function CalHeader({ title, scale, onScaleChange, onPrev, onNext, onToday }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-white/60 dark:bg-slate-800/60 backdrop-blur-xl shrink-0 flex-wrap">
      <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100 flex-1 min-w-0 truncate">
        {title}
      </h2>
      {/* Sélecteur d'échelle */}
      <div className="flex rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden shrink-0">
        {[['annee','Année'],['mois','Mois'],['semaine','Semaine'],['jour','Jour']].map(([key, label]) => (
          <button
            key={key}
            onClick={() => onScaleChange(key)}
            className={`px-2.5 py-1 text-xs font-medium transition-colors border-l border-slate-200 dark:border-slate-700 first:border-l-0 ${
              scale === key
                ? 'bg-violet-500 text-white'
                : 'bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {/* Navigation */}
      <button
        onClick={onToday}
        className="px-2.5 py-1 text-xs font-medium rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
      >
        Aujourd'hui
      </button>
      <div className="flex items-center gap-0.5">
        <button
          onClick={onPrev}
          className="w-7 h-7 rounded-full flex items-center justify-center text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        >
          <ChevronLeft size={15} />
        </button>
        <button
          onClick={onNext}
          className="w-7 h-7 rounded-full flex items-center justify-center text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        >
          <ChevronRight size={15} />
        </button>
      </div>
    </div>
  )
}

// ── Vue Année ────────────────────────────────────────────────────────────────
function YearView({ year, dayMap, onSelectMonth }) {
  return (
    <div className="grid grid-cols-3 gap-4 p-5">
      {MONTHS_FR.map((name, idx) => {
        const count = Object.entries(dayMap).reduce((acc, [k, arts]) => {
          const d = new Date(k)
          return (d.getFullYear() === year && d.getMonth() === idx)
            ? acc + arts.length : acc
        }, 0)
        return (
          <button
            key={idx}
            onClick={() => onSelectMonth(year, idx)}
            className={`rounded-xl p-4 text-left border transition-colors ${
              count > 0
                ? 'border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/20 hover:bg-violet-100 dark:hover:bg-violet-900/40'
                : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50 hover:bg-slate-50 dark:hover:bg-slate-700/50'
            }`}
          >
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200 block">{name}</span>
            {count > 0 && (
              <span className="mt-2 inline-flex items-center justify-center text-xs font-semibold bg-violet-500 text-white rounded-full px-2 py-0.5">
                {count} article{count > 1 ? 's' : ''}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ── Vue Mois — grille type Apple Calendar ────────────────────────────────────
const MAX_PILLS = 3

function MonthView({ year, month, dayMap, onSelectDay }) {
  const today = new Date()
  const todayK = dayKey(today)

  const firstDay  = new Date(year, month, 1)
  const startDow  = (firstDay.getDay() + 6) % 7   // lundi = 0
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  const cells = []
  for (let i = 0; i < startDow; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(d)
  while (cells.length % 7 !== 0) cells.push(null)

  const weeks = cells.length / 7

  return (
    <div className="flex flex-col">
      {/* En-têtes jours */}
      <div className="grid grid-cols-7 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60">
        {DAYS_FR.map(d => (
          <div key={d} className="text-center text-xs font-medium text-slate-400 dark:text-slate-500 py-2 tracking-wide">
            {d}
          </div>
        ))}
      </div>

      {/* Grille */}
      <div className="grid grid-cols-7" style={{ gridTemplateRows: `repeat(${weeks}, minmax(96px, auto))` }}>
        {cells.map((day, i) => {
          if (!day) {
            return (
              <div
                key={`e${i}`}
                className="border-r border-b border-slate-100 dark:border-slate-800/80 bg-slate-50/40 dark:bg-slate-900/40"
              />
            )
          }

          const k = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
          const arts   = dayMap[k] || []
          const isToday = k === todayK
          const pills  = arts.slice(0, MAX_PILLS)
          const extra  = arts.length - MAX_PILLS

          return (
            <div
              key={k}
              onClick={() => arts.length > 0 && onSelectDay(new Date(year, month, day))}
              className={`border-r border-b border-slate-100 dark:border-slate-800/80 p-1 flex flex-col gap-0.5 transition-colors ${
                arts.length > 0
                  ? 'cursor-pointer hover:bg-violet-50/60 dark:hover:bg-violet-900/10'
                  : 'cursor-default'
              } ${isToday ? 'bg-blue-50/30 dark:bg-blue-900/10' : ''}`}
            >
              {/* Numéro */}
              <div className="flex justify-end px-0.5 mb-0.5">
                <span className={`text-xs font-semibold w-6 h-6 flex items-center justify-center rounded-full leading-none ${
                  isToday
                    ? 'bg-violet-500 text-white'
                    : 'text-slate-500 dark:text-slate-400'
                }`}>
                  {day}
                </span>
              </div>

              {/* Pills événements */}
              {pills.map((art, j) => (
                <div
                  key={j}
                  className={`flex items-center gap-1 rounded-full text-white text-[11px] leading-4 px-1.5 py-0.5 truncate ${sourceColor(art['Sources'])}`}
                  title={art['Résumé'] || ''}
                >
                  <span className="truncate">{articleTitle(art)}</span>
                </div>
              ))}

              {extra > 0 && (
                <div className="text-[11px] text-slate-400 dark:text-slate-500 px-1 leading-4">
                  +{extra} autre{extra > 1 ? 's' : ''}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Vue Semaine ─────────────────────────────────────────────────────────────
function WeekView({ monday, dayMap, onSelectDay }) {
  const today  = new Date()
  const todayK = dayKey(today)

  // Génère les 7 jours de lun. à dim.
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday)
    d.setDate(monday.getDate() + i)
    return d
  })

  return (
    <div className="flex flex-col">
      {/* En-têtes */}
      <div className="grid grid-cols-7 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60">
        {days.map((d, i) => {
          const k = dayKey(d)
          const isToday = k === todayK
          const count = (dayMap[k] || []).length
          return (
            <div
              key={i}
              className="flex flex-col items-center py-2 gap-0.5"
            >
              <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wide">
                {DAYS_FR[i]}
              </span>
              <span className={`text-sm font-semibold w-7 h-7 flex items-center justify-center rounded-full ${
                isToday
                  ? 'bg-violet-500 text-white'
                  : 'text-slate-700 dark:text-slate-300'
              }`}>
                {d.getDate()}
              </span>
              {count > 0 && (
                <span className="text-[11px] bg-violet-100 dark:bg-violet-900/40 text-[#5856D6] dark:text-[#5E5CE6] rounded-full px-1.5 font-semibold">
                  {count}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {/* Corps : colonnes d'articles */}
      <div className="grid grid-cols-7 min-h-[320px]">
        {days.map((d, i) => {
          const k    = dayKey(d)
          const arts = dayMap[k] || []
          const isToday = k === todayK
          return (
            <div
              key={k}
              className={`border-r border-slate-100 dark:border-slate-800/80 last:border-r-0 p-1 flex flex-col gap-1 ${
                isToday ? 'bg-blue-50/30 dark:bg-blue-900/10' : ''
              }`}
            >
              {arts.map((art, j) => {
                const titre  = art['Titre']?.trim() || ''
                const resume = art['Résumé'] || ''
                const source = art['Sources'] || ''
                return (
                  <button
                    key={j}
                    onClick={() => onSelectDay(d)}
                    title={resume}
                    className="w-full text-left rounded-md overflow-hidden border border-slate-100 dark:border-slate-800 hover:border-violet-300 dark:hover:border-violet-600 bg-white dark:bg-slate-800/50 transition-colors"
                  >
                    {/* Bandeau source coloré */}
                    <div className={`px-1.5 py-0.5 text-[11px] font-semibold text-white truncate ${sourceColor(source)}`}>
                      {source || '—'}
                    </div>
                    {/* Titre ou début du résumé */}
                    {titre && (
                      <p className="px-1.5 pt-0.5 text-[11px] font-medium text-slate-700 dark:text-slate-200 line-clamp-2 leading-snug">
                        {titre}
                      </p>
                    )}
                    {/* Extrait du résumé */}
                    <p className="px-1.5 py-0.5 text-[11px] text-slate-500 dark:text-slate-400 line-clamp-3 leading-snug">
                      {resume}
                    </p>
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Vue Jour ─────────────────────────────────────────────────────────────────
function DayView({ date, dayMap }) {
  const k    = dayKey(date)
  const arts = dayMap[k] || []

  if (arts.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-slate-400 dark:text-slate-500">
        Aucun article ce jour.
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      {arts.map((art, i) => (
        <article
          key={i}
          className="bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700/60 rounded-xl p-4 space-y-2"
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              {art['Sources'] && (
                <span className={`text-xs font-semibold text-white rounded-full px-2 py-0.5 ${sourceColor(art['Sources'])}`}>
                  {art['Sources']}
                </span>
              )}
            </div>
            {art['URL'] && (
              <a
                href={art['URL']} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-accent hover:underline shrink-0"
              >
                Lire <ExternalLink size={11} />
              </a>
            )}
          </div>
          {art['Résumé'] && (
            <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed line-clamp-4">
              {art['Résumé']}
            </p>
          )}
        </article>
      ))}
    </div>
  )
}

// ── Composant principal ──────────────────────────────────────────────────────
export default function EntityCalendar({ articles }) {
  const [scale, setScale] = useState('semaine')

  const initDate = useMemo(() => {
    let latest = null
    for (const art of articles) {
      const d = parseArticleDate(art['Date de publication'])
      if (d && (!latest || d > latest)) latest = d
    }
    return latest || new Date()
  }, [articles])

  const [navDate, setNavDate] = useState(initDate)

  const dayMap = useMemo(() => {
    const map = {}
    articles.forEach(art => {
      const d = parseArticleDate(art['Date de publication'])
      if (!d) return
      const k = dayKey(d)
      map[k] = [...(map[k] || []), art]
    })
    return map
  }, [articles])

  function navigate(dir) {
    setNavDate(prev => {
      const d = new Date(prev)
      if (scale === 'annee') d.setFullYear(d.getFullYear() + dir)
      else if (scale === 'mois') d.setMonth(d.getMonth() + dir)
      else if (scale === 'semaine') d.setDate(d.getDate() + dir * 7)
      else d.setDate(d.getDate() + dir)
      return d
    })
  }

  function handleSelectMonth(year, month) {
    setNavDate(new Date(year, month, 1))
    setScale('mois')
  }

  function handleSelectDay(date) {
    setNavDate(date)
    setScale('jour')
  }

  // Calcule le lundi de la semaine de navDate
  function weekMonday(d) {
    const m = new Date(d)
    const dow = (m.getDay() + 6) % 7   // lundi = 0
    m.setDate(m.getDate() - dow)
    m.setHours(0, 0, 0, 0)
    return m
  }

  function title() {
    if (scale === 'annee') return String(navDate.getFullYear())
    if (scale === 'mois')  return `${MONTHS_FR[navDate.getMonth()]} ${navDate.getFullYear()}`
    if (scale === 'semaine') {
      const mon = weekMonday(navDate)
      const sun = new Date(mon); sun.setDate(mon.getDate() + 6)
      const fmtDay = (d) => `${d.getDate()} ${MONTHS_FR[d.getMonth()]}`
      const sameyear = mon.getFullYear() === sun.getFullYear()
      return `${fmtDay(mon)}${sameyear ? '' : ' ' + mon.getFullYear()} – ${fmtDay(sun)} ${sun.getFullYear()}`
    }
    return navDate.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  }

  return (
    <div className="flex flex-col">
      <CalHeader
        title={title()}
        scale={scale}
        onScaleChange={setScale}
        onPrev={() => navigate(-1)}
        onNext={() => navigate(1)}
        onToday={() => setNavDate(new Date())}
      />

      {scale === 'annee' && (
        <YearView year={navDate.getFullYear()} dayMap={dayMap} onSelectMonth={handleSelectMonth} />
      )}
      {scale === 'mois' && (
        <MonthView
          year={navDate.getFullYear()}
          month={navDate.getMonth()}
          dayMap={dayMap}
          onSelectDay={handleSelectDay}
        />
      )}
      {scale === 'semaine' && (
        <WeekView
          monday={weekMonday(navDate)}
          dayMap={dayMap}
          onSelectDay={handleSelectDay}
        />
      )}
      {scale === 'jour' && (
        <DayView date={navDate} dayMap={dayMap} />
      )}
    </div>
  )
}
