/**
 * ArticleFullReportDialog — génère et affiche un rapport complet d'un article.
 *
 * - Modal centré 80 % × 88 % (bascule plein écran via bouton)
 * - Bande d'avatars d'entités en en-tête (Option 6A)
 * - Image principale de l'article sous les avatars
 * - Corps en Markdown streamé (SSE) avec surlignage d'entités (Option 5B)
 *   et diagrammes Mermaid générés par l'IA (Option M1)
 * - Actions : copier, télécharger .md, imprimer/PDF, régénérer, plein écran, fermer
 */

import { useState, useEffect, useRef, useCallback, memo } from 'react'
import { createPortal } from 'react-dom'
import {
  X, Maximize2, Minimize2, Copy, Download, Printer,
  RefreshCw, FileText, Check, Terminal, BookOpen, Loader2,
  Hash, FolderOpen, Youtube, Images,
} from 'lucide-react'
import YouTubePanel from './YouTubePanel'
import ArticleGalleryPanel from './ArticleGalleryPanel'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import mermaid from 'mermaid'
import EntityHighlighter, { EntityHighlighterSegments } from './EntityHighlighter'
import { obsidianUri, openInObsidian } from '../utils/obsidian'

mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' })

// ── Mermaid block ─────────────────────────────────────────────────────────────

/** Nettoie le code Mermaid avant rendu (artifacts markdown fréquents) */
function sanitizeMermaidCode(raw) {
  let s = (raw ?? '')
    .replace(/^```mermaid\s*/i, '')   // backticks résiduels (début)
    .replace(/```\s*$/,         '')   // backticks résiduels (fin)
    .replace(/&amp;/g,          '&')  // entités HTML
    .replace(/&lt;/g,           '<')
    .replace(/&gt;/g,           '>')
    .replace(/\r\n/g,           '\n') // CRLF → LF
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
  s = s.replace(/(?<=[A-Za-z0-9_])\(([^)"(]*[:#&<>/\\][^)"(]*)\)/g,
    (_, inner) => `("${inner.replace(/"/g, "'")}")`)
  // 10. Supprimer les blocs <think>...</think> que certains modèles IA insèrent
  s = s.replace(/<think>[\s\S]*?<\/think>/gi, '')
  // 11. Retirer tous les préfixes parasites avant la déclaration du type de diagramme
  //     (supporte plusieurs lignes de preamble + xychart-beta + stateDiagram-v2)
  const m11 = s.match(/^(?:xychart-beta|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|gantt|pie|mindmap|gitGraph|erDiagram|journey|quadrantChart|xychart|block|packet|architecture|timeline|sankey|zenuml)/im)
  if (m11 && m11.index > 0) s = s.slice(m11.index)
  // 12. Pour les diagrammes timeline : le « : » dans un titre de section est
  //     interprété comme séparateur d'événement par Mermaid → crash interne
  //     "undefined is not an object (.events)". On remplace « : » par « - ».
  //     Ex: "section 2004-2015 : Debut" → "section 2004-2015 - Debut"
  if (/^timeline\s*$/im.test(s)) {
    s = s.replace(/^(\s*section\s+[^:\n]+)\s*:\s*(.+)/gim, '$1 - $2')
  }
  return s.trim()
}

function MermaidBlock({ code, isStreaming }) {
  const containerRef = useRef(null)
  const id           = useRef(`mermaid-rpt-${Math.random().toString(36).slice(2)}`)
  const [errMsg,   setErrMsg]   = useState(null)
  const [rendered, setRendered] = useState(false)

  const clean = sanitizeMermaidCode(code)

  // Ne tenter le rendu qu'une fois le stream terminé — évite le thrashing
  // de layout à chaque token (le code Mermaid est partiel pendant le stream)
  useEffect(() => {
    if (isStreaming) return            // attendre la fin du stream
    if (!containerRef.current) return
    setErrMsg(null)
    // Ne pas remettre rendered=false ici : le SVG précédent reste visible
    // pendant le re-rendu, évitant le flash "placeholder h-10 → plein écran"

    // Annuler si le composant est démonté avant la fin du rendu
    let cancelled = false

    mermaid.parse(clean)
      .then(() => mermaid.render(id.current, clean))
      .then(({ svg }) => {
        if (!cancelled && containerRef.current) {
          // Rendre le SVG responsive AVANT injection dans le DOM :
          // on manipule la chaîne pour éviter tout recalcul de layout
          // qui remettrait les dimensions fixes (flex reflow, Mermaid style attr…)
          const responsiveSvg = svg.replace(/<svg([^>]*)>/i, (_, attrs) => {
            const vbMatch    = attrs.match(/viewBox="([^"]*)"/i)
            const wMatch     = attrs.match(/\bwidth="([^"]*)"/i)
            const hMatch     = attrs.match(/\bheight="([^"]*)"/i)
            const styleMatch = attrs.match(/\bstyle="([^"]*)"/i)
            let extraViewBox = ''
            let arStyle = 'min-height:200px;'
            let vb = vbMatch ? vbMatch[1] : null
            if (!vb) {
              let w = wMatch ? parseFloat(wMatch[1]) : NaN
              let h = hMatch ? parseFloat(hMatch[1]) : NaN
              if ((isNaN(w) || isNaN(h)) && styleMatch) {
                const s = styleMatch[1]
                if (isNaN(w)) { const m = s.match(/(?:max-width|width)\s*:\s*([\d.]+)px/i); if (m) w = parseFloat(m[1]) }
                if (isNaN(h)) { const m = s.match(/height\s*:\s*([\d.]+)px/i);             if (m) h = parseFloat(m[1]) }
              }
              if (!isNaN(w) && !isNaN(h) && w > 0 && h > 0) { vb = `0 0 ${w} ${h}`; extraViewBox = ` viewBox="${vb}"` }
            }
            if (vb) {
              const parts = vb.trim().split(/\s+/)
              if (parts.length === 4) {
                const vbW = parseFloat(parts[2]) - parseFloat(parts[0])
                const vbH = parseFloat(parts[3]) - parseFloat(parts[1])
                if (vbW > 0 && vbH > 0) arStyle = `aspect-ratio:${vbW}/${vbH};`
              }
            }
            // Supprimer width, height et tout style inline existant
            const cleaned = attrs
              .replace(/\s+width="[^"]*"/gi,  '')
              .replace(/\s+height="[^"]*"/gi, '')
              .replace(/\s+style="[^"]*"/gi,  '')

            return `<svg${cleaned}${extraViewBox} width="100%" style="width:100%;${arStyle}max-width:100%;display:block;">`
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

  // Pendant le stream : placeholder stable (hauteur fixe, pas de layout shift)
  if (isStreaming) {
    return (
      <div className="my-6 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 animate-pulse" />
    )
  }

  if (errMsg) {
    return (
      <div className="my-6 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-4">
        <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-2">
          ⚠ Diagramme Mermaid non rendu — erreur de syntaxe
        </p>
        <p className="text-xs text-amber-600 dark:text-amber-500 font-mono mb-3 break-all">{errMsg}</p>
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

// ── Vue finale gelée ──────────────────────────────────────────────────────────
// Montée une seule fois quand le stream est terminé.
// Reçoit des props stables (md, components) → aucun re-render, aucun flash Mermaid.
const FinalReportView = memo(function FinalReportView({ md, components }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={components}
    >
      {md}
    </ReactMarkdown>
  )
})

// ── Entity avatar (bande en-tête) ─────────────────────────────────────────────

const CHIP_STYLE = {
  PERSON:  'bg-violet-100 dark:bg-violet-900/50 text-violet-800 dark:text-violet-200 border-violet-200 dark:border-violet-800',
  ORG:     'bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-800',
  PRODUCT: 'bg-orange-100 dark:bg-orange-900/50 text-orange-800 dark:text-orange-200 border-orange-200 dark:border-orange-800',
  GPE:     'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-800',
  EVENT:   'bg-amber-100 dark:bg-amber-900/50 text-amber-800 dark:text-amber-200 border-amber-200 dark:border-amber-800',
  LOC:     'bg-teal-100 dark:bg-teal-900/50 text-teal-800 dark:text-teal-200 border-teal-200 dark:border-teal-800',
}
const FALLBACK_CHIP = 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600'

// ── Suppression des accents (réutilisée pour les slugs Obsidian) ─────────────
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

// ── Frontmatter Obsidian complet depuis le JSON article ──────────────────────
// geoData : { "Paris": { lat: 48.85, lon: 2.35 }, "France": { lat: 46.2, lon: 2.2 }, ... }
function buildArticleObsidianFrontmatter(article, geoData = {}) {
  const today = new Date().toISOString().slice(0, 10)

  // Collecter toutes les entités nommées pour les tags
  const entities  = article.entities ?? {}
  const entityTags = Object.values(entities)
    .flat()
    .filter(v => v && typeof v === 'string' && v.trim())
  const sources   = String(article['Sources'] ?? '')
  const allTags   = [...new Set([sources, ...entityTags].filter(Boolean))].slice(0, 30)
  const tagLines  = allTags.map(t => `  - "${slugTag(t)}"`).join('\n')

  // Entités par type (listes YAML pour les propriétés Obsidian)
  const typeMap   = { PERSON: 'personnes', ORG: 'organisations', GPE: 'lieux',
                      LOC: 'lieux_geographiques', PRODUCT: 'produits', EVENT: 'evenements' }
  const entLines  = Object.entries(typeMap)
    .map(([type, key]) => {
      const vals = Array.isArray(entities[type]) ? entities[type] : []
      if (!vals.length) return null
      return `${key}:\n` + vals.map(v => `  - "${String(v).replace(/"/g, "'")}"`).join('\n')
    })
    .filter(Boolean)
    .join('\n')

  // ── Géolocalisation ───────────────────────────────────────────────────────
  // GPE principale : première GPE ayant des coordonnées résolues
  const gpeList = Array.isArray(entities['GPE']) ? entities['GPE'] : []
  const locList = Array.isArray(entities['LOC']) ? entities['LOC'] : []
  const allGeoNames = [...gpeList, ...locList]
  const mainGeoName = allGeoNames.find(n => geoData[n]?.lat != null)
  const mainCoords  = mainGeoName ? geoData[mainGeoName] : null

  // entites_geo : liste des GPE/LOC avec coordonnées
  const geoEntries = allGeoNames
    .filter(n => geoData[n]?.lat != null)
    .map(n => {
      const c = geoData[n]
      return `  - name: "${String(n).replace(/"/g, "'")}"\n    location: [${c.lat}, ${c.lon}]`
    })

  const q = v => `"${String(v ?? '').replace(/"/g, "'")}"`

  return (
    `---\n` +
    `title: ${q(article['Titre'] || article['Sources'] || 'Rapport')}\n` +
    `date: ${today}\n` +
    `date_publication: ${q(article['Date de publication'] ?? '')}\n` +
    `source: ${q(sources)}\n` +
    `url: ${q(article['URL'] ?? '')}\n` +
    `version: "1.0"\n` +
    (mainCoords ? `location: [${mainCoords.lat}, ${mainCoords.lon}]\n` : '') +
    (article['sentiment']       ? `sentiment: ${q(article['sentiment'])}\n`              : '') +
    (article['score_sentiment'] != null ? `score_sentiment: ${article['score_sentiment']}\n` : '') +
    (article['ton_editorial']   ? `ton_editorial: ${q(article['ton_editorial'])}\n`      : '') +
    (article['score_ton']       != null ? `score_ton: ${article['score_ton']}\n`         : '') +
    (article['score_source']    != null ? `score_source: ${article['score_source']}\n`   : '') +
    (article['temps_lecture_label'] ? `temps_lecture: ${q(article['temps_lecture_label'])}\n` : '') +
    `tags:\n${tagLines || '  - rapport'}\n` +
    (entLines ? entLines + '\n' : '') +
    (geoEntries.length ? `entites_geo:\n${geoEntries.join('\n')}\n` : '') +
    `type: Rapport-WUDD-ai\n` +
    `statut: generated\n` +
    `---\n\n`
  )
}

// ── Corps de note Obsidian structuré ─────────────────────────────────────────
// geoData : { "Paris": { lat, lon }, ... } — optionnel
function buildObsidianNoteBody(article, geoData = {}) {
  const entities = article.entities ?? {}
  const sources  = String(article['Sources'] ?? '')
  const url      = article['URL'] ?? ''
  const score    = article['score_source'] != null ? ` — Crédibilité : **${article['score_source']}/100**` : ''
  const lecture  = article['temps_lecture_label'] ? ` — ${article['temps_lecture_label']}` : ''
  const sentiment = [article['sentiment'], article['ton_editorial']].filter(Boolean).join(' / ')

  let body = ''

  // Images
  const imgs = Array.isArray(article['Images']) ? article['Images'] : []
  for (const img of imgs.slice(0, 2)) {
    const imgUrl = img?.URL || img?.url || ''
    if (imgUrl) body += `![](${imgUrl})\n\n`
  }

  // Résumé
  if (article['Résumé']) {
    body += `## Résumé\n\n${article['Résumé']}\n\n`
  }

  // Entités avec liens [[wikilinks]] Obsidian
  const TYPE_LABELS = {
    PERSON: 'Personnes', ORG: 'Organisations', GPE: 'Lieux',
    LOC: 'Lieux géographiques', PRODUCT: 'Produits', EVENT: 'Événements',
    NORP: 'Groupes / nationalités',
  }
  const entSections = Object.entries(TYPE_LABELS)
    .map(([type, label]) => {
      const vals = Array.isArray(entities[type]) ? entities[type] : []
      if (!vals.length) return null
      return `### ${label}\n\n` + vals.map(v => `- [[${v}]]`).join('\n')
    })
    .filter(Boolean)
  if (entSections.length) {
    body += `## Entités\n\n` + entSections.join('\n\n') + '\n\n'
  }

  // Géolocalisation (si coordonnées disponibles)
  const gpeList = Array.isArray(entities['GPE']) ? entities['GPE'] : []
  const locList = Array.isArray(entities['LOC']) ? entities['LOC'] : []
  const resolvedGeo = [...gpeList, ...locList].filter(n => geoData[n]?.lat != null)
  if (resolvedGeo.length > 0) {
    body += `## Géographie\n\n`
    body += `| Lieu | Latitude | Longitude |\n|---|---|---|\n`
    for (const name of resolvedGeo) {
      const c = geoData[name]
      body += `| [[${name}]] | ${c.lat} | ${c.lon} |\n`
    }
    body += '\n'
  }

  // Section source
  body += `## Source\n\n`
  body += `| Champ | Valeur |\n|---|---|\n`
  body += `| Source | **${sources}**${score} |\n`
  if (article['Date de publication']) body += `| Date | ${article['Date de publication']} |\n`
  if (url) body += `| URL | [↗ Lire l'article](${url}) |\n`
  if (lecture) body += `| Temps de lecture | ${lecture.replace(' — ', '')} |\n`
  if (sentiment) body += `| Ton / Sentiment | ${sentiment} |\n`
  body += `\n---\n\n`

  return body
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function ArticleFullReportDialog({ article, filePath, obsidianVaultProp, onClose, onReportSaved, onOpenFile }) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [reportMd, setReportMd]         = useState('')
  const [isLoading, setIsLoading]       = useState(true)
  const [error, setError]               = useState(null)
  const [copied, setCopied]             = useState(false)
  const [exportState, setExportState]   = useState({ local: null, obsidian: null })
  const [obsidianVault, setObsidianVault] = useState(obsidianVaultProp ?? null)
  const [youtubeOpen, setYoutubeOpen]   = useState(false)
  const [galleryOpen, setGalleryOpen]   = useState(false)
  // frozenMd : snapshot du markdown au moment où le stream se termine.
  // La FinalReportView est montée avec ce snapshot et ne change plus jamais.
  const [frozenMd,  setFrozenMd]        = useState(null)
  const frozenComponentsRef             = useRef(null)  // components capturés à la fin du stream
  const abortRef = useRef(null)

  const entities     = article.entities ?? {}
  const titre        = article['Titre']?.trim() || article['Sources'] || 'Rapport complet'
  const resume       = article['Résumé'] ?? ''
  const url          = article['URL'] ?? ''
  const sources      = article['Sources'] ?? ''
  const date         = article['Date de publication'] ?? ''
  const sentiment    = article['sentiment'] ?? ''
  const ton          = article['ton_editorial'] ?? ''
  const motCle       = article['mot_cle'] ?? ''
  const termeDeclencheur = article['terme_declencheur'] ?? ''
  const motCleLabel   = (termeDeclencheur && termeDeclencheur.toLowerCase() !== motCle.toLowerCase()) ? termeDeclencheur : motCle
  const motCleTooltip = (termeDeclencheur && termeDeclencheur.toLowerCase() !== motCle.toLowerCase()) ? `Mot-clé parent : ${motCle}` : 'Mot-clé de collecte'
  const fichierSource = article['fichier_source'] ?? ''
  const mainImageUrl = (() => {
    const imgs = article['Images']
    if (!Array.isArray(imgs) || !imgs.length) return null
    return imgs.find(i => i?.URL)?.URL ?? imgs.find(i => i?.url)?.url ?? null
  })()

  // ── Inject/remove print CSS ──────────────────────────────────────────────────
  useEffect(() => {
    const style = document.createElement('style')
    style.setAttribute('data-article-report-print', '')
    style.textContent = `
      @media print {
        /* Masquer tout sauf le wrapper du portal (ancêtre direct de body) */
        body > *:not(#article-report-portal) { display: none !important; }

        /* Supprimer backdrop / positionnement fixe du wrapper */
        #article-report-portal {
          position: static !important;
          display: block !important;
          background: transparent !important;
          backdrop-filter: none !important;
          padding: 0 !important;
          inset: unset !important;
        }

        /* La boîte de dialogue s'étale naturellement sur toutes les pages */
        #article-report-print-root {
          position: static !important;
          display: block !important;
          width: 100% !important;
          max-width: none !important;
          height: auto !important;
          overflow: visible !important;
          background: white !important;
          border-radius: 0 !important;
          box-shadow: none !important;
          border: none !important;
        }

        .no-print { display: none !important; }

        /* Les conteneurs scrollables doivent laisser passer le contenu */
        #article-report-print-root .overflow-y-auto {
          overflow: visible !important;
          height: auto !important;
          max-height: none !important;
        }
      }
    `
    document.head.appendChild(style)
    return () => style.remove()
  }, [])


  // ── SSE streaming ─────────────────────────────────────────────────────────────
  const startStream = useCallback(() => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setReportMd('')
    setFrozenMd(null)   // réinitialiser la vue gelée pour repartir en streaming
    setIsLoading(true)
    setError(null)

    const params = new URLSearchParams({
      url,
      titre,
      sources,
      date,
      resume:    resume.slice(0, 3000),
      entities:  JSON.stringify(entities),
      sentiment,
      ton,
      image_url: mainImageUrl ?? '',
    })

    fetch(`/api/article/full-report?${params}`, { signal: ac.signal })
      .then(async r => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          const errMsg = d.error
          setError(typeof errMsg === 'string' ? errMsg : (errMsg?.message ?? `Erreur HTTP ${r.status}`))
          setIsLoading(false)
          return
        }
        const reader  = r.body.getReader()
        const decoder = new TextDecoder()
        let buffer    = ''
        // Filtrage inline des blocs <think>…</think> émis par les modèles IA
        // (approche stateful identique à EntityFullReportDialog.consumeSse)
        let inThink = false

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const raw = line.slice(6).trim()
            if (!raw || raw === '[DONE]') continue
            try {
              const parsed = JSON.parse(raw)
              if (parsed.choices?.[0]?.delta?.content) {
                // Filtrer les blocs <think> inline pour éviter qu'ils
                // n'apparaissent dans le markdown final (notamment dans
                // les diagrammes Mermaid où ils génèrent des erreurs de syntaxe)
                let rem = parsed.choices[0].delta.content
                let toAppend = ''
                while (rem.length > 0) {
                  if (!inThink) {
                    const s = rem.indexOf('<think>')
                    if (s === -1) { toAppend += rem; break }
                    if (s > 0) toAppend += rem.slice(0, s)
                    rem = rem.slice(s + 7)
                    inThink = true
                  } else {
                    const e = rem.indexOf('</think>')
                    if (e === -1) break   // bloc <think> non fermé dans ce chunk
                    rem = rem.slice(e + 8)
                    inThink = false
                  }
                }
                if (toAppend) setReportMd(prev => prev + toAppend)
              } else if (parsed.error) {
                const errMsg = parsed.error
                setError(typeof errMsg === 'string' ? errMsg : (errMsg?.message ?? JSON.stringify(errMsg)))
              }
            } catch { /* ignorer les chunks malformés */ }
          }
        }
        setIsLoading(false)
      })
      .catch(e => {
        if (e.name !== 'AbortError') {
          setError(e.message)
          setIsLoading(false)
        }
      })
  }, [url, titre, sources, date, resume, entities, sentiment, ton, mainImageUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    startStream()
    return () => abortRef.current?.abort()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Récupération du nom du vault Obsidian ─────────────────────────────────────
  useEffect(() => {
    fetch('/api/config/obsidian')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.vault_name) setObsidianVault(d.vault_name) })
      .catch(() => {})
  }, [])

  // ── Gel du markdown à la fin du stream ────────────────────────────────────────
  // On capture cleanMd au moment précis où isLoading passe à false.
  // frozenMd ne changera plus jusqu'au prochain startStream → FinalReportView stable.
  useEffect(() => {
    if (!isLoading && cleanMd) {
      // Capturer le snapshot du markdown ET les composants (référence stable)
      // pour que memo(FinalReportView) ne se re-rende jamais après le gel.
      frozenComponentsRef.current = mdComponents
      setFrozenMd(cleanMd)
    }
  }, [isLoading]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Escape key ────────────────────────────────────────────────────────────────
  useEffect(() => {
    const h = e => { if (e.key === 'Escape' && !isFullscreen) onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose, isFullscreen])

  // ── Derived state ─────────────────────────────────────────────────────────────
  // Les blocs <think> sont filtrés inline dans startStream (approche stateful).
  // Ce filet de sécurité supprime tout résidu éventuel (case-insensitive + blocs non fermés).
  const cleanMd = reportMd
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/<think>[\s\S]*/gi, '')
    .trim()

  // Build entity chip list (all types, PERSON/ORG/PRODUCT first)
  const chipList = []
  const TYPE_ORDER = ['PERSON', 'ORG', 'PRODUCT', 'GPE', 'EVENT', 'LOC']
  const remaining = Object.keys(entities).filter(t => !TYPE_ORDER.includes(t))
  for (const type of [...TYPE_ORDER, ...remaining]) {
    const vals = entities[type]
    if (!Array.isArray(vals)) continue
    for (const v of vals.slice(0, 6)) {
      if (typeof v === 'string' && v.trim()) chipList.push({ name: v.trim(), type })
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────────
  const handleCopy = async () => {
    await navigator.clipboard.writeText(cleanMd).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleOpenChatbot = () => {
    window.dispatchEvent(new CustomEvent('wudd:openArticleChatbot', {
      detail: { titre, sources, date, url, entities, resume, reportMd: cleanMd },
    }))
  }

  // Impression via window.open avec CSS auto-contenu.
  // L'iframe était non fiable : onload pouvait tirer avant l'attachement du handler,
  // et en mode Vite dev les CSS sont injectés par JS (pas de <link>) → page blanche.
  const handlePrint = () => {
    const contentEl = document.querySelector('#article-report-print-root .overflow-y-auto')
    if (!contentEl) return

    const win = window.open('', '_blank')
    if (!win) return   // popup bloqué par le navigateur

    const meta = [sources, date, sentiment, ton].filter(Boolean).join(' · ')

    win.document.write(`<!DOCTYPE html><html lang="fr"><head>
<meta charset="utf-8">
<title>${titre.replace(/</g, '&lt;')}</title>
<style>
  *    { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Literata', Georgia, 'Times New Roman', serif;
         font-size: 14px; line-height: 1.75; color: #1e293b;
         max-width: 860px; margin: 0 auto; padding: 2cm; background: #fff; }
  h1   { font-size: 1.75em; font-weight: 700; border-bottom: 2px solid #e2e8f0;
         padding-bottom: .4em; margin: 1.6em 0 .8em; }
  h2   { font-size: 1.35em; font-weight: 600; margin: 1.4em 0 .6em; }
  h3   { font-size: 1.1em;  font-weight: 600; margin: 1.2em 0 .5em; }
  h4   { font-size: 1em;    font-weight: 600; margin: 1em 0 .4em; }
  p    { margin: .75em 0; }
  ul, ol { padding-left: 1.8em; margin: .75em 0; }
  li   { margin: .25em 0; }
  blockquote { border-left: 4px solid #3b82f6; padding-left: 1em;
               color: #64748b; font-style: italic; margin: 1em 0; }
  code { background: #f1f5f9; padding: .15em .4em; border-radius: .3em;
         font-family: 'Courier New', monospace; font-size: .88em; }
  pre  { background: #f1f5f9; padding: 1em; border-radius: .5em;
         overflow-x: auto; margin: 1em 0; }
  pre code { background: none; padding: 0; }
  table { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: .92em; }
  th, td { border: 1px solid #e2e8f0; padding: .45em .85em; text-align: left; }
  th   { background: #f8fafc; font-weight: 600; }
  img  { max-width: 100%; height: auto; display: block; margin: .5em 0; }
  svg  { width: 100% !important; height: auto !important;
         max-width: 100% !important; display: block !important; }
  a    { color: #2563eb; }
  hr   { border: 0; border-top: 1px solid #e2e8f0; margin: 1.5em 0; }
  figcaption { font-size: .82em; color: #94a3b8; text-align: center;
               margin-top: .3em; font-style: italic; }
  .meta { font-size: .82em; color: #64748b; margin-bottom: 1.5em; }
  @media print { body { padding: 0; } }
</style>
</head>
<body>
<h1>${titre.replace(/</g, '&lt;')}</h1>
${meta ? `<p class="meta">${meta.replace(/</g, '&lt;')}</p>` : ''}
${contentEl.innerHTML}
</body></html>`)
    win.document.close()
    win.focus()
    // Courte pause pour laisser le navigateur rendre avant d'ouvrir la dialog d'impression
    setTimeout(() => { win.print(); win.close() }, 300)
  }

  const handleDownload = () => {
    const fname = `rapport_${sources || 'article'}_${date || new Date().toISOString().slice(0, 10)}.md`
      .replace(/[/\\: ]/g, '-')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([cleanMd], { type: 'text/markdown' }))
    a.download = fname
    a.click()
  }

  const handleExport = async (target) => {
    setExportState(prev => ({ ...prev, [target]: 'saving' }))

    let markdown = cleanMd
    let filename
    let resumeForDedup = ''

    if (target === 'obsidian') {
      // ── Nom de fichier Obsidian : YYYY-MM-DD_source_slug-titre.md ───────────
      const today      = new Date().toISOString().slice(0, 10)
      const srcSlug    = removeAccents(sources || 'article')
        .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 15)
      const titreSlug  = removeAccents(titre || '')
        .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
      filename = `${today}_${srcSlug}_${titreSlug}`

      // ── Géocodage des entités GPE/LOC ────────────────────────────────────────
      let geoData = {}
      const gpeList  = Array.isArray(entities['GPE']) ? entities['GPE'] : []
      const locList  = Array.isArray(entities['LOC']) ? entities['LOC'] : []
      const geoNames = [...new Set([...gpeList, ...locList])].filter(Boolean)
      if (geoNames.length > 0) {
        try {
          const geoRes = await fetch('/api/entities/geocode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(geoNames),
          })
          if (geoRes.ok) geoData = await geoRes.json()
        } catch (_) { /* geocodage optionnel — on continue sans */ }
      }

      // ── Contenu de la note Obsidian ──────────────────────────────────────────
      const front    = buildArticleObsidianFrontmatter(article, geoData)
      const noteBody = buildObsidianNoteBody(article, geoData)
      // Corps IA : supprimer le frontmatter existant du rapport AI
      const aiReport = cleanMd.replace(/^---[\s\S]*?---\n\n?/, '')
      markdown = front + noteBody + `## Rapport IA\n\n` + aiReport

      // MD5 du résumé pour la déduplication côté serveur
      resumeForDedup = article['Résumé'] ?? ''
    } else {
      filename = `rapport_${sources || 'article'}_${date || new Date().toISOString().slice(0, 10)}`
        .replace(/[/\\: ]/g, '-')
    }

    try {
      const r = await fetch('/api/export/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown, filename, target, resume: resumeForDedup }),
      })
      const d = await r.json()
      if (d.ok) {
        const exportResult = {
          ok: true,
          path: d.path,
          filename: d.filename,
          saved_at: d.saved_at,
          deduplicated: d.deduplicated,
        }
        setExportState(prev => ({ ...prev, [target]: exportResult }))

        const rapport = {
          fichier: d.filename,
          chemin:  d.path,
          cible:   target,
          date_creation: d.saved_at,
        }

        // ── Afficher le badge immédiatement dans la session courante ─────────
        onReportSaved?.(article['URL'], rapport)

        // ── Persister les métadonnées dans l'article JSON (pour les rechargements) ──
        if (filePath && article['URL']) {
          fetch('/api/article/set-report-meta', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_path: filePath, article_url: article['URL'], rapport }),
          }).catch(() => {})
        }
      } else {
        setExportState(prev => ({ ...prev, [target]: { ok: false, error: d.error } }))
      }
    } catch (e) {
      setExportState(prev => ({ ...prev, [target]: { ok: false, error: String(e) } }))
    }
  }

  // ── Shared button class ───────────────────────────────────────────────────────
  const btnCls = 'p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors'

  // ── Helper : surligne les nœuds texte inline (string → EntityHighlighterSegments) ─
  // Fonctionne pour les enfants de <p>, <strong>, <em>, <li>…
  const hasEntities = Object.keys(entities).length > 0
  const hilite = (node, key) => {
    if (hasEntities && typeof node === 'string') {
      return <EntityHighlighterSegments key={key} text={node} entities={entities} />
    }
    return node
  }
  const hiliteChildren = (children) =>
    Array.isArray(children) ? children.map((c, i) => hilite(c, i)) : hilite(children, 0)

  // ── ReactMarkdown component overrides ─────────────────────────────────────────
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
    // Entity highlighting — fonctionne pour les paragraphes purs ET mixtes (bold, liens…)
    // On surligne chaque nœud texte inline individuellement
    p: ({ children }) => (
      <p className="font-reading text-lg text-slate-700 dark:text-slate-300 mb-4 leading-7">
        {hiliteChildren(children)}
      </p>
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
    ul: ({ children }) => (
      <ul className="list-disc text-slate-700 dark:text-slate-300 mb-4 space-y-1 ml-5">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal text-slate-700 dark:text-slate-300 mb-4 space-y-1 ml-5">{children}</ol>
    ),
    li: ({ children }) => (
      <li className="font-reading text-lg text-slate-700 dark:text-slate-300 leading-relaxed">{hiliteChildren(children)}</li>
    ),
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
      <strong className="text-slate-900 dark:text-slate-100 font-semibold">
        {hiliteChildren(children)}
      </strong>
    ),
    em: ({ children }) => (
      <em className="text-slate-700 dark:text-slate-300 italic">
        {hiliteChildren(children)}
      </em>
    ),
  }

  // ── Render ─────────────────────────────────────────────────────────────────────
  const portal = createPortal(
    <div
      id="article-report-portal"
      className="hig-overlay-enter fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 print:p-0"
      onClick={e => e.target === e.currentTarget && !isFullscreen && onClose()}
    >
      <div
        id="article-report-print-root"
        className={`hig-modal-enter flex flex-col shadow-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 transition-all duration-200 ${
          isFullscreen
            ? 'fixed inset-0 rounded-none'
            : 'w-[92vw] max-w-[1400px] h-[92vh] rounded-2xl'
        } overflow-hidden`}
      >
        {/* ── Title bar ─────────────────────────────────────────────────────── */}
        <div className="no-print flex items-start gap-2 sm:gap-3 px-3 sm:px-5 py-2 sm:py-3 border-b border-slate-200 dark:border-slate-700 shrink-0 bg-white dark:bg-slate-900">
          <FileText size={17} className="text-blue-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">{titre}</h2>
            <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
              <p className="text-[11px] text-slate-400 dark:text-slate-500">
                {[sources, date, sentiment].filter(Boolean).join(' · ')}
              </p>
              {motCleLabel && (
                <span
                  className="inline-flex items-center gap-1 text-[10px] text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/30 px-1.5 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800"
                  title={motCleTooltip}
                >
                  <Hash size={8} />{motCleLabel}
                </span>
              )}
              {fichierSource && onOpenFile && (
                <button
                  onClick={() => onOpenFile(fichierSource)}
                  className="inline-flex items-center gap-1 text-[10px] text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-900/30 px-1.5 py-0.5 rounded-full border border-sky-200 dark:border-sky-800 hover:bg-sky-100 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
                  title={`Ouvrir ${fichierSource}`}
                >
                  <FolderOpen size={8} />{fichierSource.split('/').pop()}
                </button>
              )}
            </div>
          </div>
          <div className="flex items-center gap-0.5 shrink-0 justify-end">
            {!isLoading && cleanMd && (
              <>
                <button
                  onClick={() => setGalleryOpen(true)}
                  className="hidden sm:flex items-center gap-1 px-2 py-1 mr-1 rounded-lg text-xs font-medium text-cyan-700 dark:text-cyan-300 bg-cyan-50 dark:bg-cyan-900/30 border border-cyan-200 dark:border-cyan-700 hover:bg-cyan-100 dark:hover:bg-cyan-800/40 transition-colors"
                  title="Galerie d’images de cet article"
                >
                  <Images size={12} />
                  <span className="hidden sm:inline">Galerie</span>
                </button>
                <button
                  onClick={() => setYoutubeOpen(true)}
                  className="hidden sm:flex items-center gap-1 px-2 py-1 mr-1 rounded-lg text-xs font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-900/30 border border-rose-200 dark:border-rose-700 hover:bg-rose-100 dark:hover:bg-rose-800/40 transition-colors"
                  title="Vidéos YouTube liées à cet article"
                >
                  <Youtube size={12} />
                  <span className="hidden sm:inline">Vidéos</span>
                </button>
                <button
                  onClick={handleOpenChatbot}
                  className="flex items-center gap-1 px-2 py-1 mr-1 rounded-lg text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-700 hover:bg-emerald-100 dark:hover:bg-emerald-800/40 transition-colors"
                  title="Ouvrir le Terminal IA avec ce rapport en contexte"
                >
                  <Terminal size={12} />
                  <span className="hidden sm:inline">Terminal IA</span>
                </button>
                {/* Export local — icône seule */}
                <div className="relative group">
                  <button
                    onClick={() => handleExport('local')}
                    disabled={exportState.local === 'saving'}
                    title={exportState.local?.ok ? `Enregistré : ${exportState.local.path}` : exportState.local?.error ? `Erreur : ${exportState.local.error}` : 'Sauvegarder dans rapports/'}
                    className={`p-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
                      exportState.local?.ok    ? 'bg-green-50 dark:bg-green-900/30 border-green-300 dark:border-green-700 text-green-700 dark:text-green-300' :
                      exportState.local?.error ? 'bg-red-50 dark:bg-red-900/30 border-red-300 dark:border-red-700 text-red-600 dark:text-red-400' :
                      'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:border-slate-400 hover:text-slate-700'
                    }`}
                  >
                    {exportState.local === 'saving' ? <Loader2 size={14} className="animate-spin" /> : exportState.local?.ok ? <Check size={14} /> : <Download size={14} />}
                  </button>
                  {(exportState.local?.ok || exportState.local?.error) && (
                    <div className="absolute top-full mt-1 right-0 z-10 max-w-xs bg-slate-800 text-white text-[11px] rounded-lg px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap overflow-hidden text-ellipsis">
                      {exportState.local?.ok ? exportState.local.path : exportState.local?.error}
                    </div>
                  )}
                </div>
                {/* Export Obsidian — icône seule */}
                <div className="relative group">
                  <button
                    onClick={() => handleExport('obsidian')}
                    disabled={exportState.obsidian === 'saving'}
                    title={exportState.obsidian?.ok ? `Enregistré${exportState.obsidian.deduplicated ? ' (déjà existant)' : ''} : ${exportState.obsidian.path}` : exportState.obsidian?.error ? `Erreur : ${exportState.obsidian.error}` : 'Exporter vers Obsidian'}
                    className={`p-1.5 rounded-lg border transition-colors disabled:opacity-40 ${
                      exportState.obsidian?.ok    ? 'bg-green-50 dark:bg-green-900/30 border-green-300 dark:border-green-700 text-green-700 dark:text-green-300' :
                      exportState.obsidian?.error ? 'bg-red-50 dark:bg-red-900/30 border-red-300 dark:border-red-700 text-red-600 dark:text-red-400' :
                      'bg-violet-50 dark:bg-violet-900/30 border-violet-200 dark:border-violet-700 text-[#5856D6] dark:text-[#5E5CE6] hover:bg-violet-100 dark:hover:bg-violet-900/50'
                    }`}
                  >
                    {exportState.obsidian === 'saving' ? <Loader2 size={14} className="animate-spin" /> : exportState.obsidian?.ok ? <Check size={14} /> : <BookOpen size={14} />}
                  </button>
                  {(exportState.obsidian?.ok || exportState.obsidian?.error) && (
                    <div className="absolute top-full mt-1 right-0 z-10 max-w-xs bg-slate-800 text-white text-[11px] rounded-lg px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap overflow-hidden text-ellipsis">
                      {exportState.obsidian?.ok
                        ? (exportState.obsidian.deduplicated ? '✓ Déjà exporté — ' : '') + exportState.obsidian.path
                        : exportState.obsidian?.error}
                    </div>
                  )}
                </div>

              </>
            )}
            <button onClick={handleCopy} className={btnCls} title="Copier le Markdown">
              {copied
                ? <Check size={14} className="text-emerald-500" />
                : <Copy size={14} />
              }
            </button>
            <button onClick={handleDownload} className={btnCls} title="Télécharger .md">
              <Download size={14} />
            </button>
            <button onClick={handlePrint} className={`${btnCls} hidden sm:block`} title="Imprimer / Exporter PDF">
              <Printer size={14} />
            </button>
            <button
              onClick={startStream}
              disabled={isLoading}
              className={btnCls}
              title="Régénérer le rapport"
            >
              <RefreshCw size={14} className={isLoading ? 'animate-spin text-blue-400' : ''} />
            </button>
            <button
              onClick={() => setIsFullscreen(v => !v)}
              className={`${btnCls} hidden sm:block`}
              title={isFullscreen ? 'Quitter le plein écran' : 'Plein écran'}
            >
              {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button
              onClick={onClose}
              className="p-2.5 rounded-lg text-slate-400 hover:text-rose-500 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors touch-target"
              title="Fermer"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* ── Bannière "Ouvrir dans Obsidian" après export réussi ──────────── */}
        {exportState.obsidian?.ok && (exportState.obsidian.filename || exportState.obsidian.path) && (
          <div className="no-print flex items-center gap-2 px-4 py-2.5 bg-violet-50 dark:bg-violet-900/25 border-b border-violet-200 dark:border-violet-800/50 shrink-0">
            <BookOpen size={13} className="text-violet-500 shrink-0" />
            <span className="text-[11px] text-violet-700 dark:text-violet-300 truncate flex-1 min-w-0">
              {exportState.obsidian.deduplicated ? '✓ Déjà exporté — ' : '✓ Exporté — '}
              <span className="opacity-70">{exportState.obsidian.filename ?? exportState.obsidian.path?.split('/').at(-1)}</span>
            </span>
            <button
              onClick={() => {
                const fname = (exportState.obsidian.filename ?? exportState.obsidian.path?.split('/').at(-1) ?? '').replace(/\.md$/i, '')
                openInObsidian(fname, obsidianVault)
              }}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-violet-600 dark:bg-violet-500 text-white hover:bg-violet-700 dark:hover:bg-violet-600 transition-colors"
            >
              <BookOpen size={12} />
              Ouvrir dans Obsidian
            </button>
          </div>
        )}

        {/* ── Entity chip band ─────────────────────────────────────────────── */}
        {chipList.length > 0 && (
          <div className="flex items-center gap-2 px-5 py-2.5 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 overflow-x-auto shrink-0">
            {chipList.map(({ name, type }) => (
              <span
                key={`${type}-${name}`}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border shrink-0 ${CHIP_STYLE[type] ?? FALLBACK_CHIP}`}
              >
                {name}
                <span className="opacity-60 font-normal">({type})</span>
              </span>
            ))}
          </div>
        )}


        {/* ── Rapports précédemment générés ─────────────────────────────────── */}
        {Array.isArray(article['rapports']) && article['rapports'].length > 0 && (
          <div className="no-print flex items-center gap-2 px-5 py-2 bg-violet-50/60 dark:bg-violet-900/20 border-b border-violet-100 dark:border-violet-800/40 overflow-x-auto shrink-0 flex-wrap">
            <BookOpen size={11} className="text-violet-500 shrink-0" />
            <span className="text-[11px] font-medium text-[#5856D6] dark:text-[#5E5CE6] shrink-0">Rapports générés :</span>
            {article['rapports'].map((rap, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-white dark:bg-slate-800 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-700 shrink-0"
                title={`${rap.chemin ?? ''}`}
              >
                {rap.cible === 'obsidian' ? 'Obsidian' : 'Local'}
                {rap.date_creation && <span className="opacity-60">{' '}{rap.date_creation.slice(0, 16).replace('T', ' ')}</span>}
                <span className="opacity-50 max-w-[120px] truncate">{rap.fichier}</span>
                {rap.cible === 'obsidian' && rap.fichier && (
                  <button
                    onClick={() => openInObsidian(rap.fichier, obsidianVault)}
                    className="ml-0.5 underline underline-offset-1 text-[#5856D6] dark:text-[#5E5CE6] hover:text-violet-900 dark:hover:text-violet-100"
                    title="Ouvrir dans Obsidian"
                  >↗</button>
                )}
              </span>
            ))}
          </div>
        )}

        {/* ── Report content ────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-10 py-6 bg-white dark:bg-slate-900">
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 text-sm text-rose-700 dark:text-rose-300">
              Erreur : {error}
            </div>
          )}

          {isLoading && !cleanMd && (
            <div className="flex items-center gap-3 text-slate-400 dark:text-slate-500 text-sm py-16 justify-center">
              <RefreshCw size={16} className="animate-spin" />
              Génération du rapport en cours…
            </div>
          )}

          {frozenMd ? (
            /* ── Vue finale gelée ─────────────────────────────────────────────
               Montée une seule fois après la fin du stream.
               Props stables → aucun re-render → Mermaid se rend dans le calme. */
            <div key="final" className="w-full max-w-none">
              <FinalReportView md={frozenMd} components={frozenComponentsRef.current} />
            </div>
          ) : cleanMd ? (
            /* ── Vue streaming ────────────────────────────────────────────────
               Mise à jour à chaque token — Mermaid affiche un placeholder. */
            <div key="streaming" className="w-full max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw]}
                components={mdComponents}
              >
                {cleanMd}
              </ReactMarkdown>
              <span className="inline-block w-1.5 h-4 bg-blue-500 dark:bg-blue-400 animate-pulse rounded-sm align-middle" />
            </div>
          ) : null}
        </div>
      </div>
    </div>,
    document.body
  )

  return (
    <>
      {portal}
      {youtubeOpen && (
        <YouTubePanel
          article={{ titre, entities, Sources: sources }}
          onClose={() => setYoutubeOpen(false)}
        />
      )}
      {galleryOpen && (
        <ArticleGalleryPanel
          article={article}
          filePath={filePath}
          onClose={() => setGalleryOpen(false)}
        />
      )}
    </>
  )
}
