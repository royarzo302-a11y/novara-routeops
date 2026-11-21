import { useState, type FormEvent } from 'react'
import { ArrowRight, CloudUpload, Pencil, FileSpreadsheet } from 'lucide-react'
import { type Api, type Batch, type Customer, type Ingestion, type Ride, type Terminal, clock, hostedDemo, labels } from './api'
import { Busy, Field, Notice, Panel } from './ui'

export function ImportPanel({ api, customers, terminals, date, onImport, onTerminals, demo, planning }: {
  api: Api; customers: Customer[]; terminals: Terminal[]; date: string; onImport: (result: Ingestion, automatic: boolean) => void; onTerminals: () => Promise<void>
  demo?: boolean; planning?: boolean
}) {
  const [customer, setCustomer] = useState('')
  const [file, setFile] = useState<File>()
  const [terminal, setTerminal] = useState('')
  const [drop, setDrop] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Batch>()
  const [saving, setSaving] = useState(false)
  const [manual, setManual] = useState(false)
  const client = customer || customers[0]?.id || ''
  function choose(candidate?: File) {
    setError('')
    setFile(undefined)
    if (!candidate) return
    const maximum = hostedDemo ? 500 * 1024 : 10 * 1024 * 1024
    if (!/\.xlsx$/i.test(candidate.name) || candidate.size > maximum) {
      setError('Selecciona un Excel .xlsx de hasta ' + (hostedDemo ? '500 KiB.' : '10 MB.'))
      return
    }
    setFile(candidate)
    if (!manual) {
      const body = new FormData()
      body.set('file', candidate)
      void importFile(body, true)
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    const body = new FormData(event.currentTarget)
    body.set('file', file)
    body.set('customer_id', client)
    if (!terminal) body.delete('terminal_id')
    for (const key of ['archive_date', 'expected_service_date']) if (!body.get(key)) body.delete(key)
    await importFile(body, false)
  }
  async function importFile(body: FormData, automatic: boolean) {
    setProgress(0)
    setError('')
    try {
      const response = await api.upload(body, setProgress, automatic)
      setResult(response.batch)
      setFile(undefined)
      onImport(response, automatic)
    } catch (e) { setError((e as Error).message) }
    finally { setProgress(null) }
  }
  async function createTerminal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const body = new FormData(form)
    setSaving(true)
    setError('')
    try {
      const created = await api.json<Terminal>('/v2/terminals', 'POST', {
        customer_id: client, name: body.get('name'),
        latitude: Number(body.get('lat')), longitude: Number(body.get('lon')),
      })
      await onTerminals()
      setTerminal(created.id)
      form.reset()
    } catch (e) { setError((e as Error).message) }
    finally { setSaving(false) }
  }
  return <Panel title={demo ? 'Sube tu nómina' : 'Importar nómina'} className={demo ? 'dispatch-upload' : ''}
    description={hostedDemo ? 'Simula una jornada o carga las dos nóminas descargables para probar el flujo completo.'
      : demo ? 'Cada prueba cambia la fecha, las recogidas y los horarios.' : 'Suelta el Excel original para identificar la jornada e intentar calcular las rutas.'}>
    {error && <Notice text={error} error />}
    {demo ? <button type="button" className="button primary" disabled={progress !== null || planning}
      onClick={async () => {
        setProgress(0)
        setError('')
        try { choose(await api.sample()) } catch (e) { setError((e as Error).message); setProgress(null) }
      }}><FileSpreadsheet size={17} />Probar con nómina incluida{demo && <ArrowRight size={16} />}</button>
      : <label className="check"><input type="checkbox" checked={manual} disabled={progress !== null || planning}
        onChange={e => setManual(e.target.checked)} />Importación manual</label>}
    {hostedDemo && <div className="stack">
      <p>Para probar las correcciones y la flota compartida, descarga y carga ambas planillas de ejemplo de esta jornada.</p>
      <div className="actions">{(['gran-america', 'lo-blanco'] as const).map(slug => <button key={slug} type="button" className="button"
        onClick={() => void api.downloadRoster(slug).catch((err: Error) => setError(err.message))}>Descargar demo-{slug}.xlsx</button>)}</div>
    </div>}
    <form onSubmit={submit} className="stack">
      {manual && <div className="fields">
        <Field label="Cliente"><select value={client} onChange={e => { setCustomer(e.target.value); setTerminal('') }}>
          {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></Field>
        <Field label="Fecha esperada" name="expected_service_date" type="date" defaultValue={date} />
        <Field label="Fecha de archivo (opcional)" name="archive_date" type="date" />
        <Field label="Tipo de nómina"><select name="role"><option value="original">Original del cliente</option><option value="internal">Planilla interna</option></select></Field>
        <Field label="Terminal de referencia"><select name="terminal_id" value={terminal} onChange={e => setTerminal(e.target.value)}>
          <option value="">Seleccionar después</option>
          {terminals.filter(t => t.customer_id === client).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select></Field>
      </div>}
      <label className={'dropzone ' + (drop ? 'dragging' : '')}
        onDragOver={e => { e.preventDefault(); setDrop(true) }} onDragLeave={() => setDrop(false)}
        onDrop={e => { e.preventDefault(); setDrop(false); if (progress === null && !planning) choose(e.dataTransfer.files[0]) }}>
        <input aria-label="Seleccionar archivo Excel" type="file" accept=".xlsx" disabled={progress !== null || planning}
          onChange={e => { choose(e.currentTarget.files?.[0]); e.currentTarget.value = '' }} />
        {file ? <FileSpreadsheet /> : <CloudUpload />}
        <strong>{file ? 'Excel listo para importar' : 'Arrastra tu Excel aquí'}</strong>
        <small>{file ? 'Selecciona otro archivo si lo necesitas' : demo ? 'o elige un Excel ficticio · .xlsx' : 'o selecciona un archivo · .xlsx, hasta 10 MB'}</small>
      </label>
      {progress !== null && <div role="status"><progress max={100} value={progress} /> {progress === 100 ? 'Procesando nómina…' : 'Cargando ' + progress + '%'}</div>}
      {demo && planning && <div className="dispatch-status" role="status"><Busy>Calculando rutas…</Busy></div>}
      {manual && <button className="button primary" type="submit" disabled={!file || progress !== null || !client}>Procesar Excel</button>}
    </form>
    {result && !demo && <Notice text={result.records + ' solicitudes importadas · ' + result.pending_review + ' pendientes · ' + result.unclassified_rows + ' filas sin clasificar.'} />}
    {!demo && <details><summary>Registrar un terminal para este cliente</summary>
      <form className="fields" onSubmit={createTerminal}>
        <Field label="Cliente del terminal"><select value={client} onChange={e => { setCustomer(e.target.value); setTerminal('') }}>
          {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></Field>
        <Field label="Nombre de terminal" name="name" required />
        <Field label="Latitud del terminal" name="lat" type="number" step="any" min={-90} max={90} required />
        <Field label="Longitud del terminal" name="lon" type="number" step="any" min={-180} max={180} required />
        <button className="button" disabled={saving || !client}>Guardar terminal</button>
      </form>
    </details>}
  </Panel>
}

export function ReviewTable({ rides, customers, terminals, api, onSaved, onLocate }: {
  rides: Ride[]; customers: Customer[]; terminals: Terminal[]; api: Api; onSaved: (ride: Ride) => void; onLocate: (id: string) => void
}) {
  const [active, setActive] = useState<Ride>()
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const filtered = rides.filter(r => (filter === 'all' || filter === r.validation_status)
    && [r.name, r.employee_code, r.address, r.commune].some(v => (v ?? '').toLocaleLowerCase('es').includes(query.trim().toLocaleLowerCase('es'))))
  return <Panel title="Solicitudes de traslado" description={rides.length + ' registros en los lotes seleccionados'}>
    {active && <RequestEditor key={active.id} ride={active} terminals={terminals} api={api}
      onClose={() => setActive(undefined)} onSaved={ride => { onSaved(ride); setActive(undefined) }} />}
    <div className="fields">
      <Field label="Buscar solicitud" type="search" value={query} onChange={e => setQuery(e.target.value)} />
      <Field label="Estado"><select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="all">Todos</option><option value="pending_review">Pendientes</option>
        <option value="valid">Válidas</option><option value="excluded">Excluidas</option>
      </select></Field>
    </div>
    {filtered.length ? <div className="table-wrap"><table><thead><tr><th>Pasajero</th><th>Cliente</th><th>Dirección / comuna</th><th>Ingreso</th><th>Estado</th><th>Acciones</th></tr></thead>
      <tbody>{filtered.map(r => <tr key={r.id}><td><strong>{r.name || 'Sin nombre'}</strong><small>{r.employee_code || 'Sin código'}</small></td>
        <td>{customers.find(c => c.id === r.customer_id)?.name || r.customer_id}</td>
        <td>{r.address || 'Sin dirección'}<small>{r.commune || 'Sin comuna'}</small></td>
        <td>{clock(r.work_time)}</td><td><span className={'badge ' + r.validation_status}>{labels[r.validation_status] ?? r.validation_status}</span>
          {r.validation_status === 'pending_review' && r.issues[0] && <small>{r.issues[0].message}</small>}</td>
        <td><div className="actions"><button className="button compact" onClick={() => setActive(r)}><Pencil size={14} />Editar</button>
          {!hostedDemo && <button className="button compact" onClick={() => onLocate(r.id)}>Ubicación</button>}</div></td></tr>)}</tbody>
    </table></div> : <div className="empty">No hay solicitudes para mostrar. Carga una nómina o cambia el filtro.</div>}
  </Panel>
}

function RequestEditor({ ride, api, terminals, onSaved, onClose }: { ride: Ride; api: Api; terminals: Terminal[]; onSaved: (ride: Ride) => void; onClose: () => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const changes: Record<string, string | boolean | null> = {}
    const keys = ['name', 'employee_code', 'address', 'commune', 'work_time', 'end_time', 'service_date', 'terminal_id', 'direction'] as const
    for (const key of hostedDemo ? ['commune'] as const : keys) {
      const val = String(form.get(key) ?? '').trim() || null
      const prior = ride[key]
      if (val !== (key.endsWith('_time') ? prior?.slice(0, 5) || null : prior)) changes[key] = val
    }
    if (!hostedDemo && form.has('excluded') !== ride.excluded) changes.excluded = form.has('excluded')
    setBusy(true)
    setError('')
    try { onSaved(await api.json<Ride>('/v2/requests/' + ride.id, 'PATCH', {
      changes, confirm_fields: form.getAll('confirm'), reason: hostedDemo ? 'Corrección de comuna en la demo' : form.get('reason'),
    })) } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const reviewFields = [...new Set(ride.issues.filter(i => i.code.startsWith('source_')).map(i => i.field))]
    .filter((f): f is string => !!f && ['employee_code', 'name', 'address', 'commune', 'phone', 'service_date', 'work_time', 'end_time', 'pickup_time', 'arrival_time', 'terminal_name'].includes(f))
  const fieldLabels: Record<string, string> = { employee_code: 'Código', name: 'Nombre', address: 'Dirección', commune: 'Comuna', phone: 'Teléfono', service_date: 'Fecha', work_time: 'Ingreso', end_time: 'Término', pickup_time: 'Recogida', arrival_time: 'Llegada', terminal_name: 'Terminal' }
  return <form className="editor stack" onSubmit={save}>
    <h3>Revisar solicitud</h3>
    {error && <Notice error text={error} />}
    {!!ride.issues.length && <ul className="issue-list">{ride.issues.map((i, n) => <li key={n}>{i.field && fieldLabels[i.field] ? fieldLabels[i.field] + ' · ' : ''}{i.message}</li>)}</ul>}
    {hostedDemo ? <div className="fields">
      <Field label="Dirección de ejemplo" value={ride.address ?? ''} readOnly />
      <Field label="Comuna" name="commune" defaultValue={ride.commune ?? ''} required />
      {!ride.commune && <p>En el ejemplo, la primera parada de {ride.customer_id === 'gran_america' ? 'Gran América está en Pudahuel' : 'Lo Blanco está en Maipú'}.</p>}
    </div> : <><div className="fields">
      <Field label="Pasajero" name="name" defaultValue={ride.name ?? ''} />
      <Field label="Código" name="employee_code" defaultValue={ride.employee_code ?? ''} />
      <Field label="Dirección" name="address" defaultValue={ride.address ?? ''} />
      <Field label="Comuna" name="commune" defaultValue={ride.commune ?? ''} />
      <Field label="Hora de ingreso" name="work_time" type="time" defaultValue={ride.work_time?.slice(0, 5)} />
      <Field label="Hora de término" name="end_time" type="time" defaultValue={ride.end_time?.slice(0, 5)} />
      <Field label="Fecha de servicio" name="service_date" type="date" defaultValue={ride.service_date ?? ''} />
      <Field label="Sentido"><select name="direction" defaultValue={ride.direction}>
        {ride.direction === 'unknown' && <option value="unknown">Por revisar</option>}
        <option value="inbound">Acercamiento</option><option value="outbound">Retorno</option>
      </select></Field>
      <Field label="Terminal"><select name="terminal_id" defaultValue={ride.terminal_id ?? ''}>
        <option value="">Sin terminal</option>{terminals.filter(t => t.customer_id === ride.customer_id).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select></Field>
    </div>
    {reviewFields.length > 0 && <fieldset><legend>Confirmar tras verificar con la fuente</legend>
      <div className="actions">{reviewFields.map(field => <label className="check" key={field}><input type="checkbox" name="confirm" value={field} />{fieldLabels[field]}</label>)}</div>
    </fieldset>}
    <label className="check"><input type="checkbox" name="excluded" defaultChecked={ride.excluded} />Excluir de la planificación</label>
    <Field label="Motivo de revisión" name="reason" required maxLength={300} /></>}
    <div className="actions"><button className="button primary" disabled={busy}>{busy ? <Busy>Guardando</Busy> : 'Guardar revisión'}</button>
      <button type="button" className="button" onClick={onClose} disabled={busy}>Cancelar</button></div>
  </form>
}
