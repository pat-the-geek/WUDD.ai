import { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { Loader2, ZoomIn, ZoomOut, Maximize2, ChevronLeft, ChevronRight } from 'lucide-react'

// Couleurs par type NER — cohérentes avec EntityDashboard
const TYPE_CFG = {
  PERSON:      { node: '#a78bfa', label: 'Personnes' },
  ORG:         { node: '#60a5fa', label: 'Organisations' },
  GPE:         { node: '#34d399', label: 'Lieux géopol.' },
  PRODUCT:     { node: '#fb923c', label: 'Produits' },
  EVENT:       { node: '#fbbf24', label: 'Événements' },
  LAW:         { node: '#f87171', label: 'Lois' },
  LOC:         { node: '#2dd4bf', label: 'Lieux' },
  NORP:        { node: '#e879f9', label: 'Groupes' },
  FAC:         { node: '#22d3ee', label: 'Sites' },
  WORK_OF_ART: { node: '#fb7185', label: 'Œuvres' },
  MONEY:       { node: '#facc15', label: 'Montants' },
  LANGUAGE:    { node: '#818cf8', label: 'Langues' },
  DATE:        { node: '#94a3b8', label: 'Dates' },
  TIME:        { node: '#94a3b8', label: 'Heures' },
  QUANTITY:    { node: '#a8a29e', label: 'Quantités' },
  CARDINAL:    { node: '#a1a1aa', label: 'Nombres' },
  ORDINAL:     { node: '#9ca3af', label: 'Ordinaux' },
  PERCENT:     { node: '#86efac', label: 'Pourcentages' },
}
const CENTRAL_COLOR = '#8b5cf6'
const NOISE_TYPES = new Set(['DATE', 'TIME', 'CARDINAL', 'ORDINAL', 'PERCENT', 'QUANTITY'])

const W = 720
const H = 450

// ── Force layout ────────────────────────────────────────────────────────────
// nœud 0 = central (ancré fort au centre)
// nœuds L2 (level === 2) ont une répulsion plus faible → se regroupent près de leur L1
function computeLayout(nodes, edgeTriples, kFactor = 1.0) {
  const n = nodes.length
  if (n <= 1) return [{ x: W / 2, y: H / 2 }]

  // Init : central au centre, L1 sur un cercle, L2 sur un cercle plus grand
  const pos = nodes.map((node, i) => {
    if (i === 0) return { x: W / 2, y: H / 2, vx: 0, vy: 0 }
    const level = node.level ?? 1
    const peers = nodes.filter((nd, j) => j > 0 && (nd.level ?? 1) === level)
    const idx = peers.indexOf(node)
    const angle = (2 * Math.PI * idx) / Math.max(peers.length, 1)
    const r = level === 2 ? Math.min(W, H) * 0.66 : Math.min(W, H) * 0.42
    return {
      x: W / 2 + r * Math.cos(angle),
      y: H / 2 + r * Math.sin(angle),
      vx: 0,
      vy: 0,
    }
  })

  const k = Math.sqrt((W * H) / n) * 0.90 * kFactor
  const ITERS = 240

  for (let it = 0; it < ITERS; it++) {
    const temp = Math.max(0.35, 7 * (1 - it / ITERS))
    const fx = new Float32Array(n)
    const fy = new Float32Array(n)

    // Répulsion
    for (let i = 0; i < n; i++) {
      const ri = (nodes[i].level ?? 1) === 2 ? 0.7 : 1.0  // L2 répulsion réduite
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i].x - pos[j].x
        const dy = pos[i].y - pos[j].y
        const d2 = Math.max(dx * dx + dy * dy, 1)
        const d = Math.sqrt(d2)
        const rj = (nodes[j].level ?? 1) === 2 ? 0.7 : 1.0
        const f = (k * k * ri * rj) / d2
        fx[i] += (dx / d) * f; fy[i] += (dy / d) * f
        fx[j] -= (dx / d) * f; fy[j] -= (dy / d) * f
      }
    }

    // Attraction le long des arêtes
    for (const [si, ti, w] of edgeTriples) {
      const dx = pos[ti].x - pos[si].x
      const dy = pos[ti].y - pos[si].y
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01
      const ideal = k * 0.72 / Math.log(w + 2)
      const f = (d - ideal) * 0.22
      fx[si] += (dx / d) * f; fy[si] += (dy / d) * f
      fx[ti] -= (dx / d) * f; fy[ti] -= (dy / d) * f
    }

    // Gravité (forte pour le central)
    for (let i = 0; i < n; i++) {
      fx[i] += (W / 2 - pos[i].x) * (i === 0 ? 0.15 : 0.022)
      fy[i] += (H / 2 - pos[i].y) * (i === 0 ? 0.15 : 0.022)
    }

    // Intégration
    for (let i = 0; i < n; i++) {
      pos[i].vx = (pos[i].vx + fx[i]) * 0.62
      pos[i].vy = (pos[i].vy + fy[i]) * 0.62
      const mag = Math.sqrt(pos[i].vx ** 2 + pos[i].vy ** 2) || 0.01
      const disp = Math.min(mag, temp)
      pos[i].x += (pos[i].vx / mag) * disp
      pos[i].y += (pos[i].vy / mag) * disp
      pos[i].x = Math.max(58, Math.min(W - 58, pos[i].x))
      pos[i].y = Math.max(28, Math.min(H - 28, pos[i].y))
    }
  }

  return pos.map(p => ({ x: p.x, y: p.y }))
}

// ── Composant principal ─────────────────────────────────────────────────────
/**
 * EntityGraph — graphe SVG force-directed des co-occurrences d'une entité.
 *
 * Props:
 *   entityType  {string}       — type NER du nœud central
 *   entityValue {string}       — valeur du nœud central
 *   onNavigate  {fn(type,val)} — appelé au clic sur un nœud non-central
 */
export default function EntityGraph({ entityType, entityValue, onNavigate }) {
  const [data, setData]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [showNoise, setShowNoise] = useState(false)
  const [depth, setDepth]       = useState(1)     // 1 ou 2
  const [spacing, setSpacing]   = useState(1.0)   // facteur d'espacement
  const [tooltip, setTooltip]   = useState(null)
  // Taille proportionnelle au nombre total d'articles + animation de révélation
  const [sizeByTotal, setSizeByTotal] = useState(true)   // ON par défaut
  const [animProgress, setAnimProgress] = useState(1)  // 0→1 pendant l'animation
  const animFrameRef = useRef(null)
  // Ordre de la légende (détermine le z-order des nœuds dans le SVG)
  const [typeOrder, setTypeOrder] = useState([])

  // ── Zoom / pan ─────────────────────────────────────────────────────────────
  // view = { x, y, scale } où (x,y) est l'origine du viewBox en coord. SVG
  const VIEW0 = { x: 0, y: 0, scale: 1 }
  const [view, setView]   = useState(VIEW0)
  const viewRef           = useRef(VIEW0)
  const svgRef            = useRef(null)
  const dragState         = useRef(null)   // { clientX, clientY, viewX, viewY, scale }
  const dragMoved         = useRef(false)

  const applyView = useCallback((next) => {
    viewRef.current = next
    setView(next)
  }, [])

  const resetView = useCallback(() => applyView(VIEW0), [applyView])

  // Handler de zoom — stable (utilise uniquement des refs)
  const wheelHandler = useCallback((e) => {
    e.preventDefault()
    const el = svgRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const v = viewRef.current
    const cssX = e.clientX - rect.left
    const cssY = e.clientY - rect.top
    const svgX = v.x + (cssX / rect.width)  * (W / v.scale)
    const svgY = v.y + (cssY / rect.height) * (H / v.scale)
    const factor = e.deltaY < 0 ? 1.08 : 0.93
    const newScale = Math.max(0.2, Math.min(12, v.scale * factor))
    applyView({
      x: svgX - (cssX / rect.width)  * (W / newScale),
      y: svgY - (cssY / rect.height) * (H / newScale),
      scale: newScale,
    })
  }, [applyView])

  // ── Handlers tactiles (pinch-to-zoom + drag 1 doigt) ─────────────────────
  const touchState = useRef(null)

  const touchStartHandler = useCallback((e) => {
    if (e.touches.length === 2) {
      // Pinch — empêche le zoom natif du navigateur
      e.preventDefault()
      const v = viewRef.current
      const t0 = e.touches[0], t1 = e.touches[1]
      const ddx = t0.clientX - t1.clientX, ddy = t0.clientY - t1.clientY
      touchState.current = {
        type: 'pinch',
        startDist: Math.sqrt(ddx * ddx + ddy * ddy),
        startScale: v.scale,
        startViewX: v.x,
        startViewY: v.y,
        midX: (t0.clientX + t1.clientX) / 2,
        midY: (t0.clientY + t1.clientY) / 2,
      }
    } else if (e.touches.length === 1) {
      // Drag — pas de preventDefault → le tap génère toujours un click
      dragMoved.current = false
      const v = viewRef.current
      touchState.current = {
        type: 'drag',
        startX: e.touches[0].clientX,
        startY: e.touches[0].clientY,
        viewX: v.x, viewY: v.y, scale: v.scale,
      }
    }
  }, [])

  const touchMoveHandler = useCallback((e) => {
    const ts = touchState.current
    if (!ts) return
    const el = svgRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()

    if (ts.type === 'drag' && e.touches.length === 1) {
      const dx = e.touches[0].clientX - ts.startX
      const dy = e.touches[0].clientY - ts.startY
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        e.preventDefault()
        dragMoved.current = true
        applyView({
          x: ts.viewX - (dx / rect.width)  * (W / ts.scale),
          y: ts.viewY - (dy / rect.height) * (H / ts.scale),
          scale: ts.scale,
        })
      }
    } else if (ts.type === 'pinch' && e.touches.length === 2) {
      e.preventDefault()
      const t0 = e.touches[0], t1 = e.touches[1]
      const ddx = t0.clientX - t1.clientX, ddy = t0.clientY - t1.clientY
      const newDist = Math.sqrt(ddx * ddx + ddy * ddy)
      const newScale = Math.max(0.2, Math.min(12, ts.startScale * (newDist / ts.startDist)))
      const cssX = ts.midX - rect.left
      const cssY = ts.midY - rect.top
      const svgX = ts.startViewX + (cssX / rect.width)  * (W / ts.startScale)
      const svgY = ts.startViewY + (cssY / rect.height) * (H / ts.startScale)
      applyView({
        x: svgX - (cssX / rect.width)  * (W / newScale),
        y: svgY - (cssY / rect.height) * (H / newScale),
        scale: newScale,
      })
    }
  }, [applyView])

  const touchEndHandler = useCallback(() => { touchState.current = null }, [])

  // Callback ref : attache les listeners dès que l'élément SVG existe dans le DOM
  const svgCallbackRef = useCallback((el) => {
    if (svgRef.current) {
      svgRef.current.removeEventListener('wheel', wheelHandler)
      svgRef.current.removeEventListener('touchstart', touchStartHandler)
      svgRef.current.removeEventListener('touchmove', touchMoveHandler)
      svgRef.current.removeEventListener('touchend', touchEndHandler)
      svgRef.current.removeEventListener('touchcancel', touchEndHandler)
    }
    svgRef.current = el
    if (el) {
      el.addEventListener('wheel', wheelHandler, { passive: false })
      el.addEventListener('touchstart', touchStartHandler, { passive: false })
      el.addEventListener('touchmove', touchMoveHandler, { passive: false })
      el.addEventListener('touchend', touchEndHandler, { passive: true })
      el.addEventListener('touchcancel', touchEndHandler, { passive: true })
    }
  }, [wheelHandler, touchStartHandler, touchMoveHandler, touchEndHandler])

  // Drag → pan (listeners document pour suivre hors du SVG)
  useEffect(() => {
    const onMove = (e) => {
      if (!dragState.current) return
      const rect = svgRef.current?.getBoundingClientRect()
      if (!rect) return
      const s = dragState.current
      if (
        Math.abs(e.clientX - s.clientX) > 3 ||
        Math.abs(e.clientY - s.clientY) > 3
      ) dragMoved.current = true
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

  const handleSvgMouseDown = (e) => {
    if (e.button !== 0) return
    dragMoved.current = false
    const v = viewRef.current
    dragState.current = {
      clientX: e.clientX, clientY: e.clientY,
      viewX: v.x, viewY: v.y, scale: v.scale,
    }
  }

  // ── Données ────────────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true)
    setError(null)
    setData(null)
    setSpacing(1.0)    // reset espacement à chaque nouvelle entité
    applyView(VIEW0)   // reset zoom à chaque nouvelle entité
    setTypeOrder([])   // reset ordre légende
    const params = new URLSearchParams({
      type: entityType, value: entityValue, depth, limit: 40, limit_l2: 4,
    })
    fetch(`/api/entities/cooccurrences?${params}`)
      .then(r => r.json())
      .then(d => { if (d.error) throw new Error(d.error); setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [entityType, entityValue, depth, applyView])

  // ── Animation de révélation des tailles proportionnelles ──────────────────
  // Quand on active sizeByTotal ou qu'on charge un nouveau graphe en mode total,
  // les nœuds grandissent progressivement de leur taille de base vers leur taille cible.
  useEffect(() => {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
    if (!sizeByTotal || !data) { setAnimProgress(1); return }
    setAnimProgress(0)
    const start = performance.now()
    const DURATION = 700
    const animate = (now) => {
      const p = Math.min(1, (now - start) / DURATION)
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - p, 3)
      setAnimProgress(eased)
      if (p < 1) animFrameRef.current = requestAnimationFrame(animate)
    }
    animFrameRef.current = requestAnimationFrame(animate)
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current) }
  }, [sizeByTotal, data])

  // ── Layout ─────────────────────────────────────────────────────────────────
  const { nodes, edges, positions, nodeIndex } = useMemo(() => {
    if (!data) return { nodes: [], edges: [], positions: [], nodeIndex: {} }

    const filtered = data.nodes.filter(n => n.central || showNoise || !NOISE_TYPES.has(n.type))
    const idx = {}
    filtered.forEach((n, i) => { idx[`${n.type}:${n.value}`] = i })

    const filteredEdges = data.edges.filter(
      e => idx[e.source] !== undefined && idx[e.target] !== undefined
    )
    const edgeTriples = filteredEdges.map(e => [idx[e.source], idx[e.target], e.weight])
    const positions = computeLayout(filtered, edgeTriples, spacing)

    return { nodes: filtered, edges: filteredEdges, positions, nodeIndex: idx }
  }, [data, showNoise, spacing])

  // ── Métriques visuelles ────────────────────────────────────────────────────
  const maxWeight  = edges.length  > 0 ? Math.max(...edges.map(e => e.weight)) : 1
  const maxCountL1 = nodes.filter(n => n.level === 1).reduce((m, n) => Math.max(m, n.count), 1)
  const maxTotal   = nodes.filter(n => !n.central).reduce((m, n) => Math.max(m, n.total_count ?? 0), 1)

  const nodeRadius = n => {
    if (n.central) return 22
    if (sizeByTotal) {
      // Échelle logarithmique pour bien différencier les entités rares vs dominantes
      const logVal = Math.log1p(n.total_count ?? 0)
      const logMax = Math.log1p(maxTotal)
      const t = logMax > 0 ? logVal / logMax : 0
      const targetR = n.level === 2 ? 4 + t * 12 : 5 + t * 22
      const baseR   = n.level === 2 ? 4 : 5
      return baseR + (targetR - baseR) * animProgress
    }
    if (n.level === 2) return 5 + (n.count / maxCountL1) * 6
    return 7 + (n.count / maxCountL1) * 13
  }

  // ── Ordre de la légende (initialisation + mise à jour) ─────────────────────
  const presentTypes = useMemo(
    () => [...new Set(nodes.filter(n => !n.central).map(n => n.type))],
    [nodes]
  )
  // Fusionne l'ordre utilisateur avec les types effectivement présents
  const orderedTypes = useMemo(() => {
    const known  = typeOrder.filter(t => presentTypes.includes(t))
    const newTypes = presentTypes.filter(t => !typeOrder.includes(t))
    return [...known, ...newTypes]
  }, [typeOrder, presentTypes])

  // Tri des nœuds pour le rendu SVG : typeOrder[0] = dernière couche = au dessus
  const nodesForRender = useMemo(() => {
    return [...nodes].sort((a, b) => {
      if (a.central) return 1   // central toujours au-dessus de tout
      if (b.central) return -1
      const ai = orderedTypes.indexOf(a.type)
      const bi = orderedTypes.indexOf(b.type)
      // Plus l'index est BAS dans orderedTypes, plus le nœud est en haut → rendu en dernier
      // Donc : index élevé → rendu en premier (en dessous)
      return bi - ai
    })
  }, [nodes, orderedTypes])

  // Déplacement dans la légende via boutons ◀ ▶
  const moveLegendType = (type, dir) => {
    setTypeOrder(() => {
      const order = [...orderedTypes]
      const i = order.indexOf(type)
      if (i === -1) return order
      const j = i + dir
      if (j < 0 || j >= order.length) return order
      const next = [...order]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }
  const edgeOpacity = (e, _srcNode, tgtNode) => {
    const base = (tgtNode?.level ?? 1) === 2 ? 0.12 : 0.15
    return base + (e.weight / maxWeight) * 0.50
  }
  const edgeWidth = (e, tgtNode) => {
    const max = (tgtNode?.level ?? 1) === 2 ? 2 : 4.5
    return Math.max(0.8, (e.weight / maxWeight) * max)
  }

  // ── Rendu ──────────────────────────────────────────────────────────────────
  if (loading) return (
    <div className="flex-1 flex items-center justify-center gap-2 text-slate-400 dark:text-slate-500">
      <Loader2 size={18} className="animate-spin" />
      <span className="text-sm">Calcul des relations…</span>
    </div>
  )
  if (error) return (
    <div className="flex-1 flex items-center justify-center text-red-500 dark:text-red-400 text-sm">{error}</div>
  )
  if (nodes.length <= 1) return (
    <div className="flex-1 flex items-center justify-center text-slate-400 dark:text-slate-500 text-sm">
      Aucune entité co-occurrente trouvée pour <strong>{entityValue}</strong>.
    </div>
  )

  const nL1 = nodes.filter(n => n.level === 1).length
  const nL2 = nodes.filter(n => n.level === 2).length
  const zoomPct = Math.round(view.scale * 100)

  // ViewBox dynamique pour zoom/pan
  const vb = `${view.x} ${view.y} ${W / view.scale} ${H / view.scale}`

  return (
    <div className="flex flex-col h-full min-h-0">

      {/* ══ Barre 1 : contrôles principaux (jamais wrap, scroll horizontal) ══ */}
      <div className="flex items-center gap-2 mb-1 px-1 shrink-0 select-none overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
        <span className="text-[11px] text-slate-500 dark:text-slate-400 whitespace-nowrap shrink-0">
          {nL1} L1{nL2 > 0 && <> · {nL2} L2</>} · {edges.length} liens
        </span>

        {/* Profondeur */}
        <div className="flex shrink-0 rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden text-[11px]">
          <button onClick={() => setDepth(1)}
            className={`px-2 py-1 transition-colors ${depth === 1 ? 'bg-violet-500 text-white' : 'bg-white dark:bg-slate-800 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>
            Niv.1
          </button>
          <button onClick={() => setDepth(2)}
            className={`px-2 py-1 transition-colors border-l border-slate-200 dark:border-slate-700 ${depth === 2 ? 'bg-violet-500 text-white' : 'bg-white dark:bg-slate-800 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>
            Niv.2
          </button>
        </div>

        {/* Dates/nombres */}
        <label className="flex shrink-0 items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 cursor-pointer whitespace-nowrap">
          <input type="checkbox" checked={showNoise} onChange={e => setShowNoise(e.target.checked)} className="w-3 h-3 accent-violet-500" />
          Dates
        </label>

        {/* Taille ∝ articles */}
        <label className="flex shrink-0 items-center gap-1 text-[11px] cursor-pointer whitespace-nowrap font-medium text-violet-600 dark:text-violet-400" title="Taille ∝ nombre total d'articles (échelle log)">
          <input type="checkbox" checked={sizeByTotal} onChange={e => setSizeByTotal(e.target.checked)} className="w-3 h-3 accent-violet-500" />
          Taille ∝
        </label>

        {/* Espacement */}
        <div className="flex shrink-0 items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
          <span className="whitespace-nowrap">Liens</span>
          <input type="range" min="0.4" max="3.5" step="0.05" value={spacing}
            onChange={e => setSpacing(+e.target.value)}
            className="w-16 accent-violet-500" title={`${spacing.toFixed(1)}×`} />
        </div>

        {/* Zoom */}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <button onClick={() => applyView({ ...viewRef.current, scale: Math.max(0.2, viewRef.current.scale * 0.82) })}
            className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700">
            <ZoomOut size={13} />
          </button>
          <span className="text-[11px] text-slate-400 w-9 text-center tabular-nums">{zoomPct}%</span>
          <button onClick={() => applyView({ ...viewRef.current, scale: Math.min(12, viewRef.current.scale * 1.22) })}
            className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700">
            <ZoomIn size={13} />
          </button>
          <button onClick={resetView} title="Réinitialiser"
            className="w-6 h-6 flex items-center justify-center rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700">
            <Maximize2 size={12} />
          </button>
        </div>
      </div>

      {/* ══ Barre 2 : z-order légende (jamais wrap, scroll horizontal) ══ */}
      {orderedTypes.length > 0 && (
        <div className="flex items-center gap-1 mb-1.5 px-1 shrink-0 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
          <span className="text-[10px] font-semibold text-violet-500 dark:text-violet-400 whitespace-nowrap shrink-0 mr-0.5" title="z-order : 1er = par dessus les autres">z↑</span>
          {orderedTypes.map((type, idx) => (
            <span key={type} className="inline-flex shrink-0 items-center rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 shadow-sm overflow-hidden">
              <button
                onMouseDown={e => { e.preventDefault(); e.stopPropagation(); moveLegendType(type, -1) }}
                disabled={idx === 0}
                className="w-5 h-6 flex items-center justify-center text-slate-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/40 disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
                title="Vers le dessus"
              >
                <ChevronLeft size={12} />
              </button>
              <span className="flex items-center gap-1 px-1 py-0.5 text-[11px] text-slate-600 dark:text-slate-300 whitespace-nowrap">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: TYPE_CFG[type]?.node ?? '#94a3b8' }} />
                {TYPE_CFG[type]?.label ?? type}
              </span>
              <button
                onMouseDown={e => { e.preventDefault(); e.stopPropagation(); moveLegendType(type, 1) }}
                disabled={idx === orderedTypes.length - 1}
                className="w-5 h-6 flex items-center justify-center text-slate-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/40 disabled:opacity-20 disabled:cursor-not-allowed transition-colors"
                title="Vers le dessous"
              >
                <ChevronRight size={12} />
              </button>
            </span>
          ))}
          {depth === 2 && nL2 > 0 && (
            <span className="text-[11px] text-slate-400 whitespace-nowrap shrink-0 ml-1">● L1 ╌ L2</span>
          )}
        </div>
      )}

      {/* ══ Graphe SVG ══ */}
      <div className="flex-1 min-h-0 bg-white dark:bg-slate-800/40 border border-slate-200 dark:border-slate-700/60 rounded-xl overflow-hidden">
        <svg
          ref={svgCallbackRef}
          viewBox={vb}
          className="w-full h-full block select-none"
          style={{ cursor: dragState.current ? 'grabbing' : 'grab' }}
          onMouseDown={handleSvgMouseDown}
        >
          {/* Arêtes */}
          {edges.map((edge, i) => {
            const si = nodeIndex[edge.source]
            const ti = nodeIndex[edge.target]
            if (si === undefined || ti === undefined || !positions[si] || !positions[ti]) return null
            const tgtNode = nodes[ti]
            const color = TYPE_CFG[tgtNode?.type]?.node ?? '#94a3b8'
            const isL2edge = (tgtNode?.level ?? 1) === 2
            return (
              <line key={i}
                x1={positions[si].x} y1={positions[si].y}
                x2={positions[ti].x} y2={positions[ti].y}
                stroke={color}
                strokeWidth={edgeWidth(edge, tgtNode)}
                strokeOpacity={edgeOpacity(edge, nodes[si], tgtNode)}
                strokeLinecap="round"
                strokeDasharray={isL2edge ? '3 3' : undefined}
              />
            )
          })}

          {/* Nœuds — ordre z selon la légende */}
          {nodesForRender.map((node) => {
            const i = nodes.indexOf(node)
            if (!positions[i]) return null
            const { x, y } = positions[i]
            const r = nodeRadius(node)
            const color = node.central ? CENTRAL_COLOR : (TYPE_CFG[node.type]?.node ?? '#94a3b8')
            const isL2 = (node.level ?? 1) === 2
            const label = node.value.length > (isL2 ? 11 : 15)
              ? node.value.slice(0, isL2 ? 10 : 14) + '…'
              : node.value
            return (
              <g key={i} transform={`translate(${x},${y})`}
                style={{ cursor: node.central ? 'default' : 'pointer' }}
                onClick={() => { if (!dragMoved.current && !node.central) onNavigate(node.type, node.value) }}
                onMouseEnter={e => setTooltip({ node, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setTooltip(null)}
                onMouseMove={e => tooltip && setTooltip(t => ({ ...t, x: e.clientX, y: e.clientY }))}
              >
                {!node.central && <circle r={Math.max(r + 5, 14)} fill="transparent" />}
                <circle r={r} fill={color}
                  fillOpacity={node.central ? 1 : isL2 ? 0.55 : 0.82}
                  stroke={node.central ? '#7c3aed' : isL2 ? color : 'white'}
                  strokeWidth={node.central ? 3 : isL2 ? 1 : 1.5}
                  strokeOpacity={isL2 ? 0.6 : 0.9}
                  strokeDasharray={isL2 ? '2 2' : undefined}
                />
                {node.central && (
                  <text textAnchor="middle" dominantBaseline="middle"
                    fill="white" fontSize="8.5" fontWeight="700" style={{ pointerEvents: 'none' }}>
                    {node.value.length > 12 ? node.value.slice(0, 11) + '…' : node.value}
                  </text>
                )}
                {!node.central && (
                  <text textAnchor="middle" y={r + 9}
                    fontSize={isL2 ? '7.5' : '8.5'}
                    fill={isL2 ? '#64748b' : '#374151'}
                    fillOpacity={isL2 ? 0.75 : 1}
                    style={{ pointerEvents: 'none' }}>
                    {label}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div className="fixed z-[200] pointer-events-none bg-slate-900 dark:bg-slate-700 text-white rounded-xl px-3 py-2 text-xs shadow-2xl border border-slate-700"
          style={{ left: tooltip.x + 14, top: tooltip.y - 48 }}>
          <div className="font-semibold">{tooltip.node.value}</div>
          <div className="text-slate-400 text-[11px] mt-0.5">
            {TYPE_CFG[tooltip.node.type]?.label ?? tooltip.node.type}
            {!tooltip.node.central && (
              <> · <span className="text-violet-300">
                {sizeByTotal
                  ? <>{tooltip.node.total_count ?? 0} art. total</>
                  : <>{tooltip.node.count} art. en commun</>
                }
              </span></>
            )}
          </div>
          {!tooltip.node.central && <div className="text-slate-400 text-[11px] mt-0.5">Clic → explorer</div>}
        </div>
      )}
    </div>
  )
}
