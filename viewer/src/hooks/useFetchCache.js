/**
 * useFetchCache — hook React avec cache mémoire TTL
 *
 * Évite les appels API redondants sur les panneaux lourds
 * (EntityDashboard, TopArticlesPanel, SourceBiasPanel).
 *
 * Le cache est un Map module-level partagé entre toutes les instances
 * du hook — il survit aux montages/démontages du composant.
 *
 * Usage :
 *   const { data, loading, error, reload } = useFetchCache('/api/entities/dashboard')
 *
 * Options :
 *   ttl      — durée de vie en ms (défaut : 5 min)
 *   transform — fonction appelée sur la réponse JSON avant stockage
 */

import { useEffect, useState, useCallback, useRef } from 'react'

// Cache module-level : Map<cacheKey, { data, ts }>
const _cache = new Map()

const DEFAULT_TTL = 5 * 60 * 1000 // 5 min

/**
 * Invalide toutes les entrées dont la clé commence par `prefix`.
 * Pratique pour forcer le rechargement après une mutation.
 */
export function invalidateCache(prefix = '') {
  for (const key of _cache.keys()) {
    if (key.startsWith(prefix)) _cache.delete(key)
  }
}

/**
 * @param {string|null} url  - URL à fetcher (null = pas de fetch)
 * @param {{ ttl?: number, transform?: (json: any) => any }} options
 */
export function useFetchCache(url, { ttl = DEFAULT_TTL, transform } = {}) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(!!url)
  const [error, setError]     = useState(null)

  // Permettre à transform d'être une arrow fn inline sans provoquer de boucle
  const transformRef = useRef(transform)
  transformRef.current = transform

  const load = useCallback(
    (forceReload = false) => {
      if (!url) return
      const cacheKey = url

      if (!forceReload) {
        const cached = _cache.get(cacheKey)
        if (cached && Date.now() - cached.ts < ttl) {
          setData(cached.data)
          setLoading(false)
          setError(null)
          return
        }
      }

      setLoading(true)
      setError(null)

      fetch(url)
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json()
        })
        .then(json => {
          const result = transformRef.current ? transformRef.current(json) : json
          _cache.set(cacheKey, { data: result, ts: Date.now() })
          setData(result)
          setLoading(false)
        })
        .catch(e => {
          setError(e.message)
          setLoading(false)
        })
    },
    [url, ttl],
  )

  useEffect(() => { load() }, [load])

  const reload = useCallback(() => load(true), [load])

  return { data, loading, error, reload }
}
