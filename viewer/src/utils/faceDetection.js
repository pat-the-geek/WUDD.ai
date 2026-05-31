/**
 * faceDetection.js — Détection de visages via face-api.js (TinyFaceDetector)
 *
 * Fournit :
 *  - detectFaceCenter(imageUrl)        → { cx, cy, imgW, imgH } | null  (point focal normalisé)
 *  - coverObjectPosition(...)          → "X% Y%" exact pour un conteneur object-cover donné
 *  - detectFaceObjectPosition(imageUrl)→ "X% Y%" (compat : centre du visage, sans ratio conteneur)
 *
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

// Cache URL → { cx, cy, imgW, imgH } | null (résultat de détection, indépendant du conteneur)
const centerCache = new Map()
// Dédoublonne les appels simultanés sur la même URL
const inFlightByUrl = new Map()
// Cache URL → { kind:'face'|'subject', ... } | null (point focal unifié visage OU sujet)
const focusCache = new Map()
const inFlightFocus = new Map()

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

// Proxy same-origin pour les images dont le CDN ne renvoie pas d'en-têtes CORS
// (sinon le canvas est « tainted » et l'analyse pixel est impossible).
const IMAGE_PROXY = '/api/image-proxy?url='

/**
 * Charge une image analysable (canvas non « tainted ») dans un HTMLImageElement.
 * Essaie d'abord le chargement direct en CORS ; si le CDN ne renvoie pas les
 * en-têtes CORS (onerror), retombe sur le proxy same-origin du backend.
 * Retourne null si les deux échouent.
 */
function loadImage(url) {
  return new Promise((resolve) => {
    const attempt = (src, viaProxy) => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      let settled = false
      const t = setTimeout(() => finish(false), 8000)
      const finish = (ok) => {
        if (settled) return
        settled = true
        clearTimeout(t)
        if (ok) resolve(img)
        else if (!viaProxy) attempt(IMAGE_PROXY + encodeURIComponent(url), true)
        else resolve(null)
      }
      img.onload = () => finish(true)
      img.onerror = () => finish(false)
      img.src = src
    }
    attempt(url, false)
  })
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const clamp01 = (v) => Math.max(0, Math.min(1, v))

/**
 * Choisit LE visage dominant (plus grande boîte englobante) et renvoie son
 * point focal normalisé + sa boîte.
 *
 * On ne fusionne PAS plusieurs visages : sur une photo de groupe, cadrer la
 * boîte commune tombe souvent sur le vide entre les personnes. On préfère
 * choisir un seul visage et cadrer dessus.
 *
 * - cy vise la ligne des yeux (haut de la boîte + ~40 % de sa hauteur), pas le
 *   menton, ce qui donne un cadrage plus naturel.
 */
function computeFocal(detections, imgW, imgH) {
  const largest = detections.reduce((best, d) =>
    d.box.width * d.box.height > best.box.width * best.box.height ? d : best
  )
  const { x, y, width, height } = largest.box

  const cxPx = x + width / 2
  const eyesPx = y + height * 0.40 // ligne des yeux

  return {
    cx: clamp01(cxPx / imgW),
    cy: clamp01(eyesPx / imgH),
    box: {
      x: clamp01(x / imgW),
      y: clamp01(y / imgH),
      w: clamp01(width / imgW),
      h: clamp01(height / imgH),
    },
  }
}

/**
 * Détecte le visage dominant d'une image.
 * Retourne { cx, cy, box:{x,y,w,h}, imgW, imgH } (normalisé), ou null si aucun
 * visage / erreur. Résultat mis en cache par URL (indépendant du conteneur).
 */
export async function detectFaceCenter(imageUrl) {
  if (!imageUrl) return null
  if (centerCache.has(imageUrl)) return centerCache.get(imageUrl)
  if (inFlightByUrl.has(imageUrl)) return inFlightByUrl.get(imageUrl)

  const taskPromise = runWithConcurrencyLimit(async () => {
    try {
      await loadModels()
      const img = await loadImage(imageUrl)
      if (!img) { centerCache.set(imageUrl, null); return null }

      const imgW = img.naturalWidth || img.width
      const imgH = img.naturalHeight || img.height
      if (!imgW || !imgH) { centerCache.set(imageUrl, null); return null }

      // inputSize 320 : meilleur compromis précision/vitesse que 224 pour les
      // petits visages fréquents dans les photos de presse.
      const options = new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.4 })
      const detections = await faceapi.detectAllFaces(img, options)

      if (!detections || detections.length === 0) {
        centerCache.set(imageUrl, null)
        return null
      }

      const focal = computeFocal(detections, imgW, imgH)
      const result = { ...focal, imgW, imgH }
      centerCache.set(imageUrl, result)
      return result
    } catch {
      centerCache.set(imageUrl, null)
      return null
    } finally {
      inFlightByUrl.delete(imageUrl)
    }
  })

  inFlightByUrl.set(imageUrl, taskPromise)
  return taskPromise
}

/**
 * Détecte le centre du SUJET PRINCIPAL d'une image sans visage, par saillance.
 *
 * Heuristique sans dépendance : on dessine l'image réduite sur un canvas, puis
 * on calcule une carte de saillance = magnitude du gradient (détail/netteté) +
 * saturation (couleur distinctive). Les zones floues/uniformes (ciel, mur, flou
 * d'arrière-plan) obtiennent un score faible ; les zones nettes et contrastées
 * (le sujet) un score fort. On pondère par un léger biais central (les sujets
 * sont généralement cadrés vers le centre) puis on renvoie le centroïde pondéré.
 *
 * Retourne { cx, cy } normalisé, ou null (canvas « tainted » CORS, image vide…).
 */
function detectSubjectCenter(img, imgW, imgH) {
  try {
    const MAXD = 96
    const scale = Math.min(1, MAXD / Math.max(imgW, imgH))
    const w = Math.max(8, Math.round(imgW * scale))
    const h = Math.max(8, Math.round(imgH * scale))

    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.drawImage(img, 0, 0, w, h)

    const data = ctx.getImageData(0, 0, w, h).data // throw si tainted (CORS)

    // Niveaux de gris
    const gray = new Float32Array(w * h)
    for (let i = 0; i < w * h; i++) {
      gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2]
    }

    const SIGMA = 0.38 // largeur du biais central (fraction de l'image)
    let sumS = 0, sumX = 0, sumY = 0
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x
        const xl = x > 0     ? gray[i - 1] : gray[i]
        const xr = x < w - 1 ? gray[i + 1] : gray[i]
        const yu = y > 0     ? gray[i - w] : gray[i]
        const yd = y < h - 1 ? gray[i + w] : gray[i]
        const gx = xr - xl
        const gy = yd - yu
        const grad = Math.sqrt(gx * gx + gy * gy)

        // saturation (distinctivité couleur)
        const r = data[i * 4], g = data[i * 4 + 1], b = data[i * 4 + 2]
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b)
        const sat = mx > 0 ? (mx - mn) / mx : 0

        // biais central gaussien pour éviter d'être tiré vers les bords/coins
        const nx = x / (w - 1) - 0.5
        const ny = y / (h - 1) - 0.5
        const centerBias = Math.exp(-(nx * nx + ny * ny) / (2 * SIGMA * SIGMA))

        const s = (grad + sat * 40) * centerBias
        sumS += s
        sumX += s * x
        sumY += s * y
      }
    }
    if (sumS <= 0) return null
    return {
      cx: clamp01((sumX / sumS) / (w - 1)),
      cy: clamp01((sumY / sumS) / (h - 1)),
    }
  } catch {
    return null // canvas tainted (CORS) ou autre erreur
  }
}

/**
 * Point focal UNIFIÉ d'une image pour le cadrage immersif.
 * 1) cherche un visage dominant (face-api) ;
 * 2) à défaut, cherche le sujet principal par saillance.
 *
 * Retourne :
 *  - { kind:'face',    cx, cy, box, imgW, imgH }
 *  - { kind:'subject', cx, cy,      imgW, imgH }
 *  - null (image inaccessible / aucun signal exploitable)
 * Mis en cache par URL.
 */
export async function detectImageFocus(imageUrl) {
  if (!imageUrl) return null
  if (focusCache.has(imageUrl)) return focusCache.get(imageUrl)
  if (inFlightFocus.has(imageUrl)) return inFlightFocus.get(imageUrl)

  const task = (async () => {
    try {
      // 1) Visage (réutilise le cache visage + la limite de concurrence interne)
      const face = await detectFaceCenter(imageUrl)
      if (face) {
        const r = { kind: 'face', ...face }
        focusCache.set(imageUrl, r)
        return r
      }
      // 2) Sujet par saillance
      const subj = await runWithConcurrencyLimit(async () => {
        const img = await loadImage(imageUrl)
        if (!img) return null
        const imgW = img.naturalWidth || img.width
        const imgH = img.naturalHeight || img.height
        if (!imgW || !imgH) return null
        const c = detectSubjectCenter(img, imgW, imgH)
        return c ? { kind: 'subject', cx: c.cx, cy: c.cy, imgW, imgH } : null
      })
      focusCache.set(imageUrl, subj)
      return subj
    } catch {
      focusCache.set(imageUrl, null)
      return null
    } finally {
      inFlightFocus.delete(imageUrl)
    }
  })()

  inFlightFocus.set(imageUrl, task)
  return task
}

/**
 * Calcule l'`object-position` CSS EXACT pour qu'un point focal reste bien cadré
 * dans un conteneur `object-fit: cover` de dimensions données.
 *
 * Contrairement à un simple « centre du visage en % », cette formule tient compte
 * du recadrage cover : seul l'axe qui déborde est ajusté, et le visage est placé
 * au centre horizontal et à `focusY` verticalement (légèrement au-dessus du milieu
 * pour laisser de l'air au-dessus de la tête).
 *
 * @param {number} cx,cy        point focal normalisé [0,1]
 * @param {number} imgW,imgH    dimensions naturelles de l'image
 * @param {number} cW,cH        dimensions du conteneur d'affichage
 * @param {number} focusY       cible verticale du visage dans le conteneur (def. 0.45)
 * @returns {string} "X% Y%"
 */
export function coverObjectPosition(cx, cy, imgW, imgH, cW, cH, focusY = 0.45) {
  if (!imgW || !imgH || !cW || !cH) {
    return `${Math.round(clamp01(cx) * 100)}% ${Math.round(clamp01(cy) * 100)}%`
  }
  const scale = Math.max(cW / imgW, cH / imgH)
  const sW = imgW * scale
  const sH = imgH * scale
  const excessX = sW - cW
  const excessY = sH - cH

  const pX = excessX > 1 ? clamp01((cx * sW - cW * 0.5) / excessX) : 0.5
  const pY = excessY > 1 ? clamp01((cy * sH - cH * focusY) / excessY) : 0.5

  return `${Math.round(pX * 100)}% ${Math.round(pY * 100)}%`
}

/**
 * Compat : retourne un `object-position` basé sur le centre du visage,
 * sans connaître le ratio du conteneur (suffisant pour les vignettes de cartes).
 *
 * Fallback : "50% 25%" (haut-centre, bon pour les photos de presse)
 */
export async function detectFaceObjectPosition(imageUrl) {
  if (!imageUrl) return 'center'
  const r = await detectFaceCenter(imageUrl)
  if (!r) return '50% 25%'
  const x = clamp(Math.round(r.cx * 100), 10, 90)
  const y = clamp(Math.round(r.cy * 100), 10, 90)
  return `${x}% ${y}%`
}

/** Vide le cache (utile si les URLs sont réutilisées avec des images différentes) */
export function clearFacePositionCache() {
  centerCache.clear()
  focusCache.clear()
}
