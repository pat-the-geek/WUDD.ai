import { useState, useEffect, useMemo } from 'react'
import { X, Rss, Mail, Webhook, Copy, Check, Download, Send, RefreshCw, ExternalLink, AlertTriangle, CheckCircle2 } from 'lucide-react'

// ── Helpers ──────────────────────────────────────────────────────────────────

function TabButton({ active, onClick, icon: Icon, label }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
        active
          ? 'border-blue-500 text-blue-600 dark:text-blue-400'
          : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
      }`}
    >
      <Icon size={14} />
      {label}
    </button>
  )
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border transition-colors bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300"
      title="Copier l'URL"
    >
      {copied ? <><Check size={12} className="text-green-500" /> Copié</> : <><Copy size={12} /> Copier</>}
    </button>
  )
}

function StatusBanner({ ok, message }) {
  if (!message) return null
  return (
    <div className={`flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm border ${
      ok
        ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700/40 text-green-700 dark:text-green-400'
        : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700/40 text-red-700 dark:text-red-400'
    }`}>
      {ok ? <CheckCircle2 size={14} className="shrink-0 mt-0.5" /> : <AlertTriangle size={14} className="shrink-0 mt-0.5" />}
      <span>{message}</span>
    </div>
  )
}

// ── Tab Atom XML ─────────────────────────────────────────────────────────────

function AtomTab({ fluxes, keywords }) {
  const [sourceType, setSourceType] = useState('all')   // 'all' | 'flux' | 'keyword'
  const [flux, setFlux] = useState('')
  const [keyword, setKeyword] = useState('')
  const [maxEntries, setMaxEntries] = useState(50)

  const atomUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (sourceType === 'flux' && flux) params.set('flux', flux)
    if (sourceType === 'keyword' && keyword) params.set('keyword', keyword)
    params.set('max_entries', maxEntries)
    return `/api/export/atom?${params}`
  }, [sourceType, flux, keyword, maxEntries])

  const fullUrl = `${window.location.origin}${atomUrl}`

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Génère un flux <strong className="font-medium text-slate-700 dark:text-slate-300">Atom XML</strong> pour
        les articles WUDD.ai, compatible avec tous les lecteurs de flux RSS (Reeder, NetNewsWire, Feedly…).
      </p>

      {/* Source */}
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">Source</label>
        <div className="flex gap-2 flex-wrap">
          {[['all', 'Toutes les veilles'], ['flux', 'Un flux'], ['keyword', 'Un mot-clé']].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setSourceType(v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                sourceType === v
                  ? 'bg-blue-600 text-white border-blue-500'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:bg-slate-200 dark:hover:bg-slate-600'
              }`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>

      {sourceType === 'flux' && (
        <div>
          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Flux</label>
          <select
            value={flux}
            onChange={e => setFlux(e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Choisir un flux —</option>
            {fluxes.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
      )}

      {sourceType === 'keyword' && (
        <div>
          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Mot-clé</label>
          <select
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Choisir un mot-clé —</option>
            {keywords.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
      )}

      {/* Max entries */}
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
          Nombre d'entrées max : <strong>{maxEntries}</strong>
        </label>
        <input
          type="range" min={5} max={200} step={5}
          value={maxEntries}
          onChange={e => setMaxEntries(Number(e.target.value))}
          className="w-full accent-blue-600"
        />
        <div className="flex justify-between text-xs text-slate-400 mt-0.5">
          <span>5</span><span>200</span>
        </div>
      </div>

      {/* URL générée */}
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">URL du flux</label>
        <div className="flex gap-2 items-center">
          <code className="flex-1 px-3 py-2 text-xs rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 truncate font-mono">
            {fullUrl}
          </code>
          <CopyButton text={fullUrl} />
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2 flex-wrap">
        <a
          href={atomUrl}
          download="wudd-feed.xml"
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] text-white transition-colors"
        >
          <Download size={14} /> Télécharger le flux
        </a>
        <a
          href={atomUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 transition-colors"
        >
          <ExternalLink size={14} /> Aperçu XML
        </a>
      </div>
    </div>
  )
}

// ── Tab Newsletter ───────────────────────────────────────────────────────────

function NewsletterTab() {
  const [hours, setHours] = useState(48)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState(null)  // { ok, message }

  const nlUrl = `/api/export/newsletter?hours=${hours}${title ? `&title=${encodeURIComponent(title)}` : ''}`

  const handlePreview = () => {
    window.open(nlUrl, '_blank', 'noopener,noreferrer')
  }

  const handleDownload = async () => {
    setLoading(true)
    setStatus(null)
    try {
      const r = await fetch(nlUrl)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const html = await r.text()
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `newsletter-${new Date().toISOString().slice(0,10)}.html`
      a.click()
      URL.revokeObjectURL(a.href)
      setStatus({ ok: true, message: 'Newsletter téléchargée avec succès.' })
    } catch (e) {
      setStatus({ ok: false, message: `Erreur : ${e.message}` })
    } finally {
      setLoading(false)
    }
  }

  const handleSend = async () => {
    setSending(true)
    setStatus(null)
    try {
      const params = new URLSearchParams({ hours })
      if (title) params.set('title', title)
      const r = await fetch(`/api/export/newsletter?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ send: true }),
      })
      const data = await r.json()
      if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`)
      setStatus({
        ok: data.ok !== false,
        message: data.ok
          ? `Newsletter envoyée avec succès${data.path ? ` · ${data.path}` : ''}.`
          : 'Envoi échoué — vérifiez la configuration SMTP dans .env.',
      })
    } catch (e) {
      setStatus({ ok: false, message: `Erreur : ${e.message}` })
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Génère une <strong className="font-medium text-slate-700 dark:text-slate-300">newsletter HTML</strong> avec les
        20 articles les mieux classés de la fenêtre temporelle. Peut être envoyée par SMTP si configuré dans{' '}
        <code className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-xs">.env</code>.
      </p>

      {/* Fenêtre temporelle */}
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
          Fenêtre temporelle : <strong>{hours}h</strong>
        </label>
        <div className="flex gap-2 flex-wrap">
          {[24, 48, 72, 168].map(h => (
            <button
              key={h}
              onClick={() => setHours(h)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                hours === h
                  ? 'bg-blue-600 text-white border-blue-500'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:bg-slate-200 dark:hover:bg-slate-600'
              }`}
            >
              {h === 168 ? '7 jours' : `${h}h`}
            </button>
          ))}
        </div>
      </div>

      {/* Titre optionnel */}
      <div>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
          Sujet / titre <span className="text-slate-400">(optionnel)</span>
        </label>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder={`Veille WUDD.ai — ${new Date().toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' })}`}
          className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {status && <StatusBanner ok={status.ok} message={status.message} />}

      {/* Actions */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={handlePreview}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 transition-colors"
        >
          <ExternalLink size={14} /> Aperçu
        </button>
        <button
          onClick={handleDownload}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] disabled:opacity-60 text-white transition-colors"
        >
          {loading ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
          Télécharger HTML
        </button>
        <button
          onClick={handleSend}
          disabled={sending}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white transition-colors"
          title="Requiert SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_TO dans .env"
        >
          {sending ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
          Envoyer par e-mail
        </button>
      </div>

      <p className="text-xs text-slate-400 dark:text-slate-500 flex items-start gap-1.5">
        <AlertTriangle size={12} className="shrink-0 mt-0.5" />
        L'envoi SMTP nécessite <code className="px-1 rounded bg-slate-100 dark:bg-slate-800">SMTP_HOST</code>,{' '}
        <code className="px-1 rounded bg-slate-100 dark:bg-slate-800">SMTP_USER</code>,{' '}
        <code className="px-1 rounded bg-slate-100 dark:bg-slate-800">SMTP_PASSWORD</code> et{' '}
        <code className="px-1 rounded bg-slate-100 dark:bg-slate-800">SMTP_TO</code> dans <code className="px-1 rounded bg-slate-100 dark:bg-slate-800">.env</code>.
      </p>
    </div>
  )
}

// ── Tab Webhook ──────────────────────────────────────────────────────────────

const PLATFORMS = [
  { id: 'discord', label: 'Discord', color: 'bg-indigo-600 hover:bg-indigo-500', envKey: 'WEBHOOK_DISCORD' },
  { id: 'slack',   label: 'Slack',   color: 'bg-green-600 hover:bg-green-500',   envKey: 'WEBHOOK_SLACK'   },
  { id: 'ntfy',    label: 'Ntfy',    color: 'bg-orange-600 hover:bg-orange-500', envKey: 'NTFY_URL'        },
  { id: 'all',     label: 'Toutes', color: 'bg-slate-700 hover:bg-slate-600',   envKey: null              },
]

function WebhookTab() {
  const [results, setResults] = useState({})
  const [loading, setLoading] = useState(null)
  const [globalError, setGlobalError] = useState(null)

  const handleTest = async (platform) => {
    setLoading(platform)
    setGlobalError(null)
    try {
      const r = await fetch('/api/export/webhook-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform }),
      })
      const data = await r.json()
      if (data.error) throw new Error(data.error)
      if (data.message) {
        // "Aucune alerte disponible"
        setGlobalError(data.message)
      } else {
        setResults(prev => ({ ...prev, [platform]: data }))
      }
    } catch(e) {
      setGlobalError(e.message)
    } finally {
      setLoading(null)
    }
  }

  const renderResult = (platform) => {
    const r = results[platform]
    if (!r) return null
    const entries = Object.entries(r)
    const allOk = entries.every(([, v]) => v === true)
    const anyFail = entries.some(([, v]) => v === false)
    return (
      <div className={`ml-2 text-xs font-medium ${allOk ? 'text-green-500' : anyFail ? 'text-red-500' : 'text-slate-400'}`}>
        {allOk ? '✓ Envoyé' : anyFail ? '✗ Échec' : JSON.stringify(r)}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Envoie les <strong className="font-medium text-slate-700 dark:text-slate-300">alertes de tendances</strong> actuelles
        vers vos canaux de notification. Les URLs sont configurées dans{' '}
        <code className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-xs">.env</code>.
      </p>

      {globalError && <StatusBanner ok={false} message={globalError} />}

      <div className="space-y-3">
        {PLATFORMS.map(({ id, label, color, envKey }) => (
          <div key={id} className="flex items-center gap-3">
            <button
              onClick={() => handleTest(id)}
              disabled={loading === id}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors disabled:opacity-60 ${color}`}
            >
              {loading === id
                ? <RefreshCw size={13} className="animate-spin" />
                : <Send size={13} />
              }
              Test {label}
            </button>
            {envKey && (
              <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">
                {envKey}
              </span>
            )}
            {renderResult(id)}
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/60">
              <th className="text-left px-3 py-2 font-medium text-slate-600 dark:text-slate-400">Variable .env</th>
              <th className="text-left px-3 py-2 font-medium text-slate-600 dark:text-slate-400">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
            {[
              ['WEBHOOK_DISCORD', 'URL Incoming Webhook Discord'],
              ['WEBHOOK_SLACK',   'URL Incoming Webhook Slack'],
              ['NTFY_URL',        'Ex : https://ntfy.sh/wudd-alerts'],
              ['NTFY_TOKEN',      'Token Ntfy (optionnel, auth privée)'],
            ].map(([k, v]) => (
              <tr key={k} className="hover:bg-slate-50 dark:hover:bg-slate-800/30">
                <td className="px-3 py-2 font-mono text-blue-600 dark:text-blue-400">{k}</td>
                <td className="px-3 py-2 text-slate-500 dark:text-slate-400">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Panel principal ──────────────────────────────────────────────────────────

const TABS = [
  { id: 'atom',       label: 'Atom XML',   Icon: Rss     },
  { id: 'newsletter', label: 'Newsletter', Icon: Mail    },
  { id: 'webhook',    label: 'Webhook',    Icon: Webhook },
]

export default function ExportPanel({ onClose, files = [] }) {
  const [activeTab, setActiveTab] = useState('atom')

  // Dérive les listes de flux et mots-clés depuis la liste de fichiers
  const { fluxes, keywords } = useMemo(() => {
    const fluxSet   = new Set()
    const keySet    = new Set()
    for (const f of files) {
      if (f.type !== 'json') continue
      const parts = f.path.split('/')
      if (parts[0] === 'data' && parts[1] === 'articles' && parts.length >= 3) {
        fluxSet.add(parts[2])   // data/articles/<flux>/<file>.json
      }
      if (parts[0] === 'data' && parts[1] === 'articles-from-rss') {
        keySet.add(f.name.replace(/\.json$/, ''))
      }
    }
    return {
      fluxes:   [...fluxSet].sort((a, b) => a.localeCompare(b, 'fr')),
      keywords: [...keySet].sort((a, b) => a.localeCompare(b, 'fr')),
    }
  }, [files])

  // Fermeture au clavier
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-xl glass-panel rounded-2xl shadow-2xl border border-white/45 dark:border-white/[0.09] flex flex-col overflow-hidden max-h-[90vh]">
        {/* En-tête */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <div className="flex items-center gap-2">
            <Rss size={16} className="text-orange-500" />
            <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">Export & Diffusion</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors touch-target"
          >
            <X size={16} />
          </button>
        </div>

        {/* Onglets */}
        <div className="flex border-b border-slate-200 dark:border-slate-700 shrink-0 overflow-x-auto">
          {TABS.map(({ id, label, Icon }) => (
            <TabButton
              key={id}
              active={activeTab === id}
              onClick={() => setActiveTab(id)}
              icon={Icon}
              label={label}
            />
          ))}
        </div>

        {/* Contenu de l'onglet */}
        <div className="flex-1 overflow-y-auto p-5">
          {activeTab === 'atom'       && <AtomTab fluxes={fluxes} keywords={keywords} />}
          {activeTab === 'newsletter' && <NewsletterTab />}
          {activeTab === 'webhook'    && <WebhookTab />}
        </div>
      </div>
    </div>
  )
}
