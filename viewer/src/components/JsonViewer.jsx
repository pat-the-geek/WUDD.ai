import { useMemo, useState, useEffect } from 'react'
import { Pencil, X, Save } from 'lucide-react'

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/**
 * Applique la coloration syntaxique JSON via du HTML inline.
 * Utilise des classes CSS (json-key, json-string, etc.) plutôt que des
 * styles inline, afin que les couleurs s'adaptent au thème Jour/Nuit.
 */
function highlightJson(code) {
  const safe = escapeHtml(code)
  return safe.replace(
    /("(?:\\.|[^"\\])*"(?:\s*:)?|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      // Clé d'objet : chaîne suivie de ":"
      if (/^".*"(\s*):$/.test(match) || /^".*":$/.test(match)) {
        return `<span class="json-key">${match}</span>`
      }
      // Valeur chaîne
      if (match.startsWith('"')) {
        return `<span class="json-string">${match}</span>`
      }
      // Booléen
      if (match === 'true' || match === 'false') {
        return `<span class="json-bool">${match}</span>`
      }
      // Null
      if (match === 'null') {
        return `<span class="json-null">${match}</span>`
      }
      // Nombre
      return `<span class="json-number">${match}</span>`
    },
  )
}

export default function JsonViewer({ content, onSave }) {
  const [editMode, setEditMode] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [editError, setEditError] = useState(null)
  const [saving, setSaving] = useState(false)

  // Réinitialiser l'éditeur quand le contenu change (nouveau fichier)
  useEffect(() => {
    setEditMode(false)
    setEditError(null)
  }, [content])

  const { highlighted, parseError } = useMemo(() => {
    let formatted = content
    let parseError = null
    try {
      formatted = JSON.stringify(JSON.parse(content), null, 2)
    } catch (e) {
      parseError = e.message
    }
    return { highlighted: highlightJson(formatted), parseError }
  }, [content])

  const handleEditStart = () => {
    try {
      setEditContent(JSON.stringify(JSON.parse(content), null, 2))
    } catch {
      setEditContent(content)
    }
    setEditError(null)
    setEditMode(true)
  }

  const handleCancel = () => {
    setEditMode(false)
    setEditError(null)
  }

  const handleSave = async () => {
    try {
      JSON.parse(editContent)
    } catch (e) {
      setEditError(`JSON invalide : ${e.message}`)
      return
    }
    if (!onSave) return
    setSaving(true)
    setEditError(null)
    try {
      await onSave(editContent)
      setEditMode(false)
    } catch (e) {
      setEditError(e.message || 'Erreur lors de la sauvegarde')
    } finally {
      setSaving(false)
    }
  }

  if (editMode) {
    return (
      <div className="flex flex-col gap-3">
        {/* Barre d'outils édition */}
        <div className="flex items-center gap-2 justify-end order-last md:order-first sticky bottom-0 md:static bg-slate-100 dark:bg-slate-950 py-3 z-10">
          {editError && (
            <span className="text-xs text-red-500 dark:text-red-400 flex-1">{editError}</span>
          )}
          <button
            onClick={handleCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-xs text-slate-700 dark:text-slate-300 transition-colors"
          >
            <X size={12} /> Annuler
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[#007AFF] hover:bg-[#0071EB] dark:bg-[#0A84FF] dark:hover:bg-[#1E8FFF] disabled:opacity-60 text-white rounded-lg text-xs font-medium transition-colors"
          >
            <Save size={12} />
            {saving ? 'Sauvegarde…' : 'Sauvegarder'}
          </button>
        </div>

        {/* Zone de texte éditable */}
        <textarea
          value={editContent}
          onChange={e => { setEditContent(e.target.value); setEditError(null) }}
          spellCheck={false}
          className="w-full min-h-[60vh] text-sm font-mono leading-relaxed text-slate-800 dark:text-slate-200 bg-white dark:bg-slate-950 border border-blue-500/40 rounded-xl p-4 resize-y focus:outline-none focus:border-blue-400 transition-colors"
        />
      </div>
    )
  }

  return (
    <div>
      {/* Bouton Modifier (si sauvegarde disponible) */}
      {onSave && (
        <div className="flex justify-end mb-3">
          <button
            onClick={handleEditStart}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 rounded-lg text-xs text-slate-700 dark:text-slate-300 transition-colors"
          >
            <Pencil size={12} /> Modifier
          </button>
        </div>
      )}

      {parseError && (
        <div className="mb-3 px-3 py-2 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700/50 rounded-lg text-xs text-red-600 dark:text-red-400 font-mono">
          JSON invalide : {parseError}
        </div>
      )}
      <pre
        className="text-sm font-mono leading-relaxed text-slate-700 dark:text-slate-300 whitespace-pre-wrap break-words"
        dangerouslySetInnerHTML={{ __html: highlighted }}
      />
    </div>
  )
}
