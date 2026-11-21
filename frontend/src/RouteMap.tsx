import { divIcon, latLngBounds, TileLayer, type Coords, type DoneCallback, type Marker as LeafletMarker, type TileEvent } from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polyline, Popup, useMap, useMapEvents } from 'react-leaflet'
import { useEffect, useRef, useState } from 'react'
import type { Point } from './api'
import 'leaflet/dist/leaflet.css'

export const colors = ['#117a6e', '#4267a1', '#936145']
export type MapPin = Point & { key: string; label: string; detail?: string; number?: number; color?: string; terminal?: boolean; vehicle?: string }
export type MapLine = { key: string; points: Point[]; color: string; vehicle: string }
const position = (p: Point): [number, number] => [p.latitude, p.longitude]

class CheckedTileLayer extends TileLayer {
  private pending = new WeakMap<HTMLElement, () => void>()

  cancel = ({ tile }: TileEvent) => this.pending.get(tile)?.()

  protected createTile(coords: Coords, done: DoneCallback) {
    const img = document.createElement('img')
    img.alt = ''
    img.setAttribute('role', 'presentation')
    const controller = new AbortController()
    let objectUrl: string | undefined
    const cleanup = () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      this.pending.delete(img)
    }
    const finish = (error?: Error) => {
      cleanup()
      if (!controller.signal.aborted) done(error, img)
    }
    this.pending.set(img, () => { controller.abort(); cleanup() })
    fetch(this.getTileUrl(coords), { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error('Cartografía HTTP ' + response.status)
        return response.blob()
      })
      .then(blob => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        img.onload = () => finish()
        img.onerror = () => finish(new Error('Imagen cartográfica inválida'))
        img.src = objectUrl
      })
      .catch(error => finish(error))
    return img
  }
}

function SantiagoBasemap({ reportError }: { reportError: (failed: boolean) => void }) {
  const map = useMap()
  useEffect(() => {
    const layer = new CheckedTileLayer(import.meta.env.VITE_NOVARA_DEMO_TILE_URL ||
      'https://tiles.stadiamaps.com/tiles/osm_bright/{z}/{x}/{y}.png', {
      maxZoom: 20,
      attribution: '© <a href="https://stadiamaps.com/attribution/">Stadia Maps</a> © <a href="https://openmaptiles.org/">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    })
    layer.on('loading', () => reportError(false))
    layer.on('tileerror', () => reportError(true))
    layer.on('tileunload tileabort', event => layer.cancel(event as TileEvent))
    layer.addTo(map)
    return () => { layer.remove(); layer.off() }
  }, [map, reportError])
  return null
}

function View({ pins, onPick }: { pins: MapPin[]; onPick?: (point: Point) => void }) {
  const map = useMap()
  useMapEvents({ click: e => onPick?.({ latitude: Number(e.latlng.lat.toFixed(6)), longitude: Number(e.latlng.lng.toFixed(6)) }) })
  useEffect(() => {
    const locations = pins.map(position)
    if (locations.length) map.fitBounds(latLngBounds(locations), { padding: [38, 38], maxZoom: 14, animate: false })
  }, [map, pins])
  return null
}

function NumberedPin({ pin, focused }: { pin: MapPin; focused: boolean }) {
  const marker = useRef<LeafletMarker>(null)
  useEffect(() => {
    if (focused) marker.current?.openPopup()
  }, [focused])
  return <Marker ref={marker} position={position(pin)} title={pin.label} zIndexOffset={focused ? 1000 : 0}
    icon={divIcon({ className: 'pin-icon', iconSize: [30, 30], iconAnchor: [15, 15],
      html: '<span style="--pin:' + (pin.color ?? colors[0]) + '">' + (pin.terminal ? 'T' : pin.number) + '</span>',
    })}><Popup><strong>{pin.label}</strong>{pin.detail && <div>{pin.detail}</div>}</Popup></Marker>
}

export default function RouteMap({ pins, lines = [], onPick, demo = false, focused }: {
  pins: MapPin[]; lines?: MapLine[]; onPick?: (point: Point) => void; demo?: boolean; focused?: string
}) {
  const [tileError, setTileError] = useState(false)
  return <div className="map-view" role="region" aria-label="Mapa local de recorridos">
    <MapContainer center={[-33.4489, -70.6693]} zoom={12} scrollWheelZoom={false} attributionControl={demo}>
      {demo && <SantiagoBasemap reportError={setTileError} />}
      <View pins={pins} onPick={onPick} />
      {lines.map(line => <Polyline key={line.key} positions={line.points.map(position)}
        pathOptions={{ color: line.color, dashArray: '6 8', opacity: 0.85, weight: 3 }} />)}
      {pins.map(pin => {
        const detail = <Popup><strong>{pin.label}</strong>{pin.detail && <div>{pin.detail}</div>}</Popup>
        return pin.number === undefined && !pin.terminal
          ? <CircleMarker key={pin.key} center={position(pin)} radius={8}
              pathOptions={{ color: pin.color ?? colors[0], fillOpacity: 0.7 }}>{detail}</CircleMarker>
          : <NumberedPin key={pin.key} pin={pin} focused={focused === pin.key} />
      })}
    </MapContainer>
    <span className="map-caption">{lines.length ? 'Conexiones ilustrativas · Sin geometría vial' : demo ? 'Santiago de Chile' : 'Mapa local · Sin cartografía externa'}
      {demo && tileError && ' · Fondo cartográfico no disponible'}</span>
  </div>
}
