import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, GeoJSON, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const TYPE_COLORS = {
  GPE: '#3B82F6', // bleu
  LOC: '#10B981', // vert
}

/** Déclenche map.invalidateSize() dès que le conteneur parent est redimensionné. */
function MapResizer({ containerRef }) {
  const map = useMap()
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(() => {
      setTimeout(() => map.invalidateSize(), 0)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [map, containerRef])
  return null
}

/**
 * Zoome automatiquement sur les marqueurs une fois les coordonnées disponibles.
 * - marqueur avec polygon geojson → flyToBounds du polygon (zoom précis sur le territoire)
 * - 1 marqueur sans polygon → flyTo zoom 5
 * - N marqueurs → fitBounds
 */
function FlyToMarkers({ markers }) {
  const map = useMap()
  const prevKey = useRef('')

  useEffect(() => {
    if (markers.length === 0) return
    const key = markers.map(m => `${m.lat},${m.lon},${m.bounds ? '1' : '0'}`).join('|')
    if (key === prevKey.current) return
    prevKey.current = key

    try {
      // Priorité 1 : bounds explicites (continents, grandes régions)
      if (markers.length === 1 && markers[0].bounds) {
        map.flyToBounds(markers[0].bounds, { padding: [10, 10], animate: true, duration: 1.2 })
        return
      }
      // Priorité 2 : polygon GeoJSON (pays avec contour)
      if (markers.length === 1 && markers[0].geojson && markers[0].geojson.type !== 'Point') {
        const layer = L.geoJSON(markers[0].geojson)
        const bounds = layer.getBounds()
        if (bounds.isValid()) {
          map.flyToBounds(bounds, { padding: [20, 20], animate: true, duration: 1.2 })
          return
        }
      }
      if (markers.length === 1) {
        map.flyTo([markers[0].lat, markers[0].lon], 5, { animate: true, duration: 1.2 })
      } else {
        const bounds = L.latLngBounds(markers.map(m => [m.lat, m.lon]))
        map.flyToBounds(bounds, { padding: [40, 40], animate: true, duration: 1.2 })
      }
    } catch (_) {}
  }, [map, markers])

  return null
}

const DEFAULT_COLOR = '#6B7280'

function markerRadius(count) {
  return Math.max(5, Math.min(28, Math.log2(count + 1) * 4.5))
}

export default function EntityWorldMap({ entities, onEntityClick, style }) {
  const [coords, setCoords] = useState({})
  const [loading, setLoading] = useState(true)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!entities || entities.length === 0) {
      setLoading(false)
      return
    }

    let cancelled = false
    const names = entities.map((e) => e.name)
    setCoords({})
    setLoading(true)

    const run = async () => {
      try {
        const resp = await fetch('/api/entities/geocode/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(names),
        })

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let firstResult = false

        while (true) {
          if (cancelled) { reader.cancel(); break }
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          // Découper sur les doubles newlines SSE
          const parts = buffer.split('\n\n')
          buffer = parts.pop() // conserver le fragment incomplet

          const newEntries = {}
          let addedCount = 0
          for (const part of parts) {
            const line = part.trim()
            if (!line.startsWith('data: ')) continue
            try {
              const parsed = JSON.parse(line.slice(6))
              if (parsed.type === 'done') continue
              const { name, ...rest } = parsed
              if (name && rest.lat != null) {
                newEntries[name] = rest
                addedCount++
              }
            } catch (_) {}
          }

          if (addedCount > 0 && !cancelled) {
            if (!firstResult) {
              firstResult = true
              setLoading(false)
            }
            setCoords((prev) => ({ ...prev, ...newEntries }))
          }
        }
      } catch (_) {}

      if (!cancelled) setLoading(false)
    }

    run()
    return () => { cancelled = true }
  }, [entities])

  const markers = entities
    .filter((e) => {
      const c = coords[e.name]
      return c != null && c.lat != null && c.lon != null
    })
    .map((e) => ({ ...e, ...coords[e.name] }))

  return (
    <div ref={containerRef} className="relative w-full" style={style ?? { height: '520px' }}>
      {loading && (
        <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-gray-900/70 rounded-lg">
          <span className="text-white text-sm">Géocodage en cours…</span>
        </div>
      )}

      <MapContainer
        center={[20, 10]}
        zoom={2}
        minZoom={1}
        maxZoom={18}
        scrollWheelZoom={true}
        style={{ height: '100%', width: '100%', borderRadius: '0.5rem' }}
      >
        <MapResizer containerRef={containerRef} />
        <FlyToMarkers markers={markers} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {markers.flatMap((m) => {
          const color = TYPE_COLORS[m.type] ?? DEFAULT_COLOR
          const tooltip = (
            <Tooltip direction="top" offset={[0, -4]} opacity={0.95}>
              <span className="font-medium">{m.name}</span>
              <br />
              <span className="text-xs text-gray-500">
                {m.type} · {m.count} mention{m.count > 1 ? 's' : ''}
              </span>
            </Tooltip>
          )
          const items = []
          // Vérifier si le geojson est un rectangle bbox Nominatim (Polygon 5 pts, 2 lon × 2 lat)
          const isBboxRect = (geo) => {
            if (!geo || geo.type !== 'Polygon') return false
            const ring = geo.coordinates?.[0] ?? []
            if (ring.length !== 5) return false
            const lons = new Set(ring.map((p) => Math.round(p[0] * 1e4)))
            const lats = new Set(ring.map((p) => Math.round(p[1] * 1e4)))
            return lons.size === 2 && lats.size === 2
          }
          // Polygone coloré si disponible (ignorer Point et bbox rectangles)
          if (m.geojson && m.geojson.type !== 'Point' && !isBboxRect(m.geojson)) {
            items.push(
              <GeoJSON
                key={`geo-${m.type}-${m.name}`}
                data={m.geojson}
                style={{
                  color,
                  fillColor: color,
                  fillOpacity: 0.25,
                  weight: 2,
                }}
                eventHandlers={{ click: () => onEntityClick(m.type, m.name) }}
              />
            )
          }
          // Marqueur central (tooltip + clic)
          items.push(
            <CircleMarker
              key={`cm-${m.type}-${m.name}`}
              center={[m.lat, m.lon]}
              radius={markerRadius(m.count)}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: m.geojson ? 0.9 : 0.7,
                weight: 1.5,
              }}
              eventHandlers={{ click: () => onEntityClick(m.type, m.name) }}
            >
              {tooltip}
            </CircleMarker>
          )
          return items
        })}
      </MapContainer>

      {/* Légende */}
      <div className="absolute bottom-3 left-3 z-[1000] bg-gray-900/80 text-white text-xs rounded-lg px-3 py-2 flex gap-4 pointer-events-none">
        <span className="flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full"
            style={{ background: TYPE_COLORS.GPE }}
          />
          GPE (lieu géopolitique)
        </span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block w-3 h-3 rounded-full"
            style={{ background: TYPE_COLORS.LOC }}
          />
          LOC (lieu géographique)
        </span>
        {markers.length === 0 && !loading && (
          <span className="text-gray-400">Aucune entité géolocalisée</span>
        )}
      </div>
    </div>
  )
}
