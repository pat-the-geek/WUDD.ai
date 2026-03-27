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
import {
  X, Search, ZoomIn, ZoomOut, Maximize2, Minimize2,
  RefreshCw, Loader2, Network, Crosshair, ExternalLink,
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
 * @param {object[]} nodes   — [{id, x, y, vx, vy, r}]
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

  // Répulsion O(n²) — acceptable jusqu'à ~800 nœuds
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx = nodes[i].x - nodes[j].x
      const dy = nodes[i].y - nodes[j].y
      const d2 = Math.max(dx * dx + dy * dy, 1)
      const d  = Math.sqrt(d2)
      const f  = (k * k) / d2
      const nx = (dx / d) * f
      const ny = (dy / d) * f
      fx[i] += nx;  fy[i] += ny
      fx[j] -= nx;  fy[j] -= ny
    }
  }

  // Attraction sur les arêtes
  for (const [si, ti] of edges) {
    const dx    = nodes[ti].x - nodes[si].x
    const dy    = nodes[ti].y - nodes[si].y
    const d     = Math.sqrt(dx * dx + dy * dy) || 0.01
    const ideal = k * linkMult
    const f     = (d - ideal) * 0.3
    const nx    = (dx / d) * f
    const ny    = (dy / d) * f
    fx[si] += nx;  fy[si] += ny
    fx[ti] -= nx;  fy[ti] -= ny
  }

  // Gravité vers le centre
  const cx = W / 2
  const cy = H / 2
  for (let i = 0; i < n; i++) {
    fx[i] += (cx - nodes[i].x) * 0.018
    fy[i] += (cy - nodes[i].y) * 0.018
  }

  // Intégration + amortissement
  for (let i = 0; i < n; i++) {
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
}

// ── Composant principal ────────────────────────────────────────────────────

export default function KnowledgeGraph({ onClose }) {
  // ── Filtres ──────────────────────────────────────────────────────────────
  const today       = new Date().toISOString().slice(0, 10)
  const weekAgo     = new Date(Date.now() - 7 * 86400_000).toISOString().slice(0, 10)
  const [search,    setSearch]   = useState('')
  const [dateFrom,  setDateFrom] = useState(weekAgo)
  const [dateTo,    setDateTo]   = useState(today)
  const [searchBuf, setSearchBuf] = useState('') // champ non-committée
  const [loadAll,   setLoadAll]   = useState(false) // mode "tout charger"

  // ── État de chargement ───────────────────────────────────────────────────
  const [loading,   setLoading]  = useState(false)
  const [status,    setStatus]   = useState(
    'Configurez les filtres puis cliquez sur Charger.'
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
  const ticksRef   = useRef(0)    // compteur d'itérations

  // ── Tooltip ──────────────────────────────────────────────────────────────
  const [tooltip, setTooltip] = useState(null) // {x, y, node}

  // ── Plein écran ──────────────────────────────────────────────────────────
  const [fullscreen, setFullscreen] = useState(false)

  // ── Drag (pan) ───────────────────────────────────────────────────────────
  const dragRef = useRef(null)  // {startX, startY, ox, oy}

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

  // ── Filtrage par type d'entité ─────────────────────────────────────────
  const [hiddenTypes,   setHiddenTypes]   = useState(new Set())
  const hiddenTypesRef = useRef(new Set())
  useEffect(() => { hiddenTypesRef.current = hiddenTypes }, [hiddenTypes])

  const toggleType = useCallback((type) => {
    setHiddenTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      hiddenTypesRef.current = next
      return next
    })
  }, [])

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

    const hidden = hiddenTypesRef.current
    const isHidden = (n) => n.kind === 'entity' && hidden.has(n.ner_type)

    // ── Arêtes ──────────────────────────────────────────────────────────
    ctx.strokeStyle = isDark ? 'rgba(148,163,184,0.25)' : 'rgba(100,116,139,0.20)'
    ctx.lineWidth   = lw
    ctx.beginPath()
    for (const [si, ti] of edges) {
      const s = nodes[si]
      const t = nodes[ti]
      if (!s || !t) continue
      if (isHidden(s) || isHidden(t)) continue
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
    }
    ctx.stroke()

    // ── Nœuds ───────────────────────────────────────────────────────────
    for (const node of nodes) {
      if (isHidden(node)) continue
      const color = node.kind === 'article'
        ? ARTICLE_COLOR
        : (TYPE_CFG[node.ner_type]?.color ?? ENTITY_DEFAULT)
      const r     = node.r
      const isSelected = selected && selected.id === node.id

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

      // Label : toujours visible pour le nœud pinné, sinon seulement à fort zoom
      if (node.pinned || scale > 1.4 || (scale > 0.8 && node.kind === 'article')) {
        const label = node.kind === 'article'
          ? (node.source || '').slice(0, 18)
          : (node.value  || '').slice(0, 20)
        if (label) {
          const fs = node.pinned
            ? Math.max(10, Math.min(16, 14 / scale))
            : Math.max(7, Math.min(11, 10 / scale))
          ctx.font      = node.pinned
            ? `bold ${fs}px system-ui, sans-serif`
            : `${fs}px system-ui, sans-serif`
          ctx.fillStyle = node.pinned
            ? color
            : (isDark ? 'rgba(226,232,240,0.9)' : 'rgba(30,41,59,0.9)')
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
      for (let i = 0; i < 3; i++) {
        stepForce(nodes, edges, W, H, tempRef.current, linkMultRef.current)
      }
      tempRef.current *= 0.992   // refroidissement
      ticksRef.current += 3
      // Maintenir les nœuds pinnés (= entité correspondant au critère) au centre
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
  const load = useCallback(() => {
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
    if (loadAll) {
      params.set('all', 'true')
    } else {
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo)   params.set('date_to',   dateTo)
      params.set('max_articles', '200')
    }
    if (search)   params.set('search', search)

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
                handleEvent(ev, canvas, search)
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
  }, [dateFrom, dateTo, search, loadAll])

  function handleEvent(ev, canvas, searchTerm = '') {
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
      setStatus(
        `${nArticles} article${nArticles !== 1 ? 's' : ''} · `
        + `${nEntities} entité${nEntities !== 1 ? 's' : ''} · `
        + `${ev.total_edges} liaison${ev.total_edges !== 1 ? 's' : ''}`
      )
      // Réchauffer la simulation pour la finalisation
      tempRef.current = Math.max(tempRef.current, 12)
    }
  }

  // Chargement automatique à l'ouverture
  useEffect(() => {
    load()
    return () => { if (abortRef.current) abortRef.current.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    const rect   = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
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
      const dx = e.clientX - dragRef.current.startX
      const dy = e.clientY - dragRef.current.startY
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
    const mx    = e.clientX - rect.left
    const my    = e.clientY - rect.top
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
      setTooltip({ x: mx, y: my, node: best })
      canvas.style.cursor = 'pointer'
    } else {
      setTooltip(null)
      canvas.style.cursor = dragRef.current ? 'grabbing' : 'grab'
    }
  }, [])

  const handleMouseUp = useCallback((e) => {
    if (!dragRef.current) return
    const dx = Math.abs(e.clientX - dragRef.current.startX)
    const dy = Math.abs(e.clientY - dragRef.current.startY)
    dragRef.current = null

    // Clic (pas de drag significatif) → sélection ou ouverture dialog article
    if (dx < 4 && dy < 4) {
      const node = tooltip?.node ?? null
      if (node?.kind === 'article') {
        setReportArticle({
          article: {
            'URL':                  node.url,
            'Sources':              node.source,
            'Date de publication':  node.date,
            'Résumé':               node.resume,
          },
          filePath: node.file ?? '',
        })
      } else if (node?.kind === 'entity') {
        setEntityPanel({ type: node.ner_type, value: node.value })
      } else {
        setSelected(node)
      }
    }
  }, [tooltip])

  const handleMouseLeave = useCallback(() => {
    dragRef.current = null
    setTooltip(null)
  }, [])

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

  // Types d'entités présents dans le graphe (pour la légende)
  const presentTypes = [...new Set(
    nodesArrRef.current
      .filter(n => n.kind === 'entity')
      .map(n => n.ner_type)
  )].sort()

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
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-800/80 backdrop-blur-sm shrink-0 flex-wrap gap-y-2">
        <Network size={17} className="text-violet-500 shrink-0" />
        <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 shrink-0">
          Graphe de connaissances
        </span>

        {/* Recherche */}
        <div className="flex items-center gap-1 flex-1 min-w-[140px] max-w-xs ml-2">
          <Search size={13} className="text-slate-400 shrink-0" />
          <input
            type="text"
            placeholder="Recherche plein texte…"
            value={searchBuf}
            onChange={e => setSearchBuf(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                setSearch(searchBuf)
                setTimeout(load, 0)
              }
            }}
            className="w-full text-xs bg-transparent outline-none text-slate-700 dark:text-slate-200 placeholder-slate-400"
          />
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
          onClick={() => { setSearch(searchBuf); setTimeout(load, 0) }}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-1.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors shrink-0"
        >
          {loading
            ? <Loader2 size={12} className="animate-spin" />
            : <RefreshCw size={12} />}
          Charger
        </button>

        <div className="flex-1" />

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
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title={fullscreen ? 'Quitter le plein écran' : 'Plein écran'}
        >
          {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400 transition-colors"
          title="Fermer"
        >
          <X size={16} />
        </button>
      </div>

      {/* ── Corps ── */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Canvas */}
        <div ref={containerRef} className="flex-1 relative overflow-hidden">
          <canvas
            ref={canvasRef}
            className="absolute inset-0"
            style={{ cursor: 'grab' }}
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
              {presentTypes.map(t => (
                <LegendItem
                  key={t}
                  color={TYPE_CFG[t]?.color ?? ENTITY_DEFAULT}
                  label={TYPE_CFG[t]?.label ?? t}
                  r={R_ENTITY}
                  isPerson={t === 'PERSON'}
                  hidden={hiddenTypes.has(t)}
                  onClick={() => toggleType(t)}
                />
              ))}
              {presentTypes.length === 0 && (
                <span className="text-slate-400 italic">Chargez le graphe</span>
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
                left: Math.min(tooltip.x + 12, (canvasRef.current?.width ?? 800) - 200),
                top:  Math.min(tooltip.y + 12, (canvasRef.current?.height ?? 600) - 80),
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
                  : <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full inline-block" style={{ background: TYPE_CFG[selected.ner_type]?.color ?? ENTITY_DEFAULT }} />
                      {TYPE_CFG[selected.ner_type]?.label ?? selected.ner_type}
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
function LegendItem({ color, label, r, isPerson, hidden, onClick }) {
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
      title={onClick ? (hidden ? `Afficher ${label}` : `Masquer ${label}`) : undefined}
    >
      <svg width={r * 2 + 2} height={r * 2 + 2}>
        <circle cx={cx} cy={cy} r={r} fill={color} opacity={hidden ? 0.35 : 0.9} />
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
