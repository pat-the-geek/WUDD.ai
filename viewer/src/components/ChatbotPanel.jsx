import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { X, Send, Save, Trash2, FileText, FileJson, Folder, ChevronRight, Loader2, Terminal, RefreshCw, Check, BookOpen, Maximize2, Minimize2, SlidersHorizontal } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import mermaid from 'mermaid'

mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'antiscript' })

/**
 * ChatbotPanel — Chatbot IA style terminal
 * Permet d'interroger les données data/ et rapports/ par IA.
 * Répond en Markdown, supporte les tableaux, les diagrammes Mermaid,
 * et peut sauvegarder les réponses.
 */

/** Rend le SVG Mermaid responsive (extrait depuis MarkdownViewer). */
function makeResponsiveSvg(svg) {
  return svg.replace(/<svg([^>]*)>/i, (_, attrs) => {
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
  // 12. Pour les diagrammes timeline : le « : » dans un titre de section est
  //     interprété comme séparateur d'événement par Mermaid → crash interne
  //     "undefined is not an object (.events)". On remplace « : » par « - ».
  //     Ex: "section 2004-2015 : Debut" → "section 2004-2015 - Debut"
  if (/^timeline\s*$/im.test(s)) {
    s = s.replace(/^(\s*section\s+[^:\n]+)\s*:\s*(.+)/gim, '$1 - $2')
  }
  return s.trim()
}

/** Composant de rendu d'un bloc Mermaid dans le terminal IA (thème sombre).
 *  Le SVG est stocké dans le state React (dangerouslySetInnerHTML) et non écrit
 *  directement dans le DOM — l'ancien diagramme reste affiché tant que le nouveau
 *  n'est pas prêt, ce qui élimine tout flickering pendant le streaming. */
function MermaidBlock({ code }) {
  const id           = useRef(`mermaid-chat-${Math.random().toString(36).slice(2)}`)
  const lastCode     = useRef(null)           // dernier code rendu avec succès
  const [svgHtml, setSvgHtml] = useState(null) // SVG figé dans le state
  const [errMsg,  setErrMsg ] = useState(null) // erreur finale (aucun rendu dispo)

  const clean = sanitizeMermaid(code)

  useEffect(() => {
    // Ignorer si le code n'a pas changé depuis le dernier rendu réussi
    if (!clean || clean === lastCode.current) return
    let cancelled = false
    // Debounce 300 ms : attend la fin du streaming avant de tenter un rendu
    const timer = setTimeout(() => {
      mermaid.parse(clean)
        .then(() => mermaid.render(id.current, clean))
        .then(({ svg }) => {
          if (cancelled) return
          lastCode.current = clean
          setSvgHtml(makeResponsiveSvg(svg)) // fige le SVG dans le state
          setErrMsg(null)
        })
        .catch(err => {
          if (cancelled) return
          // N'affiche l'erreur que si aucun rendu précédent n'est disponible
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
      <div className="my-4 rounded-lg border border-amber-800/60 bg-amber-900/20 p-3">
        <p className="text-xs text-amber-400 font-mono mb-2">⚠ Diagramme non rendu : {errMsg}</p>
        <pre className="text-xs text-slate-300 bg-slate-900/60 rounded p-2 overflow-x-auto whitespace-pre-wrap select-all">{clean}</pre>
      </div>
    )
  }
  return (
    <div
      className="my-4 w-full flex justify-center overflow-x-auto bg-slate-900/40 rounded-lg p-2"
      style={{ opacity: svgHtml ? 1 : 0, transition: 'opacity 0.3s ease' }}
      dangerouslySetInnerHTML={svgHtml ? { __html: svgHtml } : undefined}
    />
  )
}

// Suggestions de commandes rapides affichées dans l'interface
const QUICK_COMMANDS = [
  { label: 'Résumé des derniers articles',   text: 'Résume les articles récents du fichier de contexte en 5 points.' },
  { label: 'Tableau des entités',            text: 'Génère un tableau Markdown listant les entités (personnes, organisations, lieux) mentionnées dans les fichiers de contexte, avec leur nombre d\'occurrences.' },
  { label: 'Analyse des sentiments',         text: 'Analyse les sentiments et le ton éditorial des articles en contexte. Présente les résultats dans un tableau Markdown.' },
  { label: 'Tendances et sujets clés',       text: 'Quels sont les sujets et tendances clés qui ressortent des données en contexte ?' },
  { label: 'Rapport de synthèse',            text: 'Génère un rapport de synthèse complet au format Markdown, prêt à être sauvegardé, basé sur les fichiers de contexte.' },
  { label: 'Comparaison de sources',         text: 'Compare les différentes sources d\'information dans les articles du contexte. Quelles sources sont les plus citées ? Quels biais éditoriaux peut-on observer ?' },
  { label: 'Frise chronologique',            text: 'Construis une frise chronologique des événements mentionnés dans les articles de contexte, du plus ancien au plus récent.' },
  { label: 'Top 10 thématiques',             text: 'Identifie et classe les 10 principales thématiques abordées dans les articles de contexte. Présente le résultat sous forme de tableau avec le nombre d\'articles par thème.' },
  { label: 'Fiche d\'entité principale',     text: 'Génère une fiche structurée sur l\'entité (personne, organisation ou pays) la plus mentionnée dans les articles de contexte : qui est-elle, quel rôle joue-t-elle, quels sont les faits clés ?' },
  { label: 'FAQ sur les données',            text: 'À partir des articles de contexte, génère 5 questions fréquentes (FAQ) avec leurs réponses sur les principaux sujets abordés.' },
  { label: 'Diagramme Mermaid',             text: 'Génère un diagramme Mermaid (sequenceDiagram ou graph TD) illustrant les relations entre les principales entités mentionnées dans les articles de contexte. Entoure le code avec ```mermaid ... ```.' },
]

// Commandes rapides spécifiques aux notes personnelles
const NOTES_QUICK_COMMANDS = [
  { label: 'Notes de la semaine',   period: 'week',  text: 'Quelles sont mes notes personnelles de la semaine ? Liste-les par article avec le titre, la source et ma note pour chacun.' },
  { label: 'Notes du mois',         period: 'month', text: 'Quelles sont mes notes personnelles du mois ? Regroupe-les par tag et indique l\'article correspondant pour chaque note.' },
  { label: 'Toutes mes notes',      period: 'all',   text: 'Liste toutes mes notes personnelles, regroupées par tag. Pour chaque note, indique l\'article et la date.' },
  { label: 'Articles importants ⭐', period: 'week',  text: 'Parmi mes notes de la semaine, lesquels sont marqués comme importants (⭐) ? Présente-les avec leur titre et ma note.' },
]

// ── Protection anti-suppression ───────────────────────────────────────────────
// Verbes et mots-clés signalant une tentative de destruction/suppression
const _VERBES_DESTRUCTION = [
  'supprim', 'efface', 'delete', 'remove', 'détruit', 'détruire', 'détruis',
  'purge', 'wipe', 'unlink', 'shred',
]
// Regex pour capturer « rm » en tant que commande shell indépendante (\b = limite de mot)
const _RM_REGEX = /\brm\b/
// Objets protégés (données et rapports)
const _OBJETS_PROTEGES = [
  'fichier', 'rapport', 'donnée', 'dossier', 'répertoire',
  '.json', '.md', 'data/', 'rapports/', 'article',
]

/**
 * Renvoie true si le texte ressemble à une demande de suppression/destruction
 * de fichiers ou de données.
 */
const isDestructiveRequest = (text) => {
  const lower = text.toLowerCase()
  const hasDestructionVerb =
    _VERBES_DESTRUCTION.some(v => lower.includes(v)) || _RM_REGEX.test(lower)
  const hasProtectedObject = _OBJETS_PROTEGES.some(o => lower.includes(o))
  return hasDestructionVerb && hasProtectedObject
}

// Labels pour les périodes de notes personnelles
const PERIOD_LABELS = { week: 'semaine', month: 'mois', all: 'toutes' }

// ── Thèmes de couleur du terminal ─────────────────────────────────────────────
const TERMINAL_THEMES = {
  // ── GitHub Dark — fond near-black, texte vert saturé (défaut)
  // Inspiré du thème GitHub Dark, ratio de contraste ≥ 7:1 sur tous les éléments
  matrix: {
    label:           'Matrix',
    bg:              '#0d1117',   // github: canvas.default
    headerBg:        '#161b22',   // github: canvas.subtle
    border:          'rgba(22,101,52,0.4)',
    titleColor:      '#3fb950',   // github: success.fg
    cursorColor:     '#238636',   // github: success.emphasis
    promptColor:     '#d29922',   // github: attention.fg
    inputColor:      '#e6edf3',   // github: fg.default — contraste 13:1
    textColor:       '#aff5b4',   // github: success.muted — texte IA
    userMsgColor:    '#ffa657',   // github: attention.muted — texte utilisateur
    placeholderColor:'#484f58',   // github: fg.muted
    lightBg:         false,
    mermaid:         'dark',
  },
  // ── Nord — palette arctique (Arctic Ice Studio, 2016)
  // 4 groupes : Polar Night (bg), Snow Storm (fg), Frost (blues), Aurora (accents)
  // Rapport texte/fond ≥ 7:1 WCAG AAA sur snow storm / polar night
  nord: {
    label:           'Nord',
    bg:              '#2e3440',   // nord0 — Polar Night
    headerBg:        '#3b4252',   // nord1
    border:          'rgba(94,129,172,0.4)',  // nord10 — Frost dark blue
    titleColor:      '#88c0d0',   // nord8 — Frost teal
    cursorColor:     '#81a1c1',   // nord9 — Frost blue
    promptColor:     '#ebcb8b',   // nord13 — Aurora yellow
    inputColor:      '#eceff4',   // nord6 — Snow Storm lightest — contraste 8.5:1
    textColor:       '#d8dee9',   // nord4 — Snow Storm
    userMsgColor:    '#ebcb8b',   // nord13 — Aurora yellow
    placeholderColor:'#4c566a',   // nord3 — Polar Night light
    lightBg:         false,
    mermaid:         'dark',
  },
  // ── Solarized Dark — palette CIELAB précise (Ethan Schoonover, 2011)
  // Conçue pour minimiser la fatigue oculaire ; contrastes précisément calculés
  solarized: {
    label:           'Solarized',
    bg:              '#002b36',   // base03
    headerBg:        '#073642',   // base02
    border:          'rgba(42,161,152,0.45)',  // cyan
    titleColor:      '#268bd2',   // blue — ratio 4.6:1
    cursorColor:     '#2aa198',   // cyan
    promptColor:     '#cb4b16',   // orange
    inputColor:      '#eee8d5',   // base2 — ratio 16:1 sur base03
    textColor:       '#93a1a1',   // base1 (emphasized text)
    userMsgColor:    '#b58900',   // yellow
    placeholderColor:'#586e75',   // base01
    lightBg:         false,
    mermaid:         'dark',
  },
  // ── Solarized Light — version claire de la même palette (fond crème chaud)
  // bg #fdf6e3 (base3), texte #657b83 (base00) → ratio 4.6:1 WCAG AA garanti
  paper: {
    label:           'Papier',
    bg:              '#fdf6e3',   // base3 — crème chaud (moins agressif que blanc pur)
    headerBg:        '#eee8d5',   // base2
    border:          'rgba(147,161,161,0.4)',  // base1
    titleColor:      '#268bd2',   // blue — ratio 4.6:1 sur base3
    cursorColor:     '#2aa198',   // cyan
    promptColor:     '#cb4b16',   // orange — ratio 5.6:1
    inputColor:      '#586e75',   // base01 — ratio 5.9:1
    textColor:       '#657b83',   // base00 — ratio 4.6:1 WCAG AA
    userMsgColor:    '#859900',   // green — ratio 4.5:1
    placeholderColor:'#93a1a1',   // base1
    lightBg:         true,
    mermaid:         'default',
  },
  // ── Dracula — palette violette (Zeno Rocha, 2013 ; >2M installs VS Code)
  // Fond #282a36, fg #f8f8f2 → ratio 10.5:1. Accents saturés bien différenciés.
  dracula: {
    label:           'Dracula',
    bg:              '#282a36',   // background
    headerBg:        '#44475a',   // current line / selection
    border:          'rgba(189,147,249,0.4)',  // purple
    titleColor:      '#bd93f9',   // purple
    cursorColor:     '#ff79c6',   // pink
    promptColor:     '#50fa7b',   // green
    inputColor:      '#f8f8f2',   // foreground — ratio 10.5:1
    textColor:       '#f8f8f2',   // foreground
    userMsgColor:    '#8be9fd',   // cyan
    placeholderColor:'#6272a4',   // comment
    lightBg:         false,
    mermaid:         'dark',
  },
}



function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`
}

function formatDateShort(ts) {
  const d = new Date(ts * 1000)
  const now = new Date()
  if (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  ) {
    return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

// ── Composant principal ───────────────────────────────────────────────────────

// Étiquettes des types NER en français
const NER_LABELS = {
  PERSON: 'Personne', ORG: 'Organisation', GPE: 'Pays/Région',
  LOC: 'Lieu', PRODUCT: 'Produit', EVENT: 'Événement',
}

export default function ChatbotPanel({ onClose, onFileSaved, initialFile, entityContext, articleContext, fluxContext }) {
  // entityContext  : { type, value } | null — contexte entité pré-chargé depuis EntityArticlePanel
  // articleContext : { titre, sources, date, url, entities, resume, reportMd } | null — rapport complet
  // fluxContext    : { articles, filePath, count } | null — liste d'articles depuis ArticleListViewer

  const entityLabel = entityContext
    ? `${entityContext.value} (${NER_LABELS[entityContext.type] ?? entityContext.type})`
    : null

  // Texte de contexte flux injecté directement depuis la liste d'articles affichés
  const fluxContextText = fluxContext ? (() => {
    const articles = fluxContext.articles || []
    const fileName = fluxContext.filePath ? fluxContext.filePath.split('/').pop() : 'flux'

    // Trier par date décroissante — les plus récents en priorité
    const parseDateForSort = (d) => {
      if (!d) return 0
      if (/^\d{4}-\d{2}-\d{2}/.test(d)) return new Date(d).getTime() || 0
      const m = d.match(/^(\d{2})\/(\d{2})\/(\d{4})/)
      if (m) return new Date(`${m[3]}-${m[2]}-${m[1]}`).getTime() || 0
      return new Date(d).getTime() || 0
    }
    const sorted = [...articles].sort((a, b) =>
      parseDateForSort(b['Date de publication']) - parseDateForSort(a['Date de publication'])
    )

    const header = `# Flux d'actualités : ${articles.length} article${articles.length > 1 ? 's' : ''} (${fileName})\n\n`

    // Budget caractères ~150 000 — maximise le nombre d'articles inclus
    const CHAR_BUDGET = 150_000
    let usedChars = header.length
    const blocks = []

    for (const a of sorted) {
      const parts = [`## Article ${blocks.length + 1}`]
      if (a['Date de publication']) parts.push(`- **Date** : ${a['Date de publication']}`)
      if (a['Sources']) parts.push(`- **Source** : ${a['Sources']}`)
      if (a['URL']) parts.push(`- **URL** : ${a['URL']}`)
      if (a['Résumé']) parts.push(`- **Résumé** : ${a['Résumé']}`)
      if (a.entities && Object.keys(a.entities).length) {
        const ents = Object.entries(a.entities)
          .filter(([, v]) => Array.isArray(v) && v.length)
          .map(([t, v]) => `${t}: ${v.slice(0, 5).join(', ')}`)
          .join(' | ')
        if (ents) parts.push(`- **Entités** : ${ents}`)
      }
      parts.push('')
      const block = parts.join('\n')
      if (usedChars + block.length > CHAR_BUDGET) break
      usedChars += block.length
      blocks.push(block)
    }

    let result = header + blocks.join('\n')
    if (blocks.length < articles.length) {
      result += `\n_(${articles.length - blocks.length} articles supplémentaires non inclus — budget dépassé)_`
    }
    return result
  })() : ''

  // Texte de contexte article injecté directement (pas de SSE serveur nécessaire)
  const articleContextText = articleContext ? (() => {
    const lines = [
      `# Rapport complet : ${articleContext.titre || 'Article'}`,
      `Source : ${articleContext.sources || '—'} | Date : ${articleContext.date || '—'}`,
      articleContext.url ? `URL : ${articleContext.url}` : '',
      '',
    ]
    if (articleContext.entities && Object.keys(articleContext.entities).length) {
      lines.push('## Entités nommées')
      for (const [type, vals] of Object.entries(articleContext.entities)) {
        if (Array.isArray(vals) && vals.length) lines.push(`- ${type} : ${vals.join(', ')}`)
      }
      lines.push('')
    }
    if (articleContext.resume) {
      lines.push('## Résumé original', articleContext.resume, '')
    }
    if (articleContext.reportMd) {
      lines.push('## Rapport généré', articleContext.reportMd)
    }
    return lines.filter(l => l !== undefined).join('\n')
  })() : ''

  const WELCOME_MSG = fluxContext ? {
    role: 'assistant',
    content: `**Terminal IA — Flux d'actualités**

Le contexte de **${fluxContext.count ?? fluxContext.articles?.length ?? 0} articles** est chargé. Je peux vous aider à :
- 📰 **Synthétiser** les grandes tendances et thématiques
- 🔍 **Identifier** les acteurs, événements et lieux clés
- 📊 **Comparer** les points de vue entre sources
- 🏆 **Classer** les articles par importance ou pertinence
- 📝 **Générer** un rapport structuré par catégories

Exemples de questions :
- _Quelles sont les 5 grandes tendances de ce flux ?_
- _Quels acteurs reviennent le plus souvent ?_
- _Génère un rapport synthèse groupé par thématique._
- _Y a-t-il des contradictions entre les sources ?_`,
    welcome: true,
  } : articleContext ? {
    role: 'assistant',
    content: `**Terminal IA — Rapport article**

Le rapport complet de l'article est chargé en contexte :
- 📰 **${articleContext.titre || 'Article'}** — ${[articleContext.sources, articleContext.date].filter(Boolean).join(' · ')}
- 📊 Entités nommées détectées
- 📝 Rapport Markdown complet (analyse, diagrammes, acteurs)

Exemples de questions :
- _Quels sont les principaux acteurs mentionnés et leurs rôles ?_
- _Quelle est la position éditoriale de la source ?_
- _Résume les points clés en 5 bullets._
- _Génère un tableau comparatif des entités._`,
    welcome: true,
  } : entityContext ? {
    role: 'assistant',
    content: `**Terminal IA — Entité : ${entityLabel}**

Je suis prêt à répondre à vos questions sur cette entité. Le contexte chargé comprend :
- 📰 Les articles de presse la mentionnant
- 🔗 Les entités co-occurrentes (relations)
- 📅 Le calendrier des mentions
- 📊 La tonalité éditoriale et les sources

Exemples de questions :
- _Quel rôle joue ${entityContext.value} dans l'actualité récente ?_
- _Quelles organisations sont liées à ${entityContext.value} ?_
- _Comment la couverture médiatique a-t-elle évolué ?_
- _Quels sont les points de vue éditoriaux sur ce sujet ?_`,
    welcome: true,
  } : {
    role: 'assistant',
    content: `**Bienvenue dans le terminal IA de WUDD.ai** 👋

Voici ce que je peux faire pour vous :
- 📊 Analyser et résumer des articles, rapports ou fichiers JSON
- 🗂 Répondre à des questions sur les données chargées en contexte
- 📝 Produire des tableaux, synthèses et analyses comparatives en Markdown

**Règles de fonctionnement :**
- 🔒 **Lecture seule** — je ne peux pas supprimer, modifier ou créer des fichiers
- 🌐 Les réponses sont générées par l'IA sélectionnée (EurIA / Claude)
- 📁 Ajoutez des fichiers de contexte via le bouton 📎 pour des analyses ciblées
- ⬆️ Utilisez la flèche ↑ pour rappeler une commande précédente
- 💾 Sauvegardez la conversation avec l'icône 💾 en bas à droite`,
    welcome: true,
  }

  const [messages, setMessages]         = useState([WELCOME_MSG])
  const [input, setInput]               = useState('')
  const [streaming, setStreaming]       = useState(false)
  const [contextFiles, setContextFiles] = useState(() => initialFile?.path ? [initialFile.path] : [])
  // Contexte entité pré-formaté (texte) chargé depuis /api/entity-context (SSE)
  const [entityContextText, setEntityContextText]         = useState('')
  const [entityContextLoading, setEntityContextLoading]   = useState(false)
  const [entityContextStep, setEntityContextStep]         = useState(null)   // étape courante
  const [entityContextLogs, setEntityContextLogs]         = useState([])     // log de chargement
  const [entityContextStats, setEntityContextStats]       = useState(null)   // { article_count, has_info, has_rag }
  const [availableFiles, setAvailableFiles] = useState([])
  const [pickerOpen, setPickerOpen]     = useState(false)
  const [fileSearch, setFileSearch]     = useState('')
  const [saving, setSaving]             = useState(false)
  const [savedMsg, setSavedMsg]         = useState(null)
  const [notesPeriod, setNotesPeriod]   = useState(null)  // null | "week" | "month" | "all"
  const [fullscreen, setFullscreen]     = useState(false)
  const [aiProviders, setAiProviders]   = useState([])          // providers disponibles
  const [selectedProvider, setSelectedProvider] = useState(null) // null = env default
  const [webSearch, setWebSearch]       = useState(false)        // Web Search EurIA (désactivé par défaut)
  const [terminalTheme, setTerminalTheme] = useState(
    () => localStorage.getItem('chatbot_theme') || 'matrix'
  )
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const theme = TERMINAL_THEMES[terminalTheme] || TERMINAL_THEMES.matrix

  // Provider effectif : selectedProvider si défini, sinon le seul provider disponible, sinon 'euria' (défaut)
  const effectiveProvider = selectedProvider || (aiProviders.length === 1 ? aiProviders[0] : 'euria')

  const ctrlRef         = useRef(null)
  const endRef          = useRef(null)
  const inputRef        = useRef(null)
  const mobileMenuRef   = useRef(null)
  const historyIdxRef   = useRef(-1)   // -1 = pas en navigation historique
  const historyDraft    = useRef('')   // sauvegarde du texte en cours avant navigation

  // Ferme le menu mobile si on clique en dehors
  useEffect(() => {
    if (!mobileMenuOpen) return
    const handler = (e) => {
      if (mobileMenuRef.current && !mobileMenuRef.current.contains(e.target)) {
        setMobileMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [mobileMenuOpen])

  // Détecte si un fichier a été modifié aujourd'hui
  const isToday = (mtime) => {
    const d = new Date(mtime * 1000)
    const now = new Date()
    return d.getFullYear() === now.getFullYear() &&
           d.getMonth()    === now.getMonth()    &&
           d.getDate()     === now.getDate()
  }

  // Sélection du provider IA (desktop et mobile)
  const handleProviderSelect = (p) => {
    setSelectedProvider(p)
    if (p === 'claude') setWebSearch(false)
  }

  // Auto-scroll vers le bas à chaque nouveau message
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Ferme le stream au démontage
  useEffect(() => {
    return () => ctrlRef.current?.abort()
  }, [])

  // Focus sur l'input à l'ouverture
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 80)
  }, [])

  // Auto-dismiss du message de sauvegarde après 3 secondes
  useEffect(() => {
    if (!savedMsg) return
    const t = setTimeout(() => setSavedMsg(null), 3000)
    return () => clearTimeout(t)
  }, [savedMsg])

  // Ré-initialiser Mermaid et persister le thème quand il change
  useEffect(() => {
    localStorage.setItem('chatbot_theme', terminalTheme)
    mermaid.initialize({ startOnLoad: false, theme: theme.mermaid, securityLevel: 'antiscript' })
  }, [terminalTheme, theme.mermaid])


  // Charger les providers IA disponibles (EurIA / Claude)
  useEffect(() => {
    fetch('/api/ai-providers')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.providers) {
          setAiProviders(d.providers)
          // Pré-sélectionner le provider actif seulement si les deux sont disponibles
          if (d.providers.length >= 2) setSelectedProvider(d.active || d.providers[0])
        }
      })
      .catch(() => {})
  }, [])

  // Charger le contexte entité via SSE depuis /api/entity-context
  useEffect(() => {
    if (!entityContext?.type || !entityContext?.value) return
    setEntityContextLoading(true)
    setEntityContextLogs([])
    setEntityContextStep(null)
    setEntityContextStats(null)
    setEntityContextText('')

    const params = new URLSearchParams({ type: entityContext.type, value: entityContext.value, n: 25 })
    const ctrl = new AbortController()

    fetch(`/api/entity-context?${params}`, { signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const reader  = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop()

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const raw = line.slice(6).trim()
            if (!raw) continue
            try {
              const evt = JSON.parse(raw)
              if (evt.type === 'progress') {
                setEntityContextStep(evt.step)
                setEntityContextLogs(prev => [...prev, evt.message])
              } else if (evt.type === 'done') {
                setEntityContextText(evt.context_text || '')
                setEntityContextStats({
                  article_count: evt.article_count,
                  has_info: evt.has_info,
                  has_rag: evt.has_rag,
                })
                setEntityContextStep('done')
                setEntityContextLoading(false)
              }
            } catch (_) { /* ignore */ }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') setEntityContextLoading(false)
      })

    return () => ctrl.abort()
  }, [entityContext?.type, entityContext?.value])

  // Charger la liste des fichiers disponibles pour le contexte
  // et pré-sélectionner 48-heures.json s'il existe
  useEffect(() => {
    fetch('/api/files')
      .then(r => r.ok ? r.json() : [])
      .then(d => {
        const files = Array.isArray(d) ? d : (d.files || [])
        setAvailableFiles(files)
        setContextFiles(prev => {
          if (prev.length > 0) return prev
          // Fallback : 48-heures.json si aucun fichier n'est déjà en contexte
          const file48h = files.find(f => f.name === '48-heures.json')
          return file48h ? [file48h.path] : prev
        })
      })
      .catch(() => {})
  }, [])

  // ── Envoi d'un message ────────────────────────────────────────────────────

  const sendMessage = useCallback(async (text, overrideNotesPeriod) => {
    const content = (text || input).trim()
    if (!content || streaming) return

    // ── Bloquer les demandes de suppression/destruction ───────────────────
    if (isDestructiveRequest(content)) {
      setInput('')
      setMessages(prev => [
        ...prev,
        { role: 'user', content },
        {
          role: 'assistant',
          content: '🚫 **Action non autorisée.** Ce chatbot est en lecture seule et ne peut pas supprimer, effacer ou modifier des fichiers, des données ou des rapports. Pour toute opération de suppression, utilisez les contrôles appropriés dans l\'interface.',
          streaming: false,
          error: false,
        },
      ])
      return
    }

    setInput('')

    const userMsg = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setStreaming(true)

    // Placeholder pour la réponse IA en cours
    const assistantIdx = newMessages.length
    setMessages(prev => [...prev, { role: 'assistant', content: '', streaming: true }])

    const ctrl = new AbortController()
    ctrlRef.current = ctrl

    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: newMessages.filter(m => !m.welcome),
          context_files: contextFiles,
          notes_period: overrideNotesPeriod || notesPeriod || undefined,
          ...(articleContextText ? { entity_context: articleContextText } : fluxContextText ? { entity_context: fluxContextText } : entityContextText ? { entity_context: entityContextText } : {}),
          provider: effectiveProvider,
          web_search: webSearch,
        }),
        signal: ctrl.signal,
      })

      if (!res.ok) {
        const err = await res.text()
        setMessages(prev => {
          const updated = [...prev]
          updated[assistantIdx] = { role: 'assistant', content: `⚠ Erreur serveur : ${err}`, streaming: false, error: true }
          return updated
        })
        return
      }

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let accumulated = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop()

        for (const line of lines) {
          if (!line.trim()) continue
          let raw = ''
          if (line.startsWith('data: ')) raw = line.slice(6).trim()
          else raw = line.trim()

          if (raw === '[DONE]') break
          if (!raw) continue

          try {
            const parsed = JSON.parse(raw)
            if (parsed.error) {
              accumulated += `\n⚠ ${parsed.error}`
            } else {
              const chunk = parsed.choices?.[0]?.delta?.content ?? ''
              accumulated += chunk
            }
            // Mettre à jour en temps réel
            setMessages(prev => {
              const updated = [...prev]
              updated[assistantIdx] = { role: 'assistant', content: accumulated, streaming: true }
              return updated
            })
          } catch (e) { /* ligne SSE non-JSON (ex: ping, commentaire), ignorer */ }
        }
      }

      // Finaliser le message IA
      setMessages(prev => {
        const updated = [...prev]
        updated[assistantIdx] = { role: 'assistant', content: accumulated, streaming: false }
        return updated
      })
    } catch (e) {
      if (e.name !== 'AbortError') {
        setMessages(prev => {
          const updated = [...prev]
          updated[assistantIdx] = { role: 'assistant', content: `⚠ ${e.message}`, streaming: false, error: true }
          return updated
        })
      }
    } finally {
      setStreaming(false)
    }
  }, [input, messages, streaming, contextFiles, notesPeriod, selectedProvider])

  // ── Sauvegarde en Markdown ────────────────────────────────────────────────

  const saveConversation = async () => {
    if (saving || messages.length === 0) return
    setSaving(true)
    setSavedMsg(null)

    // Construire le contenu Markdown de la conversation
    const now = new Date()
    const dateStr = now.toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' })
    const timeStr = now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })

    let md = `# Conversation WUDD.ai — ${dateStr} à ${timeStr}\n\n`
    if (contextFiles.length > 0) {
      md += `**Fichiers de contexte :** ${contextFiles.join(', ')}\n\n`
      md += '---\n\n'
    }
    for (const msg of messages) {
      if (msg.role === 'user') {
        md += `## 💬 Question\n\n${msg.content}\n\n`
      } else if (msg.role === 'assistant') {
        md += `## 🤖 Réponse IA\n\n${msg.content}\n\n`
      }
      md += '---\n\n'
    }

    try {
      const res = await fetch('/api/chat/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: md, filename: 'chatbot' }),
      })
      const data = await res.json()
      if (data.ok) {
        setSavedMsg(data.path)
        onFileSaved?.()
      } else {
        setSavedMsg(`Erreur : ${data.error}`)
      }
    } catch (e) {
      setSavedMsg(`Erreur : ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  // ── Sauvegarde d'un seul message IA ────────────────────────────────────────

  const saveMessage = async (content) => {
    if (!content) return
    setSaving(true)
    setSavedMsg(null)
    try {
      const res = await fetch('/api/chat/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, filename: 'reponse_ia' }),
      })
      const data = await res.json()
      if (data.ok) {
        setSavedMsg(data.path)
        onFileSaved?.()
      } else {
        setSavedMsg(`Erreur : ${data.error}`)
      }
    } catch (e) {
      setSavedMsg(`Erreur : ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  // ── Gestion du picker de fichiers de contexte ─────────────────────────────

  const toggleContextFile = (path) => {
    setContextFiles(prev =>
      prev.includes(path) ? prev.filter(p => p !== path) : [...prev, path]
    )
  }

  const filteredFiles = availableFiles.filter(f =>
    !fileSearch || f.path.toLowerCase().includes(fileSearch.toLowerCase()) ||
    (f.flux || '').toLowerCase().includes(fileSearch.toLowerCase())
  )

  // Grouper les fichiers disponibles par flux (comme l'explorateur)
  const groupedFiles = useMemo(() => {
    const groups = {}
    filteredFiles.forEach(f => {
      const key = f.flux || 'Racine'
      if (!groups[key]) groups[key] = []
      groups[key].push(f)
    })
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b, 'fr'))
  }, [filteredFiles])

  // ── Rendu d'un message ────────────────────────────────────────────────────

  const renderMessage = (msg, idx) => {
    const isUser      = msg.role === 'user'
    const isStreaming = msg.streaming

    return (
      <div key={idx} className={`mb-4 ${isUser ? 'pl-0' : 'pl-0'}`}>
        {isUser ? (
          /* Message utilisateur */
          <div className="flex items-start gap-2">
            <span className="font-mono text-xs mt-0.5 shrink-0 select-none" style={{ color: theme.promptColor }}>$&gt;</span>
            <span className="font-mono text-sm break-words leading-relaxed" style={{ color: theme.userMsgColor }}>{msg.content}</span>
          </div>
        ) : (
          /* Réponse IA */
          <div className="group">
            <div className="flex items-start gap-2 mb-1">
              <span className="text-green-500 font-mono text-xs mt-0.5 shrink-0 select-none">
                {isStreaming ? '▋' : '◆'}
              </span>
              <div className="flex-1 min-w-0">
                {msg.error ? (
                  <span className="text-red-400 font-mono text-sm">{msg.content}</span>
                ) : (
                  <div
                    className={`prose prose-sm max-w-none chat-markdown ${theme.lightBg ? '' : 'prose-invert'}`}
                    style={{ color: theme.textColor }}
                  >
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        pre: ({ children }) => {
                          const child = Array.isArray(children) ? children[0] : children
                          if (child?.props?.className === 'language-mermaid') {
                            return <>{children}</>
                          }
                          return <pre>{children}</pre>
                        },
                        code: ({ className, children }) => {
                          if (className === 'language-mermaid') {
                            return <MermaidBlock code={String(children).trim()} />
                          }
                          return (
                            <code className={className}>
                              {children}
                            </code>
                          )
                        },
                      }}
                    >
                      {msg.content + (isStreaming ? '▌' : '')}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
            {/* Bouton sauvegarder ce message */}
            {!isStreaming && !msg.error && msg.content && (
              <div className="flex items-center gap-2 pl-4 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => saveMessage(msg.content)}
                  className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-green-400 transition-colors font-mono"
                  title="Sauvegarder cette réponse en Markdown"
                >
                  <Save size={10} />
                  sauvegarder
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  // ── Rendu principal ───────────────────────────────────────────────────────

  return (
    <>
      {/* Fond semi-transparent */}
      <div className="hig-overlay-enter fixed inset-0 bg-black/80 backdrop-blur-sm z-[220]" onClick={onClose} />

      {/* Panneau principal — z-[221] pour passer au-dessus de tous les modals (rapport z-[200]) */}
      <div className="fixed inset-0 z-[221] flex items-stretch md:items-center justify-center md:p-4 pointer-events-none" style={{ height: '100dvh' }}>
        <div
          className={`hig-modal-enter pointer-events-auto w-full h-full md:h-auto md:max-h-[92vh] relative flex flex-col overflow-hidden shadow-2xl border ${
            fullscreen
              ? 'rounded-none'
              : 'md:max-w-5xl md:rounded-2xl'
          }`}
          style={{
            borderColor: theme.border,
            maxHeight: fullscreen ? '100dvh' : undefined,
            height: fullscreen ? '100dvh' : undefined,
            background: theme.bg,
          }}
        >
          {/* ── En-tête ─────────────────────────────────────────────── */}
          <div
            className="flex items-center gap-2 px-4 py-2.5 shrink-0 border-b border-green-900/40"
            style={{ background: theme.headerBg, borderColor: theme.border }}
          >
            <Terminal size={14} className="hidden md:block text-green-500 shrink-0" />
            <span className="font-mono text-sm flex-1 min-w-0 tracking-wider" style={{ color: theme.titleColor }}>
              <span className="hidden md:inline">WUDD.ai ▸ Terminal IA</span>
              <span className="md:hidden">&gt;_</span>
              <span className="animate-pulse ml-1" style={{ color: theme.cursorColor }}>█</span>
            </span>
            {/* Badge entité — masqué sur mobile pour préserver la place */}
            {entityContext && (
              <span
                className={`hidden md:inline font-mono text-[11px] px-2 py-0.5 rounded-full border max-w-[200px] truncate ${
                  entityContextLoading
                    ? 'text-amber-400 bg-amber-900/30 border-amber-800/50 animate-pulse'
                    : entityContextStep === 'done'
                      ? 'text-emerald-300 bg-emerald-900/40 border-emerald-800/60'
                      : 'text-slate-400 bg-slate-800/40 border-slate-700'
                }`}
                title={
                  entityContextLoading
                    ? (entityContextLogs[entityContextLogs.length - 1] || 'Chargement du contexte…')
                    : entityContextStats
                      ? `${entityContext.value} — ${entityContextStats.article_count} article(s)${entityContextStats.has_info ? ' + synthèse IA' : ''}${entityContextStats.has_rag ? ' + RAG' : ''}`
                      : `Contexte entité : ${entityLabel}`
                }
              >
                {entityContextLoading
                  ? `⟳ ${entityContextLogs[entityContextLogs.length - 1] || 'entité…'}`
                  : `◆ ${entityContext.value}`}
              </span>
            )}
            {/* Indicateur de fichiers de contexte — masqué sur mobile */}
            {contextFiles.length > 0 && (
              <span className="hidden md:inline font-mono text-[11px] text-slate-300 bg-slate-800/60 px-2 py-0.5 rounded-full">
                {contextFiles.length} fichier{contextFiles.length > 1 ? 's' : ''} en contexte
              </span>
            )}
            {/* Indicateur de notes personnelles actives — masqué sur mobile */}
            {notesPeriod && (
              <button
                onClick={() => setNotesPeriod(null)}
                className="hidden md:inline-flex items-center gap-1 font-mono text-[11px] text-amber-400 bg-amber-900/30 border border-amber-800/50 px-2 py-0.5 rounded-full hover:bg-amber-900/50 transition-colors"
                title="Cliquez pour désactiver les notes personnelles"
              >
                <BookOpen size={9} />
                Notes {PERIOD_LABELS[notesPeriod]}
              </button>
            )}
            {/* Toggle EurIA / Claude — masqué sur mobile (accessible via menu ⚙) */}
            {aiProviders.length >= 2 && (
              <div className="hidden md:flex items-center gap-0.5 bg-slate-800 rounded-lg p-0.5" title="Choisir le moteur IA">
                {aiProviders.map(p => (
                  <button
                    key={p}
                    onClick={() => handleProviderSelect(p)}
                    className={`px-2 py-0.5 rounded-full text-[11px] font-mono font-semibold uppercase tracking-wide transition-colors ${
                      selectedProvider === p
                        ? p === 'claude'
                          ? 'bg-purple-700 text-white'
                          : 'bg-green-800 text-green-200'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {p === 'claude' ? 'Claude' : 'EurIA'}
                  </button>
                ))}
              </div>
            )}
            {/* Toggle Web Search — masqué sur mobile (accessible via menu ⚙) */}
            {effectiveProvider === 'euria' && (
              <button
                onClick={() => setWebSearch(v => !v)}
                title={webSearch ? 'Recherche web activée (cliquez pour désactiver)' : 'Recherche web désactivée (cliquez pour activer)'}
                className={`hidden md:inline-flex items-center gap-1 font-mono text-[11px] px-2 py-0.5 rounded-full border transition-colors ${
                  webSearch
                    ? 'bg-blue-900/50 border-blue-700/60 text-blue-300 hover:bg-blue-900/70'
                    : 'bg-slate-800 border-slate-700/40 text-slate-500 hover:text-slate-300'
                }`}
              >
                🌐 Web
              </button>
            )}
            {/* Sélecteur de thème — masqué sur mobile (accessible via menu ⚙) */}
            <select
              value={terminalTheme}
              onChange={e => setTerminalTheme(e.target.value)}
              title="Thème de couleur du terminal"
              className="hidden md:block font-mono text-[11px] rounded-lg px-2 py-0.5 border border-slate-700 focus:outline-none cursor-pointer transition-colors"
              style={{
                background: theme.headerBg,
                color: theme.titleColor,
                borderColor: theme.border,
              }}
            >
              {Object.entries(TERMINAL_THEMES).map(([key, t]) => (
                <option key={key} value={key} style={{ background: '#1e1e1e', color: '#e2e8f0' }}>
                  {t.label}
                </option>
              ))}
            </select>

            {/* Bouton menu mobile — visible uniquement sur mobile, donne accès aux options avancées */}
            <div ref={mobileMenuRef} className="relative md:hidden shrink-0">
              <button
                onClick={() => setMobileMenuOpen(v => !v)}
                className={`w-6 h-6 rounded-full flex items-center justify-center transition-colors ${
                  mobileMenuOpen
                    ? 'bg-green-800 text-green-200'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white'
                }`}
                title="Options"
              >
                <SlidersHorizontal size={11} />
              </button>
              {mobileMenuOpen && (
                <div
                  className="absolute right-0 top-8 z-30 min-w-[200px] rounded-xl border border-green-900/40 shadow-lg flex flex-col gap-1 p-2"
                  style={{ background: theme.headerBg, borderColor: theme.border }}
                >
                  {/* Notes actives */}
                  {notesPeriod && (
                    <button
                      onClick={() => { setNotesPeriod(null); setMobileMenuOpen(false) }}
                      className="flex items-center gap-2 w-full text-left font-mono text-[11px] text-amber-400 bg-amber-900/30 border border-amber-800/50 px-2 py-1.5 rounded-lg hover:bg-amber-900/50 transition-colors"
                    >
                      <BookOpen size={10} />
                      Notes {PERIOD_LABELS[notesPeriod]} — désactiver
                    </button>
                  )}
                  {/* Sélection du provider IA */}
                  {aiProviders.length >= 2 && (
                    <div>
                      <p className="font-mono text-[10px] text-slate-500 px-1 mb-1">Moteur IA</p>
                      <div className="flex items-center gap-0.5 bg-slate-800 rounded-lg p-0.5">
                        {aiProviders.map(p => (
                          <button
                            key={p}
                            onClick={() => handleProviderSelect(p)}
                            className={`flex-1 px-2 py-1 rounded-full text-[11px] font-mono font-semibold uppercase tracking-wide transition-colors ${
                              selectedProvider === p
                                ? p === 'claude'
                                  ? 'bg-purple-700 text-white'
                                  : 'bg-green-800 text-green-200'
                                : 'text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            {p === 'claude' ? 'Claude' : 'EurIA'}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* Toggle Web Search */}
                  {effectiveProvider === 'euria' && (
                    <button
                      onClick={() => setWebSearch(v => !v)}
                      className={`flex items-center gap-2 w-full text-left font-mono text-[11px] px-2 py-1.5 rounded-lg border transition-colors ${
                        webSearch
                          ? 'bg-blue-900/50 border-blue-700/60 text-blue-300'
                          : 'bg-slate-800 border-slate-700/40 text-slate-400'
                      }`}
                    >
                      🌐 Recherche web {webSearch ? '— activée' : '— désactivée'}
                    </button>
                  )}
                  {/* Sélecteur de thème */}
                  <div>
                    <p className="font-mono text-[10px] text-slate-500 px-1 mb-1">Thème</p>
                    <select
                      value={terminalTheme}
                      onChange={e => { setTerminalTheme(e.target.value); setMobileMenuOpen(false) }}
                      className="w-full font-mono text-[11px] rounded-lg px-2 py-1 border border-slate-700 focus:outline-none cursor-pointer transition-colors"
                      style={{
                        background: theme.bg,
                        color: theme.titleColor,
                        borderColor: theme.border,
                      }}
                    >
                      {Object.entries(TERMINAL_THEMES).map(([key, t]) => (
                        <option key={key} value={key} style={{ background: '#1e1e1e', color: '#e2e8f0' }}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
            </div>

            {/* Bouton plein écran */}
            <button
              onClick={() => setFullscreen(v => !v)}
              className="w-6 h-6 shrink-0 rounded-full bg-slate-800 hover:bg-slate-700 flex items-center justify-center text-slate-300 hover:text-white transition-colors"
              title={fullscreen ? 'Réduire' : 'Plein écran'}
            >
              {fullscreen ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
            </button>
            {/* Bouton fermer — toujours visible */}
            <button
              onClick={onClose}
              className="w-6 h-6 shrink-0 rounded-full bg-slate-800 hover:bg-slate-700 flex items-center justify-center text-slate-300 hover:text-white transition-colors ml-1"
              title="Fermer"
            >
              <X size={12} />
            </button>
          </div>

          {/* ── Picker plein écran sur mobile ───────────────────────── */}
          {pickerOpen && (
            <div className="lg:hidden absolute inset-0 z-20 flex flex-col" style={{ background: theme.bg }}>
              {/* En-tête */}
              <div className="flex items-center gap-2 px-3 py-2.5 shrink-0 border-b border-green-900/40" style={{ background: theme.headerBg }}>
                <FileText size={12} className="text-green-500 shrink-0" />
                <span className="font-mono text-xs text-green-400 flex-1 uppercase tracking-widest">Contexte</span>
                {contextFiles.length > 0 && (
                  <span className="font-mono text-[11px] text-green-300 bg-green-900/40 px-2 py-0.5 rounded-full">
                    {contextFiles.length} sélectionné{contextFiles.length > 1 ? 's' : ''}
                  </span>
                )}
                <button
                  onClick={() => setPickerOpen(false)}
                  className="w-7 h-7 rounded-full bg-slate-700 hover:bg-slate-600 flex items-center justify-center text-slate-200 ml-1"
                >
                  <X size={13} />
                </button>
              </div>
              {/* Filtre */}
              <div className="px-3 py-2 border-b border-green-900/30 shrink-0">
                <input
                  type="text"
                  placeholder="Filtrer les fichiers…"
                  value={fileSearch}
                  onChange={e => setFileSearch(e.target.value)}
                  className="w-full bg-slate-900 border border-green-900/40 rounded-lg px-3 py-2 text-sm font-mono text-green-400 placeholder:text-slate-400 focus:outline-none focus:border-green-600"
                />
              </div>
              {/* Liste */}
              <div className="flex-1 overflow-y-auto">
                {groupedFiles.map(([flux, fluxFiles]) => (
                  <div key={flux}>
                    <div className="sticky top-0 z-10 flex items-center gap-1.5 px-3 py-2 border-b border-green-900/20" style={{ background: theme.bg }}>
                      <Folder size={10} className="text-green-800 shrink-0" />
                      <span className="font-mono text-[11px] text-green-700 uppercase tracking-widest truncate flex-1">{flux}</span>
                      <span className="font-mono text-[11px] text-green-900">{fluxFiles.length}</span>
                    </div>
                    {fluxFiles.map(f => (
                      <button
                        key={f.path}
                        onClick={() => toggleContextFile(f.path)}
                        className={`w-full text-left px-3 py-3 border-b border-green-900/10 flex items-center gap-2.5 transition-colors ${
                          contextFiles.includes(f.path)
                            ? 'bg-green-900/30 border-l-2 border-l-green-500 pl-[10px]'
                            : 'active:bg-slate-800/60'
                        }`}
                      >
                        {f.type === 'json'
                          ? <FileJson size={15} className="shrink-0 text-amber-500" />
                          : <FileText size={15} className="shrink-0 text-blue-400" />
                        }
                        <span className={`flex-1 text-sm font-mono truncate ${contextFiles.includes(f.path) ? 'text-green-300' : 'text-slate-200'}`}>
                          {f.name}
                        </span>
                        {isToday(f.modified) && (
                          <span className="shrink-0 text-[11px] font-bold uppercase bg-orange-500 text-white px-1.5 py-0.5 rounded-full">new</span>
                        )}
                        {contextFiles.includes(f.path) && (
                          <Check size={14} className="shrink-0 text-green-500" />
                        )}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
              {/* Bouton confirmer */}
              <div
                className="shrink-0 px-3 py-3 border-t border-green-900/30"
                style={{
                  background: theme.headerBg,
                  paddingBottom: 'max(12px, env(safe-area-inset-bottom))',
                }}
              >
                <button
                  onClick={() => setPickerOpen(false)}
                  className="w-full bg-green-800 hover:bg-green-700 active:bg-green-600 text-green-100 font-mono text-sm rounded-lg py-3 transition-colors"
                >
                  {contextFiles.length > 0
                    ? `✓ Valider (${contextFiles.length} fichier${contextFiles.length > 1 ? 's' : ''})`
                    : 'Fermer'}
                </button>
              </div>
            </div>
          )}

          {/* ── Corps : sidebar contexte + zone chat ────────────────── */}
          <div className="flex flex-1 min-h-0 overflow-hidden">

            {/* Sidebar sélection de fichiers (desktop) — masquée si contexte entité, article ou flux */}
            <div
              className={`${entityContext || articleContext || fluxContext ? 'hidden' : 'hidden lg:flex'} flex-col w-64 shrink-0 border-r border-green-900/30 overflow-hidden`}
              style={{ background: theme.bg }}
            >
              <div className="px-3 py-2 border-b border-green-900/30">
                <div className="flex items-center gap-1.5 mb-2">
                  <FileText size={11} className="text-green-600" />
                  <span className="font-mono text-[11px] text-green-600 uppercase tracking-widest">Contexte</span>
                </div>
                <input
                  type="text"
                  placeholder="Filtrer…"
                  value={fileSearch}
                  onChange={e => setFileSearch(e.target.value)}
                  className="w-full bg-slate-900 border border-green-900/40 rounded-lg px-2 py-1 text-[11px] font-mono text-green-400 placeholder:text-slate-400 focus:outline-none focus:border-green-600"
                />
              </div>
              <div className="flex-1 overflow-y-auto custom-scrollbar">
                {filteredFiles.length === 0 ? (
                  <p className="text-[11px] font-mono text-slate-400 px-3 py-3">Aucun fichier disponible</p>
                ) : (
                  groupedFiles.map(([flux, fluxFiles]) => (
                    <div key={flux}>
                      {/* En-tête de groupe */}
                      <div className="sticky top-0 z-10 flex items-center gap-1.5 px-3 py-1.5 border-b border-green-900/30" style={{ background: theme.bg }}>
                        <Folder size={10} className="text-green-800 shrink-0" />
                        <span className="font-mono text-[11px] text-green-700 uppercase tracking-widest truncate flex-1">{flux}</span>
                        <span className="font-mono text-[11px] text-green-900">{fluxFiles.length}</span>
                      </div>
                      {/* Fichiers du groupe */}
                      {fluxFiles.map(f => (
                        <button
                          key={f.path}
                          onClick={() => toggleContextFile(f.path)}
                          className={`w-full text-left px-3 py-2 border-b border-green-900/20 transition-colors flex items-start gap-2 ${
                            contextFiles.includes(f.path)
                              ? 'bg-green-900/30 border-l-2 border-l-green-500 pl-[10px]'
                              : 'hover:bg-slate-800/60'
                          }`}
                        >
                          {f.type === 'json'
                            ? <FileJson size={12} className="shrink-0 mt-0.5 text-amber-500" />
                            : <FileText size={12} className="shrink-0 mt-0.5 text-blue-400" />
                          }
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1 leading-snug">
                              <span className={`truncate text-[11px] font-mono ${
                                contextFiles.includes(f.path) ? 'text-green-300' : 'text-slate-200'
                              }`}>{f.name}</span>
                              {isToday(f.modified) && (
                                <span className="shrink-0 text-[8px] font-bold uppercase tracking-wide px-1 rounded-full bg-orange-500 text-white leading-tight" style={{paddingTop:'1px',paddingBottom:'1px'}}>new</span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className={`text-[11px] px-1 rounded-full font-mono leading-4 ${
                                f.type === 'json'
                                  ? 'bg-amber-900/40 text-amber-600'
                                  : 'bg-blue-900/40 text-blue-500'
                              }`}>{f.type === 'json' ? 'JSON' : 'MD'}</span>
                              <span className="text-[11px] text-slate-500">{formatSize(f.size)}</span>
                              <span className="text-[11px] text-slate-600 ml-auto">{formatDateShort(f.modified)}</span>
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  ))
                )}
              </div>
              {/* Notes personnelles (section dans la sidebar) */}
              <div className="px-3 py-2 border-t border-green-900/30">
                <div className="flex items-center gap-1.5 mb-2">
                  <BookOpen size={11} className="text-amber-600" />
                  <span className="font-mono text-[11px] text-amber-600 uppercase tracking-widest">Notes</span>
                </div>
                <div className="space-y-0.5">
                  {[
                    { label: 'Cette semaine', value: 'week' },
                    { label: 'Ce mois', value: 'month' },
                    { label: 'Toutes', value: 'all' },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setNotesPeriod(prev => prev === opt.value ? null : opt.value)}
                      className={`w-full text-left px-2 py-1 rounded-lg text-[11px] font-mono transition-colors flex items-start gap-1.5 ${
                        notesPeriod === opt.value
                          ? 'bg-amber-900/40 text-amber-300'
                          : 'text-slate-300 hover:text-amber-400 hover:bg-slate-800/50'
                      }`}
                    >
                      <span className="mt-0.5 shrink-0 text-amber-700">
                        {notesPeriod === opt.value ? '■' : '□'}
                      </span>
                      <span className="truncate leading-tight">{opt.label}</span>
                    </button>
                  ))}
                </div>
              </div>
              {/* Actions contexte */}
              {(contextFiles.length > 0 || notesPeriod) && (
                <div className="px-2 py-2 border-t border-green-900/30">
                  {contextFiles.length > 0 && (
                    <button
                      onClick={() => setContextFiles([])}
                      className="w-full text-[11px] font-mono text-slate-400 hover:text-red-400 transition-colors text-left flex items-center gap-1 mb-1"
                    >
                      <Trash2 size={9} />
                      Vider le contexte
                    </button>
                  )}
                  {notesPeriod && (
                    <button
                      onClick={() => setNotesPeriod(null)}
                      className="w-full text-[11px] font-mono text-slate-400 hover:text-amber-400 transition-colors text-left flex items-center gap-1"
                    >
                      <Trash2 size={9} />
                      Désactiver les notes
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Zone principale : chat + input */}
            <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

              {/* ── Zone de chat ─────────────────────────────────────── */}
              <div
                className="flex-1 overflow-y-auto px-4 py-4 custom-scrollbar"
                style={{ background: theme.bg }}
              >
                {/* Message de bienvenue */}
                {messages.length === 0 && (
                  <div className="mb-6">
                    <p className="font-mono text-xs text-green-400 mb-1">
                      WUDD.ai Terminal IA — prêt.
                    </p>
                    <p className="font-mono text-xs text-slate-400 mb-4">
                      Interrogez vos articles et rapports. Sélectionnez des fichiers comme contexte dans la barre latérale.
                    </p>
                    {/* Fichiers de contexte sur mobile */}
                    <div className="lg:hidden mb-4">
                      <div className="flex gap-2 flex-wrap">
                        <button
                          onClick={() => setPickerOpen(v => !v)}
                          className="inline-flex items-center gap-1.5 text-xs font-mono text-green-600 hover:text-green-400 border border-green-900/40 rounded-lg px-2 py-1 transition-colors"
                        >
                          <FileText size={11} />
                          {contextFiles.length > 0
                            ? `${contextFiles.length} fichier${contextFiles.length > 1 ? 's' : ''} en contexte`
                            : 'Ajouter contexte'}
                        </button>
                        <button
                          onClick={() => setNotesPeriod(prev => prev ? null : 'week')}
                          className={`inline-flex items-center gap-1.5 text-xs font-mono border rounded-lg px-2 py-1 transition-colors ${
                            notesPeriod
                              ? 'text-amber-400 border-amber-800/50 bg-amber-900/30'
                              : 'text-amber-700 border-amber-900/40 hover:text-amber-400'
                          }`}
                        >
                          <BookOpen size={11} />
                          {notesPeriod ? `Notes (${PERIOD_LABELS[notesPeriod]})` : 'Notes personnelles'}
                        </button>
                      </div>
                      {pickerOpen && (
                        <div className="mt-2 border border-green-900/30 rounded-lg overflow-hidden max-h-52 overflow-y-auto">
                          <div className="p-2 border-b border-green-900/30">
                            <input
                              type="text"
                              placeholder="Filtrer…"
                              value={fileSearch}
                              onChange={e => setFileSearch(e.target.value)}
                              className="w-full bg-slate-900 border border-green-900/40 rounded-lg px-2 py-1 text-[11px] font-mono text-green-400 placeholder:text-slate-400 focus:outline-none focus:border-green-600"
                            />
                          </div>
                          {groupedFiles.map(([flux, fluxFiles]) => (
                            <div key={flux}>
                              <div className="flex items-center gap-1.5 px-2 py-1 bg-slate-900/60 border-b border-green-900/20">
                                <Folder size={9} className="text-green-800 shrink-0" />
                                <span className="font-mono text-[11px] text-green-700 uppercase tracking-widest truncate">{flux}</span>
                              </div>
                              {fluxFiles.map(f => (
                                <button
                                  key={f.path}
                                  onClick={() => toggleContextFile(f.path)}
                                  className={`w-full text-left px-2 py-1.5 border-b border-green-900/10 flex items-center gap-1.5 transition-colors ${
                                    contextFiles.includes(f.path)
                                      ? 'bg-green-900/30 border-l-2 border-l-green-500'
                                      : 'hover:bg-slate-800/60'
                                  }`}
                                >
                                  {f.type === 'json'
                                    ? <FileJson size={10} className="shrink-0 text-amber-500" />
                                    : <FileText size={10} className="shrink-0 text-blue-400" />
                                  }
                                  <span className={`truncate flex-1 text-[11px] font-mono ${
                                    contextFiles.includes(f.path) ? 'text-green-300' : 'text-slate-200'
                                  }`}>{f.name}</span>
                                  {isToday(f.modified) && (
                                    <span className="shrink-0 text-[8px] font-bold uppercase bg-orange-500 text-white px-1 rounded-full" style={{paddingTop:'1px',paddingBottom:'1px'}}>new</span>
                                  )}
                                </button>
                              ))}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    {/* Commandes rapides spécifiques à l'entité */}
                    {entityContext && (
                      <div className="space-y-1 mb-4">
                        <p className="font-mono text-[11px] text-emerald-600 uppercase tracking-widest mb-2 flex items-center gap-1">
                          <span>◆</span>
                          {entityContext.value}
                        </p>
                        {[
                          { label: 'Synthèse de l\'actualité', text: `Fais une synthèse structurée de l'actualité récente concernant ${entityContext.value} à partir des articles en contexte.` },
                          { label: 'Entités liées', text: `Quelles sont les principales entités (personnes, organisations, pays) liées à ${entityContext.value} dans les articles ? Présente-les dans un tableau avec le nombre de co-occurrences.` },
                          { label: 'Évolution dans le temps', text: `Comment la couverture médiatique de ${entityContext.value} a-t-elle évolué dans le temps ? Identifie les périodes clés.` },
                          { label: 'Analyse éditoriale', text: `Analyse le ton éditorial des sources qui couvrent ${entityContext.value}. Y a-t-il des biais ou des divergences entre les sources ?` },
                          { label: 'Points de controverse', text: `Identifie les points de controverse ou de débat autour de ${entityContext.value} dans les articles en contexte.` },
                          { label: 'Fiche entité complète', text: `Génère une fiche structurée complète sur ${entityContext.value} : présentation, rôle, actualité récente, chiffres clés, relations principales, et tendances émergentes.` },
                        ].map((cmd, i) => (
                          <button
                            key={i}
                            onClick={() => sendMessage(cmd.text)}
                            disabled={streaming || entityContextLoading}
                            className="block w-full text-left font-mono text-xs text-slate-300 hover:text-emerald-400 hover:bg-slate-800/40 px-2 py-1 rounded-lg transition-colors disabled:opacity-40"
                          >
                            <ChevronRight size={10} className="inline mr-1 text-emerald-800" />
                            {cmd.label}
                          </button>
                        ))}
                      </div>
                    )}
                    {/* Commandes rapides */}
                    <div className="space-y-1">
                      <p className="font-mono text-[11px] text-slate-400 uppercase tracking-widest mb-2">
                        Commandes rapides
                      </p>
                      {QUICK_COMMANDS.map((cmd, i) => (
                        <button
                          key={i}
                          onClick={() => sendMessage(cmd.text)}
                          disabled={streaming}
                          className="block w-full text-left font-mono text-xs text-slate-300 hover:text-green-400 hover:bg-slate-800/40 px-2 py-1 rounded-lg transition-colors disabled:opacity-40"
                        >
                          <ChevronRight size={10} className="inline mr-1 text-green-700" />
                          {cmd.label}
                        </button>
                      ))}
                    </div>
                    {/* Notes personnelles */}
                    <div className="space-y-1 mt-4">
                      <p className="font-mono text-[11px] text-amber-700 uppercase tracking-widest mb-2 flex items-center gap-1">
                        <BookOpen size={9} />
                        Notes personnelles
                      </p>
                      {NOTES_QUICK_COMMANDS.map((cmd, i) => (
                        <button
                          key={i}
                          onClick={() => {
                            setNotesPeriod(cmd.period)
                            sendMessage(cmd.text, cmd.period)
                          }}
                          disabled={streaming}
                          className="block w-full text-left font-mono text-xs text-slate-300 hover:text-amber-400 hover:bg-slate-800/40 px-2 py-1 rounded-lg transition-colors disabled:opacity-40"
                        >
                          <ChevronRight size={10} className="inline mr-1 text-amber-800" />
                          {cmd.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Log de chargement du contexte entité */}
                {entityContext && (entityContextLoading || entityContextStats) && (
                  <div className="mb-4 font-mono text-[11px] border border-emerald-900/40 rounded-lg overflow-hidden">
                    <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-emerald-900/30" style={{ background: '#0f2318' }}>
                      <span className="text-emerald-600">◆</span>
                      <span className="text-emerald-500 font-semibold uppercase tracking-widest">
                        {entityContextLoading ? 'Chargement contexte entité…' : 'Contexte entité chargé'}
                      </span>
                      {entityContextStats && !entityContextLoading && (
                        <span className="ml-auto text-emerald-700">
                          {entityContextStats.article_count} art.
                          {entityContextStats.has_info ? ' · Synthèse IA ✓' : ''}
                          {entityContextStats.has_rag ? ' · RAG ✓' : ''}
                        </span>
                      )}
                    </div>
                    <div className="px-3 py-2 space-y-0.5" style={{ background: '#050d09' }}>
                      {entityContextLogs.map((log, i) => (
                        <div key={i} className={`flex items-start gap-1.5 ${i === entityContextLogs.length - 1 && entityContextLoading ? 'text-amber-400' : 'text-slate-500'}`}>
                          <span className="shrink-0 mt-0.5">
                            {i === entityContextLogs.length - 1 && entityContextLoading ? '▶' : '✓'}
                          </span>
                          <span>{log}</span>
                        </div>
                      ))}
                      {entityContextStep === 'done' && entityContextStats && (
                        <div className="flex items-center gap-1.5 text-emerald-600 mt-1 pt-1 border-t border-emerald-900/30">
                          <span>✓</span>
                          <span>Contexte prêt — vous pouvez poser vos questions</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Messages */}
                {messages.map((msg, idx) => renderMessage(msg, idx))}
                <div ref={endRef} />
              </div>

              {/* ── Zone de saisie ───────────────────────────────────── */}
              {/* Toast sauvegarde — flotte au-dessus sans pousser le layout */}
              {savedMsg && (
                <div className="shrink-0 px-3 pt-1.5 pb-0" style={{ background: theme.headerBg }}>
                  <div className="flex items-center gap-1.5 font-mono text-[11px] border border-green-900/40 rounded-lg px-2 py-1 bg-slate-900/80">
                    {savedMsg.startsWith('Erreur') ? (
                      <span className="text-red-400">{savedMsg}</span>
                    ) : (
                      <span className="text-green-500 flex items-center gap-1">
                        <Check size={10} />
                        Sauvegardé : {savedMsg}
                      </span>
                    )}
                  </div>
                </div>
              )}
              <div
                className="shrink-0 border-t border-green-900/30 px-3 py-2"
                style={{
                  background: theme.headerBg,
                  paddingBottom: 'max(20px, env(safe-area-inset-bottom))',
                  '--placeholder-color': theme.placeholderColor,
                }}
              >
                {/* Saisie */}
                <div className="flex items-end gap-2">
                  <div className="flex-1 flex items-start gap-2">
                    <span className="font-mono text-sm shrink-0 pt-0.5 select-none" style={{ color: theme.promptColor }}>▸</span>
                    <textarea
                      ref={inputRef}
                      value={input}
                      onChange={e => { setInput(e.target.value); historyIdxRef.current = -1 }}
                      onKeyDown={e => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          historyIdxRef.current = -1
                          historyDraft.current  = ''
                          sendMessage()
                          return
                        }
                        // Navigation historique : flèche haut/bas (desktop uniquement,
                        // seulement si le curseur est sur la première/dernière ligne)
                        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                          const userMsgs = messages
                            .filter(m => m.role === 'user')
                            .map(m => m.content)
                          if (userMsgs.length === 0) return
                          const ta = e.target
                          const atStart = ta.selectionStart === 0 && ta.selectionEnd === 0
                          const atEnd   = ta.selectionStart === ta.value.length
                          if (e.key === 'ArrowUp' && atStart) {
                            e.preventDefault()
                            if (historyIdxRef.current === -1) historyDraft.current = input
                            const next = Math.min(historyIdxRef.current + 1, userMsgs.length - 1)
                            historyIdxRef.current = next
                            const val = userMsgs[userMsgs.length - 1 - next]
                            setInput(val)
                            // Place le curseur en fin après le render
                            requestAnimationFrame(() => {
                              if (inputRef.current) {
                                inputRef.current.selectionStart = val.length
                                inputRef.current.selectionEnd   = val.length
                              }
                            })
                          } else if (e.key === 'ArrowDown' && atEnd) {
                            if (historyIdxRef.current === -1) return
                            e.preventDefault()
                            const next = historyIdxRef.current - 1
                            if (next < 0) {
                              historyIdxRef.current = -1
                              setInput(historyDraft.current)
                            } else {
                              historyIdxRef.current = next
                              setInput(userMsgs[userMsgs.length - 1 - next])
                            }
                          }
                        }
                      }}
                      rows={3}
                      placeholder="Posez votre question… (Shift+Entrée pour un saut de ligne)"
                      disabled={streaming}
                      className="flex-1 bg-transparent border-none resize-none font-mono text-sm focus:outline-none leading-relaxed chatbot-input"
                      style={{ color: theme.inputColor, minHeight: '5.25rem', maxHeight: '10rem', overflow: 'auto' }}
                    />
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0 pb-0.5">
                    {/* Sélecteur de fichiers — mobile uniquement */}
                    <button
                      onClick={() => setPickerOpen(v => !v)}
                      title="Ajouter des fichiers en contexte"
                      className="lg:hidden w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
                      style={{ color: contextFiles.length > 0 ? '#4ade80' : '#64748b' }}
                    >
                      <FileText size={13} />
                    </button>
                    {/* Effacer la conversation */}
                    {messages.some(m => !m.welcome) && (
                      <button
                        onClick={() => { ctrlRef.current?.abort(); setMessages([WELCOME_MSG]); setSavedMsg(null) }}
                        title="Effacer la conversation"
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-600 hover:text-red-400 transition-colors"
                      >
                        <RefreshCw size={13} />
                      </button>
                    )}
                    {/* Sauvegarder la conversation */}
                    {messages.some(m => !m.welcome) && (
                      <button
                        onClick={saveConversation}
                        disabled={saving}
                        title="Sauvegarder la conversation en Markdown"
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-500 hover:text-green-400 transition-colors disabled:opacity-40"
                      >
                        {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                      </button>
                    )}
                    {/* Envoyer */}
                    <button
                      onClick={() => sendMessage()}
                      disabled={!input.trim() || streaming}
                      className="w-7 h-7 rounded-lg bg-green-800 hover:bg-green-700 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-green-200 transition-colors"
                    >
                      {streaming ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
