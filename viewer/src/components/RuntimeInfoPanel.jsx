import React from 'react'
import { useState } from 'react'
import { Check, Copy } from 'lucide-react'

export default function RuntimeInfoPanel({ runtimeInfo, activePort, compact = false }) {
  const [copied, setCopied] = useState(false)

  if (!runtimeInfo) return null

  const port = String(activePort || runtimeInfo.default_viewer_port || '')
  const projectName = runtimeInfo.project_root
    ? runtimeInfo.project_root.split('/').filter(Boolean).at(-1)
    : 'WUDD.ai'

  const handleCopy = async () => {
    const payload = [
      `Port: ${port}`,
      `Port par défaut: ${runtimeInfo.default_viewer_port}`,
      `Projet: ${projectName}`,
      `Racine: ${runtimeInfo.project_root}`,
    ].join('\n')

    await navigator.clipboard.writeText(payload).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (compact) {
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 dark:border-amber-800 bg-amber-50/95 dark:bg-amber-900/25 px-2 py-1 text-[10px] font-semibold text-amber-700 dark:text-amber-300 shadow-sm backdrop-blur">
        <span>{`Port ${port}`}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center justify-center rounded-full p-0.5 hover:bg-amber-100 dark:hover:bg-amber-800/40 transition-colors"
          title="Copier les infos runtime"
          aria-label="Copier les infos runtime"
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
        </button>
      </div>
    )
  }

  return (
    <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-800/60 text-xs text-slate-600 dark:text-slate-300 shrink-0">
      <span className="font-semibold text-slate-700 dark:text-slate-200">Runtime</span>
      <span className="text-slate-400 dark:text-slate-500">•</span>
      <span>{`Port ${port}`}</span>
      <span className="text-slate-400 dark:text-slate-500">•</span>
      <span className="max-w-[120px] truncate" title={runtimeInfo.project_root}>{projectName}</span>
      <button
        type="button"
        onClick={handleCopy}
        className="ml-1 inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-600 px-2 py-1 text-[11px] font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        title="Copier les infos runtime"
      >
        {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
        {copied ? 'Copié' : 'Copier'}
      </button>
    </div>
  )
}