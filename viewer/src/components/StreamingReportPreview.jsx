export default function StreamingReportPreview({ text, tone = 'slate' }) {
  const palette = tone === 'violet'
    ? 'border-violet-200 dark:border-violet-800 bg-violet-50/70 dark:bg-violet-900/15'
    : 'border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/40'

  return (
    <div className={`rounded-2xl border px-5 py-4 ${palette}`}>
      <div className="whitespace-pre-wrap break-words font-reading text-[17px] leading-8 text-slate-700 dark:text-slate-300">
        {text}
      </div>
    </div>
  )
}

export function StreamingCursor({ tone = 'slate' }) {
  const palette = tone === 'violet'
    ? 'bg-violet-500 dark:bg-violet-400'
    : 'bg-blue-500 dark:bg-blue-400'

  return <span className={`inline-block w-1.5 h-4 rounded-sm align-middle animate-pulse ${palette}`} />
}