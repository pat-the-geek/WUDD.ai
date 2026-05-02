/**
 * faceDetection.js — Détection de visages via face-api.js (TinyFaceDetector)
 *
 * Fournit detectFaceObjectPosition(imageUrl) → "X% Y%"
 * Le modèle est chargé une seule fois (singleton) depuis /models/.
 */
import * as faceapi from 'face-api.js'

const MODEL_URL = '/models'
const MAX_CONCURRENT_DETECTIONS = 2

let modelsLoaded = false
let loadingPromise = null

async function loadModels() {
  if (modelsLoaded) return
  if (loadingPromise) return loadingPromise
  loadingPromise = faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL).then(() => {
    modelsLoaded = true
  })
  return loadingPromise
}

// Cache URL → objectPosition pour éviter de re-détecter la même image
const positionCache = new Map()
// Dédoublonne les appels simultanés sur la même URL
const inFlightByUrl = new Map()

let activeDetections = 0
const waitingQueue = []

function acquireSlot() {
  if (activeDetections < MAX_CONCURRENT_DETECTIONS) {
    activeDetections += 1
    return Promise.resolve()
  }
  return new Promise((resolve) => waitingQueue.push(resolve))
}

function releaseSlot() {
  if (waitingQueue.length > 0) {
    const next = waitingQueue.shift()
    next()
    return
  }
  activeDetections = Math.max(0, activeDetections - 1)
}

async function runWithConcurrencyLimit(task) {
  await acquireSlot()
  try {
    return await task()
  } finally {
    releaseSlot()
  }
}

/**
 * Charge une image crossorigin dans un HTMLImageElement temporaire.
 * Retourne null en cas d'erreur (image inaccessible, CORS bloqué, etc.).
 */
function loadImage(url) {
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload  = () => resolve(img)
    img.onerror = () => resolve(null)
    // Timeout 8s pour ne pas bloquer indéfiniment
    const t = setTimeout(() => resolve(null), 8000)
    img.onload = () => { clearTimeout(t); resolve(img) }
    img.src = url
  })
}

/**
 * Détecte la position du visage dominant dans l'image et retourne
 * un string CSS `object-position` centré sur ce visage.
 *
 * Fallback : "50% 25%" (haut-centre, bon pour les photos de presse)
 */
export async function detectFaceObjectPosition(imageUrl) {
  if (!imageUrl) return 'center'
  if (positionCache.has(imageUrl)) return positionCache.get(imageUrl)
  if (inFlightByUrl.has(imageUrl)) return inFlightByUrl.get(imageUrl)

  const FALLBACK = '50% 25%'

  const taskPromise = runWithConcurrencyLimit(async () => {
    try {
      await loadModels()
      const img = await loadImage(imageUrl)
      if (!img) {
        positionCache.set(imageUrl, FALLBACK)
        return FALLBACK
      }

      const options = new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.4 })
      const detections = await faceapi.detectAllFaces(img, options)

      if (!detections || detections.length === 0) {
        positionCache.set(imageUrl, FALLBACK)
        return FALLBACK
      }

      // Choisir le visage avec la plus grande boîte englobante
      const largest = detections.reduce((best, d) =>
        d.box.width * d.box.height > best.box.width * best.box.height ? d : best
      )

      const { x, y, width, height } = largest.box
      const imgW = img.naturalWidth  || img.width
      const imgH = img.naturalHeight || img.height

      if (!imgW || !imgH) {
        positionCache.set(imageUrl, FALLBACK)
        return FALLBACK
      }

      // Centre du visage en pourcentage, clamped pour ne pas couper les bords
      const faceCenterX = x + width  / 2
      const faceCenterY = y + height / 2

      const pctX = Math.round(Math.max(10, Math.min(90, (faceCenterX / imgW) * 100)))
      const pctY = Math.round(Math.max(10, Math.min(90, (faceCenterY / imgH) * 100)))

      const position = `${pctX}% ${pctY}%`
      positionCache.set(imageUrl, position)
      return position
    } catch {
      positionCache.set(imageUrl, FALLBACK)
      return FALLBACK
    } finally {
      inFlightByUrl.delete(imageUrl)
    }
  })

  inFlightByUrl.set(imageUrl, taskPromise)
  return taskPromise
}

/** Vide le cache (utile si les URLs sont réutilisées avec des images différentes) */
export function clearFacePositionCache() {
  positionCache.clear()
}
