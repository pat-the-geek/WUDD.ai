import { useState, useEffect, useCallback } from 'react'
import { Volume2, VolumeX } from 'lucide-react'

// Singleton global : une seule instance TTS active à la fois
let _setActive = null

/** Arrête toute synthèse vocale en cours et réinitialise l'état React associé. */
export function stopAll() {
  window.speechSynthesis?.cancel()
  if (_setActive) { _setActive(false); _setActive = null }
}

/** Nettoie le Markdown pour produire du texte brut lisible à voix haute. */
export function stripMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/^---[\s\S]*?---\n?/, '')        // frontmatter YAML
    .replace(/#{1,6}\s+/g, '')                // titres
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')      // gras
    .replace(/\*([^*\n]+)\*/g, '$1')          // italique
    .replace(/__([^_\n]+)__/g, '$1')
    .replace(/_([^_\n]+)_/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')  // liens Markdown
    .replace(/`{1,3}[^`]*`{1,3}/g, '')        // code inline / bloc
    .replace(/^[-*+]\s+/gm, '')               // listes à puces
    .replace(/^\d+\.\s+/gm, '')               // listes numérotées
    .replace(/^>\s+/gm, '')                   // blockquotes
    .replace(/---+/g, '. ')                   // séparateurs horizontaux
    .replace(/\n{2,}/g, '. ')
    .replace(/\n/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

/**
 * Hook TTS partagé.
 * Garantit qu'une seule synthèse vocale est active à la fois.
 * @param {string} text — texte brut ou Markdown à lire
 */
export function useTTS(text) {
  const [speaking, setSpeaking] = useState(false)

  const toggle = useCallback(() => {
    if (!window.speechSynthesis) return

    // Arrête toujours la synthèse en cours
    window.speechSynthesis.cancel()

    if (speaking) {
      if (_setActive === setSpeaking) _setActive = null
      setSpeaking(false)
      return
    }

    // Réinitialise l'état de l'instance précédente
    if (_setActive && _setActive !== setSpeaking) {
      _setActive(false)
    }
    _setActive = setSpeaking

    const clean = stripMarkdown(text)
    if (!clean) return

    const utt = new SpeechSynthesisUtterance(clean)
    utt.lang  = 'fr-FR'
    utt.rate  = 0.92

    const onDone = () => {
      setSpeaking(false)
      if (_setActive === setSpeaking) _setActive = null
    }
    utt.onend   = onDone
    utt.onerror = onDone

    setSpeaking(true)
    window.speechSynthesis.speak(utt)
  }, [speaking, text])

  // Nettoyage si le composant est démonté pendant la lecture
  useEffect(() => () => {
    if (_setActive === setSpeaking) {
      window.speechSynthesis?.cancel()
      _setActive = null
    }
  }, [])

  return { speaking, toggle }
}

/**
 * Bouton icône pour activer / arrêter la lecture à voix haute.
 *
 * Props :
 *   text      — texte à lire (Markdown accepté, sera nettoyé)
 *   size      — taille de l'icône (défaut 13)
 *   className — classes Tailwind supplémentaires
 */
export default function TTSButton({ text, size = 13, className = '' }) {
  const { speaking, toggle } = useTTS(text)

  if (typeof window === 'undefined' || !window.speechSynthesis || !text) return null

  return (
    <button
      onClick={toggle}
      title={speaking ? 'Arrêter la lecture' : 'Lire à voix haute'}
      aria-label={speaking ? 'Arrêter la lecture' : 'Lire à voix haute'}
      className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
        speaking
          ? 'text-[#007AFF] dark:text-[#0A84FF] bg-blue-50 dark:bg-blue-900/30'
          : 'text-slate-400 dark:text-slate-500 hover:text-[#007AFF] dark:hover:text-[#0A84FF] hover:bg-blue-50 dark:hover:bg-blue-900/20'
      } ${className}`}
    >
      {speaking ? <VolumeX size={size} /> : <Volume2 size={size} />}
    </button>
  )
}
