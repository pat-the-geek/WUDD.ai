/**
 * useFacePosition — Hook React pour la détection de visages.
 *
 * Retourne `objectPosition` (string CSS) calculé par face-api.js.
 * Pendant la détection, retourne la valeur de `initialPosition`.
 *
 * Usage :
 *   const pos = useFacePosition(imageUrl)
 *   <img style={{ objectFit: 'cover', objectPosition: pos }} ... />
 */
import { useState, useEffect } from 'react'
import { detectFaceObjectPosition } from '../utils/faceDetection'

const FALLBACK = '50% 25%'

export default function useFacePosition(imageUrl, initialPosition = FALLBACK) {
  const [objectPosition, setObjectPosition] = useState(initialPosition)

  useEffect(() => {
    if (!imageUrl) {
      setObjectPosition(initialPosition)
      return
    }

    let cancelled = false
    // Réinitialise à la valeur initiale pendant le calcul (évite le flash de mauvais cadrage)
    setObjectPosition(initialPosition)

    detectFaceObjectPosition(imageUrl).then((pos) => {
      if (!cancelled) setObjectPosition(pos)
    })

    return () => { cancelled = true }
  }, [imageUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  return objectPosition
}
