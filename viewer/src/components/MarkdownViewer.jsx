import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { useMemo, useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import TTSButton from './TTSButton'
import KeywordForceGraph from './KeywordForceGraph'
import FluxBarChart from './FluxBarChart'

mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' })

/** Rend le SVG Mermaid responsive.
 * Calcule l'aspect-ratio depuis le viewBox pour éviter height:0 sur les mindmaps.
 */
function makeResponsiveSvg(svg) {
  return svg.replace(/<svg([^>]*)>/i, (_, attrs) => {
    const vbMatch    = attrs.match(/viewBox="([^"]*)"/i)
    const wMatch     = attrs.match(/\bwidth="([^"]*)"/i)
    const hMatch     = attrs.match(/\bheight="([^"]*)"/i)
    const styleMatch = attrs.match(/\bstyle="([^"]*)"/i)

    let extraViewBox = ''
    let arStyle = 'min-height:200px;'  // fallback si aucune dimension trouvée

    let vb = vbMatch ? vbMatch[1] : null

    if (!vb) {
      // Essayer attributs explicites, puis style (ex. mindmap: style="max-width:Npx;")
      let w = wMatch ? parseFloat(wMatch[1]) : NaN
      let h = hMatch ? parseFloat(hMatch[1]) : NaN
      if ((isNaN(w) || isNaN(h)) && styleMatch) {
        const s = styleMatch[1]
        if (isNaN(w)) { const m = s.match(/(?:max-width|width)\s*:\s*([\d.]+)px/i); if (m) w = parseFloat(m[1]) }
        if (isNaN(h)) { const m = s.match(/height\s*:\s*([\d.]+)px/i);             if (m) h = parseFloat(m[1]) }
      }
      if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0) {
        vb = `0 0 ${w} ${h}`
        extraViewBox = ` viewBox="${vb}"`
      }
    }

    if (vb) {
      const parts = vb.trim().split(/\s+/)
      if (parts.length === 4) {
        const vbW = parseFloat(parts[2]) - parseFloat(parts[0])
        const vbH = parseFloat(parts[3]) - parseFloat(parts[1])
        if (vbW > 0 && vbH > 0) arStyle = `aspect-ratio:${vbW}/${vbH};`
      }
    }

    const cleaned = attrs
      .replace(/\s+width="[^"]*"/gi, '')
      .replace(/\s+height="[^"]*"/gi, '')
      .replace(/\s+style="[^"]*"/gi, '')
    return `<svg${cleaned}${extraViewBox} width="100%" style="width:100%;${arStyle}max-width:100%;display:block;">`
  })
}

/** Sanitise le code Mermaid généré par l'IA avant rendu. */
function sanitizeMermaid(code) {
  let s = (code ?? '')
    // 1. Supprimer les accents
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    // 2. Tirets Unicode → tiret ASCII
    .replace(/[\u2013\u2014\u2012\u2015]/g, '-')
    // 3. Guillemets français et typographiques → guillemet droit
    .replace(/[\u00AB\u00BB\u2018\u2019\u201A\u201B\u201C\u201D\u201E\u201F]/g, "'")
    // 4. Points de suspension → trois points
    .replace(/\u2026/g, '...')
    // 5. Puces et caractères de liste → tiret
    .replace(/[\u2022\u2023\u25AA\u25AB\u25B6\u25CF\u2043]/g, '-')
    // 6. Espaces insécables et autres espaces Unicode → espace normal
    .replace(/[\u00A0\u202F\u2009\u200A\u2007]/g, ' ')
    // 7. Supprimer les caractères de contrôle sauf newline/tab
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
  // 8. Auto-quoter les labels [bracket] non quotés contenant des caractères spéciaux
  //    Ex: A[OpenAI (US)] → A["OpenAI (US)"]  |  B[x: valeur] → B["x: valeur"]
  s = s.replace(/\[([^\]"\[]*[():#&<>/\\][^\]"\[]*)\]/g,
    (_, inner) => `["${inner.replace(/"/g, "'")}"]`)
  // 9. Idem pour les labels (paren) ronds non quotés avec caractères spéciaux
  //    Ex: A(text: note) → A("text: note")    -- attention: ne pas toucher les subgraphs
  s = s.replace(/(?<=[A-Za-z0-9_])\(([^)"(]*[:#&<>/\\][^)"(]*)\)/g,
    (_, inner) => `("${inner.replace(/"/g, "'")}")`)
  // 10. Supprimer les blocs <think>...</think> que certains modèles IA insèrent
  s = s.replace(/<think>[\s\S]*?<\/think>/gi, '')
  // 11. Retirer tous les préfixes parasites avant la déclaration du type de diagramme
  //     (supporte plusieurs lignes de preamble + xychart-beta + stateDiagram-v2)
  const m11 = s.match(/^(?:xychart-beta|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|gantt|pie|mindmap|gitGraph|erDiagram|journey|quadrantChart|xychart|block|packet|architecture|timeline|sankey|zenuml)/im)
  if (m11 && m11.index > 0) s = s.slice(m11.index)
  return s.trim()
}

function MermaidBlock({ code }) {
  const id           = useRef(`mermaid-${Math.random().toString(36).slice(2)}`)
  const lastCode     = useRef(null)
  const [svgHtml, setSvgHtml] = useState(null)
  const [errMsg,  setErrMsg ] = useState(null)

  const clean = sanitizeMermaid(code)
  useEffect(() => {
    if (!clean || clean === lastCode.current) return
    let cancelled = false
    // Debounce 300 ms — le SVG précédent reste affiché, aucun flickering
    const timer = setTimeout(() => {
      mermaid.parse(clean)
        .then(() => mermaid.render(id.current, clean))
        .then(({ svg }) => {
          if (cancelled) return
          lastCode.current = clean
          setSvgHtml(makeResponsiveSvg(svg))
          setErrMsg(null)
        })
        .catch(err => {
          if (cancelled) return
          if (!lastCode.current) {
            const msg = (err?.message ?? 'Erreur Mermaid').split('\n').find(l => l.trim()) ?? 'Erreur Mermaid'
            setErrMsg(msg.length > 120 ? msg.slice(0, 120) + '…' : msg)
          }
        })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [clean])

  if (errMsg && !svgHtml) {
    return (
      <div className="my-6 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3">
        <p className="text-xs text-amber-700 dark:text-amber-400 mb-2">⚠ Diagramme non rendu : {errMsg}</p>
        <pre className="text-xs text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-900/60 rounded p-2 overflow-x-auto whitespace-pre-wrap select-all">{clean}</pre>
      </div>
    )
  }
  return (
    <div
      className="my-6 w-full flex justify-center overflow-x-auto"
      style={{ opacity: svgHtml ? 1 : 0, transition: 'opacity 0.3s ease' }}
      dangerouslySetInnerHTML={svgHtml ? { __html: svgHtml } : undefined}
    />
  )
}

/** Parse le frontmatter YAML entre --- et retourne { meta, body } */
function parseFrontmatter(content) {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) return { meta: null, body: content }
  const meta = {}
  match[1].split('\n').forEach(line => {
    const idx = line.indexOf(':')
    if (idx > 0) {
      const key = line.slice(0, idx).trim()
      const val = line.slice(idx + 1).trim()
      if (key && val) meta[key] = val
    }
  })
  return { meta: Object.keys(meta).length ? meta : null, body: match[2] }
}

/** Prétraite le corps : remplace {{TOC}} et === (saut de page iA Writer) */
function preprocess(body) {
  return body
    .replace(/\{\{TOC\}\}/g, '*[Table des matières — générée automatiquement]*')
    .replace(/^===\s*$/gm, '---')
}

// ── Composants de rendu Markdown (définis hors du composant pour référence stable)
// Cela empêche React de remonter les composants enfants (ex: KeywordForceGraph)
// à chaque re-rendu de MarkdownViewer, ce qui préserve l'état interne (zoom, etc.)
const mdComponents = {
          h1: ({ children }) => (
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mt-8 mb-4 pb-2 border-b border-slate-200 dark:border-slate-700 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100 mt-7 mb-3">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-base font-semibold text-slate-800 dark:text-slate-200 mt-5 mb-2">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mt-4 mb-1">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="text-base text-slate-700 dark:text-slate-300 mb-4 leading-7">{children}</p>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#007AFF] dark:text-[#0A84FF] hover:text-blue-500 dark:hover:text-blue-300 underline underline-offset-2"
            >
              {children}
            </a>
          ),
          pre: ({ children }) => {
            const child = Array.isArray(children) ? children[0] : children
            if (child?.props?.className === 'language-mermaid') {
              return <>{children}</>
            }
            if (child?.props?.className === 'language-keyword-graph') {
              return <>{children}</>
            }
            if (child?.props?.className === 'language-flux-chart') {
              return <>{children}</>
            }
            return (
              <pre className="bg-slate-100 dark:bg-slate-950 rounded-xl p-4 overflow-x-auto mb-4 border border-slate-200 dark:border-slate-800">
                {children}
              </pre>
            )
          },
          code: ({ className, children }) => {
            if (className === 'language-mermaid') {
              return <MermaidBlock code={String(children).trim()} />
            }
            if (className === 'language-keyword-graph') {
              try {
                const kwData = JSON.parse(String(children).trim())
                return (
                  <div className="my-6 w-full" style={{ height: 600 }}>
                    <KeywordForceGraph keywords={kwData} />
                  </div>
                )
              } catch {
                return null
              }
            }
            if (className === 'language-flux-chart') {
              try {
                const items = JSON.parse(String(children).trim())
                return <FluxBarChart items={items} />
              } catch {
                return null
              }
            }
            const isBlock = className || String(children).includes('\n')
            if (!isBlock) {
              return (
                <code className="bg-slate-100 dark:bg-slate-800 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded-full text-[0.85em] font-mono">
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
          ul: ({ children }) => (
            <ul className="list-disc text-slate-700 dark:text-slate-300 mb-4 space-y-1 ml-5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal text-slate-700 dark:text-slate-300 mb-4 space-y-1 ml-5">{children}</ol>
          ),
          li: ({ children }) => <li className="text-base text-slate-700 dark:text-slate-300 leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-blue-500/60 pl-4 italic text-slate-500 dark:text-slate-400 my-4">
              {children}
            </blockquote>
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
            <th className="border-b border-slate-200 dark:border-slate-700 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-slate-200/50 dark:border-slate-700/50 px-4 py-2.5">{children}</td>
          ),
          img: ({ src, alt }) => (
            <figure className="my-6">
              <img
                src={src}
                alt={alt}
                className="max-w-full rounded-xl border border-slate-200 dark:border-slate-700"
                loading="lazy"
              />
              {alt && (
                <figcaption className="text-center text-slate-400 dark:text-slate-500 text-sm mt-2 italic">{alt}</figcaption>
              )}
            </figure>
          ),
          hr: () => <hr className="border-slate-200 dark:border-slate-700 my-8" />,
          strong: ({ children }) => (
            <strong className="text-slate-900 dark:text-slate-100 font-semibold">{children}</strong>
          ),
          em: ({ children }) => <em className="text-slate-700 dark:text-slate-300 italic">{children}</em>,
}

export default function MarkdownViewer({ content }) {
  const { meta, body } = useMemo(() => {
    const { meta, body } = parseFrontmatter(content)
    return { meta, body: preprocess(body) }
  }, [content])

  return (
    <div className="max-w-3xl mx-auto">
      {/* Bouton lecture à voix haute */}
      <div className="no-print flex justify-end mb-2">
        <TTSButton text={body} size={14} />
      </div>

      {/* Métadonnées frontmatter */}
      {meta && (
        <div className="mb-6 p-4 bg-white/60 dark:bg-slate-800/60 rounded-xl border border-slate-200 dark:border-slate-700 text-sm">
          <div className="text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-3">
            Métadonnées du rapport
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
            {Object.entries(meta).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-slate-400 dark:text-slate-500 text-xs">{k}</dt>
                <dd className="text-slate-700 dark:text-slate-300 text-xs">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Rendu Markdown */}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={mdComponents}
      >
        {body}
      </ReactMarkdown>
    </div>
  )
}
