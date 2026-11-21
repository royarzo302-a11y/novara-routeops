import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, Check, LockKeyhole, MapPin, Route, Truck } from 'lucide-react'
import type { Api, Customer, Depot, Driver, Matrix, Preparation, Review, Ride, Session, Terminal, Van } from './api'
import { Busy, Field, Notice, Panel } from './ui'

const ruleFields = [
  ['max_onboard_minutes', 'Máximo a bordo (min)', 1, 240],
  ['arrival_buffer_minutes', 'Margen de llegada (min)', 0, 120],
  ['max_early_arrival_minutes', 'Anticipación máxima (min)', 0, 180],
  ['preparation_seconds', 'Preparación entre viajes (s)', 0, 7200],
  ['boarding_seconds', 'Embarque por pasajero (s)', 0, 600],
] as const

export function PreparationPanel({ api, customers, terminals, vans, drivers, rides, reviews, date, session, onTerminals, onLocations, onChange, onReview, onGeo, onFleet, onImport, onCalculate, calculating }: {
  api: Api; customers: Customer[]; terminals: Terminal[]; vans: Van[]; drivers: Driver[]; rides: Ride[];
  reviews: Record<string, Review>; date: string; session: Session; onTerminals: () => Promise<void>;
  onLocations: (ids: string[]) => Promise<void>;
  onChange: () => void; onReview: () => void; onGeo: () => void; onFleet: () => void; onImport: () => void;
  onCalculate: () => void; calculating: boolean
}) {
  const [config, setConfig] = useState<Preparation>()
  const [depots, setDepots] = useState<Depot[]>([])
  const [matrices, setMatrices] = useState<Matrix[]>([])
  const [busy, setBusy] = useState('Cargando preparación')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [dirty, setDirty] = useState(false)
  async function load() {
    const [value, bases, catalog] = await Promise.all([
      api.json<Preparation>('/v5/operator/preparation'), api.json<Depot[]>('/depots'),
      api.json<Matrix[]>('/v4/geo/matrix-catalog'),
    ])
    setConfig(value); setDepots(bases); setMatrices(catalog)
  }
  useEffect(() => {
    let active = true
    load().catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setBusy('') })
    return () => { active = false }
  }, [api])
  function update(next: Preparation) { setConfig(next); setDirty(true); setNotice(''); onChange() }
  async function execute(label: string, action: () => Promise<void>) {
    setBusy(label); setError(''); setNotice('')
    try { await action() } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!config) return
    await execute('Guardando factores', async () => {
      const { locked: _, ...body } = config
      setConfig(await api.json<Preparation>('/v5/operator/preparation', 'PUT', body))
      setDirty(false); onChange(); setNotice('Factores guardados. Se usarán en el próximo cálculo.')
    })
  }
  async function create(event: FormEvent<HTMLFormElement>, kind: 'terminal' | 'base') {
    event.preventDefault()
    if (!config) return
    const form = event.currentTarget, fields = new FormData(form)
    await execute('Guardando ' + kind, async () => {
      const point = { name: String(fields.get('name')), address: String(fields.get('address')),
        latitude: Number(fields.get('latitude')), longitude: Number(fields.get('longitude')) }
      if (kind === 'base') {
        const base = await api.json<Depot>('/depots', 'POST', point)
        setDepots(previous => [...previous, base]); update({ ...config, depot_id: base.id })
      } else {
        const customer_id = String(fields.get('customer_id'))
        const terminal = await api.json<Terminal>('/v2/terminals', 'POST', { ...point, customer_id })
        await onTerminals(); update({ ...config, terminal_ids: { ...config.terminal_ids, [customer_id]: terminal.id } })
      }
      form.reset(); setNotice('Registro creado. Guarda los factores para usar esta selección.')
    })
  }
  async function importMatrix(file: File) {
    await execute('Importando matriz', async () => {
      if (file.size > 512 * 1024) throw new Error('La matriz JSON supera 512 KiB.')
      const body: unknown = JSON.parse(await file.text())
      const matrix = await api.json<Matrix>('/v5/operator/matrices/import', 'POST', body)
      setMatrices(previous => [matrix, ...previous]); update({ ...config!, matrix_id: matrix.id })
      setNotice('Matriz importada. Guarda los factores para seleccionarla.')
    })
  }
  function downloadMatrixTemplate() {
    const depot = depots.find(d => d.id === config?.depot_id) ?? (depots.length === 1 ? depots[0] : undefined)
    if (!depot) { setError('Selecciona primero una base de salida.'); return }
    const ids = inbound.filter(r => r.validation_status === 'valid').map(r => r.id)
    const vehicle_origins = Object.fromEntries(crews.map(v => [v.id, { latitude: depot.latitude, longitude: depot.longitude }]))
    const location_keys = [...ids.map(id => 'pickup:' + id), ...new Set(inbound.map(r => 'terminal:' + r.terminal_id)), ...crews.map(v => 'origin:' + v.id)]
    const values = location_keys.map((_, i) => location_keys.map((_, j) => i === j ? 0 : null))
    const body = { request_ids: ids, vehicle_origins, matrix: { source: 'Indicar proveedor vial y versión', verified_at: new Date().toISOString(), location_keys, seconds: values, meters: values } }
    const url = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'plantilla-matriz-vial.json'; anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const inbound = rides.filter(r => !r.excluded && r.direction === 'inbound' && r.service_date === date)
  const requestKey = inbound.map(r => r.id).sort().join(',')
  useEffect(() => {
    if (!requestKey) return
    onLocations(requestKey.split(',')).catch(e => setError(e.message))
  }, [requestKey, onLocations])
  const pending = inbound.filter(r => r.validation_status !== 'valid').length
  const approved = inbound.filter(r => reviews[r.id]?.status === 'approved').length
  const terminalReady = inbound.every(r => terminals.some(t => t.id === r.terminal_id && t.latitude != null && t.longitude != null))
  const crews = vans.filter(v => v.available && drivers.some(d => d.vehicle_id === v.id && d.available))
  const baseReady = !!config?.depot_id || depots.length === 1
  const roadReady = session.road_available || !!config?.matrix_id
  const checks = [
    { label: 'Terminales de llegada', detail: inbound.length ? (terminalReady ? 'Nómina con destinos georreferenciados' : 'Asigna los terminales pendientes en Solicitudes') : 'Selecciona el destino habitual de cada cliente', ready: inbound.length ? terminalReady : customers.every(c => !!config?.terminal_ids[c.id]) },
    { label: 'Tiempos de viaje', detail: session.demo ? 'Red vial de ejemplo fija · sin tráfico en vivo' : roadReady ? 'Proveedor local o matriz vial seleccionada' : 'Falta proveedor vial o matriz compatible', ready: roadReady },
    { label: 'Recogidas', detail: inbound.length ? `${approved} de ${inbound.length} aprobadas · ${pending} solicitudes por revisar` : 'Se verifican al cargar la nómina', ready: inbound.length > 0 && approved === inbound.length && !pending },
    { label: 'Origen y flota', detail: `${crews.length} vans con conductor · ${baseReady ? 'base definida' : 'selecciona una base'}`, ready: baseReady && crews.length === 3 },
  ]
  const pointFields = <>
    <Field label="Nombre" name="name" required /><Field label="Dirección verificada" name="address" required />
    <Field label="Latitud" name="latitude" type="number" step="any" min={-90} max={90} required />
    <Field label="Longitud" name="longitude" type="number" step="any" min={-180} max={180} required />
  </>
  return <div className="stack preparation">
    <Panel title="Antes de ponderar" description="Completa los factores de la operación y luego calcula con la nómina de la jornada."
      action={config?.locked ? <span className="badge valid"><LockKeyhole size={13} /> Factores fijos</span> : <span className="badge">{dirty ? 'Cambios sin guardar' : 'Configuración operativa'}</span>}>
      <ol className="preparation-checks">{checks.map((check, i) => <li key={check.label}>
        <span className={'preparation-number ' + (check.ready ? 'ready' : '')}>{check.ready ? <Check size={15} /> : i + 1}</span>
        <div><strong>{check.label}</strong><small>{check.detail}</small></div>
      </li>)}</ol>
      {config?.locked && <p className="preparation-note">Prueba ceteris paribus: terminales, base, flota, red vial y reglas constantes. La nómina determina las rutas y horarios calculados.</p>}
      {error && <Notice text={error} error />}{notice && <Notice text={notice} />}
      {busy && <span role="status" className="actions"><Busy>{busy}…</Busy></span>}
      {!config && !busy && <button className="button" onClick={() => void execute('Cargando preparación', load)}>Reintentar carga</button>}
    </Panel>
    {config && <>
      <form onSubmit={save} className="stack">
        <Panel title="Terminales y salida" description="Valores habituales para nuevas cargas. Las solicitudes ya importadas se corrigen desde Solicitudes.">
          <fieldset disabled={!!busy || calculating || config.locked}><div className="fields preparation-terminals">
            {customers.map(customer => <Field label={'Terminal · ' + customer.name} key={customer.id}>
              <select value={config.terminal_ids[customer.id] ?? ''} onChange={e => {
                const terminal_ids = { ...config.terminal_ids }; if (e.target.value) terminal_ids[customer.id] = e.target.value; else delete terminal_ids[customer.id]
                update({ ...config, terminal_ids })
              }}><option value="">Seleccionar terminal</option>{terminals.filter(t => t.customer_id === customer.id && t.latitude != null && t.longitude != null)
                .map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
            </Field>)}
            <Field label="Base de salida compartida"><select value={config.depot_id ?? ''} onChange={e => update({ ...config, depot_id: e.target.value || null })}>
              <option value="">Seleccionar base</option>{depots.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select></Field>
          </div></fieldset>
          <div className="actions"><button type="button" className="button compact" onClick={onReview}><MapPin size={15} />Revisar destinos de la nómina</button>
            <button type="button" className="button compact" onClick={onFleet}><Truck size={15} />Ver flota y turnos</button></div>
        </Panel>
        <Panel title="Tiempos y reglas de cálculo" description="Mantén estos valores constantes al comparar cargas de pasajeros.">
          <fieldset disabled={!!busy || calculating || config.locked}>
            <Field label="Matriz vial guardada"><select value={config.matrix_id ?? ''} onChange={e => update({ ...config, matrix_id: e.target.value || null })}>
              <option value="">{session.road_available ? 'Generar con el proveedor configurado' : 'Seleccionar matriz vial'}</option>
              {matrices.filter(m => m.mode === 'static_road' && !m.simulation).map(m => <option key={m.id} value={m.id}>{m.provider} · {m.map_version} · {m.id.slice(0, 8)}</option>)}
            </select></Field>
            <div className="fields">{ruleFields.map(([key, label, min, max]) => <Field key={key} label={label} type="number" min={min} max={max} step={1} required
              value={config.rules[key]} onChange={e => update({ ...config, rules: { ...config.rules, [key]: e.target.value === '' ? '' : Number(e.target.value) } } as Preparation)} />)}</div>
          </fieldset>
          <p className="preparation-note">Los tiempos viales son estáticos. Una matriz guardada debe corresponder a las recogidas, terminales y orígenes actuales.</p>
          {!config.locked && <details className="preparation-matrix"><summary>Cargar una matriz vial verificada</summary>
            <p className="preparation-note">Completa las recogidas y descarga la plantilla de esta nómina. Rellena cada tramo con segundos y metros del proveedor vial; indica su fuente y fecha de verificación.</p>
            <div className="actions"><button className="button compact" type="button" disabled={!inbound.length || !terminalReady || !!pending || crews.length !== 3} onClick={downloadMatrixTemplate}>Descargar plantilla JSON</button>
              <Field label="Importar matriz JSON" type="file" accept=".json,application/json" disabled={!!busy || calculating} onChange={event => {
                const file = event.target.files?.[0]; if (file) void importMatrix(file); event.target.value = ''
              }} /></div>
          </details>}
          {!config.locked && <button className="button primary" disabled={!!busy || calculating || !dirty}>Guardar factores</button>}
        </Panel>
      </form>
      {!config.locked && <details className="preparation-register"><summary>Registrar un terminal o una base</summary><div className="preparation-forms">
        <form className="stack" onSubmit={e => void create(e, 'terminal')}><h3>Nuevo terminal</h3>
          <Field label="Cliente"><select name="customer_id">{customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
          {pointFields}<button className="button" disabled={!!busy}>Registrar terminal</button>
        </form>
        <form className="stack" onSubmit={e => void create(e, 'base')}><h3>Nueva base</h3>{pointFields}<button className="button" disabled={!!busy}>Registrar base</button></form>
      </div></details>}
      <Panel title="Nómina de la jornada" description={inbound.length ? `${inbound.length} pasajeros · ${date}` : 'Carga el listado de pasajeros para verificar recogidas y horarios.'}>
        <div className="actions">
          <button className="button" onClick={onImport}>Cargar nómina <ArrowRight size={15} /></button>
          {!config.locked && <button className="button" onClick={onGeo}>Completar recogidas</button>}
          <button className="button primary" disabled={!!busy || dirty || calculating || !inbound.length || !baseReady || !roadReady || !terminalReady || !!pending || crews.length !== 3}
            onClick={onCalculate}>{calculating ? <Busy>Calculando rutas…</Busy> : <><Route size={16} />Ponderar rutas</>}</button>
        </div>
        {dirty && <p className="preparation-note">Guarda los factores antes de calcular.</p>}
      </Panel>
    </>}
  </div>
}
