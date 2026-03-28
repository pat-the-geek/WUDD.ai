/**
 * KnowledgeGraph.jsx — Graphe de connaissances style Obsidian.
 *
 * Nœuds :
 *   - Articles  : cercles bleus
 *   - Entités   : cercles colorés par type NER
 * Arêtes : trait gris entre chaque entité et les articles qui la mentionnent.
 *
 * Fonctionnalités :
 *   - Chargement en streaming SSE depuis /api/graph/knowledge
 *   - Simulation force-directed (répulsion + attraction) via requestAnimationFrame
 *   - Rendu Canvas haute performance
 *   - Zoom / pan à la souris
 *   - Recherche plein-texte + filtre par période
 *   - Tooltip au survol d'un nœud
 *   - Légende
 */
import { useEffect, useState, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import {
  X, Search, ZoomIn, ZoomOut, Maximize2, Minimize2,
  RefreshCw, Loader2, Network, Crosshair, ExternalLink,
  ChevronUp, ChevronDown,
} from 'lucide-react'
import ArticleFullReportDialog from './ArticleFullReportDialog'
import GraphArticlePanel from './GraphArticlePanel'
import EntityArticlePanel from './EntityArticlePanel'

// ── Couleurs par type NER ──────────────────────────────────────────────────
const TYPE_CFG = {
  PERSON:      { color: '#a78bfa', label: 'Personnes'     },
  ORG:         { color: '#60a5fa', label: 'Organisations'  },
  GPE:         { color: '#34d399', label: 'Lieux géopol.'  },
  PRODUCT:     { color: '#fb923c', label: 'Produits'       },
  EVENT:       { color: '#fbbf24', label: 'Événements'     },
  LAW:         { color: '#f87171', label: 'Lois'           },
  LOC:         { color: '#2dd4bf', label: 'Lieux'          },
  NORP:        { color: '#e879f9', label: 'Groupes'        },
  FAC:         { color: '#22d3ee', label: 'Sites'          },
  WORK_OF_ART: { color: '#fb7185', label: 'Œuvres'         },
  MONEY:       { color: '#facc15', label: 'Montants'       },
  LANGUAGE:    { color: '#818cf8', label: 'Langues'        },
  DATE:        { color: '#94a3b8', label: 'Dates'          },
  TIME:        { color: '#94a3b8', label: 'Heures'         },
  QUANTITY:    { color: '#a8a29e', label: 'Quantités'      },
  CARDINAL:    { color: '#a1a1aa', label: 'Nombres'        },
  ORDINAL:     { color: '#9ca3af', label: 'Ordinaux'       },
  PERCENT:     { color: '#86efac', label: 'Pourcentages'   },
}
const ARTICLE_COLOR  = '#3b82f6'   // blue-500
const ENTITY_DEFAULT = '#94a3b8'   // slate-400

// ── Rendu spécial : silhouette avatar pour les entités PERSON ────────────────
function drawPersonNode(ctx, x, y, r, color, lw, isDark) {
  // 1. Fond coloré (cercle complet)
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.globalAlpha = 0.92
  ctx.fill()
  ctx.globalAlpha = 1.0

  // 2. Silence des formes internes clippées au cercle
  ctx.save()
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.clip()

  const avatarColor = isDark ? 'rgba(255,255,255,0.88)' : 'rgba(255,255,255,0.95)'

  // Tête
  const headR = r * 0.30
  const headY = y - r * 0.18
  ctx.beginPath()
  ctx.arc(x, headY, headR, 0, Math.PI * 2)
  ctx.fillStyle = avatarColor
  ctx.fill()

  // Épaules (grand cercle positionné bas)
  const shoulderR = r * 0.58
  const shoulderY = y + r * 0.82
  ctx.beginPath()
  ctx.arc(x, shoulderY, shoulderR, 0, Math.PI * 2)
  ctx.fillStyle = avatarColor
  ctx.fill()

  ctx.restore()

  // 3. Contour
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.15)'
  ctx.lineWidth = lw
  ctx.stroke()
}

// Rayon des cercles
const R_ARTICLE = 9
const R_ENTITY  = 6

// ── Simulation force-directed ──────────────────────────────────────────────

/**
 * Avance d'un pas la simulation de Fruchterman-Reingold.
 *
 * Stratégie anti-superposition à deux couches :
 *   1. Répulsion FR radius-aware (distance surface-à-surface) — évite les
 *      approches dangereuses avant qu'elles ne surviennent.
 *   2. Correction de position directe PBD (Position-Based Dynamics) —
 *      après l'intégration, sépare géométriquement les paires encore
 *      superposées, 3 itérations, indépendamment de la température.
 *
 * @param {object[]} nodes   — [{id, x, y, vx, vy, r, pinned?}]
 * @param {number[][]} edges — [[si, ti], ...]  (indices dans nodes)
 * @param {number} W / H     — dimensions du canvas
 * @param {number} temp      — température (refroidissement)
 */
function stepForce(nodes, edges, W, H, temp, linkMult = 1.2) {
  const n   = nodes.length
  if (n === 0) return
  const k   = Math.sqrt((W * H) / Math.max(n, 1)) * 0.85
  const fx  = new Float32Array(n)
  const fy  = new Float32Array(n)

  // ── 1. Répulsion O(n²) radius-aware ─────────────────────────────────────
  // Utilise la distance surface-à-surface (dSurf) et un kEff élargi
  // proportionnellement aux rayons → les gros nœuds repoussent plus loin.
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx    = nodes[i].x - nodes[j].x
      const dy    = nodes[i].y - nodes[j].y
      const d     = Math.sqrt(dx * dx + dy * dy) || 0.01
      const ri    = nodes[i].r
      const rj    = nodes[j].r
      const kEff  = k + (ri + rj) * 0.5
      // distance libre entre surfaces — plancher à 1 pour éviter /0
      const dSurf = Math.max(d - ri - rj, 1)
      const f     = (kEff * kEff) / (dSurf * dSurf)
      const nx    = (dx / d) * f
      const ny    = (dy / d) * f
      fx[i] += nx;  fy[i] += ny
      fx[j] -= nx;  fy[j] -= ny
    }
  }

  // ── 2. Attraction sur les arêtes ─────────────────────────────────────────
  // La longueur idéale tient compte des deux rayons pour que deux gros nœuds
  // connectés restent naturellement plus éloignés.
  for (const [si, ti] of edges) {
    const dx    = nodes[ti].x - nodes[si].x
    const dy    = nodes[ti].y - nodes[si].y
    const d     = Math.sqrt(dx * dx + dy * dy) || 0.01
    const ri    = nodes[si].r
    const rj    = nodes[ti].r
    const ideal = k * linkMult + (ri + rj) * 0.8
    const f     = (d - ideal) * 0.25
    const nx    = (dx / d) * f
    const ny    = (dy / d) * f
    fx[si] += nx;  fy[si] += ny
    fx[ti] -= nx;  fy[ti] -= ny
  }

  // ── 3. Gravité vers le centre ────────────────────────────────────────────
  // Valeur réduite (0.009) pour laisser les nœuds occuper plus d'espace.
  const cx = W / 2
  const cy = H / 2
  for (let i = 0; i < n; i++) {
    fx[i] += (cx - nodes[i].x) * 0.009
    fy[i] += (cy - nodes[i].y) * 0.009
  }

  // ── 4. Intégration + amortissement ──────────────────────────────────────
  for (let i = 0; i < n; i++) {
    if (nodes[i].pinned) continue
    nodes[i].vx = (nodes[i].vx + fx[i]) * 0.6
    nodes[i].vy = (nodes[i].vy + fy[i]) * 0.6
    const mag   = Math.sqrt(nodes[i].vx ** 2 + nodes[i].vy ** 2) || 0.01
    const disp  = Math.min(mag, temp)
    nodes[i].x += (nodes[i].vx / mag) * disp
    nodes[i].y += (nodes[i].vy / mag) * disp
    const pad   = nodes[i].r + 4
    nodes[i].x  = Math.max(pad, Math.min(W - pad, nodes[i].x))
    nodes[i].y  = Math.max(pad, Math.min(H - pad, nodes[i].y))
  }

  // ── 5. Correction de position PBD (Position-Based Dynamics) ─────────────
  // Après l'intégration, on sépare directement les paires superposées.
  // 3 itérations convergent bien même pour les clusters denses.
  // Indépendant de la température : garantit qu'il n'y a plus de superposition
  // même quand temp → 0 et que les forces deviennent insuffisantes.
  const GAP = 4  // marge minimale entre surfaces (px)
  for (let iter = 0; iter < 3; iter++) {
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (nodes[i].pinned && nodes[j].pinned) continue
        const dx   = nodes[i].x - nodes[j].x
        const dy   = nodes[i].y - nodes[j].y
        const d    = Math.sqrt(dx * dx + dy * dy) || 0.01
        const minD = nodes[i].r + nodes[j].r + GAP
        if (d < minD) {
          // Chevauchement → pousse chaque nœud d'une demi-correction
          const push = (minD - d) * 0.5
          const nx   = (dx / d) * push
          const ny   = (dy / d) * push
          if (!nodes[i].pinned) { nodes[i].x += nx; nodes[i].y += ny }
          if (!nodes[j].pinned) { nodes[j].x -= nx; nodes[j].y -= ny }
        }
      }
    }
    // Reclamper aux bords après chaque passe PBD
    for (let i = 0; i < n; i++) {
      const pad = nodes[i].r + 4
      nodes[i].x = Math.max(pad, Math.min(W - pad, nodes[i].x))
      nodes[i].y = Math.max(pad, Math.min(H - pad, nodes[i].y))
    }
  }
}

// ── Composant principal ────────────────────────────────────────────────────

export default function KnowledgeGraph({ onClose }) {
  // ── Filtres ──────────────────────────────────────────────────────────────
  // Dates en heure locale (évite le décalage UTC)
  const localDate = (offset = 0) => {
    const d = new Date()
    d.setDate(d.getDate() + offset)
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  const today       = localDate(0)
  const yesterday   = localDate(-1)
  const [search,    setSearch]   = useState('')
  const [dateFrom,  setDateFrom] = useState(yesterday)
  const [dateTo,    setDateTo]   = useState(today)
  const [searchBuf, setSearchBuf] = useState('') // champ non-committée
  const [articleQuery, setArticleQuery] = useState('')
  const [articleQueryBuf, setArticleQueryBuf] = useState('')
  const [loadAll,   setLoadAll]   = useState(false) // mode "tout charger"
  const [selectedEntityKeys, setSelectedEntityKeys] = useState(new Set())
  const selectedEntityKeysRef = useRef(new Set())
  useEffect(() => { selectedEntityKeysRef.current = selectedEntityKeys }, [selectedEntityKeys])

  // ── Autocomplétion entités ──────────────────────────────────────────────────
  // suggestions : [{value, type, count}]
  const [suggestions,    setSuggestions]    = useState([])
  const [suggestImages,  setSuggestImages]  = useState({}) // name => {url}
  const [showSuggestions, setShowSuggestions] = useState(false)
  const suggestAbortRef     = useRef(null)
  const searchContainerRef  = useRef(null)
  const [dropdownPos, setDropdownPos] = useState(null) // {top, left, width} en px fixed

  const openSuggestDropdown = useCallback(() => {
    if (!searchContainerRef.current) return
    const r = searchContainerRef.current.getBoundingClientRect()
    setDropdownPos({ top: r.bottom + 4, left: r.left, width: Math.max(288, r.width) })
    setShowSuggestions(true)
  }, [])

  useEffect(() => {
    const q = searchBuf.trim()
    if (q.length < 1) { setSuggestions([]); setShowSuggestions(false); return }
    // Debounce 250 ms
    const timer = setTimeout(async () => {
      suggestAbortRef.current?.abort()
      const ctrl = new AbortController()
      suggestAbortRef.current = ctrl
      try {
        const res = await fetch(`/api/entities/search?q=${encodeURIComponent(q)}`, { signal: ctrl.signal })
        if (!res.ok) return
        const data = await res.json()
        const flat = []
        for (const t of (data.by_type ?? [])) {
          for (const item of (t.top ?? [])) {
            flat.push({ value: item.value, type: t.type, count: item.count })
          }
        }
        flat.sort((a, b) => b.count - a.count)
        const top = flat.slice(0, 20)
        setSuggestions(top)
        setShowSuggestions(false) // sera rouvert via openSuggestDropdown si focus
        if (top.length > 0 && document.activeElement === searchContainerRef.current?.querySelector('input')) {
          openSuggestDropdown()
        }
        // Charge les images en arrière-plan
        if (top.length > 0) {
          const imgRes = await fetch('/api/entities/images', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(top.map(s => ({ name: s.value, type: s.type }))),
            signal: ctrl.signal,
          })
          if (imgRes.ok) {
            const imgs = await imgRes.json()
            setSuggestImages(imgs)
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') console.error(err)
      }
    }, 250)
    return () => clearTimeout(timer)
  }, [searchBuf])

  // ── Autocomplétion articles (filtre titre/résumé) ────────────────────────────
  // Suggestions calcées client-side depuis les nœuds déjà chargés dans le graphe.
  // articleSuggestions : [{source, resume, url, excerpt}]
  const [articleSuggestions,     setArticleSuggestions]     = useState([])
  const [showArticleSuggestions, setShowArticleSuggestions] = useState(false)
  const [articleDropdownPos,     setArticleDropdownPos]     = useState(null)
  const articleContainerRef = useRef(null)
  const openArticleDropdown = useCallback(() => {
    if (!articleContainerRef.current) return
    const r = articleContainerRef.current.getBoundingClientRect()
    setArticleDropdownPos({ top: r.bottom + 4, left: r.left, width: Math.max(320, r.width) })
    setShowArticleSuggestions(true)
  }, [])

  useEffect(() => {
    const q = articleQueryBuf.trim().toLowerCase()
    if (q.length < 1) { setArticleSuggestions([]); setShowArticleSuggestions(false); return }
    const nodes = nodesArrRef.current.filter(n => n.kind === 'article')
    if (nodes.length === 0) { setArticleSuggestions([]); setShowArticleSuggestions(false); return }
    const matches = []
    for (const n of nodes) {
      const resume = n.resume ?? ''
      const source = n.source ?? ''
      const pos = resume.toLowerCase().indexOf(q)
      if (pos === -1) continue
      // Extrait centré sur la correspondance (~80 caractères)
      const start   = Math.max(0, pos - 30)
      const end     = Math.min(resume.length, pos + q.length + 50)
      const excerpt = (start > 0 ? '…' : '') + resume.slice(start, end) + (end < resume.length ? '…' : '')
      const posInExcerpt = excerpt.indexOf(resume.slice(pos, pos + q.length))
      matches.push({ source, resume, url: n.url, excerpt, matchStart: start > 0 ? pos - start + 1 : pos, matchLen: q.length })
      if (matches.length >= 15) break
    }
    setArticleSuggestions(matches)
    if (matches.length > 0) openArticleDropdown()
    else setShowArticleSuggestions(false)
  }, [articleQueryBuf, openArticleDropdown])

  // ── État de chargement ───────────────────────────────────────────────────
  const [loading,   setLoading]  = useState(false)
  const [status,    setStatus]   = useState(
    "Entrez un mot-clé pour afficher les entités correspondantes."
  )
  const [stats,     setStats]    = useState(null) // {total_nodes, total_edges}

  // ── Vue (zoom/pan) ───────────────────────────────────────────────────────
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 })
  const viewRef = useRef({ x: 0, y: 0, scale: 1 })

  // ── Graphe (refs, pas de state pour les positions) ───────────────────────
  // nodesArr: [{id, kind, ner_type?, value?, url?, source?, date?, resume?, x, y, vx, vy, r}]
  const nodesArrRef  = useRef([])
  // edgesArr: [[si, ti], ...]  (indices dans nodesArr)
  const edgesArrRef  = useRef([])
  // nodeIndex: id -> indice dans nodesArr
  const nodeIndexRef = useRef({})

  // ── Canvas ───────────────────────────────────────────────────────────────
  const canvasRef  = useRef(null)
  const rafRef     = useRef(null)
  const tempRef    = useRef(0)    // température de simulation (0 = stoppée)
  const autoFitRef = useRef(false) // flag : fitView() à déclencher après refroidissement
  const ticksRef   = useRef(0)    // compteur d'itérations

  // ── Tooltip ──────────────────────────────────────────────────────────────
  const [tooltip, setTooltip] = useState(null) // {x, y, node}

  // ── Plein écran ──────────────────────────────────────────────────────────
  const [fullscreen, setFullscreen] = useState(false)

  // ── Drag (pan) + touch refs ──────────────────────────────────────────────
  const dragRef       = useRef(null)  // {startX, startY, ox, oy}
  const touchDistRef  = useRef(null)  // pinch {dist, scale}
  const tapRef        = useRef(null)  // tap {x, y} — position touchstart

  // ── Légende ──────────────────────────────────────────────────────────────
  const [showLegend, setShowLegend] = useState(true)

  // ── Nœud sélectionné ─────────────────────────────────────────────────────
  const [selected, setSelected] = useState(null)
  // ── Dialog rapport article ────────────────────────────────────────────
  const [reportArticle, setReportArticle] = useState(null) // { article, filePath }
  const [entityPanel,   setEntityPanel]   = useState(null) // { type, value }

  // ── Multiplicateur longueur des liens ─────────────────────────────────
  const [linkMult,   setLinkMult]   = useState(1.2)
  const linkMultRef = useRef(1.2)
  useEffect(() => { linkMultRef.current = linkMult }, [linkMult])

  // ── Taille ∝ articles + z-order ────────────────────────────────────────
  const [sizeByTotal, setSizeByTotal] = useState(true)
  const sizeByTotalRef = useRef(true)
  useEffect(() => { sizeByTotalRef.current = sizeByTotal }, [sizeByTotal])

  const [typeOrder, setTypeOrder] = useState([])
  const typeOrderRef = useRef([])
  useEffect(() => { typeOrderRef.current = typeOrder }, [typeOrder])

  const moveLegendType = useCallback((type, dir) => {
    setTypeOrder(prev => {
      const order = [...prev]
      const i = order.indexOf(type)
      if (i === -1) return order
      const j = i + dir
      if (j < 0 || j >= order.length) return order
      const next = [...order]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }, [])

  // Recalcule les rayons quand sizeByTotal est basculé
  useEffect(() => {
    const nodes = nodesArrRef.current
    if (nodes.length === 0) return
    const maxC = Math.max(...nodes.filter(n => n.kind === 'entity').map(n => n.article_count ?? 0), 1)
    for (const n of nodes) {
      if (n.kind === 'article') { n.r = R_ARTICLE; continue }
      if (sizeByTotal && (n.article_count ?? 0) > 0) {
        const t = Math.log1p(n.article_count) / Math.log1p(maxC)
        n.r = 4 + t * 36
      } else {
        n.r = R_ENTITY
      }
    }
    if (nodes.length > 0 && tempRef.current < 3) tempRef.current = 3
  }, [sizeByTotal])

  // ── Types d'entité actifs (filtre positif — envoyé au serveur) ───────────
  const ALL_NER_TYPES = ['PERSON', 'ORG', 'GPE', 'LOC', 'EVENT', 'PRODUCT', 'NORP', 'FAC', 'DATE', 'MONEY']
  const [activeTypes, setActiveTypes] = useState(new Set())
  const activeTypesRef = useRef(new Set())
  useEffect(() => { activeTypesRef.current = activeTypes }, [activeTypes])

  // ── Relations L2 : co-occurrences entité↔entité ─────────────────────────
  const [showL2, setShowL2] = useState(false)
  const showL2Ref = useRef(false)
  useEffect(() => { showL2Ref.current = showL2 }, [showL2])
  const l2EdgesArrRef = useRef([]) // arêtes entité↔entité (co-occurrence dans articles)

  // Ref stable vers la fonction load (pour appel depuis toggleType sans dépendance cyclique)
  const loadRef = useRef(null)

  const toggleType = useCallback((type) => {
    const next = new Set(activeTypesRef.current)
    if (next.has(type)) next.delete(type)
    else next.add(type)
    activeTypesRef.current = next
    setActiveTypes(new Set(next))
    // Les types servent à enrichir les articles issus des entités sélectionnées
    if (selectedEntityKeysRef.current.size > 0) {
      loadRef.current?.('articles')
    }
  }, [])

  // Calcule les arêtes L2 (co-occurrences entité↔entité via articles partagés)
  const computeL2Edges = useCallback(() => {
    if (!showL2Ref.current) {
      l2EdgesArrRef.current = []
      return
    }
    const nodes = nodesArrRef.current
    const edges = edgesArrRef.current
    // Article → liste d'indices d'entités connectées
    const artToEntities = {}
    for (const [si, ti] of edges) {
      const sNode = nodes[si]
      const tNode = nodes[ti]
      if (!sNode || !tNode) continue
      let entityIdx, artIdx
      if (sNode.kind === 'entity' && tNode.kind === 'article') {
        entityIdx = si; artIdx = ti
      } else if (sNode.kind === 'article' && tNode.kind === 'entity') {
        entityIdx = ti; artIdx = si
      } else continue
      if (!artToEntities[artIdx]) artToEntities[artIdx] = []
      artToEntities[artIdx].push(entityIdx)
    }
    // Paires uniques d'entités qui partagent au moins un article
    const l2EdgeSet = new Set()
    const l2Edges   = []
    for (const entityList of Object.values(artToEntities)) {
      for (let i = 0; i < entityList.length; i++) {
        for (let j = i + 1; j < entityList.length; j++) {
          const a   = Math.min(entityList[i], entityList[j])
          const b   = Math.max(entityList[i], entityList[j])
          const key = `${a}-${b}`
          if (!l2EdgeSet.has(key)) {
            l2EdgeSet.add(key)
            l2Edges.push([a, b])
          }
        }
      }
    }
    l2EdgesArrRef.current = l2Edges
  }, [])

  // Quand showL2 change : recalcule les arêtes L2 et relance la simulation
  useEffect(() => {
    computeL2Edges()
    if (nodesArrRef.current.length > 0) tempRef.current = Math.max(tempRef.current, 5)
  }, [showL2, computeL2Edges])

  // Calcule automatiquement le multiplicateur idéal selon densité du graphe
  const autoLinkMult = useCallback(() => {
    const n = nodesArrRef.current.length
    const e = edgesArrRef.current.length
    if (n === 0) return
    // Degré moyen : liens par nœud (2×arêtes / nœuds)
    const avgDegree = e > 0 ? (2 * e) / n : 1
    // Plus de nœuds + fort degré moyen → liens plus longs pour aérer
    // Formule : mult = 0.6 × log2(n/8+1) × sqrt(avgDegree/3 + 0.5)
    // Plafonnée entre 0.5 et 3.5
    const raw     = 0.6 * Math.log2(Math.max(n, 8) / 8 + 1) * Math.sqrt(avgDegree / 3 + 0.5)
    const clamped = Math.min(40.0, Math.max(0.5, raw))
    const v       = Math.round(clamped * 10) / 10
    setLinkMult(v)
    linkMultRef.current = v
    if (tempRef.current < 5) tempRef.current = 10  // relance la simulation
  }, [])

  // ── SSE ref pour pouvoir annuler ─────────────────────────────────────────
  const abortRef = useRef(null)

  // ── Initialise / redimensionne le canvas ─────────────────────────────────
  const containerRef = useRef(null)

  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const cont   = containerRef.current
    if (!canvas || !cont) return
    const rect = cont.getBoundingClientRect()
    canvas.width  = rect.width
    canvas.height = rect.height
  }, [])

  useEffect(() => {
    resizeCanvas()
    const obs = new ResizeObserver(resizeCanvas)
    if (containerRef.current) obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [resizeCanvas])

  // ── Dessin canvas ─────────────────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W   = canvas.width
    const H   = canvas.height
    const { x: ox, y: oy, scale } = viewRef.current
    const nodes = nodesArrRef.current
    const edges = edgesArrRef.current
    const isDark = document.documentElement.classList.contains('dark')

    ctx.clearRect(0, 0, W, H)

    // Fond
    ctx.fillStyle = isDark ? '#0f172a' : '#f8fafc'
    ctx.fillRect(0, 0, W, H)

    ctx.save()
    ctx.translate(ox, oy)
    ctx.scale(scale, scale)

    const lw = Math.max(0.3, 0.8 / scale)

    // ── Arêtes ──────────────────────────────────────────────────────────
    ctx.strokeStyle = isDark ? 'rgba(148,163,184,0.25)' : 'rgba(100,116,139,0.20)'
    ctx.lineWidth   = lw
    ctx.beginPath()
    for (const [si, ti] of edges) {
      const s = nodes[si]
      const t = nodes[ti]
      if (!s || !t) continue
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
    }
    ctx.stroke()

    // ── Arêtes L2 (co-occurrences entité↔entité) ────────────────────────────
    const l2Edges = l2EdgesArrRef.current
    if (l2Edges.length > 0) {
      ctx.save()
      ctx.strokeStyle = isDark ? 'rgba(167,139,250,0.40)' : 'rgba(124,58,237,0.28)'
      ctx.lineWidth   = lw * 1.6
      ctx.setLineDash([Math.max(2, 4 / scale), Math.max(2, 4 / scale)])
      ctx.beginPath()
      for (const [si, ti] of l2Edges) {
        const s = nodes[si]
        const t = nodes[ti]
        if (!s || !t) continue
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(t.x, t.y)
      }
      ctx.stroke()
      ctx.setLineDash([])
      ctx.restore()
    }

    // ── Nœuds (z-order : typeOrder[0] = au dessus = dessiné en dernier) ──
    const _to = typeOrderRef.current
    const drawOrder = [...nodes].sort((a, b) => {
      if (a.kind === 'article' && b.kind !== 'article') return -1
      if (b.kind === 'article' && a.kind !== 'article') return 1
      const ai = _to.indexOf(a.ner_type ?? '')
      const bi = _to.indexOf(b.ner_type ?? '')
      return bi - ai
    })
    for (const node of drawOrder) {
      const color = node.kind === 'article'
        ? ARTICLE_COLOR
        : (TYPE_CFG[node.ner_type]?.color ?? ENTITY_DEFAULT)
      const r     = node.r
      const isSelected = selected && selected.id === node.id
      const isSeed = node.kind === 'entity' && selectedEntityKeysRef.current.has(`${node.ner_type}:${node.value}`)

      // Anneau de mise en avant pour le nœud dont le nom = critère de recherche
      if (node.pinned) {
        // Halo pulsant extérieur
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 10, 0, Math.PI * 2)
        ctx.strokeStyle = `${color}55`
        ctx.lineWidth = 4 / scale
        ctx.stroke()
        // Anneau intérieur
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2)
        ctx.strokeStyle = `${color}cc`
        ctx.lineWidth = 2 / scale
        ctx.stroke()
      }

      // Halo si sélectionné
      if (isSelected) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 5, 0, Math.PI * 2)
        ctx.fillStyle = `${color}44`
        ctx.fill()
      }

      // Halo des entités pilotes (sélectionnées pour le filtrage articles)
      if (isSeed) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 7, 0, Math.PI * 2)
        ctx.strokeStyle = isDark ? 'rgba(16,185,129,0.85)' : 'rgba(5,150,105,0.9)'
        ctx.lineWidth = 2.4 / scale
        ctx.stroke()
      }

      // Cercle principal (ou silhouette pour PERSON)
      if (node.kind === 'entity' && node.ner_type === 'PERSON') {
        drawPersonNode(ctx, node.x, node.y, r, color, lw, isDark)
      } else {
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.globalAlpha = node.kind === 'entity' ? 0.85 : 1.0
        ctx.fill()
        ctx.globalAlpha = 1.0

        // Contour
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
        ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'
        ctx.lineWidth = lw
        ctx.stroke()
      }

      // Label : entités toujours visibles (petit texte sous le nœud),
      // articles visibles à partir d'un certain zoom.
      const showEntityLabel = node.kind === 'entity'
      const showArticleLabel = node.kind === 'article' && (node.pinned || scale > 1.4 || scale > 0.8)
      if (showEntityLabel || showArticleLabel) {
        const label = node.kind === 'article'
          ? (node.source || '').slice(0, 18)
          : (node.value  || '').slice(0, 24)
        if (label) {
          const fs = node.kind === 'entity'
            ? Math.max(7, Math.min(9, 8 / scale))
            : (node.pinned
              ? Math.max(10, Math.min(16, 14 / scale))
              : Math.max(7, Math.min(11, 10 / scale)))
          ctx.font      = node.pinned
            ? `bold ${fs}px system-ui, sans-serif`
            : `${fs}px system-ui, sans-serif`
          ctx.fillStyle = node.pinned
            ? color
            : (isDark ? 'rgba(226,232,240,0.92)' : 'rgba(30,41,59,0.9)')
          ctx.textAlign = 'center'
          ctx.fillText(label, node.x, node.y + r + fs + 2)
        }
      }
    }

    ctx.restore()
  }, [selected])

  // ── Boucle d'animation ────────────────────────────────────────────────────
  const animate = useCallback(() => {
    const nodes = nodesArrRef.current
    const edges = edgesArrRef.current
    const canvas = canvasRef.current

    if (tempRef.current > 0.3 && canvas) {
      const W = canvas.width
      const H = canvas.height
      // 3 itérations par frame pour vitesse/qualité
      const simEdges = showL2Ref.current && l2EdgesArrRef.current.length > 0
        ? [...edges, ...l2EdgesArrRef.current]
        : edges
      for (let i = 0; i < 3; i++) {
        stepForce(nodes, simEdges, W, H, tempRef.current, linkMultRef.current)
      }
      tempRef.current *= 0.992   // refroidissement
    } else if (autoFitRef.current && canvas && nodes.length > 0) {
      // Simulation stabilisée → ajuster la vue sur le graphe une seule fois
      autoFitRef.current = false
      fitView()
      ticksRef.current += 3
    }

    // Maintenir les nœuds pinnés (= entité correspondant au critère) au centre
    // Note : W et H sont lus ici pour être disponibles dans tous les cas
    if (canvas) {
      const W = canvas.width
      const H = canvas.height
      for (const node of nodes) {
        if (node.pinned) {
          node.x  = W / 2
          node.y  = H / 2
          node.vx = 0
          node.vy = 0
        }
      }
    }

    draw()
    rafRef.current = requestAnimationFrame(animate)
  }, [draw])

  // Démarre / arrête le RAF
  useEffect(() => {
    rafRef.current = requestAnimationFrame(animate)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [animate])

  // ── Chargement SSE ────────────────────────────────────────────────────────
  const load = useCallback((forcedMode = null, forcedKeyword = null, forcedArticleQuery = null) => {
    const keyword = (forcedKeyword ?? search).trim()
    const articleQueryNow = (forcedArticleQuery ?? articleQuery).trim()
    const activeTypesNow = activeTypesRef.current
    const selectedNow = selectedEntityKeysRef.current
    const mode = forcedMode ?? (selectedNow.size > 0 ? 'articles' : 'entities')

    if (!keyword) {
      if (abortRef.current) abortRef.current.abort()
      nodesArrRef.current  = []
      edgesArrRef.current  = []
      nodeIndexRef.current = {}
      tempRef.current      = 0
      setSelected(null)
      setTooltip(null)
      setStats(null)
      setLoading(false)
      setStatus("Entrez un mot-clé pour afficher les entités correspondantes.")
      return
    }

    if (mode === 'articles' && selectedNow.size === 0) {
      setStatus("Sélectionnez au moins une entité pour charger les articles.")
      return
    }

    // Annule un chargement précédent
    if (abortRef.current) abortRef.current.abort()

    // Vide le graphe
    nodesArrRef.current  = []
    edgesArrRef.current  = []
    nodeIndexRef.current = {}
    tempRef.current      = 0
    ticksRef.current     = 0
    setSelected(null)
    setTooltip(null)
    setStats(null)
    setLoading(true)
    setStatus('Chargement en cours…')

    const ctrl = new AbortController()
    abortRef.current = ctrl

    const params = new URLSearchParams()
    params.set('mode', mode)
    params.set('keyword', keyword)

    if (mode === 'articles') {
      if (loadAll) {
        params.set('all', 'true')
      } else {
        if (dateFrom) params.set('date_from', dateFrom)
        if (dateTo)   params.set('date_to',   dateTo)
        params.set('max_articles', '500')
      }
      params.set('selected_entities', JSON.stringify([...selectedNow]))
      if (activeTypesNow.size > 0) params.set('entity_types', [...activeTypesNow].join(','))
      if (articleQueryNow) params.set('article_query', articleQueryNow)
    }

    const url    = `/api/graph/knowledge?${params}`
    const canvas = canvasRef.current

    fetch(url, { signal: ctrl.signal })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const reader  = r.body.getReader()
        const decoder = new TextDecoder()
        let   buffer  = ''

        function readChunk() {
          reader.read().then(({ done, value }) => {
            if (done) {
              setLoading(false)
              return
            }
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() // garder l'éventuelle ligne incomplète

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue
              try {
                const ev = JSON.parse(line.slice(6))
                handleEvent(ev, canvas, keyword, mode)
              } catch { /* ignore */ }
            }
            readChunk()
          }).catch(e => {
            if (e.name !== 'AbortError') {
              setLoading(false)
              setStatus(`Erreur : ${e.message}`)
            }
          })
        }
        readChunk()
      })
      .catch(e => {
        if (e.name !== 'AbortError') {
          setLoading(false)
          setStatus(`Erreur : ${e.message}`)
        }
      })
  }, [dateFrom, dateTo, search, articleQuery, loadAll])

  // Maintient loadRef à jour pour les appels depuis toggleType
  useEffect(() => { loadRef.current = load }, [load])

  // Applique le filtre article depuis une suggestion
  const selectArticleSuggestion = useCallback((sug) => {
    setShowArticleSuggestions(false)
    // Extrait le terme tapé (preserving case depuis le champ)
    const q = articleQueryBuf.trim()
    setArticleQueryBuf(q)
    setArticleQuery(q)
    if (selectedEntityKeysRef.current.size > 0) {
      setTimeout(() => loadRef.current?.('articles', search, q), 0)
    } else {
      setTimeout(() => loadRef.current?.('entities', search, q), 0)
    }
  }, [articleQueryBuf, search])

  // Lance la recherche directement depuis une suggestion
  const selectSuggestion = useCallback((sug) => {
    setShowSuggestions(false)
    setSuggestions([])
    const kw = sug.value
    setSearchBuf(kw)
    setSearch(kw)
    setSelectedEntityKeys(new Set())
    selectedEntityKeysRef.current = new Set()
    setActiveTypes(new Set())
    activeTypesRef.current = new Set()
    setTimeout(() => loadRef.current?.('entities', kw, articleQuery), 0)
  }, [articleQuery])

  const runSearchOrReload = useCallback(() => {
    const nextKeyword = searchBuf.trim()
    const nextArticleQuery = articleQueryBuf.trim()
    const keywordChanged = nextKeyword !== search
    const articleFilterChanged = nextArticleQuery !== articleQuery
    if (keywordChanged) {
      setSearch(nextKeyword)
      setArticleQuery(nextArticleQuery)
      setSelectedEntityKeys(new Set())
      selectedEntityKeysRef.current = new Set()
      setActiveTypes(new Set())
      activeTypesRef.current = new Set()
      setTimeout(() => loadRef.current?.('entities', nextKeyword, nextArticleQuery), 0)
      return
    }
    if (articleFilterChanged) {
      setArticleQuery(nextArticleQuery)
      if (selectedEntityKeysRef.current.size > 0) {
        setTimeout(() => loadRef.current?.('articles', nextKeyword, nextArticleQuery), 0)
      } else {
        setTimeout(() => loadRef.current?.('entities', nextKeyword, nextArticleQuery), 0)
      }
      return
    }
    if (selectedEntityKeysRef.current.size > 0) {
      setTimeout(() => loadRef.current?.('articles'), 0)
    } else {
      setTimeout(() => loadRef.current?.('entities'), 0)
    }
  }, [search, searchBuf, articleQuery, articleQueryBuf])

  // Si des entités sont déjà sélectionnées, changer la plage de dates relance les articles.
  useEffect(() => {
    if (selectedEntityKeysRef.current.size > 0) {
      loadRef.current?.('articles')
    }
  }, [dateFrom, dateTo, loadAll])

  function handleEvent(ev, canvas, searchTerm = '', mode = 'articles') {
    const nodes = nodesArrRef.current
    const edges = edgesArrRef.current
    const idx   = nodeIndexRef.current
    const W     = canvas?.width  ?? 800
    const H     = canvas?.height ?? 600

    if (ev.type === 'node') {
      if (idx[ev.id] !== undefined) return  // déjà présent
      // Détecte si l'entité correspond exactement au critère de recherche
      const isMatch =
        ev.kind === 'entity' &&
        searchTerm.trim().length > 0 &&
        (ev.value || '').trim().toLowerCase() === searchTerm.trim().toLowerCase()
      const r = isMatch ? R_ENTITY * 3 : (ev.kind === 'article' ? R_ARTICLE : R_ENTITY)
      // Position initiale : centre si match, sinon cercle aléatoire
      const angle = Math.random() * Math.PI * 2
      const dist  = 80 + Math.random() * Math.min(W, H) * 0.35
      nodes.push({
        ...ev,
        r,
        pinned: isMatch,
        x: isMatch ? W / 2 : W / 2 + Math.cos(angle) * dist,
        y: isMatch ? H / 2 : H / 2 + Math.sin(angle) * dist,
        vx: 0,
        vy: 0,
      })
      idx[ev.id] = nodes.length - 1
      // Relance la simulation à chaque batch de nœuds
      if (tempRef.current < 8) tempRef.current = Math.max(tempRef.current, 8)

    } else if (ev.type === 'edge') {
      const si = idx[ev.source]
      const ti = idx[ev.target]
      if (si !== undefined && ti !== undefined) {
        edges.push([si, ti])
      }

    } else if (ev.type === 'done') {
      setLoading(false)
      setStats({ total_nodes: ev.total_nodes, total_edges: ev.total_edges })
      const nArticles  = nodes.filter(n => n.kind === 'article').length
      const nEntities  = nodes.filter(n => n.kind === 'entity').length
      const filteredTotal = ev.filtered_total ?? nArticles

      if (mode === 'entities') {
        if (nEntities === 0) {
          setSelectedEntityKeys(new Set())
          setStatus(`Aucune entité trouvée pour "${searchTerm}".`)
        } else {
          const autoSelected = new Set(
            nodes
              .filter(n => n.kind === 'entity')
              .map(n => `${n.ner_type}:${n.value}`)
          )
          selectedEntityKeysRef.current = autoSelected
          setSelectedEntityKeys(autoSelected)
          setStatus(`${nEntities} entités trouvées · chargement des articles liés…`)
          setTimeout(() => loadRef.current?.('articles'), 0)
        }
      } else if (nEntities === 0 && searchTerm.trim().length > 0) {
        const scope = loadAll
          ? 'dans toutes les données'
          : 'dans la plage de dates sélectionnée'
        setStatus(`Aucune entité trouvée pour "${searchTerm}" ${scope}. Essayez d'élargir les dates ou d'activer "Tout".`)
      } else {
        const articleLabel = filteredTotal > nArticles
          ? `${nArticles} / ${filteredTotal} articles`
          : `${nArticles} article${nArticles !== 1 ? 's' : ''}`
        const allShownHint = ev.date_limited === false && (ev.matched_total ?? 0) < 20
          ? ' · affichage complet (<20)'
          : ''
        setStatus(
          `${articleLabel} · `
          + `${nEntities} entité${nEntities !== 1 ? 's' : ''} · `
          + `${ev.total_edges} liaison${ev.total_edges !== 1 ? 's' : ''}`
          + allShownHint
        )
      }
      // Taille ∝ articles : compter les arêtes par entité pour obtenir article_count
      const degMap = {}
      for (const [si, ti] of edges) {
        const s = nodes[si]; const t = nodes[ti]
        if (s?.kind === 'entity') degMap[si] = (degMap[si] ?? 0) + 1
        if (t?.kind === 'entity') degMap[ti] = (degMap[ti] ?? 0) + 1
      }
      let maxC = 1
      for (const [i, cnt] of Object.entries(degMap)) {
        nodes[i].article_count = cnt
        if (cnt > maxC) maxC = cnt
      }
      if (sizeByTotalRef.current) {
        for (const n of nodes) {
          if (n.kind === 'article') { n.r = R_ARTICLE; continue }
          const cnt = n.article_count ?? 0
          if (cnt > 0) {
            const t = Math.log1p(cnt) / Math.log1p(maxC)
            n.r = 4 + t * 36
          }
        }
      }
      // Initialiser l'ordre de la légende avec les types présents
      const presentNerTypes = [...new Set(nodes.filter(n => n.kind === 'entity').map(n => n.ner_type))]
      setTypeOrder(prev => [
        ...prev.filter(t => presentNerTypes.includes(t)),
        ...presentNerTypes.filter(t => !prev.includes(t)),
      ])
      // Calculer les arêtes L2 si l'option est activée
      computeL2Edges()
      // Réchauffer la simulation pour la finalisation
      tempRef.current = Math.max(tempRef.current, 12)
      // Demander un auto-fit dès que la simulation sera refroidie
      autoFitRef.current = true
    }
  }

  // ── Zoom ─────────────────────────────────────────────────────────────────
  const applyView = useCallback((v) => {
    viewRef.current = v
    setView(v)
  }, [])

  const zoom = useCallback((factor, cx, cy) => {
    const v = viewRef.current
    const newScale = Math.min(8, Math.max(0.1, v.scale * factor))
    // Zoom centré sur le point (cx, cy) en coordonnées canvas
    const ratio = newScale / v.scale
    const newX  = cx - (cx - v.x) * ratio
    const newY  = cy - (cy - v.y) * ratio
    applyView({ x: newX, y: newY, scale: newScale })
  }, [applyView])

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const canvas = canvasRef.current
    const rect   = canvas?.getBoundingClientRect()
    if (!rect || !canvas) return
    const scaleX = canvas.width  / rect.width
    const scaleY = canvas.height / rect.height
    const cx = (e.clientX - rect.left) * scaleX
    const cy = (e.clientY - rect.top ) * scaleY
    zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, cx, cy)
  }, [zoom])

  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      ox: viewRef.current.x,
      oy: viewRef.current.y,
    }
  }, [])

  const handleMouseMove = useCallback((e) => {
    if (dragRef.current) {
      // Correction scaleX/scaleY pour panning exact
      const canvas = canvasRef.current
      const rect   = canvas ? canvas.getBoundingClientRect() : null
      const sX     = (canvas && rect) ? canvas.width  / rect.width  : 1
      const sY     = (canvas && rect) ? canvas.height / rect.height : 1
      const dx = (e.clientX - dragRef.current.startX) * sX
      const dy = (e.clientY - dragRef.current.startY) * sY
      applyView({
        ...viewRef.current,
        x: dragRef.current.ox + dx,
        y: dragRef.current.oy + dy,
      })
      setTooltip(null)
      return
    }

    // Hover : cherche le nœud le plus proche du curseur
    const canvas = canvasRef.current
    if (!canvas) return
    const rect  = canvas.getBoundingClientRect()
    // scaleX/scaleY : corrige toute divergence entre taille CSS et attribut canvas
    // (Flexbox peut donner des tailles CSS fractionnaires, DPR peut laisser un écart)
    const scaleX = canvas.width  / rect.width
    const scaleY = canvas.height / rect.height
    // Coordonnées CSS pour positionner le tooltip dans le DOM
    const mxCss = e.clientX - rect.left
    const myCss = e.clientY - rect.top
    // Coordonnées canvas pour la conversion monde (hit detection)
    const mx    = mxCss * scaleX
    const my    = myCss * scaleY
    const v     = viewRef.current
    const wx    = (mx - v.x) / v.scale
    const wy    = (my - v.y) / v.scale

    let best = null
    let bestDist = Infinity
    for (const node of nodesArrRef.current) {
      const d = Math.hypot(node.x - wx, node.y - wy)
      if (d < node.r + 8 && d < bestDist) {
        bestDist = d
        best = node
      }
    }

    if (best) {
      setTooltip({ x: mxCss, y: myCss, node: best })
      canvas.style.cursor = 'pointer'
    } else {
      setTooltip(null)
      canvas.style.cursor = dragRef.current ? 'grabbing' : 'grab'
    }
  }, [])

  // ── Détection de nœud à une position CSS ────────────────────────────────
  // slopCss : tolérance supplémentaire en pixels CSS (au-delà du rayon visuel)
  const getNodeAtClientPos = useCallback((clientX, clientY, slopCss = 0) => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect  = canvas.getBoundingClientRect()
    const sX    = canvas.width  / rect.width
    const sY    = canvas.height / rect.height
    const mx    = (clientX - rect.left) * sX
    const my    = (clientY - rect.top)  * sY
    const v     = viewRef.current
    const wx    = (mx - v.x) / v.scale
    const wy    = (my - v.y) / v.scale
    // Rayon de détection minimal en CSS = rayon visuel + 10px slop fixe + slopCss
    // Converti en unités-monde pour la comparaison de distance
    const BASE_SLOP_CSS = 10
    let best = null, bestDist = Infinity
    for (const node of nodesArrRef.current) {
      const hitWorld = node.r + (BASE_SLOP_CSS + slopCss) / v.scale
      const d = Math.hypot(node.x - wx, node.y - wy)
      if (d < hitWorld && d < bestDist) { bestDist = d; best = node }
    }
    return best
  }, [])

  // ── Action sur un nœud cliqué ─────────────────────────────────────────────
  const openNode = useCallback((node, modifierKey = false) => {
    if (!node) return
    if (node.kind === 'article') {
      setReportArticle({
        article: {
          'URL':                 node.url,
          'Sources':             node.source,
          'Date de publication': node.date,
          'Résumé':              node.resume,
        },
        filePath: node.file ?? '',
      })
    } else if (node.kind === 'entity') {
      if (modifierKey) {
        const key = `${node.ner_type}:${node.value}`
        const next = new Set(selectedEntityKeysRef.current)
        if (next.has(key)) { next.delete(key) } else { next.add(key) }
        selectedEntityKeysRef.current = next
        setSelectedEntityKeys(new Set(next))
        setTimeout(() => loadRef.current?.(next.size > 0 ? 'articles' : 'entities'), 0)
      } else {
        setEntityPanel({ type: node.ner_type, value: node.value })
      }
    } else {
      setSelected(node)
    }
  }, [])

  const handleMouseUp = useCallback((e) => {
    if (!dragRef.current) return
    const dx = Math.abs(e.clientX - dragRef.current.startX)
    const dy = Math.abs(e.clientY - dragRef.current.startY)
    dragRef.current = null
    if (dx < 6 && dy < 6) {
      const node = getNodeAtClientPos(e.clientX, e.clientY)
      openNode(node, e.shiftKey || e.metaKey || e.ctrlKey)
    }
  }, [getNodeAtClientPos, openNode])

  const handleMouseLeave = useCallback(() => {
    dragRef.current = null
    setTooltip(null)
  }, [])

  // ── Refs stables pour fermetures dans canvasCallbackRef ──────────────────
  const applyViewRef    = useRef(applyView)
  const getNodeAtPosRef = useRef(getNodeAtClientPos)
  const openNodeRef     = useRef(openNode)
  useEffect(() => { applyViewRef.current    = applyView },         [applyView])
  useEffect(() => { getNodeAtPosRef.current = getNodeAtClientPos }, [getNodeAtClientPos])
  useEffect(() => { openNodeRef.current     = openNode },          [openNode])

  // ── Handlers touch (callback ref — attachés synchro à l'entrée dans le DOM) ──
  // 100% touch events — les pointer events sont supprimés par preventDefault() sur iOS.
  const canvasCallbackRef = useCallback((el) => {
    if (canvasRef.current?._touchCleanup) {
      canvasRef.current._touchCleanup()
      delete canvasRef.current._touchCleanup
    }
    canvasRef.current = el
    if (!el) return

    const opt = { passive: false }

    const onTouchStart = (e) => {
      e.preventDefault()
      if (e.touches.length === 1) {
        const t = e.touches[0]
        dragRef.current       = { startX: t.clientX, startY: t.clientY, ox: viewRef.current.x, oy: viewRef.current.y }
        tapRef.current        = { x: t.clientX, y: t.clientY }
        touchDistRef.current  = null
      } else if (e.touches.length === 2) {
        const dx = e.touches[0].clientX - e.touches[1].clientX
        const dy = e.touches[0].clientY - e.touches[1].clientY
        touchDistRef.current = { dist: Math.hypot(dx, dy), scale: viewRef.current.scale }
        dragRef.current = null
        tapRef.current  = null
      }
    }

    const onTouchMove = (e) => {
      e.preventDefault()
      // Annuler le tap si le doigt bouge
      if (tapRef.current && e.touches.length === 1) {
        const t = e.touches[0]
        if (Math.abs(t.clientX - tapRef.current.x) > 10 ||
            Math.abs(t.clientY - tapRef.current.y) > 10) {
          tapRef.current = null
        }
      }
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const sX   = canvas.width  / rect.width
      const sY   = canvas.height / rect.height
      if (e.touches.length === 2 && touchDistRef.current) {
        const dx     = e.touches[0].clientX - e.touches[1].clientX
        const dy     = e.touches[0].clientY - e.touches[1].clientY
        const dist   = Math.hypot(dx, dy)
        const factor = dist / touchDistRef.current.dist
        const cx     = ((e.touches[0].clientX + e.touches[1].clientX) / 2 - rect.left) * sX
        const cy     = ((e.touches[0].clientY + e.touches[1].clientY) / 2 - rect.top)  * sY
        const newScale = Math.min(8, Math.max(0.1, touchDistRef.current.scale * factor))
        const v = viewRef.current
        const ratio = newScale / v.scale
        applyViewRef.current({ x: cx - (cx - v.x) * ratio, y: cy - (cy - v.y) * ratio, scale: newScale })
      } else if (e.touches.length === 1 && dragRef.current) {
        const t  = e.touches[0]
        const dx = (t.clientX - dragRef.current.startX) * sX
        const dy = (t.clientY - dragRef.current.startY) * sY
        applyViewRef.current({ ...viewRef.current, x: dragRef.current.ox + dx, y: dragRef.current.oy + dy })
        setTooltip(null)
      }
    }

    const onTouchEnd = (e) => {
      e.preventDefault()
      const tap = tapRef.current
      dragRef.current      = null
      tapRef.current       = null
      touchDistRef.current = null
      // Si tapRef est encore défini, le doigt n'a pas bougé → c'est un tap
      if (tap && e.changedTouches.length === 1) {
        const node = getNodeAtPosRef.current(tap.x, tap.y, 12)
        if (node) openNodeRef.current(node)
      }
    }

    el.addEventListener('touchstart', onTouchStart, opt)
    el.addEventListener('touchmove',  onTouchMove,  opt)
    el.addEventListener('touchend',   onTouchEnd,   opt)
    el._touchCleanup = () => {
      el.removeEventListener('touchstart', onTouchStart, opt)
      el.removeEventListener('touchmove',  onTouchMove,  opt)
      el.removeEventListener('touchend',   onTouchEnd,   opt)
    }
  }, []) // déps vides — toutes les fonctions appelées via des refs stables

  // ── Centrer la vue ────────────────────────────────────────────────────────
  const fitView = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || nodesArrRef.current.length === 0) return
    const nodes = nodesArrRef.current
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const n of nodes) {
      minX = Math.min(minX, n.x - n.r)
      minY = Math.min(minY, n.y - n.r)
      maxX = Math.max(maxX, n.x + n.r)
      maxY = Math.max(maxY, n.y + n.r)
    }
    const gW = maxX - minX
    const gH = maxY - minY
    const pad = 40
    const s   = Math.min(
      (canvas.width  - pad * 2) / Math.max(gW, 1),
      (canvas.height - pad * 2) / Math.max(gH, 1),
      3,
    )
    applyView({
      x: canvas.width  / 2 - (minX + gW / 2) * s,
      y: canvas.height / 2 - (minY + gH / 2) * s,
      scale: s,
    })
  }, [applyView])

  // Types d'entités présents dans le graphe (pour la légende, dans l'ordre z-order)
  const allPresentTypes = [...new Set(
    nodesArrRef.current
      .filter(n => n.kind === 'entity')
      .map(n => n.ner_type)
  )]
  const presentTypes = [
    ...typeOrder.filter(t => allPresentTypes.includes(t)),
    ...allPresentTypes.filter(t => !typeOrder.includes(t)),
  ]

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <>
    <div
      className={`fixed inset-0 z-50 flex flex-col bg-slate-50 dark:bg-slate-900 ${
        fullscreen ? '' : 'md:inset-4 md:rounded-2xl md:shadow-2xl'
      }`}
      style={{ overflow: 'hidden' }}
    >
      {/* ── En-tête ── */}
      <div className="relative flex items-center gap-2 px-4 py-2.5 pr-14 border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/80 backdrop-blur-sm shrink-0 flex-wrap gap-y-2">
        <Network size={17} className="text-violet-500 shrink-0" />
        <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 shrink-0">
          Graphe de connaissances
        </span>

        {/* Recherche avec autocomplétion */}
        <div ref={searchContainerRef} className="relative flex items-center gap-1 flex-1 min-w-[140px] max-w-xs ml-2">
          <Search size={13} className="text-slate-400 shrink-0" />
          <input
            type="text"
            placeholder="Mot-clé entité…"
            value={searchBuf}
            onChange={e => setSearchBuf(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { setShowSuggestions(false); runSearchOrReload() }
              if (e.key === 'Escape') { setShowSuggestions(false) }
            }}
            onFocus={() => suggestions.length > 0 && openSuggestDropdown()}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            className="w-full text-xs bg-transparent outline-none text-slate-700 dark:text-slate-200 placeholder-slate-400"
          />
          {/* Dropdown suggestions — portal dans document.body pour échapper aux overflow/transform parents */}
          {showSuggestions && dropdownPos && createPortal(
            <div
              className="fixed overflow-y-auto z-[9999] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl"
              style={{ top: dropdownPos.top, left: dropdownPos.left, width: dropdownPos.width, maxHeight: '50vh' }}
            >
              {suggestions.map((sug, i) => {
                const img  = suggestImages[sug.value]
                const cfg  = TYPE_CFG[sug.type]
                const isRound = sug.type === 'PERSON'
                const initials = sug.value.split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')
                return (
                  <button
                    key={`${sug.type}:${sug.value}:${i}`}
                    onMouseDown={e => { e.preventDefault(); selectSuggestion(sug) }}
                    className="flex items-center gap-2.5 w-full px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-700/60 transition-colors first:rounded-t-xl last:rounded-b-xl"
                  >
                    {/* Avatar */}
                    <div
                      className={`shrink-0 overflow-hidden border border-slate-200 dark:border-slate-600 ${
                        isRound ? 'rounded-full' : 'rounded-md'
                      } ${img ? 'bg-white' : 'bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center'}`}
                      style={{ width: 28, height: 28 }}
                    >
                      {img ? (
                        <img src={img.url} alt={sug.value} className={`w-full h-full ${isRound ? 'object-cover' : 'object-contain p-0.5'}`} />
                      ) : (
                        <span className="text-violet-500 dark:text-violet-300 font-semibold" style={{ fontSize: 9 }}>{initials}</span>
                      )}
                    </div>
                    {/* Nom */}
                    <span className="flex-1 text-xs text-slate-800 dark:text-slate-100 truncate">{sug.value}</span>
                    {/* Badge type */}
                    <span
                      className="shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded-full text-white"
                      style={{ background: cfg?.color ?? ENTITY_DEFAULT }}
                    >{cfg?.label ?? sug.type}</span>
                  </button>
                )
              })}
            </div>,
            document.body
          )}

          {/* Dropdown suggestions articles — portal */}
          {showArticleSuggestions && articleDropdownPos && createPortal(
            <div
              className="fixed overflow-y-auto z-[9999] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl"
              style={{ top: articleDropdownPos.top, left: articleDropdownPos.left, width: articleDropdownPos.width, maxHeight: '50vh' }}
            >
              <div className="px-3 pt-2 pb-1 text-[10px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wide">
                Articles du graphe actuel — cliquez pour filtrer
              </div>
              {articleSuggestions.map((sug, i) => {
                const q   = articleQueryBuf.trim()
                const low = sug.excerpt.toLowerCase()
                const pos = low.indexOf(q.toLowerCase())
                const before = pos >= 0 ? sug.excerpt.slice(0, pos) : sug.excerpt
                const match  = pos >= 0 ? sug.excerpt.slice(pos, pos + q.length) : ''
                const after  = pos >= 0 ? sug.excerpt.slice(pos + q.length) : ''
                return (
                  <button
                    key={`${sug.url}:${i}`}
                    onMouseDown={e => { e.preventDefault(); selectArticleSuggestion(sug) }}
                    className="flex flex-col w-full px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-700/60 transition-colors last:rounded-b-xl border-t border-slate-100 dark:border-slate-700/50 first:border-t-0"
                  >
                    <span className="text-[10px] font-semibold text-blue-500 dark:text-blue-400 mb-0.5 truncate">{sug.source}</span>
                    <span className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-2">
                      {before}<strong className="text-slate-900 dark:text-white bg-yellow-100 dark:bg-yellow-900/40 rounded px-0.5">{match}</strong>{after}
                    </span>
                  </button>
                )
              })}
            </div>,
            document.body
          )}
        </div>

        {/* Filtres de date (masqués en mode tout charger) */}
        {!loadAll && (
          <>
            <input
              type="date"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
              className="text-xs px-2 py-1 bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-200 outline-none"
              title="Date de début"
            />
            <span className="text-xs text-slate-400">→</span>
            <input
              type="date"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
              className="text-xs px-2 py-1 bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-200 outline-none"
              title="Date de fin"
            />
          </>
        )}

        {/* Toggle Tout charger */}
        <button
          onClick={() => setLoadAll(v => !v)}
          className={`flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors shrink-0 ${
            loadAll
              ? 'bg-amber-500 border-amber-600 text-white hover:bg-amber-600'
              : 'bg-slate-100 dark:bg-slate-700 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
          }`}
          title={loadAll ? 'Mode : tous les fichiers (sans filtre de date)' : 'Mode : filtré par date (7 derniers jours)'}
        >
          Tout
        </button>

        {/* Charger */}
        <button
          onClick={runSearchOrReload}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-1.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
        >
          {loading
            ? <Loader2 size={12} className="animate-spin" />
            : <RefreshCw size={12} />}
          Charger
        </button>

        {selectedEntityKeys.size > 0 && (
          <span className="text-[11px] px-2 py-1 rounded-full bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 font-medium shrink-0">
            {selectedEntityKeys.size} entité{selectedEntityKeys.size > 1 ? 's' : ''} sélectionnée{selectedEntityKeys.size > 1 ? 's' : ''}
          </span>
        )}

        {/* ── Sélecteur de types d'entité (2e ligne) ── */}
        <div className="basis-full h-0" />
        <div className="flex items-center gap-1 flex-wrap basis-full">
          <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 mr-1 shrink-0">Types</span>
          {ALL_NER_TYPES.map(t => (
            <button
              key={t}
              onClick={() => {
                if (selectedEntityKeys.size === 0) return
                toggleType(t)
              }}
              disabled={selectedEntityKeys.size === 0}
              className={`px-1.5 py-0.5 rounded text-[10px] font-medium border transition-colors whitespace-nowrap ${
                activeTypes.has(t)
                  ? 'text-white border-transparent'
                  : 'bg-slate-100 dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:border-slate-400 disabled:opacity-40 disabled:cursor-not-allowed'
              }`}
              style={activeTypes.has(t) ? { background: TYPE_CFG[t]?.color ?? '#8b5cf6', borderColor: 'transparent' } : {}}
              title={selectedEntityKeys.size === 0
                ? 'Sélectionnez d\'abord une ou plusieurs entités'
                : (activeTypes.has(t) ? `Retirer ${t} du graphe` : `Ajouter ${t} au graphe`)}
            >
              {TYPE_CFG[t]?.label ?? t}
            </button>
          ))}
          {/* Checkbox L2 — toujours visible en fin de ligne Types */}
          <label
            className={`ml-auto flex shrink-0 items-center gap-1 text-[11px] cursor-pointer font-semibold whitespace-nowrap select-none px-1.5 py-0.5 rounded border transition-colors ${
              showL2
                ? 'bg-violet-500 text-white border-transparent'
                : 'bg-slate-100 dark:bg-slate-700 border-slate-300 dark:border-slate-600 text-slate-500 dark:text-slate-400'
            }`}
            title="Afficher les relations L2 : liaisons directes entre entités co-citées dans les mêmes articles"
          >
            <input
              type="checkbox"
              checked={showL2}
              onChange={e => setShowL2(e.target.checked)}
              className="w-3 h-3 accent-violet-500 cursor-pointer"
            />
            L2
          </label>
        </div>

        {/* ── Filtre article (titre + résumé) ── */}
        <div className="relative flex items-center gap-2 basis-full">
          <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 shrink-0">Article</span>
          <div ref={articleContainerRef} className="relative flex-1 min-w-[220px]">
            <input
              type="text"
              placeholder={nodesArrRef.current.filter(n => n.kind === 'article').length > 0 ? 'Filtre titre / résumé…' : 'Chargez d’abord le graphe'}
              value={articleQueryBuf}
              onChange={e => setArticleQueryBuf(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') { setShowArticleSuggestions(false); runSearchOrReload() }
                if (e.key === 'Escape') setShowArticleSuggestions(false)
              }}
              onFocus={() => articleSuggestions.length > 0 && openArticleDropdown()}
              onBlur={() => setTimeout(() => setShowArticleSuggestions(false), 150)}
              className="w-full text-xs px-2 py-1 bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-200 outline-none"
              title="Filtrer les articles sur le titre et le résumé"
            />
          </div>
        </div>

        <div className="flex-1" />

        {/* Taille ∝ articles */}
        <label className="flex shrink-0 items-center gap-1.5 text-xs cursor-pointer font-semibold text-violet-600 dark:text-violet-400 whitespace-nowrap select-none" title="Taille des nœuds ∝ nombre d'articles qui mentionnent l'entité (log)">
          <input
            type="checkbox"
            checked={sizeByTotal}
            onChange={e => setSizeByTotal(e.target.checked)}
            className="w-3 h-3 accent-violet-500"
          />
          Taille ∝
        </label>

        {/* ── Contrôle longueur des liens ── */}
        <div className="flex items-center gap-1.5 shrink-0 bg-slate-100/70 dark:bg-slate-700/50 border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-1">
          <span className="text-[11px] text-slate-500 dark:text-slate-400 shrink-0 select-none whitespace-nowrap">Liens</span>
          <input
            type="range"
            min="0.4"
            max="40"
            step="0.1"
            value={linkMult}
            onChange={e => {
              const v = parseFloat(e.target.value)
              setLinkMult(v)
              if (tempRef.current < 5) tempRef.current = 8
            }}
            className="w-20 accent-violet-500 cursor-pointer"
            title={`Longueur des liens : ${linkMult.toFixed(1)}×`}
          />
          <span className="text-[11px] font-mono text-slate-600 dark:text-slate-300 w-7 shrink-0 tabular-nums">{linkMult.toFixed(1)}×</span>
          <button
            onClick={autoLinkMult}
            className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 hover:bg-violet-200 dark:hover:bg-violet-800/50 transition-colors shrink-0"
            title={`Calcul automatique de la longueur idéale (${nodesArrRef.current.length} nœuds)`}
          >
            Auto
          </button>
        </div>

        {/* Zoom in/out/fit */}
        <button
          onClick={() => { const c = canvasRef.current; if (c) zoom(1.25, c.width / 2, c.height / 2) }}
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title="Zoom avant"
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={() => { const c = canvasRef.current; if (c) zoom(0.8, c.width / 2, c.height / 2) }}
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title="Zoom arrière"
        >
          <ZoomOut size={14} />
        </button>
        <button
          onClick={fitView}
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title="Ajuster la vue"
        >
          <Crosshair size={14} />
        </button>
        <button
          onClick={() => setFullscreen(f => !f)}
          className="absolute top-2 right-11 z-10 p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title={fullscreen ? 'Quitter le plein écran' : 'Plein écran'}
        >
          {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        <button
          onClick={onClose}
          className="absolute top-2 right-2 z-10 p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title="Fermer"
        >
          <X size={16} />
        </button>
      </div>

      {/* ── Corps ── */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Canvas */}
        <div ref={containerRef} className="flex-1 relative overflow-hidden" style={{ touchAction: 'none' }}>
          <canvas
            ref={canvasCallbackRef}
            className="absolute inset-0"
            style={{ cursor: 'grab', touchAction: 'none' }}
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseLeave}
          />

          {/* Barre de statut */}
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm rounded-full text-[11px] text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-700 pointer-events-none whitespace-nowrap">
            {loading && <Loader2 size={10} className="inline animate-spin mr-1" />}
            {status}
          </div>

          {/* Légende */}
          {showLegend && (
            <div className="absolute top-3 left-3 bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-xl border border-slate-200 dark:border-slate-700 px-3 py-2.5 text-[11px] overflow-y-auto shadow-sm"
              style={{ maxHeight: '50%', width: 'auto', minWidth: '9rem' }}
            >
              <div className="font-semibold text-slate-600 dark:text-slate-300 mb-1.5">Légende</div>
              <LegendItem color={ARTICLE_COLOR} label="Article" r={R_ARTICLE} />
              {presentTypes.map((t, idx) => (
                <div key={t} className="flex items-center gap-0.5">
                  <LegendItem
                    color={TYPE_CFG[t]?.color ?? ENTITY_DEFAULT}
                    label={TYPE_CFG[t]?.label ?? t}
                    r={R_ENTITY}
                    isPerson={t === 'PERSON'}
                    hidden={false}
                    active={activeTypes.has(t)}
                    onClick={() => toggleType(t)}
                  />
                  <div className="flex flex-col ml-auto pl-1 shrink-0">
                    <button
                      onMouseDown={e => { e.stopPropagation(); moveLegendType(t, -1) }}
                      disabled={idx === 0}
                      className="h-3.5 flex items-center justify-center text-slate-400 hover:text-violet-600 disabled:opacity-20 disabled:cursor-not-allowed"
                      title="Vers le dessus (z-order)"
                    >
                      <ChevronUp size={10} />
                    </button>
                    <button
                      onMouseDown={e => { e.stopPropagation(); moveLegendType(t, 1) }}
                      disabled={idx === presentTypes.length - 1}
                      className="h-3.5 flex items-center justify-center text-slate-400 hover:text-violet-600 disabled:opacity-20 disabled:cursor-not-allowed"
                      title="Vers le dessous (z-order)"
                    >
                      <ChevronDown size={10} />
                    </button>
                  </div>
                </div>
              ))}
              {presentTypes.length === 0 && (
                <span className="text-slate-400 italic">Chargez le graphe</span>
              )}
              {/* Entrée L2 si activé */}
              {showL2 && l2EdgesArrRef.current.length > 0 && (
                <div className="mt-1.5 pt-1.5 border-t border-slate-200 dark:border-slate-700 flex items-center gap-1.5">
                  <svg width="22" height="10" className="shrink-0">
                    <line x1="1" y1="5" x2="21" y2="5"
                      stroke="#7c3aed" strokeWidth="1.5"
                      strokeDasharray="3 3" strokeOpacity="0.7" />
                  </svg>
                  <span className="text-[10px] text-violet-600 dark:text-violet-400 font-medium">L2 co-occur.</span>
                </div>
              )}
            </div>
          )}

          {/* Bouton légende */}
          <button
            onClick={() => setShowLegend(l => !l)}
            className="absolute top-3 right-3 px-2 py-1 bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm rounded-lg border border-slate-200 dark:border-slate-700 text-[11px] text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          >
            {showLegend ? 'Masquer légende' : 'Légende'}
          </button>

          {/* Tooltip */}
          {tooltip && (
            <div
              className="absolute pointer-events-none z-10 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg px-3 py-2 text-xs max-w-xs"
              style={{
                left: Math.min(tooltip.x + 12, (canvasRef.current?.getBoundingClientRect().width  ?? 800) - 200),
                top:  Math.min(tooltip.y + 12, (canvasRef.current?.getBoundingClientRect().height ?? 600) - 80),
              }}
            >
              {tooltip.node.kind === 'article' ? (
                <>
                  <div className="font-semibold text-blue-600 dark:text-blue-400 mb-0.5">📰 Article</div>
                  <div className="font-medium text-slate-700 dark:text-slate-200 mb-0.5 truncate max-w-[200px]">
                    {tooltip.node.source}
                  </div>
                  <div className="text-slate-400 mb-1">{tooltip.node.date}</div>
                  {tooltip.node.resume && (
                    <div className="text-slate-500 dark:text-slate-400 leading-relaxed line-clamp-3">
                      {tooltip.node.resume}
                    </div>
                  )}
                  <button
                    className="pointer-events-auto text-blue-500 hover:underline mt-1 inline-block text-left"
                    onClick={e => {
                      e.stopPropagation()
                      setReportArticle({
                        article: {
                          'URL': tooltip.node.url,
                          'Sources': tooltip.node.source,
                          'Date de publication': tooltip.node.date,
                          'Résumé': tooltip.node.resume,
                        },
                        filePath: tooltip.node.file ?? '',
                      })
                    }}
                  >
                    Voir l’article →
                  </button>
                </>
              ) : (
                <>
                  <div
                    className="font-semibold mb-0.5"
                    style={{ color: TYPE_CFG[tooltip.node.ner_type]?.color ?? ENTITY_DEFAULT }}
                  >
                    ● {tooltip.node.ner_type}
                  </div>
                  <div className="font-medium text-slate-700 dark:text-slate-200">
                    {tooltip.node.value}
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Panneau latéral nœud sélectionné */}
        {selected && (
          <div className="w-72 border-l border-slate-200 dark:border-slate-700 bg-white/95 dark:bg-slate-800 overflow-y-auto shrink-0 text-sm flex flex-col">
            {/* En-tête */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-700">
              <span className="font-semibold text-slate-800 dark:text-slate-100 text-[13px]">
                {selected.kind === 'article'
                  ? <span className="flex items-center gap-1.5"><span className="text-base">📰</span> Article</span>
                  : <span className="flex items-center gap-1.5 min-w-0">
                      <span className="w-2 h-2 rounded-full inline-block" style={{ background: TYPE_CFG[selected.ner_type]?.color ?? ENTITY_DEFAULT }} />
                      <span className="truncate">
                        {selected.value} · {TYPE_CFG[selected.ner_type]?.label ?? selected.ner_type}
                      </span>
                    </span>
                }
              </span>
              <button onClick={() => setSelected(null)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
                <X size={14} />
              </button>
            </div>
            {/* Bouton Ouvrir entité (affiché uniquement pour les nœuds entité) */}
            {selected.kind === 'entity' && (
              <div className="px-4 pt-3 pb-0">
                <button
                  onClick={() => setEntityPanel({ type: selected.ner_type, value: selected.value })}
                  className="w-full px-3 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700 text-white text-xs font-semibold rounded-xl transition-all shadow-sm"
                >
                  Ouvrir le panneau entité
                </button>
              </div>
            )}

            {/* Corps */}
            <div className="flex-1 p-4 space-y-3">
            {selected.kind === 'article' ? (
              <>
                {/* Badge source + date */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="inline-flex items-center text-[11px] font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider bg-black/5 dark:bg-white/10 px-3 py-0.5 rounded-full">
                    {selected.source ?? '—'}
                  </span>
                  {selected.date && (
                    <span className="text-[11px] text-slate-400 dark:text-slate-500">{selected.date}</span>
                  )}
                </div>

                {/* Résumé aperçu */}
                {selected.resume && (
                  <p className="text-[12px] leading-relaxed text-slate-600 dark:text-slate-300 line-clamp-6">
                    {selected.resume}
                  </p>
                )}

                {/* URL tronquée */}
                {selected.url && (
                  <a
                    href={selected.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-500 hover:underline truncate"
                    title={selected.url}
                  >
                    <ExternalLink size={10} className="shrink-0" />
                    {selected.url.replace(/^https?:\/\//, '').slice(0, 45)}…
                  </a>
                )}

                {/* CTA principal */}
                <button
                  onClick={() => setReportArticle({ article: { 'URL': selected.url, 'Sources': selected.source, 'Date de publication': selected.date, 'Résumé': selected.resume }, filePath: selected.file ?? '' })}
                  className="w-full px-3 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-700 hover:to-indigo-700 text-white text-xs font-semibold rounded-xl transition-all shadow-sm shadow-violet-200 dark:shadow-none"
                >
                  Ouvrir l'article complet
                </button>
              </>
            ) : (
              <>
                {/* Nom entité */}
                <div>
                  <p className="text-base font-bold mt-0.5" style={{ color: TYPE_CFG[selected.ner_type]?.color ?? ENTITY_DEFAULT }}>
                    {selected.value}
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5 uppercase tracking-wider">
                    {TYPE_CFG[selected.ner_type]?.label ?? selected.ner_type}
                  </p>
                </div>

                {/* Articles liés */}
                <div>
                  <span className="text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                    Articles liés
                  </span>
                  <ul className="mt-2 space-y-1.5">
                    {edgesArrRef.current
                      .filter(([si]) => nodesArrRef.current[si]?.id === selected.id)
                      .slice(0, 10)
                      .map(([, ti]) => {
                        const art = nodesArrRef.current[ti]
                        if (!art) return null
                        return (
                          <li key={art.id}>
                            <button
                              onClick={() => setReportArticle({ article: { 'URL': art.url, 'Sources': art.source, 'Date de publication': art.date, 'Résumé': art.resume }, filePath: art.file ?? '' })}
                              className="w-full text-left px-3 py-1.5 rounded-xl bg-slate-50 dark:bg-slate-700/50 hover:bg-violet-50 dark:hover:bg-violet-900/30 border border-slate-100 dark:border-slate-700 hover:border-violet-200 dark:hover:border-violet-800 transition-colors group"
                            >
                              <span className="block text-[11px] font-semibold text-slate-600 dark:text-slate-300 group-hover:text-violet-700 dark:group-hover:text-violet-300 truncate">
                                {art.source}
                              </span>
                              <span className="block text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
                                {art.date}
                              </span>
                            </button>
                          </li>
                        )
                      })
                    }
                  </ul>
                </div>
              </>
            )}
            </div>
          </div>
        )}
      </div>
    </div>

    {/* ── Panel article ── */}
    {reportArticle && (
      <GraphArticlePanel
        article={reportArticle.article}
        filePath={reportArticle.filePath}
        onClose={() => setReportArticle(null)}
      />
    )}

    {/* ── Panel entité ── */}
    {entityPanel && (
      <EntityArticlePanel
        entityType={entityPanel.type}
        entityValue={entityPanel.value}
        onClose={() => setEntityPanel(null)}
      />
    )}
    </>
  )
}

// ── Légende item ─────────────────────────────────────────────────────────────
function LegendItem({ color, label, r, isPerson, hidden, active, onClick }) {
  const cx = r + 1
  const cy = r + 1
  return (
    <div
      className={[
        'flex items-center gap-2 py-0.5 rounded',
        onClick ? 'cursor-pointer select-none px-1 -mx-1 hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors' : '',
        hidden  ? 'opacity-40' : '',
      ].join(' ')}
      onClick={onClick}
      title={onClick ? (active ? `Retirer ${label} du filtre` : `Ajouter ${label} au filtre`) : undefined}
    >
      <svg width={r * 2 + 2} height={r * 2 + 2}>
        <circle cx={cx} cy={cy} r={r} fill={color} opacity={hidden ? 0.35 : 0.9} />
        {active && <circle cx={cx} cy={cy} r={r} fill="none" stroke="white" strokeWidth="1.5" opacity="0.7" />}
        {isPerson && !hidden && (
          <>
            {/* Tête */}
            <circle cx={cx} cy={cy - r * 0.18} r={r * 0.30} fill="rgba(255,255,255,0.92)" />
            {/* Épaules (grand cercle bas, clippé par le cercle principal) */}
            <clipPath id="person-legend-clip">
              <circle cx={cx} cy={cy} r={r} />
            </clipPath>
            <circle
              cx={cx} cy={cy + r * 0.82} r={r * 0.58}
              fill="rgba(255,255,255,0.92)"
              clipPath="url(#person-legend-clip)"
            />
          </>
        )}
      </svg>
      <span className={`text-slate-600 dark:text-slate-300 ${hidden ? 'line-through' : ''}`}>{label}</span>
    </div>
  )
}
