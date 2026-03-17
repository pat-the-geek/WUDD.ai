/**
 * EntityFullReportDialog — génère et affiche un rapport complet d'une entité.
 *
 * - Modal centré similaire à ArticleFullReportDialog
 * - Corps en Markdown streamé progressivement (Info SSE → RAG SSE → articles)
 * - Diagrammes Mermaid : mindmap co-occurrences L1, camembert sources
 * - Actions : copier, Export local, Export Obsidian, régénérer, plein écran, fermer
 */

import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { createPortal } from 'react-dom'
import {
  X, Maximize2, Minimize2, Copy, Download, RefreshCw,
  FileText, Check, BookOpen, Loader2,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import mermaid from 'mermaid'

mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'loose' })

// ── Mermaid block ──────────────────────────────────────────────────────────────

function sanitizeMermaidCode(raw) {
  return raw
    .replace(/^```mermaid\s*/i, '')
    .replace(/```\s*$/, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\r\n/g, '\n')
    .trim()
}

function MermaidBlock({ code, isStreaming }) {
  const containerRef = useRef(null)
  const id = useRef(`mermaid-ent-${Math.random().toString(36).slice(2)}`)
  const [errMsg, setErrMsg] = useState(null)
  const [rendered, setRendered] = useState(false)

  const clean = sanitizeMermaidCode(code)

  useEffect(() => {
    if (isStreaming) return
    if (!containerRef.current) return
    setErrMsg(null)
    let cancelled = false
    mermaid.parse(clean)
      .then(() => mermaid.render(id.current, clean))
      .then(({ svg }) => {
        if (!cancelled && containerRef.current) {
          const responsiveSvg = svg.replace(/<svg([^>]*)>/i, (_, attrs) => {
            const vbMatch = attrs.match(/viewBox="([^"]*)"/i)
            const wMatch  = attrs.match(/width="([^"]*)"/i)
            const hMatch  = attrs.match(/height="([^"]*)"/i)
            let extra = ''
            if (!vbMatch && wMatch && hMatch) {
              extra = ` viewBox="0 0 ${parseFloat(wMatch[1])} ${parseFloat(hMatch[1])}"`
            }
            const cleaned = attrs
              .replace(/\s+width="[^"]*"/gi, '')
              .replace(/\s+height="[^"]*"/gi, '')
              .replace(/\s+style="[^"]*"/gi, '')
            return `<svg${cleaned}${extra} width="100%" style="width:100%;height:auto;max-width:100%;display:block;">`
          })
          containerRef.current.innerHTML = responsiveSvg
          setRendered(true)
        }
      })
      .catch(e => {
        if (cancelled) return
        const msg = e?.message ?? 'Syntaxe invalide'
        const firstLine = msg.split('\n').find(l => l.trim()) ?? msg
        setErrMsg(firstLine.length > 120 ? firstLine.slice(0, 120) + '…' : firstLine)
      })
    return () => { cancelled = true }
  }, [clean, isStreaming])

  if (isStreaming) {
    return <div className="my-6 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 animate-pulse" />
  }
  if (errMsg) {
    return (
      <div className="my-6 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-4">
        <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-2">
          ⚠ Diagramme Mermaid non rendu
        </p>
        <pre className="text-xs text-slate-600 dark:text-slate-400 font-mono whitespace-pre-wrap bg-white dark:bg-slate-900 rounded-lg p-3 border border-amber-100 dark:border-amber-900 overflow-x-auto">
          {clean}
        </pre>
      </div>
    )
  }
  return (
    <div
      ref={containerRef}
      className={`my-6 w-full overflow-x-auto ${rendered ? '' : 'h-10 bg-slate-100 dark:bg-slate-800 rounded-xl animate-pulse'}`}
    />
  )
}

// ── Vue finale gelée ───────────────────────────────────────────────────────────
const FinalReportView = memo(function FinalReportView({ md, components }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={components}>
      {md}
    </ReactMarkdown>
  )
})

// ── Helper: stream SSE et filtre <think> ───────────────────────────────────────
async function consumeSse(url, onChunk, signal) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`Erreur serveur ${res.status}`)
  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let inThink = false
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      let raw
      if (line.startsWith('data: ')) raw = line.slice(6).trim()
      else if (line.startsWith('{')) raw = line.trim()
      else continue
      if (!raw || raw === '[DONE]') continue
      let chunk
      try {
        const parsed = JSON.parse(raw)
        if (parsed.error) throw new Error(parsed.error)
        chunk = parsed.choices?.[0]?.delta?.content ?? ''
      } catch (e) { if (e.message?.startsWith('Erreur')) throw e; continue }
      if (!chunk) continue
      let rem = chunk
      while (rem.length > 0) {
        if (!inThink) {
          const s = rem.indexOf('<think>')
          if (s === -1) { onChunk(rem); break }
          onChunk(rem.slice(0, s))
          rem = rem.slice(s + 7)
          inThink = true
        } else {
          const e = rem.indexOf('</think>')
          if (e === -1) break
          rem = rem.slice(e + 8)
          inThink = false
        }
      }
    }
  }
}

// ── Suppression des accents ────────────────────────────────────────────────────
const removeAccents = s =>
  String(s ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')

// ── Nettoyage d'un tag pour Obsidian ─────────────────────────────────────────
// Obsidian n'accepte que lettres, chiffres, tirets, underscores et slashes.
// Tout autre caractère (espaces, ":", ".", ",", "?", etc.) → tiret.
const slugTag = s => removeAccents(String(s ?? ''))
  .replace(/\s+/g, '-')                   // espaces → tirets
  .replace(/[^a-zA-Z0-9\-_\/]/g, '-')    // caractères spéciaux → tirets
  .replace(/-{2,}/g, '-')                 // tirets consécutifs → un seul
  .replace(/^-+|-+$/g, '')               // tirets en début/fin → supprimés
  .slice(0, 50)                           // longueur maximale

// ── Générateur Mermaid mindmap pour co-occurrences ─────────────────────────────
function buildMindmapMd(entityValue, l1Nodes) {
  if (!l1Nodes || l1Nodes.length === 0) return ''
  const CARTO_TYPES = ['PERSON', 'ORG', 'GPE', 'LOC', 'NORP', 'EVENT']
  const byType = {}
  for (const n of l1Nodes) {
    if (!CARTO_TYPES.includes(n.type)) continue
    if (!byType[n.type]) byType[n.type] = []
    // Limiter à 4 entités par type — au-delà le rendu se superpose
    if (byType[n.type].length < 4) byType[n.type].push(String(n.value ?? ''))
  }
  const types = CARTO_TYPES.filter(t => byType[t]?.length > 0)
  if (types.length === 0) return ''

  // Nettoyer les valeurs pour Mermaid : sans accents, sans guillemets/parenthèses
  const esc = v => removeAccents(v)
    .replace(/[()[\]"']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 30)   // 30 chars max pour éviter les chevauchements

  let diagram = `mindmap\n  root(${esc(entityValue)})\n`
  for (const type of types) {
    diagram += `    ${type}\n`
    for (const val of byType[type]) {
      diagram += `      ${esc(val)}\n`
    }
  }
  return `\`\`\`mermaid\n${diagram}\`\`\``
}

// ── Générateur Mermaid camembert sources ───────────────────────────────────────
function buildPieMd(articles) {
  if (!articles || articles.length === 0) return ''
  const counts = {}
  for (const art of articles) {
    const src = String(art['Sources'] || 'Inconnu')
    counts[src] = (counts[src] || 0) + 1
  }
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8)
  if (entries.length < 2) return ''
  // Sans accents, sans guillemets doubles — labels courts pour éviter la superposition
  const esc = v => removeAccents(v).replace(/"/g, "'").replace(/\s+/g, ' ').trim().slice(0, 28)
  let diagram = `pie title Distribution sources (${articles.length} articles)\n`
  for (const [src, count] of entries) {
    diagram += `    "${esc(src)}" : ${count}\n`
  }
  return `\`\`\`mermaid\n${diagram}\`\`\``
}

// ── Frontmatter Obsidian ───────────────────────────────────────────────────────
function buildObsidianFrontmatter(title, tags) {
  const date     = new Date().toISOString().slice(0, 10)
  const dedupTags = [...new Set(
    tags.filter(t => t && typeof t === 'string' && t.trim().length > 0)
  )].slice(0, 30)
  const tagLines = dedupTags
    .map(t => `  - "${slugTag(t)}"`)
    .join('\n')
  return (
    `---\n` +
    `title: "${title.replace(/"/g, "'")}"\n` +
    `date: ${date}\n` +
    `version: "1.0"\n` +
    `tags:\n${tagLines || '  - rapport'}\n` +
    `type: Rapport\n` +
    `statut: generated\n` +
    `---\n\n`
  )
}

// ── Composant principal ────────────────────────────────────────────────────────

export default function EntityFullReportDialog({
  entityType,
  entityValue,
  articles,
  onClose,
}) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [reportMd, setReportMd]         = useState('')
  const [isLoading, setIsLoading]       = useState(true)
  const [phase, setPhase]               = useState('init')
  const [error, setError]               = useState(null)
  const [copied, setCopied]             = useState(false)
  const [exportState, setExportState]   = useState({ local: null, obsidian: null })
  const [frozenMd, setFrozenMd]         = useState(null)
  const frozenComponentsRef             = useRef(null)
  const abortRef    = useRef(null)
  const l1NodesRef  = useRef([])   // co-occurrences L1, conservées pour l'export Obsidian

  // ── Dérivé : markdown nettoyé ──────────────────────────────────────────────
  const cleanMd = reportMd
    .replace(/<think>[\s\S]*?<\/think>/g, '')
    .replace(/<think>[\s\S]*/g, '')
    .trim()

  // ── Gel au moment où le stream se termine ─────────────────────────────────
  useEffect(() => {
    if (!isLoading && cleanMd && !frozenMd) {
      frozenComponentsRef.current = mdComponents
      setFrozenMd(cleanMd)
    }
  }, [isLoading]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Escape key ────────────────────────────────────────────────────────────
  useEffect(() => {
    const h = e => { if (e.key === 'Escape' && !isFullscreen) onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose, isFullscreen])

  // ── Génération progressive du rapport ─────────────────────────────────────
  const buildReport = useCallback(async () => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac

    setReportMd('')
    setFrozenMd(null)
    setIsLoading(true)
    setError(null)
    setExportState({ local: null, obsidian: null })

    const today = new Date().toISOString().slice(0, 10)
    const safe  = entityValue.replace(/[^a-zA-Z0-9_\-]/g, '_')
    const append = (text) => setReportMd(prev => prev + text)

    try {
      // ── Phase 1 : Frontmatter + titre + co-occurrences (synchrone) ────────
      setPhase('init')

      // Frontmatter iA Writer
      append(`---\nAuteur: Patrick Ostertag\nTitre: Rapport — ${entityType} : ${entityValue}\nAuteurAdresse: patrick.ostertag@gmail.com\nAuteurSite: http://patrickostertag.ch\nDate: ${today}\nIAEngine: WUDD.ai\n---\n\n`)
      append(`# Rapport — ${entityValue}\n\n`)
      append(`---\nSynthèse des articles et analyses pour l'entité **${entityValue}** (${entityType}) — ${articles.length} source${articles.length !== 1 ? 's' : ''} — *${today}*\n---\n\n`)
      append(`{{TOC}}\n\n===\n\n`)

      // Co-occurrences L1
      let l1Nodes = []
      try {
        const gParams = new URLSearchParams({
          type: entityType, value: entityValue, depth: 1, limit: 40, limit_l2: 0,
        })
        const gRes = await fetch(`/api/entities/cooccurrences?${gParams}`, { signal: ac.signal })
        const gData = await gRes.json()
        if (!gData.error && Array.isArray(gData.nodes)) {
          l1Nodes = gData.nodes.filter(n => n.level === 1).sort((a, b) => b.count - a.count)
        }
      } catch (_) {}
      l1NodesRef.current = l1Nodes  // conserver pour l'export Obsidian

      if (l1Nodes.length > 0) {
        append(`## Cartographie des acteurs — Co-occurrences directes (L1)\n\n`)
        const mindmap = buildMindmapMd(entityValue, l1Nodes)
        if (mindmap) append(`${mindmap}\n\n`)
        // Liste textuelle complémentaire
        const CARTO_TYPES = new Set(['EVENT', 'GPE', 'LOC', 'NORP', 'ORG', 'PERSON'])
        const byType = {}
        for (const n of l1Nodes.filter(n => CARTO_TYPES.has(n.type))) {
          if (!byType[n.type]) byType[n.type] = []
          byType[n.type].push(n.value)
        }
        for (const type of ['PERSON', 'ORG', 'GPE', 'LOC', 'NORP', 'EVENT'].filter(t => byType[t])) {
          append(`**${type}** — ${byType[type].join(', ')}\n\n`)
        }
      }

      // Camembert sources
      const pieMd = buildPieMd(articles)
      if (pieMd) {
        append(`## Répartition des sources\n\n${pieMd}\n\n`)
      }

      // ── Phase 2 : Synthèse IA encyclopédique (SSE streaming) ───────────────
      setPhase('info')
      append(`## Informations — Synthèse IA\n\n`)
      try {
        const infoParams = new URLSearchParams({ type: entityType, value: entityValue })
        await consumeSse(`/api/entities/info?${infoParams}`, chunk => append(chunk), ac.signal)
      } catch (e) {
        if (e.name === 'AbortError') return
        append(`*Erreur lors de la génération de la synthèse encyclopédique.*\n\n`)
      }
      append(`\n\n`)

      // ── Phase 3 : Analyse RAG multi-sources (SSE streaming) ─────────────────
      setPhase('rag')
      append(`## Analyse comparative — Synthèse RAG\n\n`)
      try {
        const ragParams = new URLSearchParams({ entity_type: entityType, entity_value: entityValue, n: 15 })
        await consumeSse(`/api/synthesize-topic?${ragParams}`, chunk => append(chunk), ac.signal)
      } catch (e) {
        if (e.name === 'AbortError') return
        append(`*Erreur lors de la génération de la synthèse RAG.*\n\n`)
      }
      append(`\n\n`)

      // ── Phase 4 : Articles + tableau des références (synchrone) ─────────────
      setPhase('articles')
      append(`## Articles — ${articles.length} source${articles.length !== 1 ? 's' : ''}\n\n`)
      for (const art of articles) {
        const header = [art['Date de publication'], art['Sources']].filter(Boolean).join(' — ')
        if (header) append(`### ${header}\n\n`)
        if (art['Résumé']) append(`${art['Résumé']}\n\n`)
        const imgs = Array.isArray(art['Images']) ? art['Images'] : []
        for (const img of imgs.slice(0, 2)) {
          const imgUrl = img?.URL || img?.url || ''
          const imgAlt = img?.alt || img?.title || entityValue
          if (imgUrl) append(`![${imgAlt}](${imgUrl})\n*Source : ${art['Sources'] ?? ''}*\n\n`)
        }
        if (art['URL']) append(`[Lire l'article](${art['URL']})\n\n`)
        append(`---\n\n`)
      }

      append(`===\n\n# Tableau des références\n\n| # | Date | Source | URL |\n|---|---|---|---|\n`)
      articles.forEach((art, i) => {
        const date   = art['Date de publication'] ?? ''
        const source = String(art['Sources'] ?? '').replace(/\|/g, '\\|')
        const url    = art['URL'] ?? ''
        append(`| ${i + 1} | ${date} | ${source} | [↗](${url}) |\n`)
      })
      append(`\n---\n*Rapport préparé avec [WUDD.ai](https://github.com/pat-the-geek/WUDD.ai) — ${today}*\n`)

      setPhase('done')
      setIsLoading(false)
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message)
        setIsLoading(false)
      }
    }
  }, [entityType, entityValue, articles])

  useEffect(() => {
    buildReport()
    return () => abortRef.current?.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Actions ────────────────────────────────────────────────────────────────
  const getFilename = () => {
    const safe = entityValue.replace(/[^a-zA-Z0-9_\-]/g, '_')
    const today = new Date().toISOString().slice(0, 10)
    return `rapport_${entityType}_${safe}_${today}`
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(cleanMd).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([cleanMd], { type: 'text/markdown' }))
    a.download = `${getFilename()}.md`
    a.click()
  }

  const handleExport = async (target) => {
    setExportState(prev => ({ ...prev, [target]: 'saving' }))

    // Pour l'export Obsidian : remplacer le frontmatter iA Writer par un frontmatter Obsidian
    let markdown = cleanMd
    if (target === 'obsidian') {
      const title   = `Rapport — ${entityType} : ${entityValue}`
      const l1Tags  = l1NodesRef.current.map(n => String(n.value ?? '')).filter(Boolean)
      const tags    = [entityValue, ...l1Tags]
      const front   = buildObsidianFrontmatter(title, tags)
      // Supprimer le frontmatter iA Writer existant (bloc --- … ---)
      markdown = front + cleanMd.replace(/^---[\s\S]*?---\n\n?/, '')
    }

    try {
      const r = await fetch('/api/export/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown, filename: getFilename(), target }),
      })
      const d = await r.json()
      if (d.ok) {
        setExportState(prev => ({ ...prev, [target]: { ok: true, path: d.path } }))
      } else {
        setExportState(prev => ({ ...prev, [target]: { ok: false, error: d.error } }))
      }
    } catch (e) {
      setExportState(prev => ({ ...prev, [target]: { ok: false, error: String(e) } }))
    }
    setTimeout(() => setExportState(prev => ({ ...prev, [target]: null })), 4000)
  }

  // ── Phase label ────────────────────────────────────────────────────────────
  const phaseLabel = {
    init:     'Initialisation…',
    info:     'Synthèse encyclopédique en cours…',
    rag:      'Analyse comparative multi-sources…',
    articles: 'Assemblage des articles…',
    done:     '',
  }[phase] ?? ''

  // ── Styles boutons ─────────────────────────────────────────────────────────
  const btnCls = 'p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors'

  // ── ReactMarkdown component overrides ─────────────────────────────────────
  const mdComponents = {
    h1: ({ children }) => (
      <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mt-8 mb-4 pb-2 border-b border-slate-200 dark:border-slate-700 first:mt-0">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100 mt-7 mb-3">{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className="text-base font-semibold text-slate-800 dark:text-slate-200 mt-5 mb-2">{children}</h3>
    ),
    p: ({ children }) => (
      <p className="text-base text-slate-700 dark:text-slate-300 mb-4 leading-7">{children}</p>
    ),
    pre: ({ children }) => {
      const child = Array.isArray(children) ? children[0] : children
      if (child?.props?.className === 'language-mermaid') return <>{children}</>
      return (
        <pre className="bg-slate-100 dark:bg-slate-950 rounded-xl p-4 overflow-x-auto mb-4 border border-slate-200 dark:border-slate-800">
          {children}
        </pre>
      )
    },
    code: ({ className, children }) => {
      if (className === 'language-mermaid') {
        return <MermaidBlock code={String(children).trim()} isStreaming={isLoading} />
      }
      const isBlock = className || String(children).includes('\n')
      if (!isBlock) {
        return (
          <code className="bg-slate-100 dark:bg-slate-800 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded text-[0.85em] font-mono">
            {children}
          </code>
        )
      }
      return (
        <code className={`text-slate-700 dark:text-slate-300 text-sm font-mono leading-relaxed ${className || ''}`}>
          {children}
        </code>
      )
    },
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-blue-600 dark:text-blue-400 hover:text-blue-500 dark:hover:text-blue-300 underline underline-offset-2">
        {children}
      </a>
    ),
    ul: ({ children }) => <ul className="list-disc text-slate-700 dark:text-slate-300 mb-4 space-y-1 ml-5">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal text-slate-700 dark:text-slate-300 mb-4 space-y-1 ml-5">{children}</ol>,
    li: ({ children }) => <li className="text-base text-slate-700 dark:text-slate-300 leading-relaxed">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-violet-500/60 pl-4 italic text-slate-500 dark:text-slate-400 my-4">{children}</blockquote>
    ),
    table: ({ children }) => (
      <div className="overflow-x-auto mb-4 rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-sm text-slate-700 dark:text-slate-300">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200">{children}</thead>
    ),
    th: ({ children }) => (
      <th className="border-b border-slate-200 dark:border-slate-700 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider">{children}</th>
    ),
    td: ({ children }) => (
      <td className="border-b border-slate-200/50 dark:border-slate-700/50 px-4 py-2.5">{children}</td>
    ),
    img: ({ src, alt }) => (
      <figure className="my-6">
        <img src={src} alt={alt} className="max-w-full rounded-xl border border-slate-200 dark:border-slate-700" loading="lazy" />
        {alt && <figcaption className="text-center text-slate-400 dark:text-slate-500 text-sm mt-2 italic">{alt}</figcaption>}
      </figure>
    ),
    hr: () => <hr className="border-slate-200 dark:border-slate-700 my-8" />,
    strong: ({ children }) => <strong className="text-slate-900 dark:text-slate-100 font-semibold">{children}</strong>,
    em: ({ children }) => <em className="text-slate-700 dark:text-slate-300 italic">{children}</em>,
  }

  // ── Export button helper (icône seule — économise l'espace en mobile) ────────
  const ExportBtn = ({ target, label, icon: Icon, colors }) => {
    const st = exportState[target]
    const isSaving = st === 'saving'
    const isDone   = st?.ok === true
    const isFail   = st?.ok === false
    return (
      <div className="relative group">
        <button
          onClick={() => handleExport(target)}
          disabled={isLoading || !cleanMd || isSaving}
          title={isDone ? `Enregistré : ${st.path}` : isFail ? `Erreur : ${st.error}` : label}
          className={`p-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
            isDone  ? 'bg-green-50 dark:bg-green-900/30 border-green-300 dark:border-green-700 text-green-700 dark:text-green-300' :
            isFail  ? 'bg-red-50 dark:bg-red-900/30 border-red-300 dark:border-red-700 text-red-700 dark:text-red-300' :
            colors
          }`}
        >
          {isSaving ? <Loader2 size={14} className="animate-spin" /> : isDone ? <Check size={14} /> : <Icon size={14} />}
        </button>
        {(isDone || isFail) && (
          <div className="absolute top-full mt-1 right-0 z-10 max-w-xs bg-slate-800 text-white text-[10px] rounded px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap overflow-hidden text-ellipsis">
            {isDone ? st.path : st.error}
          </div>
        )}
      </div>
    )
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={e => e.target === e.currentTarget && !isFullscreen && onClose()}
    >
      <div
        className={`flex flex-col shadow-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 transition-all duration-200 ${
          isFullscreen
            ? 'fixed inset-0 rounded-none'
            : 'w-[92vw] max-w-[1400px] h-[92vh] rounded-2xl'
        } overflow-hidden`}
      >
        {/* ── Barre de titre ──────────────────────────────────────────────── */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-200 dark:border-slate-700 shrink-0 bg-white dark:bg-slate-900">
          <FileText size={17} className="text-violet-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">
              Rapport — <span className="text-violet-600 dark:text-violet-400">{entityValue}</span>
              <span className="ml-1.5 text-[10px] uppercase tracking-wider text-slate-400">{entityType}</span>
            </h2>
            <p className="text-[11px] text-slate-400 dark:text-slate-500 truncate">
              {articles.length} article{articles.length !== 1 ? 's' : ''}
              {isLoading && phaseLabel ? ` · ${phaseLabel}` : ''}
            </p>
          </div>

          <div className="flex items-center gap-1 shrink-0 flex-wrap justify-end">
            {/* Export local */}
            {!isLoading && cleanMd && (
              <>
                <ExportBtn
                  target="local"
                  label="Export"
                  icon={Download}
                  colors="bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:border-slate-400 hover:text-slate-700"
                />
                <ExportBtn
                  target="obsidian"
                  label="Export Obsidian"
                  icon={BookOpen}
                  colors="bg-violet-50 dark:bg-violet-900/30 border-violet-200 dark:border-violet-700 text-violet-700 dark:text-violet-300 hover:bg-violet-100 dark:hover:bg-violet-900/50"
                />
              </>
            )}
            <button onClick={handleCopy} className={btnCls} title="Copier le Markdown">
              {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
            </button>
            <button onClick={handleDownload} disabled={isLoading || !cleanMd} className={btnCls} title="Télécharger .md">
              <Download size={14} />
            </button>
            <button onClick={buildReport} disabled={isLoading} className={btnCls} title="Régénérer le rapport">
              <RefreshCw size={14} className={isLoading ? 'animate-spin text-violet-400' : ''} />
            </button>
            <button onClick={() => setIsFullscreen(v => !v)} className={btnCls} title={isFullscreen ? 'Quitter le plein écran' : 'Plein écran'}>
              {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-500 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors"
              title="Fermer">
              <X size={14} />
            </button>
          </div>
        </div>

        {/* ── Indicateur de phase (pendant la génération) ────────────────── */}
        {isLoading && (
          <div className="flex items-center gap-2 px-5 py-2 bg-violet-50 dark:bg-violet-900/20 border-b border-violet-100 dark:border-violet-800/30 shrink-0">
            <Loader2 size={12} className="animate-spin text-violet-500" />
            <span className="text-xs text-violet-700 dark:text-violet-300">{phaseLabel || 'Génération en cours…'}</span>
          </div>
        )}

        {/* ── Erreur ────────────────────────────────────────────────────────── */}
        {error && (
          <div className="px-5 py-3 bg-rose-50 dark:bg-rose-900/20 border-b border-rose-200 dark:border-rose-800 shrink-0">
            <p className="text-sm text-rose-700 dark:text-rose-300">Erreur : {error}</p>
          </div>
        )}

        {/* ── Contenu ──────────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-10 py-6 bg-white dark:bg-slate-900">
          {isLoading && !cleanMd && (
            <div className="flex items-center gap-3 text-slate-400 dark:text-slate-500 text-sm py-16 justify-center">
              <Loader2 size={16} className="animate-spin" />
              Génération du rapport en cours…
            </div>
          )}

          {frozenMd ? (
            <div key="final" className="w-full max-w-none">
              <FinalReportView md={frozenMd} components={frozenComponentsRef.current} />
            </div>
          ) : cleanMd ? (
            <div key="streaming" className="w-full max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw]}
                components={mdComponents}
              >
                {cleanMd}
              </ReactMarkdown>
              {isLoading && (
                <span className="inline-block w-1.5 h-4 bg-violet-500 dark:bg-violet-400 animate-pulse rounded-sm align-middle" />
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>,
    document.body
  )
}
