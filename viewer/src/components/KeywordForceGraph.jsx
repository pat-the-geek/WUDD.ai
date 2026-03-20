/**
 * KeywordForceGraph — Graphe force-directed des mots-clés de veille WUDD.ai.
 *
 * Props:
 *   keywords  {Array}  — tableau d'objets { keyword, or, and }
 *
 * Affichage :
 *   - Centre : WUDD.ai (violet)
 *   - Niveau 1 : mots-clés (bleu)
 *   - Niveau 2 : termes "ou" (teal) et termes "et" (orange), optionnels
 * Interactions : zoom molette, drag, slider longueur des liens, toggle sous-termes
 */
import { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

// ── Couleurs ─────────────────────────────────────────────────────────────────
const COLOR_ROOT = '#8b5cf6'   // violet
const COLOR_KW   = '#60a5fa'   // bleu
const COLOR_OR   = '#34d399'   // teal — termes OU
const COLOR_AND  = '#fb923c'   // orange — termes ET

// ── Dimensions du canvas interne ─────────────────────────────────────────────
const W = 1000
const H = 700

// ── Force layout (adapté de EntityGraph) ─────────────────────────────────────
function computeLayout(nodes, edgeTriples, kFactor = 1.0) {
  const n = nodes.length
  if (n <= 1) return [{ x: W / 2, y: H / 2 }]

  const pos = nodes.map((node, i) => {
    if (i === 0) return { x: W / 2, y: H / 2, vx: 0, vy: 0 }
    const level = node.level ?? 1
    const peers = nodes.filter((nd, j) => j > 0 && (nd.level ?? 1) === level)
    const idx   = peers.indexOf(node)
    const angle = (2 * Math.PI * idx) / Math.max(peers.length, 1)
    const r     = level === 2
      ? Math.min(W, H) * 0.68
      : Math.min(W, H) * 0.38
    return { x: W / 2 + r * Math.cos(angle), y: H / 2 + r * Math.sin(angle), vx: 0, vy: 0 }
  })

  const k = Math.sqrt((W * H) / n) * 0.88 * kFactor
  const ITERS = 280

  for (let it = 0; it < ITERS; it++) {
    const temp = Math.max(0.3, 6 * (1 - it / ITERS))
    const fx = new Float32Array(n)
    const fy = new Float32Array(n)

    // Répulsion
    for (let i = 0; i < n; i++) {
      const ri = (nodes[i].level ?? 1) === 2 ? 0.55 : 1.0
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i].x - pos[j].x
        const dy = pos[i].y - pos[j].y
        const d2 = Math.max(dx * dx + dy * dy, 1)
        const d  = Math.sqrt(d2)
        const rj = (nodes[j].level ?? 1) === 2 ? 0.55 : 1.0
        const f  = (k * k * ri * rj) / d2
        fx[i] += (dx / d) * f;  fy[i] += (dy / d) * f
        fx[j] -= (dx / d) * f;  fy[j] -= (dy / d) * f
      }
    }

    // Attraction le long des arêtes
    for (const [si, ti] of edgeTriples) {
      const dx = pos[ti].x - pos[si].x
      const dy = pos[ti].y - pos[si].y
      const d  = Math.sqrt(dx * dx + dy * dy) || 0.01
      const ideal = k * 0.68
      const f  = (d - ideal) * 0.20
      fx[si] += (dx / d) * f;  fy[si] += (dy / d) * f
      fx[ti] -= (dx / d) * f;  fy[ti] -= (dy / d) * f
    }

    // Gravité
    for (let i = 0; i < n; i++) {
      fx[i] += (W / 2 - pos[i].x) * (i === 0 ? 0.14 : 0.016)
      fy[i] += (H / 2 - pos[i].y) * (i === 0 ? 0.14 : 0.016)
    }

    // Intégration
    for (let i = 0; i < n; i++) {
      pos[i].vx = (pos[i].vx + fx[i]) * 0.60
      pos[i].vy = (pos[i].vy + fy[i]) * 0.60
      const mag = Math.sqrt(pos[i].vx ** 2 + pos[i].vy ** 2) || 0.01
      const disp = Math.min(mag, temp)
      pos[i].x += (pos[i].vx / mag) * disp
      pos[i].y += (pos[i].vy / mag) * disp
      pos[i].x = Math.max(72, Math.min(W - 72, pos[i].x))
      pos[i].y = Math.max(32, Math.min(H - 32, pos[i].y))
    }
  }

  return pos.map(p => ({ x: p.x, y: p.y }))
}

// ── Composant principal ───────────────────────────────────────────────────────
export default function KeywordForceGraph({ keywords }) {
  const [showTerms, setShowTerms] = useState(true)
  const [spacing,   setSpacing]   = useState(1.0)
  const [tooltip,   setTooltip]   = useState(null)

  // ── Zoom / pan ──────────────────────────────────────────────────────────────
  const VIEW0 = { x: 0, y: 0, scale: 1 }
  const [view,  setView] = useState(VIEW0)
  const viewRef          = useRef(VIEW0)
  const svgRef           = useRef(null)
  const dragState        = useRef(null)
  const dragMoved        = useRef(false)

  const applyView = useCallback((next) => { viewRef.current = next; setView(next) }, [])
  const resetView = useCallback(() => applyView(VIEW0), [applyView])

  const wheelHandler = useCallback((e) => {
    e.preventDefault()
    const el = svgRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const v    = viewRef.current
    const cssX = e.clientX - rect.left
    const cssY = e.clientY - rect.top
    const svgX = v.x + (cssX / rect.width)  * (W / v.scale)
    const svgY = v.y + (cssY / rect.height) * (H / v.scale)
    const factor   = e.deltaY < 0 ? 1.10 : 0.91
    const newScale = Math.max(0.15, Math.min(14, v.scale * factor))
    applyView({
      x: svgX - (cssX / rect.width)  * (W / newScale),
      y: svgY - (cssY / rect.height) * (H / newScale),
      scale: newScale,
    })
  }, [applyView])

  const svgCallbackRef = useCallback((el) => {
    if (svgRef.current) svgRef.current.removeEventListener('wheel', wheelHandler)
    svgRef.current = el
    if (el) el.addEventListener('wheel', wheelHandler, { passive: false })
  }, [wheelHandler])

  // Drag → pan
  useEffect(() => {
    const onMove = (e) => {
      if (!dragState.current) return
      const rect = svgRef.current?.getBoundingClientRect()
      if (!rect) return
      const s = dragState.current
      if (Math.abs(e.clientX - s.clientX) > 3 || Math.abs(e.clientY - s.clientY) > 3) {
        dragMoved.current = true
      }
      const dx = (e.clientX - s.clientX) / rect.width  * (W / s.scale)
      const dy = (e.clientY - s.clientY) / rect.height * (H / s.scale)
      applyView({ x: s.viewX - dx, y: s.viewY - dy, scale: s.scale })
    }
    const onUp = () => { dragState.current = null }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }
  }, [applyView])

  const handleMouseDown = (e) => {
    if (e.button !== 0) return
    dragMoved.current = false
    const v = viewRef.current
    dragState.current = { clientX: e.clientX, clientY: e.clientY, viewX: v.x, viewY: v.y, scale: v.scale }
  }

  // ── Construction du graphe ──────────────────────────────────────────────────
  const { nodes, edges } = useMemo(() => {
    const nodes = [{ id: 'root', label: 'WUDD.ai', level: 0, termType: 'root' }]
    const edges = []

    if (!keywords?.length) return { nodes, edges }

    keywords.forEach((entry, ki) => {
      const raw = (entry.keyword || '').trim()
      if (!raw) return
      // Nettoyer les caractères de syntaxe (ex: [Art])
      const kwLabel = raw.replace(/[[\](){}`"']/g, '').trim().slice(0, 20)
      if (!kwLabel) return

      const kwId  = `kw-${ki}`
      const kwIdx = nodes.length
      nodes.push({ id: kwId, label: kwLabel, level: 1, termType: 'kw' })
      edges.push([0, kwIdx])

      if (showTerms) {
        const orTerms  = (entry.or  || []).map(t => t.trim()).filter(Boolean).slice(0, 3)
        const andTerms = (entry.and || []).map(t => t.trim()).filter(Boolean).slice(0, 3)

        orTerms.forEach((t, ti) => {
          const idx = nodes.length
          nodes.push({ id: `${kwId}-or-${ti}`, label: t.slice(0, 18), level: 2, termType: 'or' })
          edges.push([kwIdx, idx])
        })
        andTerms.forEach((t, ti) => {
          const idx = nodes.length
          nodes.push({ id: `${kwId}-and-${ti}`, label: t.slice(0, 18), level: 2, termType: 'and' })
          edges.push([kwIdx, idx])
        })
      }
    })

    return { nodes, edges }
  }, [keywords, showTerms])

  const positions = useMemo(
    () => computeLayout(nodes, edges, spacing),
    [nodes, edges, spacing]
  )

  // ── Aides visuelles ─────────────────────────────────────────────────────────
  const nodeColor = (n) => {
    if (n.termType === 'root') return COLOR_ROOT
    if (n.termType === 'kw')   return COLOR_KW
    if (n.termType === 'or')   return COLOR_OR
    return COLOR_AND
  }
  const nodeRadius = (n) => {
    if (n.level === 0) return 26
    if (n.level === 1) return 11
    return 6
  }

  const zoomPct = Math.round(view.scale * 100)
  const vb = `${view.x} ${view.y} ${W / view.scale} ${H / view.scale}`

  return (
    <div className="flex flex-col h-full min-h-0 select-none">
      {/* ── Barre de contrôle ─────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-200 dark:border-slate-700 shrink-0 flex-wrap bg-white/80 dark:bg-slate-900/80">
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {keywords?.length ?? 0} mots-clés · {nodes.length} nœuds
        </span>

        {/* Toggle sous-termes */}
        <label className="flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400 cursor-pointer">
          <input
            type="checkbox"
            checked={showTerms}
            onChange={e => setShowTerms(e.target.checked)}
            className="w-3 h-3 accent-violet-500"
          />
          Sous-termes
        </label>

        {/* Longueur des liens — slider */}
        <div className="flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
          <span>Liens</span>
          <input
            type="range"
            min="0.4" max="3.5" step="0.05"
            value={spacing}
            onChange={e => setSpacing(+e.target.value)}
            className="w-24 accent-violet-500"
            title={`Longueur des liens : ${spacing.toFixed(2)}×`}
          />
          <span className="tabular-nums w-8">{spacing.toFixed(1)}×</span>
        </div>

        {/* Légende */}
        <div className="flex items-center gap-2.5">
          {[
            { color: COLOR_KW,  label: 'Mot-clé' },
            { color: COLOR_OR,  label: 'OU' },
            { color: COLOR_AND, label: 'ET' },
          ].map(({ color, label }) => (
            <span key={label} className="inline-flex items-center gap-1 text-[10px] text-slate-500 dark:text-slate-400 whitespace-nowrap">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
              {label}
            </span>
          ))}
        </div>

        {/* Contrôles zoom */}
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={() => applyView({ ...viewRef.current, scale: Math.max(0.15, viewRef.current.scale * 0.82) })}
            title="Dézoomer"
            className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <ZoomOut size={13} />
          </button>
          <span className="text-[10px] text-slate-400 w-10 text-center tabular-nums">{zoomPct}%</span>
          <button
            onClick={() => applyView({ ...viewRef.current, scale: Math.min(14, viewRef.current.scale * 1.22) })}
            title="Zoomer"
            className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <ZoomIn size={13} />
          </button>
          <button
            onClick={resetView}
            title="Vue initiale"
            className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <Maximize2 size={12} />
          </button>
        </div>
      </div>

      {/* ── SVG ───────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 bg-white dark:bg-slate-800/40">
        <svg
          ref={svgCallbackRef}
          viewBox={vb}
          className="w-full h-full block"
          style={{ cursor: dragState.current ? 'grabbing' : 'grab' }}
          onMouseDown={handleMouseDown}
        >
          {/* Arêtes */}
          {edges.map(([si, ti], i) => {
            if (!positions[si] || !positions[ti]) return null
            const tgt   = nodes[ti]
            const color = nodeColor(tgt)
            const isL2  = tgt.level === 2
            return (
              <line
                key={i}
                x1={positions[si].x} y1={positions[si].y}
                x2={positions[ti].x} y2={positions[ti].y}
                stroke={color}
                strokeWidth={isL2 ? 0.9 : 1.8}
                strokeOpacity={isL2 ? 0.30 : 0.50}
                strokeLinecap="round"
                strokeDasharray={isL2 ? '3 3' : undefined}
              />
            )
          })}

          {/* Nœuds */}
          {nodes.map((node, i) => {
            if (!positions[i]) return null
            const { x, y } = positions[i]
            const r      = nodeRadius(node)
            const color  = nodeColor(node)
            const isRoot = node.level === 0
            const isL2   = node.level === 2

            return (
              <g
                key={node.id}
                transform={`translate(${x},${y})`}
                style={{ cursor: 'default' }}
                onMouseEnter={e => setTooltip({ node, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setTooltip(null)}
                onMouseMove={e => tooltip && setTooltip(t => ({ ...t, x: e.clientX, y: e.clientY }))}
              >
                {/* Zone de clic élargie pour petits nœuds */}
                {!isRoot && <circle r={Math.max(r + 4, 12)} fill="transparent" />}

                <circle
                  r={r}
                  fill={color}
                  fillOpacity={isRoot ? 1 : isL2 ? 0.48 : 0.82}
                  stroke={isRoot ? '#7c3aed' : isL2 ? color : 'white'}
                  strokeWidth={isRoot ? 3 : isL2 ? 0.8 : 1.5}
                  strokeOpacity={isL2 ? 0.55 : 0.9}
                  strokeDasharray={isL2 ? '2 2' : undefined}
                />

                {/* Label dans le cercle central */}
                {isRoot && (
                  <text
                    textAnchor="middle" dominantBaseline="middle"
                    fill="white" fontSize="9.5" fontWeight="700"
                    style={{ pointerEvents: 'none' }}
                  >
                    WUDD.ai
                  </text>
                )}

                {/* Label sous les nœuds */}
                {!isRoot && (
                  <text
                    textAnchor="middle"
                    y={r + (isL2 ? 8 : 10)}
                    fontSize={isL2 ? '7' : '8.5'}
                    fill={isL2 ? '#64748b' : '#1e293b'}
                    fillOpacity={isL2 ? 0.80 : 1}
                    style={{ pointerEvents: 'none' }}
                  >
                    {node.label}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* ── Tooltip ───────────────────────────────────────────────────── */}
      {tooltip && (
        <div
          className="fixed z-[300] pointer-events-none bg-slate-900 dark:bg-slate-700 text-white rounded-xl px-3 py-2 text-xs shadow-2xl border border-slate-700"
          style={{ left: tooltip.x + 14, top: tooltip.y - 46 }}
        >
          <div className="font-semibold">{tooltip.node.label}</div>
          <div className="text-slate-300 text-[10px] mt-0.5">
            {tooltip.node.termType === 'root' ? 'Centre — WUDD.ai'
              : tooltip.node.termType === 'kw' ? 'Mot-clé de veille'
              : tooltip.node.termType === 'or' ? 'Terme OU (élargit la recherche)'
              : 'Terme ET (restreint la recherche)'}
          </div>
        </div>
      )}
    </div>
  )
}
