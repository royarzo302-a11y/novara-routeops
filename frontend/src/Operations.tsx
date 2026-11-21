import { lazy, Suspense, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Download, MapPin, Radar, Route } from 'lucide-react'
import { type Api, type Batch, type Customer, type Driver, type Matrix, type Plan, type Point, type Preparation, type Review, type Ride, type Session, type Terminal, type Van, clock, hostedDemo, labels } from './api'
import { Busy, Field, Notice, Panel, VanArt } from './ui'
import type { MapPin as Pin, MapLine } from './RouteMap'
import type { PlanInputs } from './quickPlan'

const Map = lazy(() => import('./RouteMap'))
const colors = ['#117a6e', '#4267a1', '#936145']
type Origin = Point & { source: string }
const number = (value: FormDataEntryValue | null) => Number(String(value))
const idLabel = (id: string) => id.slice(0, 8)

export function GeoPanel({ api, rides, selected, setSelected, terminals, updates, reviews, session, onApproval }: {
  api: Api; rides: Ride[]; selected: string; setSelected: (id: string) => void; terminals: Terminal[]
  updates: (id: string, review: Review) => void; reviews: Record<string, Review>; session: Session; onApproval: () => void
}) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [point, setPoint] = useState({ latitude: '', longitude: '' })
  const [candidate, setCandidate] = useState('')
  const [city, setCity] = useState('Santiago')
  const ride = rides.find(r => r.id === selected)
  const review = reviews[selected]
  useEffect(() => {
    if (!selected) return
    let active = true
    api.json<Review>('/v4/geo/requests/' + selected + '/location')
      .then(result => { if (active) updates(selected, result) })
      .catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [api, selected, updates])
  async function operation(action: string, body: unknown, method: string) {
    setBusy(true)
    setError('')
    try {
      updates(selected, await api.json<Review>('/v4/geo/requests/' + selected + '/' + action, method, body))
      if (method === 'PUT') onApproval()
    }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    const body = candidate ? { candidate_id: candidate } : { point: { latitude: Number(point.latitude), longitude: Number(point.longitude) } }
    void operation('location', { ...body, reason: data.get('reason') }, 'PUT')
  }
  const pins = useMemo(() => {
    const result: Pin[] = (review?.candidates ?? []).map((c, i) => ({
      ...c, key: c.id, label: 'Candidato ' + (i + 1), number: i + 1, color: c.context_match ? colors[0] : colors[2],
    }))
    if (review?.approved_point) result.push({ ...review.approved_point, key: 'approved', label: 'Recogida aprobada' })
    const terminal = terminals.find(t => t.id === ride?.terminal_id)
    if (terminal?.latitude != null && terminal.longitude != null) result.push({ latitude: terminal.latitude, longitude: terminal.longitude, key: 'terminal', terminal: true, label: terminal.name })
    return result
  }, [review, ride, terminals])
  return <div className="split">
    <Panel title="Resolver ubicaciones" description="Verifica el punto antes de aprobar la recogida.">
      <Field label="Solicitud"><select value={selected} disabled={busy} onChange={e => {
        setSelected(e.target.value); setPoint({ latitude: '', longitude: '' }); setCandidate(''); setError(''); setCity('Santiago')
      }}><option value="">Seleccionar solicitud</option>
        {rides.map(r => <option key={r.id} value={r.id}>{r.name || r.employee_code || idLabel(r.id)} · {r.commune || 'Sin comuna'}{reviews[r.id]?.status === 'approved' ? ' · Aprobada' : ''}</option>)}
      </select></Field>
      {error && <Notice text={error} error />}
      {!ride ? <div className="empty">Selecciona una solicitud para revisar su ubicación.</div> : <div className="stack">
        <div className="info-line"><MapPin size={16} /><div><strong>{ride.address || 'Sin dirección'}</strong><small>{ride.commune || 'Sin comuna'}</small></div><span className="badge">{labels[review?.status ?? 'pending']}</span></div>
        {review?.address?.issues.map(issue => <Notice key={issue} text={labels[issue] ?? issue} />)}
        {!session.geocoder_available && <Notice text="Geocodificador local no configurado. Puedes registrar una coordenada verificada manualmente." />}
        <Field label="Ciudad" value={city} onChange={e => setCity(e.target.value)} />
        <button className="button" disabled={busy || !session.geocoder_available || !city.trim()} onClick={() => void operation('candidates', { city }, 'POST')}><Radar size={16} />Buscar candidatos</button>
        {review?.status === 'review_required' && !review.candidates.length && <Notice text="El proveedor no encontró candidatos dentro de la cobertura." />}
        <form className="stack" onSubmit={submit}>
          <Field label="Candidato"><select value={candidate} onChange={e => setCandidate(e.target.value)}>
            <option value="">Ingresar coordenadas manualmente</option>
            {review?.candidates.map((c, i) => <option key={c.id} value={c.id} disabled={!c.context_match}>Candidato {i + 1} · {c.latitude}, {c.longitude}{c.context_match ? '' : ' · Contexto distinto'}</option>)}
          </select></Field>
          {!candidate && <div className="fields">
            <Field label="Latitud de recogida" type="number" step="any" min={-90} max={90} required value={point.latitude} onChange={e => setPoint({ ...point, latitude: e.target.value })} />
            <Field label="Longitud de recogida" type="number" step="any" min={-180} max={180} required value={point.longitude} onChange={e => setPoint({ ...point, longitude: e.target.value })} />
          </div>}
          <Field label="Motivo de aprobación" name="reason" required maxLength={300} />
          <button className="button primary" disabled={busy}>{busy ? <Busy>Procesando</Busy> : 'Aprobar ubicación'}</button>
        </form>
      </div>}
    </Panel>
    <Panel title="Puntos de referencia" description="Seleccionar en el mapa rellena los campos de coordenadas.">
      <Suspense fallback={<div className="empty">Cargando mapa…</div>}><Map pins={pins} onPick={ride ? p => {
        setCandidate(''); setPoint({ latitude: String(p.latitude), longitude: String(p.longitude) })
      } : undefined} /></Suspense>
    </Panel>
  </div>
}

export function FleetCards({ vans, drivers }: { vans: Van[]; drivers: Driver[] }) {
  const slots = vans.length ? vans : [null, null, null]
  return <div className="fleet-grid">{slots.map((van, index) => {
    const driver = drivers.find(d => d.vehicle_id === van?.id)
    const available = van?.available && driver?.available
    return <article className="vehicle" key={van?.id ?? index}>
      <div className="vehicle-meta"><strong>{van?.identifier ?? 'Espacio de flota'}</strong>
        <span className={'badge ' + (available ? 'valid' : '')}>{van ? available ? 'Disponible' : 'No disponible' : 'Sin registrar'}</span></div>
      <VanArt />
      <div className="vehicle-meta"><span>{van ? van.capacity + ' plazas' : 'Capacidad inicial 12'}</span><span>{driver?.identifier ?? 'Sin conductor'}</span></div>
    </article>
  })}</div>
}

export function FleetPanel({ vans, drivers, api, onChange }: { vans: Van[]; drivers: Driver[]; api: Api; onChange: () => Promise<void> }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  async function save(event: FormEvent<HTMLFormElement>, kind: 'vehicles' | 'drivers', record?: Van | Driver) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const body = kind === 'vehicles' ? {
      identifier: data.get('identifier'), capacity: number(data.get('capacity')), available: data.has('available'),
      allowed_communes: String(data.get('zones') ?? '').split(',').map(x => x.trim()).filter(Boolean),
    } : {
      identifier: data.get('identifier'), vehicle_id: data.get('vehicle_id'), available: data.has('available'),
      available_from: data.get('available_from'), available_until: data.get('available_until'), max_trips: number(data.get('max_trips')),
    }
    setBusy(true); setError(''); setMessage('')
    try {
      await api.json(record ? '/v5/operator/' + kind + '/' + record.id : '/' + kind, record ? 'PUT' : 'POST', body)
      await onChange()
      if (!record) form.reset()
      setMessage(kind === 'vehicles' ? 'Van guardada.' : 'Conductor guardado.')
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  function vehicleForm(van?: Van) {
    return <form className="fields" onSubmit={e => void save(e, 'vehicles', van)}>
      <Field label="Identificador de van" name="identifier" required readOnly={!!van} defaultValue={van?.identifier} />
      <Field label="Capacidad" name="capacity" type="number" min={1} max={12} defaultValue={van?.capacity ?? 12} required />
      <Field label="Comunas permitidas (separadas por coma)" name="zones" defaultValue={van?.allowed_communes.join(', ')} />
      <label className="check"><input name="available" type="checkbox" defaultChecked={van?.available ?? true} />Van disponible</label>
      <button className="button primary" disabled={busy}>{van ? 'Actualizar van' : 'Registrar van'}</button>
    </form>
  }
  function driverForm(driver?: Driver) {
    return <form className="fields" onSubmit={e => void save(e, 'drivers', driver)}>
      <Field label="Identificador de conductor" name="identifier" required readOnly={!!driver} defaultValue={driver?.identifier} />
      <Field label="Van asignada"><select name="vehicle_id" required defaultValue={driver?.vehicle_id}>
        {!driver && <option value="">Seleccionar</option>}
        {vans.filter(v => driver ? v.id === driver.vehicle_id : !drivers.some(d => d.vehicle_id === v.id)).map(v => <option key={v.id} value={v.id}>{v.identifier}</option>)}
      </select></Field>
      <Field label="Disponible desde" name="available_from" type="time" required defaultValue={driver?.available_from.slice(0, 5) ?? '00:00'} />
      <Field label="Disponible hasta" name="available_until" type="time" required defaultValue={driver?.available_until.slice(0, 5) ?? '08:00'} />
      <Field label="Viajes habilitados"><select name="max_trips" defaultValue={driver?.max_trips ?? 2}><option value="1">1 viaje</option><option value="2">2 viajes</option></select></Field>
      <label className="check"><input name="available" type="checkbox" defaultChecked={driver?.available ?? true} />Conductor disponible</label>
      <button className="button primary" disabled={busy}>{driver ? 'Actualizar conductor' : 'Registrar conductor'}</button>
    </form>
  }
  return <div className="stack">
    <Panel title="Flota compartida" description="La planificación combina tres vans y permite hasta dos viajes por vehículo.">
      <FleetCards vans={vans} drivers={drivers} />
      {error && <Notice text={error} error />}{message && <Notice text={message} />}
    </Panel>
    <div className="split">
      <Panel title="Registrar van">{vehicleForm()}</Panel>
      <Panel title="Asignar conductor">{driverForm()}</Panel>
    </div>
    <Panel title="Editar recursos">
      {!vans.length && <div className="empty">Registra las vans para configurar su disponibilidad.</div>}
      {vans.map(van => <details key={van.id}><summary>{van.identifier}</summary>{vehicleForm(van)}
        {drivers.filter(d => d.vehicle_id === van.id).map(d => <div key={d.id}>{driverForm(d)}</div>)}</details>)}
    </Panel>
  </div>
}

export function PlanningPanel({ api, rides, batches, vans, reviews, date, inputs, invalidatePlan, startPlan, onLocations, session, overlap }: {
  api: Api; rides: Ride[]; batches: Batch[]; vans: Van[]; reviews: Record<string, Review>; date: string;
  inputs?: PlanInputs; invalidatePlan: () => void; startPlan: () => (plan: Plan, inputs: PlanInputs) => void;
  onLocations: (ids: string[]) => Promise<void>; session: Session; overlap: boolean
}) {
  const [catalog, setCatalog] = useState<Matrix[]>([])
  const [matrix, setMatrix] = useState<Matrix>()
  const [selection, setSelection] = useState<string[]>([])
  const [chosen, setChosen] = useState<string[] | null>(null)
  const [originFields, setOriginFields] = useState<Record<string, { latitude: string; longitude: string }>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const originals = new Set(batches.filter(b => b.role === 'original').map(b => b.id))
  const eligible = rides.filter(r => r.service_date === date && originals.has(r.batch_id) && r.direction === 'inbound' && r.validation_status === 'valid' && !r.excluded)
  const chosenVans = chosen ?? vans.slice(0, 3).map(v => v.id)
  const eligibleIds = new Set(eligible.map(r => r.id))
  const compatible = catalog.filter(m => m.mode !== 'time_dependent' && m.location_keys.some(k => k.startsWith('pickup:'))
    && m.location_keys.filter(k => k.startsWith('pickup:')).every(k => eligibleIds.has(k.slice(7))))
  function fillInputs(origins: Record<string, Point>, ids: string[]) {
    setChosen(Object.keys(origins))
    setOriginFields(Object.fromEntries(Object.entries(origins).map(([id, p]) => [id, { latitude: String(p.latitude), longitude: String(p.longitude) }])))
    setSelection(ids)
  }
  useEffect(() => {
    if (!inputs) return
    fillInputs(inputs.origins, inputs.requestIds)
    setMatrix(inputs.matrix)
  }, [inputs])
  useEffect(() => {
    let active = true
    api.json<Matrix[]>('/v4/geo/matrix-catalog').then(m => { if (active) setCatalog(m) })
      .catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [api])
  function invalidate() { setMatrix(undefined); invalidatePlan() }
  async function execute(label: string, callback: () => Promise<void>) {
    setBusy(label); setError('')
    try { await callback() } catch (e) { setError((e as Error).message) }
    finally { setBusy('') }
  }
  function getOrigins(): Record<string, Origin> {
    const origins: Record<string, Origin> = {}
    if (chosenVans.length !== 3) throw new Error('Selecciona exactamente tres vans.')
    for (const id of chosenVans) {
      const p = originFields[id]
      if (!p?.latitude.trim() || !p.longitude.trim()) throw new Error('Indica las coordenadas de salida de cada van.')
      const latitude = Number(p.latitude), longitude = Number(p.longitude)
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) throw new Error('Revisa las coordenadas de salida.')
      origins[id] = { latitude, longitude, source: 'operador' }
    }
    return origins
  }
  async function selectMatrix(id: string) {
    invalidate()
    const match = compatible.find(m => m.id === id)
    if (!match) return
    const origins = await api.json<Record<string, Point>>('/v4/geo/matrices/' + id + '/origins')
    const originIds = Object.keys(origins)
    if (originIds.length !== 3 || !originIds.every(id => vans.some(v => v.id === id))) throw new Error('La matriz no corresponde a tres vans registradas.')
    fillInputs(origins, match.location_keys.filter(k => k.startsWith('pickup:')).map(k => k.slice(7)))
    setMatrix(match)
    await onLocations(match.location_keys.filter(k => k.startsWith('pickup:')).map(k => k.slice(7)))
  }
  const visibleSelection = selection.filter(id => eligibleIds.has(id))
  const canCreate = !overlap && visibleSelection.length > 0 && visibleSelection.every(id => reviews[id]?.status === 'approved')
  const pickups = matrix?.location_keys.filter(k => k.startsWith('pickup:')).map(k => k.slice(7))
  const canPreview = !overlap && pickups && pickups.length === visibleSelection.length &&
    visibleSelection.length > 0 && visibleSelection.every(id => pickups.includes(id))
  async function buildMatrix(origins: Record<string, Origin>) {
    const points = Object.fromEntries(Object.entries(origins).map(([id, p]) => [id, { latitude: p.latitude, longitude: p.longitude }]))
    const created = await api.json<Matrix>('/v4/geo/matrices', 'POST', { request_ids: visibleSelection, vehicle_origins: points })
    setCatalog(prev => [created, ...prev.filter(item => item.id !== created.id)])
    setMatrix(created)
    return created
  }
  async function calculate() {
    const finish = startPlan()
    const config = await api.json<Preparation>('/v5/operator/preparation')
    const origins = getOrigins()
    const selected = canPreview && matrix ? matrix : await buildMatrix(origins)
    const ids = [...new Set(eligible.filter(r => visibleSelection.includes(r.id)).map(r => r.batch_id))]
    await onLocations(visibleSelection)
    finish(await api.json<Plan>('/v3/plans/preview', 'POST', {
      ...config.rules, service_date: date, original_batch_ids: ids, vehicle_ids: chosenVans, vehicle_origins: origins,
      matrix_id: selected.id, request_ids: visibleSelection,
    }), { date, matrix: selected, requestIds: visibleSelection, origins })
  }
  return <div className="stack">
    <Panel title="Solicitudes para planificar" description={visibleSelection.length + ' seleccionadas de ' + eligible.length + ' solicitudes válidas.'}
      action={<button className="button compact" disabled={!!busy || !eligible.length} onClick={() => void execute('Consultando ubicaciones', () => onLocations(eligible.map(r => r.id)))}>Actualizar ubicaciones</button>}>
      {!eligible.length && <div className="empty">Aún no hay solicitudes originales validadas para esta fecha.</div>}
      <div className="selection">{eligible.map(r => <label key={r.id} className="check">
        <input type="checkbox" checked={selection.includes(r.id)} disabled={!!busy} onChange={e => { invalidate(); setSelection(e.target.checked ? [...selection, r.id] : selection.filter(x => x !== r.id)) }} />
        {r.name || r.employee_code || idLabel(r.id)} · {clock(r.work_time)}
        <span className={'badge ' + (reviews[r.id]?.status === 'approved' ? 'valid' : '')}>{reviews[r.id]?.status === 'approved' ? 'Ubicación aprobada' : 'Ubicación por comprobar'}</span>
      </label>)}</div>
    </Panel>
    <Panel title="Flota y matriz" description="Usa una matriz guardada o genera una con las ubicaciones aprobadas.">
      {error && <Notice text={error} error />}
      <Field label="Matriz disponible"><select value={matrix?.id ?? ''} disabled={!!busy} onChange={e => { const value = e.target.value; void execute('Cargando matriz', () => selectMatrix(value)) }}>
        <option value="">Seleccionar matriz</option>{compatible.map(m => <option key={m.id} value={m.id}>
          {m.simulation ? 'Simulación' : 'Red vial estática'} · {m.provider} · {m.map_version} · {idLabel(m.id)}
        </option>)}
      </select></Field>
      <fieldset><legend>Vans del plan</legend><div className="actions">{vans.map(v => <label className="check" key={v.id}>
        <input type="checkbox" disabled={!!busy} checked={chosenVans.includes(v.id)} onChange={e => { invalidate(); setChosen(e.target.checked ? [...chosenVans, v.id] : chosenVans.filter(id => id !== v.id)) }} />{v.identifier}
      </label>)}</div></fieldset>
      {chosenVans.map(id => <fieldset key={id}><legend>Origen · {vans.find(v => v.id === id)?.identifier}</legend><div className="fields">
        {(['latitude', 'longitude'] as const).map(axis => <Field key={axis} label={axis === 'latitude' ? 'Latitud de salida' : 'Longitud de salida'}
          type="number" step="any" value={originFields[id]?.[axis] ?? ''} disabled={!!busy} onChange={e => {
            invalidate(); setOriginFields({ ...originFields, [id]: { ...(originFields[id] ?? { latitude: '', longitude: '' }), [axis]: e.target.value } })
          }} />)}
      </div></fieldset>)}
      {!session.road_available && <Notice text="Proveedor vial local deshabilitado. Puedes reutilizar una matriz guardada que corresponda a esta jornada." />}
      {visibleSelection.length > 0 && !canCreate && !matrix && <Notice text="Actualiza los estados de ubicación y aprueba las recogidas antes de generar la matriz." />}
      {matrix && <Notice text={(matrix.simulation ? 'Simulación' : 'Estimación en red vial estática') + ' · ' + matrix.unreachable_pairs + ' tramos inaccesibles.'} />}
      <div className="actions">
        {!session.demo && <button className="button" disabled={!!busy || !canCreate || !session.road_available} onClick={() => void execute('Generando matriz', async () => {
          invalidatePlan()
          await buildMatrix(getOrigins())
        })}>Generar matriz</button>}
        <button className="button primary" disabled={!!busy || !(canPreview || (session.demo && canCreate && session.road_available))}
          onClick={() => void execute('Optimizando la jornada', calculate)}>
          <Route size={16} />{session.demo ? 'Recalcular rutas' : 'Ejecutar planificación'}
        </button>
        {busy && <span role="status" className="actions"><Busy>{busy}…</Busy></span>}
      </div>
    </Panel>
  </div>
}

export function planMapData(plan: Plan, terminals: Terminal[], reviews: Record<string, Review>, rides: Ride[], vans: Van[]) {
    const pins: Pin[] = [], lines: MapLine[] = []
    const tripVans = [...new Set(plan.trips.map(t => t.vehicle_id))]
    plan.trips.forEach(trip => {
      const color = colors[tripVans.indexOf(trip.vehicle_id) % colors.length]
      const key = trip.vehicle_id + ':' + trip.trip_number
      const points: Point[] = []
      let complete = true
      trip.stops.forEach(stop => {
        const point = reviews[stop.request_id]?.approved_point
        if (!point) { complete = false; return }
        points.push(point)
        const passenger = rides.find(ride => ride.id === stop.request_id)
        const van = vans.find(item => item.id === trip.vehicle_id)?.identifier ?? trip.vehicle_id
        pins.push({ ...point, key: stop.request_id, number: stop.sequence, color, vehicle: trip.vehicle_id,
          label: passenger?.name || 'Recogida ' + stop.sequence,
          detail: [van + ' · Viaje ' + trip.trip_number + ' · Parada ' + stop.sequence + ' · ' + clock(stop.pickup_at),
            passenger?.address, passenger?.commune].filter(Boolean).join(' · ') })
      })
      const terminal = terminals.find(t => t.id === trip.terminal_id)
      if (terminal?.latitude != null && terminal.longitude != null) {
        const point = { latitude: terminal.latitude, longitude: terminal.longitude }
        points.push(point)
        if (!pins.some(p => p.key === terminal.id)) pins.push({ ...point, key: terminal.id, label: terminal.name, terminal: true })
      } else complete = false
      if (complete && points.length > 1) lines.push({ key, points, color, vehicle: trip.vehicle_id })
    })
    return { pins, lines }
}

export function Results({ plan, api, vans, drivers, rides, terminals, customers, reviews, demo, onAdjust }: {
  plan: Plan; api: Api; vans: Van[]; drivers: Driver[]; rides: Ride[]; terminals: Terminal[]; customers: Customer[]; reviews: Record<string, Review>
  demo?: boolean; onAdjust?: () => void
}) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [vanFilter, setVanFilter] = useState('')
  const [focused, setFocused] = useState<string>()
  const { pins, lines } = useMemo(() => planMapData(plan, terminals, reviews, rides, vans), [plan, terminals, reviews, rides, vans])
  const visiblePins = useMemo(() => vanFilter ? pins.filter(pin => !pin.vehicle || pin.vehicle === vanFilter) : pins, [pins, vanFilter])
  const vehicles = [...new Set(plan.trips.map(trip => trip.vehicle_id))]
  const assigned = new Set(plan.trips.flatMap(trip => trip.stops.map(stop => stop.request_id)))
  const communes = new Set(rides.filter(ride => assigned.has(ride.id) && ride.commune).map(ride => ride.commune))
  const dateLabel = new Intl.DateTimeFormat('es-CL', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(plan.service_date))
  async function download() {
    setBusy(true); setError('')
    try { await api.download(plan) } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <div className="stack" id="plan-results">
    <Panel title={demo ? 'Viajes calculados' : 'Vista previa de la jornada'} description={labels[plan.status] + ' · ' + (plan.simulation ? 'Simulación' : plan.matrix_mode === 'static_road' ? 'Estimación vial estática' : 'Sin matriz aplicada') + (demo ? ' · ' + dateLabel : '')}
      className={demo ? 'dispatch-results' : ''}
      action={<div className="actions">{onAdjust && <button className="button" onClick={onAdjust}>Ajustar plan</button>}
        <button className={'button' + (demo ? ' primary' : '')} disabled={!plan.trips.length || busy} onClick={() => void download()}>{busy ? <Busy>Preparando Excel…</Busy> : <><Download size={16} />Descargar Excel</>}</button></div>}>
      {error && <Notice text={error} error />}
      <div className="plan-totals">
        <span><strong>{plan.trips.length}</strong> viajes</span>
        <span><strong>{assigned.size}</strong> recogidas</span>
        <span><strong>{new Set(plan.trips.map(trip => trip.vehicle_id)).size}</strong> vans en ruta</span>
        {demo && <span><strong>{communes.size}</strong> comunas atendidas</span>}
        {demo && plan.unassigned.length > 0 && <a href="#sin-asignar"><strong>{plan.unassigned.length}</strong> sin asignar ↓</a>}
      </div>
      {demo && plan.matrix_source?.startsWith('OSRM') && <p className="map-caption">
        Tiempos estimados sin tráfico en vivo. <a href="https://routing.openstreetmap.de/about.html">OSRM / FOSSGIS</a>
        {' · '}<a href="https://www.openstreetmap.org/fixthemap">Corregir el mapa</a>
      </p>}
      <div className={demo ? 'dispatch-results-grid' : 'stack'}>
      <div className="stack">
      {!!vehicles.length && <div className="actions" aria-label="Vans en el mapa">
        <button className="button compact" aria-pressed={!vanFilter} onClick={() => { setVanFilter(''); setFocused(undefined) }}>Todas</button>
        {vehicles.map((id, index) => <button className="button compact" key={id} aria-pressed={vanFilter === id}
          onClick={() => { setVanFilter(id); setFocused(undefined) }}><span className="route-dot" style={{ background: colors[index % colors.length] }} />
          {vans.find(van => van.id === id)?.identifier || id}</button>)}
      </div>}
      <Suspense fallback={<div className="empty">Cargando mapa…</div>}><Map demo={demo && !hostedDemo} pins={visiblePins}
        lines={vanFilter ? lines.filter(line => line.vehicle === vanFilter) : lines} focused={focused} /></Suspense>
      </div>
      <div className="stack trip-list" aria-label="Itinerario">{demo && <h3>Itinerario</h3>}
      {plan.trips.filter(t => !demo || !vanFilter || t.vehicle_id === vanFilter).map(t => <details key={t.vehicle_id + ':' + t.trip_number} open>
        <summary>{vans.find(v => v.id === t.vehicle_id)?.identifier || idLabel(t.vehicle_id)} · Viaje {t.trip_number} · {customers.find(c => c.id === t.customer_id)?.name || t.customer_id}</summary>
        <div className="trip-meta"><span>Conduce {drivers.find(d => d.id === t.driver_id)?.identifier || idLabel(t.driver_id)}</span>
          <span>{t.stops.length} recogidas</span><span>Salida {clock(t.dispatch_at)}</span><span>Llegada {clock(t.arrival_at)}</span><span>{Math.ceil(t.duration_seconds / 60)} min</span></div>
        <ol>{t.stops.map(s => <li key={s.request_id} className="stop"><button className="stop-link" aria-pressed={focused === s.request_id} onClick={() => {
          if (vanFilter && vanFilter !== t.vehicle_id) setVanFilter(t.vehicle_id)
          setFocused(current => current === s.request_id ? undefined : s.request_id)
          document.querySelector('#plan-results .map-view')?.scrollIntoView({ block: 'nearest' })
        }}>{s.sequence}. {rides.find(r => r.id === s.request_id)?.name || idLabel(s.request_id)}</button><time>{clock(s.pickup_at)}</time></li>)}</ol>
      </details>)}</div>
      </div>
    </Panel>
    {(!demo || plan.unassigned.length > 0) && <div id="sin-asignar"><Panel title="Solicitudes sin asignar" description={plan.unassigned.length + (plan.unassigned.length === 1 ? ' registro' : ' registros')}>
      {plan.unassigned.length ? <ul>{plan.unassigned.map(s => <li className="stop" key={s.request_id}>{rides.find(r => r.id === s.request_id)?.name || idLabel(s.request_id)}<span>{labels[s.reason] || s.reason}</span></li>)}</ul>
        : <div className="empty">Todas las solicitudes del plan tienen viaje asignado.</div>}
    </Panel></div>}
  </div>
}
