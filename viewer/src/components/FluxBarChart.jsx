/**
 * FluxBarChart — Graphe en barres horizontales pour les top flux.
 *
 * Props:
 *   items  {Array}  — [{ label, name, count }] — trié par count décroissant
 */

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
function toLabel(i) {
  return i < 26 ? LETTERS[i] : LETTERS[Math.floor(i / 26) - 1] + LETTERS[i % 26]
}

const PALETTE = [
  '#818cf8', '#60a5fa', '#34d399', '#fb923c', '#f472b6',
  '#a78bfa', '#38bdf8', '#4ade80', '#fbbf24', '#f87171',
]

export default function FluxBarChart({ items }) {
  if (!items?.length) return null

  const maxCount = Math.max(...items.map(d => d.count))
  const BAR_HEIGHT = 28
  const GAP = 8
  const LETTER_W = 22
  const LABEL_W = 160
  const VALUE_W = 48
  const BAR_MAX_W = 360
  const PADDING_TOP = 32
  const PADDING_BOTTOM = 16
  const PADDING_LEFT = 12
  const totalH = PADDING_TOP + items.length * (BAR_HEIGHT + GAP) - GAP + PADDING_BOTTOM
  const totalW = PADDING_LEFT + LETTER_W + LABEL_W + BAR_MAX_W + VALUE_W + 16

  return (
    <div className="my-6 w-full overflow-x-auto">
      <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2 ml-1">
        Top flux — nb articles
      </div>
      <svg
        viewBox={`0 0 ${totalW} ${totalH}`}
        width="100%"
        style={{ display: 'block', maxWidth: totalW }}
      >
        {/* Lignes de grille */}
        {[0, 0.25, 0.5, 0.75, 1].map(frac => {
          const x = PADDING_LEFT + LETTER_W + LABEL_W + Math.round(frac * BAR_MAX_W)
          return (
            <g key={frac}>
              <line
                x1={x} y1={PADDING_TOP - 12}
                x2={x} y2={totalH - PADDING_BOTTOM}
                stroke="#e2e8f0" strokeWidth="1"
              />
              <text x={x} y={PADDING_TOP - 16} textAnchor="middle"
                fontSize={9} fill="#94a3b8">
                {Math.round(frac * maxCount)}
              </text>
            </g>
          )
        })}

        {items.map((item, i) => {
          const y = PADDING_TOP + i * (BAR_HEIGHT + GAP)
          const barW = maxCount > 0 ? Math.round((item.count / maxCount) * BAR_MAX_W) : 0
          const color = PALETTE[i % PALETTE.length]
          // Nom affiché : strip préfixe rss:
          const displayName = item.name.startsWith('rss:')
            ? item.name.slice(4).replace('/', ' / ')
            : item.name

          return (
            <g key={item.name}>
              {/* Lettre (depuis les données Python, sinon calculée) */}
              <text
                x={PADDING_LEFT + LETTER_W - 2}
                y={y + BAR_HEIGHT / 2 + 4}
                textAnchor="end"
                fontSize={11}
                fontWeight="700"
                fill={color}
                style={{ fontFamily: 'system-ui, sans-serif' }}
              >
                {item.letter || toLabel(i)}
              </text>

              {/* Nom du flux */}
              <text
                x={PADDING_LEFT + LETTER_W + LABEL_W - 6}
                y={y + BAR_HEIGHT / 2 + 4}
                textAnchor="end"
                fontSize={11}
                fill="#64748b"
                style={{ fontFamily: 'system-ui, sans-serif' }}
              >
                {displayName.length > 22
                  ? displayName.slice(0, 21) + '…'
                  : displayName}
              </text>

              {/* Barre */}
              <rect
                x={PADDING_LEFT + LETTER_W + LABEL_W}
                y={y}
                width={barW}
                height={BAR_HEIGHT}
                rx={4}
                fill={color}
                opacity={0.85}
              />

              {/* Valeur */}
              <text
                x={PADDING_LEFT + LETTER_W + LABEL_W + barW + 6}
                y={y + BAR_HEIGHT / 2 + 4}
                fontSize={11}
                fill="#475569"
                style={{ fontFamily: 'system-ui, sans-serif', fontWeight: 600 }}
              >
                {item.count}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
