import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Activity, ArrowRight, ArrowUpRight, CalendarDays, Check, ClipboardList, CloudUpload, Download, LayoutDashboard,
  LockKeyhole, LogOut, MapPin, Navigation, Route, ScanLine, Settings2, Truck, UsersRound, Waypoints } from 'lucide-react'
import { apiClient, hostedDemo, type Batch, type Customer, type Driver, type Ingestion, type Plan, type Review, type Ride, type Session, type Terminal, type Van, labels } from './api'
import { ImportPanel, ReviewTable } from './Manifest'
import { FleetCards, FleetPanel, GeoPanel, PlanningPanel, Results, planMapData } from './Operations'
import { Busy, Field, Notice, Panel } from './ui'
import { overlappingRosters, quickPlan, rosterDates, type PlanInputs } from './quickPlan'
import { PreparationPanel } from './Preparation'

const RouteMap = lazy(() => import('./RouteMap'))
const sections = [
  { id: 'home', label: 'Resumen', icon: LayoutDashboard },
  { id: 'prepare', label: 'Preparación', icon: Settings2 },
  { id: 'import', label: 'Importar Excel', icon: CloudUpload },
  { id: 'review', label: 'Solicitudes', icon: ClipboardList },
  { id: 'geo', label: 'Ubicaciones', icon: MapPin },
  { id: 'fleet', label: 'Flota', icon: Truck },
  { id: 'plan', label: 'Planificación', icon: Route },
] as const
type Page = typeof sections[number]['id']
type Connection = { token: string; session: Session }
const demoToken = !hostedDemo && import.meta.env.VITE_NOVARA_DEMO === '1' ? 'novara-local-demo' : ''
const pageUrls: Record<Page, string> = { home: '/inicio', prepare: '/preparacion', import: '/importar', review: '/solicitudes',
  geo: '/ubicaciones', fleet: '/flota', plan: '/planificacion' }
const fromUrl = () => (Object.keys(pageUrls) as Page[]).find(page => pageUrls[page] === window.location.pathname) ?? 'import'

function today() {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Santiago', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts()
  return ['year', 'month', 'day'].map(key => parts.find(p => p.type === key)?.value).join('-')
}

export default function App() {
  const [connection, setConnection] = useState<Connection>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!demoToken && !hostedDemo) return
    const token = demoToken
    apiClient(token).json<Session>('/v4/geo/session')
      .then(session => {
        if (!session.authenticated || !session.demo) throw new Error('El entorno de demostración no está disponible.')
        setConnection({ token, session })
      })
      .catch((err: Error) => { if (!hostedDemo) setError(err.message) })
  }, [])
  async function connect(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const token = String(new FormData(e.currentTarget).get('token') ?? '')
      .trim().replace(/^NOVARA_GEO_TOKEN\s*=\s*/, '')
    if (!token) return
    setError(''); setLoading(true)
    try {
      if (hostedDemo) await apiClient('').json('/demo/login', 'POST', { password: token })
      const session = await apiClient(hostedDemo ? '' : token).json<Session>('/v4/geo/session')
      if (!session.authenticated) throw new Error('La sesión no se pudo verificar.')
      setConnection({ token: hostedDemo ? '' : token, session })
    } catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }
  if (connection) return <Workspace connection={connection} onLogout={async () => {
    try { if (hostedDemo) await apiClient('').json('/demo/logout', 'POST', {}) }
    catch (err) { setError((err as Error).message) }
    finally { setConnection(undefined) }
  }} />
  if (hostedDemo) return <Shell page="import" demo>
    <Panel title="Acceso a Novara RouteOps" description="Ingresa la clave de la demo. Usa únicamente las nóminas ficticias descargables. La sesión es temporal.">
      <form className="stack" onSubmit={connect}>
        {error && <Notice text={error} error />}
        <Field label="Clave de la demo" name="token" type="password" autoComplete="current-password" required />
        <button className="button primary" disabled={loading}>{loading ? <Busy>Conectando…</Busy> : 'Entrar a la demo'}</button>
      </form>
    </Panel>
  </Shell>
  if (demoToken) return <Shell page="import" demo>
    <Panel title="Planificador de rutas">
      {error ? <><Notice text={error} error /><button className="button primary" onClick={() => window.location.reload()}>Reintentar conexión</button></>
        : <span className="actions" role="status"><Busy>Preparando la demo…</Busy></span>}
    </Panel>
  </Shell>
  return <Shell page="home">
    <Title page="home" />
    <div className="metric-grid">
      <Metric label="Pasajeros" icon={UsersRound} value="—" />
      <Metric label="Solicitudes válidas" icon={ScanLine} value="—" />
      <Metric label="Pendientes de revisión" icon={ClipboardList} value="—" />
      <Metric label="Vans disponibles" icon={Truck} value="—" />
    </div>
    <div className="dashboard-grid">
      <Panel title="Mapa operativo" description="Recogidas y terminales de la jornada">
        <div className="map-placeholder">
          <div className="map-empty"><span><Navigation size={24} /></span><strong>Vista de jornada</strong><p>Conecta tu sesión para consultar nóminas, ubicaciones y recorridos.</p></div>
        </div>
      </Panel>
      <Panel title="Acceso de operador" description="Pega el token o la línea NOVARA_GEO_TOKEN completa del archivo .env." action={<LockKeyhole size={18} className="muted" />}>
        <form className="stack" onSubmit={connect}>
          {error && <Notice text={error} error />}
          <Field label="Token de operador" name="token" type="password" required autoComplete="off" />
          <button className="button primary" disabled={loading}>{loading ? <Busy>Conectando…</Busy> : <>Conectar sesión <ArrowRight size={16} /></>}</button>
        </form>
      </Panel>
    </div>
    <Panel title="Flota compartida" description="Gran América y Lo Blanco"><FleetCards vans={[]} drivers={[]} /></Panel>
  </Shell>
}

function Title({ page, children }: { page: Page; children?: React.ReactNode }) {
  const headings: Record<Page, [string, string]> = {
    home: ['Resumen operativo', 'Organiza la jornada de traslado de Novara.'],
    prepare: ['Preparación de la operación', 'Define los factores antes de ponderar las rutas.'],
    import: ['Importación', 'Nóminas de Gran América y Lo Blanco.'],
    review: ['Revisión de solicitudes', 'Corrige datos de origen y verifica las incidencias.'],
    geo: ['Ubicaciones', 'Aprueba las recogidas que alimentan la matriz de viaje.'],
    fleet: ['Configuración de flota', 'Vans, capacidad y disponibilidad de conductores.'],
    plan: ['Planificación', 'Calcula y revisa los viajes de la jornada.'],
  }
  return <div className="title"><div><h1>{headings[page][0]}</h1><p>{headings[page][1]}</p></div>{children}</div>
}

function Metric({ icon: Icon, label, value }: { icon: typeof UsersRound; label: string; value: string | number }) {
  return <article className="metric"><span className="metric-icon"><Icon size={19} /></span><span>{label}</span><strong>{value}</strong></article>
}

function Shell({ page, go, onLogout, children, demo }: { page: Page; go?: (p: Page) => void; onLogout?: () => void; children: React.ReactNode; demo?: boolean }) {
  const navButton = ({ id, label, icon: Icon }: typeof sections[number]) => <button key={id} className={page === id ? 'selected' : ''}
    aria-current={page === id ? 'page' : undefined} disabled={!go && id !== 'home'} onClick={() => go?.(id)}><Icon size={17} />{label}</button>
  return <div className={'shell' + (demo ? ' demo-shell' : '')}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon"><Waypoints size={22} /></div><div><strong>Novara</strong><small>ROUTEOPS</small></div></div>
      <p className="nav-label">OPERACIONES</p>
      <nav aria-label="Operaciones">{demo ? <>
        {sections.filter(s => s.id === 'prepare' || s.id === 'import' || s.id === 'plan').map(navButton)}
        <details className="nav-tools" open={page !== 'import' && page !== 'plan' && page !== 'prepare' || undefined}>
          <summary><Settings2 size={16} /> Herramientas</summary>
        {sections.filter(s => s.id !== 'prepare' && s.id !== 'import' && s.id !== 'plan' && (!hostedDemo || s.id !== 'geo')).map(navButton)}
        </details>
      </> : sections.map(navButton)}</nav>
      <div className="sidebar-bottom"><div className="local-marker" /><div><strong>{demo ? 'Demo local' : 'Entorno local'}</strong><small>{demo ? 'Datos ficticios' : 'Novara RouteOps v0.5'}</small></div></div>
    </aside>
    <div className="workspace"><header className="topbar"><div><span>Operaciones</span><span className="divider">/</span><strong>{sections.find(p => p.id === page)?.label}</strong></div>
      {demo ? <div className="actions"><span className="demo-chip"><span />Modo simulación</span>
        {hostedDemo && onLogout && <button className="button compact" onClick={onLogout}>Cerrar sesión</button>}</div>
        : onLogout ? <button className="button compact" onClick={onLogout}><LogOut size={15} />Cerrar sesión</button> : <span className="badge"><LockKeyhole size={13} />Sesión privada</span>}
    </header><main id="main">{children}</main></div>
  </div>
}

function Workspace({ connection, onLogout }: { connection: Connection; onLogout: () => Promise<void> }) {
  const api = useMemo(() => apiClient(connection.token), [connection.token])
  const [page, updatePage] = useState<Page>(() => hostedDemo ? fromUrl() : connection.session.demo ? 'import' : 'home')
  const setPage = useCallback((next: Page) => {
    if (hostedDemo && window.location.pathname !== pageUrls[next]) window.history.pushState(null, '', pageUrls[next])
    updatePage(next)
  }, [])
  useEffect(() => {
    if (!hostedDemo) return
    const sync = () => updatePage(fromUrl())
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [])
  const [date, setDate] = useState(today)
  const [client, setClient] = useState('')
  const [customers, setCustomers] = useState<Customer[]>([])
  const [terminals, setTerminals] = useState<Terminal[]>([])
  const [batches, setBatches] = useState<Batch[]>([])
  const [vans, setVans] = useState<Van[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [selectedBatches, setSelectedBatches] = useState<string[]>([])
  const [loaded, setLoaded] = useState<Record<string, Ride[]>>({})
  const [reviews, setReviews] = useState<Record<string, Review>>({})
  const [plan, setPlan] = useState<Plan>()
  const [planInputs, setPlanInputs] = useState<PlanInputs>()
  const [stale, setStale] = useState(false)
  const generation = useRef(0)
  const hasPlan = useRef(false)
  const advanced = useRef<HTMLDetailsElement>(null)
  const invalidatePlan = useCallback(() => {
    generation.current += 1
    if (hasPlan.current) setStale(true)
    hasPlan.current = false
    setPlan(undefined)
  }, [])
  const [geoId, setGeoId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [loadingBatch, setLoadingBatch] = useState('')
  const [lastAutomatic, setLastAutomatic] = useState<Batch>()
  const [quickNotice, setQuickNotice] = useState('')
  const [runningQuick, setRunningQuick] = useState(false)
  const [loadingScenario, setLoadingScenario] = useState(false)
  const demo = connection.session.demo === true
  const refreshFleet = useCallback(async () => {
    const [fleet, team] = await Promise.all([api.json<Van[]>('/vehicles'), api.json<Driver[]>('/drivers')])
    invalidatePlan(); setVans(fleet); setDrivers(team)
  }, [api, invalidatePlan])
  const refreshTerminals = useCallback(async () => setTerminals(await api.json<Terminal[]>('/v2/terminals')), [api])
  const refresh = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const [clients, imports] = await Promise.all([
        api.json<Customer[]>('/v2/customers'), api.json<Batch[]>('/v2/ingestions'), refreshFleet(), refreshTerminals(),
      ])
      setCustomers(clients); setBatches(imports)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }, [api, refreshFleet, refreshTerminals])
  useEffect(() => { void refresh() }, [refresh])
  const updateLocation = useCallback((id: string, review: Review) => {
    setReviews(prev => ({ ...prev, [id]: review }))
  }, [])
  const loadLocations = useCallback(async (ids: string[]) => {
    const updates = await Promise.all(ids.map(async id => [id, await api.json<Review>('/v4/geo/requests/' + id + '/location')] as const))
    setReviews(prev => ({ ...prev, ...Object.fromEntries(updates) }))
  }, [api])
  const rides = useMemo(() => selectedBatches.flatMap(id => loaded[id] ?? []), [selectedBatches, loaded])
  const daily = rides.filter(r => r.service_date === date && (!client || r.customer_id === client))
  const filteredRides = rides.filter(r => !client || r.customer_id === client)
  const available = vans.filter(v => v.available && drivers.some(d => d.vehicle_id === v.id && d.available)).length
  const originalIds = new Set(batches.filter(batch => batch.role === 'original').map(batch => batch.id))
  const overlap = overlappingRosters(rides.filter(ride => originalIds.has(ride.batch_id)), date)
  async function runQuick(source: Ride[]) {
    const dates = rosterDates(source)
    if (dates.length !== 1) {
      setQuickNotice(dates.length
        ? 'La nómina trae más de una fecha de acercamiento. Revisa las solicitudes y elige la jornada.'
        : 'No se encontró una fecha operativa de acercamiento. Revisa las solicitudes.')
      return
    }
    invalidatePlan()
    const revision = generation.current
    const serviceDate = dates[0]
    if (overlappingRosters(source, serviceDate)) {
      setQuickNotice('Hay personas repetidas en lotes originales. Desactiva una copia antes de calcular.')
      return
    }
    setDate(serviceDate); setRunningQuick(true); setQuickNotice('Preparando las recogidas y calculando rutas…')
    try {
      const result = await quickPlan({
        api, date: serviceDate, rides: source, vans, drivers, terminals,
        roadAvailable: connection.session.road_available, demo: connection.session.demo,
        onReviews: values => setReviews(prev => ({ ...prev, ...values })),
      })
      if (revision !== generation.current) return
      setQuickNotice(result.notice)
      if (result.plan) {
        hasPlan.current = true; setPlan(result.plan); setPlanInputs(result.inputs); setStale(false); setPage('plan')
        window.scrollTo(0, 0)
        requestAnimationFrame(() => document.getElementById('journey-heading')?.focus({ preventScroll: true }))
      }
    } catch (e) { setQuickNotice((e as Error).message) }
    finally { setRunningQuick(false) }
  }
  function addImport(result: Ingestion, automatic: boolean) {
    const dates = rosterDates(result.requests)
    setBatches(prev => [result.batch, ...prev.filter(b => b.id !== result.batch.id)])
    setLoaded(prev => ({ ...prev, [result.batch.id]: result.requests }))
    setSelectedBatches(prev => demo && !hostedDemo && automatic ? [result.batch.id] : [...prev.filter(id => id !== result.batch.id && !(automatic && dates.length === 1
      && batches.some(batch => batch.id === id && batch.customer_id === result.batch.customer_id && batch.role === 'original')
      && rosterDates(loaded[id] ?? []).includes(dates[0]))), result.batch.id])
    setClient('')
    invalidatePlan()
    setPlanInputs(undefined)
    setQuickNotice('')
    if (automatic) {
      setLastAutomatic(result.batch)
      if (hostedDemo && result.batch.pending_review) {
        if (dates.length === 1) setDate(dates[0])
        setPage('review')
      } else {
        if (dates.length === 1) setDate(dates[0])
        setPage('prepare')
      }
    }
  }
  async function simulateAgain() {
    setLoadingScenario(true)
    setError('')
    try {
      const file = await api.sample()
      const data = new FormData()
      data.set('file', file)
      const result = await api.upload(data, () => {}, true)
      setPage('import')
      addImport(result, true)
    } catch (err) { setError((err as Error).message) }
    finally { setLoadingScenario(false) }
  }
  async function resetDemo() {
    try {
      await api.json('/demo/reset', 'POST', {})
      window.location.replace('/importar')
    } catch (err) { setError((err as Error).message) }
  }
  async function saveBase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const fields = new FormData(form)
    const name = String(fields.get('name') ?? '').trim()
    setQuickNotice('')
    try {
      const existing = await api.json<unknown[]>('/depots')
      if (existing.length) {
        setQuickNotice('Ya hay una base registrada. Usa sus coordenadas o define los orígenes desde Planificación.')
        return
      }
      await api.json('/depots', 'POST', {
        name, address: name, latitude: Number(fields.get('latitude')), longitude: Number(fields.get('longitude')),
      })
      setQuickNotice('Base de salida guardada.')
      form.reset()
    } catch (e) { setQuickNotice((e as Error).message) }
  }
  async function toggleBatch(id: string, enabled: boolean) {
    setError('')
    invalidatePlan()
    if (!enabled) { setSelectedBatches(prev => prev.filter(b => b !== id)); return }
    setLoadingBatch(id)
    try {
      const result = await api.json<Ingestion>('/v2/ingestions/' + id)
      setLoaded(prev => ({ ...prev, [id]: result.requests }))
      setBatches(prev => prev.map(batch => batch.id === id ? result.batch : batch))
      const dates = rosterDates(result.requests)
      if (!selectedBatches.length && dates.length === 1) setDate(dates[0])
      setSelectedBatches(prev => Array.from(new Set([...prev, id])))
    } catch (e) { setError((e as Error).message) }
    finally { setLoadingBatch('') }
  }
  async function saved(ride: Ride) {
    invalidatePlan()
    setPlanInputs(previous => previous && { ...previous, matrix: undefined })
    setReviews(prev => { const copy = { ...prev }; delete copy[ride.id]; return copy })
    setLoaded(prev => ({ ...prev, [ride.batch_id]: (prev[ride.batch_id] ?? []).map(r => r.id === ride.id ? ride : r) }))
    try {
      const result = await api.json<Ingestion>('/v2/ingestions/' + ride.batch_id)
      setLoaded(prev => ({ ...prev, [ride.batch_id]: result.requests }))
      setBatches(prev => prev.map(batch => batch.id === ride.batch_id ? result.batch : batch))
    } catch (e) { setError((e as Error).message) }
  }
  const previewMap = useMemo(() => plan ? planMapData(plan, terminals, reviews, rides, vans) : undefined, [plan, terminals, reviews, rides, vans])
  const batchPicker = <Panel title="Lotes de trabajo" description="Activa los archivos que quieres revisar o planificar.">
    {!selectedBatches.length && batches.length > 0 && <button className="button compact" disabled={!!loadingBatch}
      onClick={() => void toggleBatch(batches[0].id, true)}>Reabrir último lote</button>}
    {!batches.length ? <div className="empty">Todavía no hay nóminas importadas.</div> : <div className="selection">
      {batches.map(b => <label key={b.id} className="check"><input type="checkbox" disabled={!!loadingBatch}
        checked={selectedBatches.includes(b.id)} onChange={e => void toggleBatch(b.id, e.target.checked)} />
        {customers.find(c => c.id === b.customer_id)?.name || b.customer_id} · {(b.service_dates ?? rosterDates(loaded[b.id] ?? [])).join(', ') || b.expected_service_date || 'Fecha operativa por revisar'} · {b.records} solicitudes
        {b.created_at && <small>Importado {new Intl.DateTimeFormat('es-CL', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Santiago' }).format(new Date(b.created_at))}</small>}
        <span className="badge">{b.role === 'original' ? 'Original' : 'Interna'} · {b.id.slice(0, 8)}</span>
      </label>)}</div>}
    {loadingBatch && <span role="status" className="actions"><Busy>Cargando lote…</Busy></span>}
    {overlap && <Notice error text="Hay personas repetidas en lotes originales del mismo cliente y fecha. Desactiva una copia antes de calcular." />}
  </Panel>
  const dateControl = <div className="date-control"><CalendarDays size={17} /><Field label="Fecha operativa" type="date" value={date} onChange={e => {
      invalidatePlan(); setDate(e.target.value)
    }} /></div>
  const activeStep = plan && page === 'plan' ? 3 : runningQuick || (page === 'plan' && selectedBatches.length) ? 2 : page === 'prepare' ? 1 : 0
  const uploadPanel = <ImportPanel api={api} customers={customers} terminals={terminals} date={date}
    onImport={addImport} onTerminals={refreshTerminals} demo={demo} planning={runningQuick} />
  const importFeedback = lastAutomatic && !plan && <Panel title={customers.find(item => item.id === lastAutomatic.customer_id)?.name ?? 'Cliente detectado'}
    description={lastAutomatic.records + ' solicitudes en la nómina' + (date ? ' · ' + date : '')}>
    {quickNotice && <Notice text={quickNotice} />}
    {!runningQuick && <div className="actions"><button className="button primary" onClick={() => setPage('prepare')}>Completar preparación</button>
      <button className="button" onClick={() => setPage('review')}>Revisar pendientes</button></div>}
  </Panel>
  const planningTools = <>{batchPicker}<PlanningPanel key={date} api={api} rides={rides} batches={batches}
    vans={vans} reviews={reviews} date={date} inputs={planInputs?.date === date ? planInputs : undefined}
    overlap={overlap} invalidatePlan={invalidatePlan} startPlan={() => {
      invalidatePlan()
      const revision = generation.current
      return (result, inputs) => {
        if (revision !== generation.current) return
        hasPlan.current = true; setPlan(result); setPlanInputs(inputs); setStale(false); setQuickNotice('')
        requestAnimationFrame(() => document.getElementById('plan-results')?.scrollIntoView({ block: 'start' }))
      }
    }} onLocations={loadLocations} session={connection.session} /></>
  return <Shell page={page} go={setPage} onLogout={onLogout} demo={demo}>
    {demo && (page === 'import' || page === 'plan') ? <header className="journey-header">
      <div><h1 id="journey-heading" tabIndex={-1}>{page === 'import' ? 'Planifica tus rutas' : plan ? 'Rutas de la jornada' : 'Prepara tus rutas'}</h1>
      <p>{page === 'import' ? 'Simula una jornada con direcciones públicas de Santiago y pasajeros ficticios.' : 'Revisa los viajes, sus horarios y puntos de recogida.'}</p></div>
      {page === 'plan' && <div className="actions">
        <button className="button" disabled={loadingScenario} onClick={() => setPage('import')}><CloudUpload size={17} />Cargar otra nómina</button>
        <button className="button" disabled={loadingScenario || runningQuick} onClick={() => void simulateAgain()}>
          {loadingScenario ? <Busy>Preparando jornada…</Busy> : <><Route size={17} />Simular otra jornada</>}
        </button>
      </div>}
    </header> : <Title page={page}>{dateControl}</Title>}
    {demo && (page === 'import' || page === 'prepare' || page === 'plan') && <ol className="journey-steps" aria-label="Avance de la jornada">
      {[{ label: 'Cargar nómina', icon: CloudUpload }, { label: 'Preparar factores', icon: Settings2 }, { label: 'Calcular rutas', icon: Route }, { label: 'Revisar y exportar', icon: Download }].map(({ label, icon: Icon }, index) =>
        <li key={label} aria-current={index === activeStep ? 'step' : undefined} className={index < activeStep ? 'done' : undefined}>
          <span>{index < activeStep ? <Check size={16} /> : <Icon size={16} />}</span>{label}
        </li>)}
    </ol>}
    {busy && <Notice text="Cargando la sesión y la flota…" />}
    {error && <div className="actions"><Notice text={error} error /><button className="button" onClick={() => void refresh()}>Reintentar carga</button></div>}
    {!busy && page === 'home' && <>
      <section className="quick-hero"><div><h2>De la nómina a las rutas</h2><p>Sube el Excel original y revisa el recorrido de cada van.</p></div>
        <button className="button" onClick={() => setPage('import')}><CloudUpload size={16} />Subir nómina</button></section>
      <div className="metric-grid">
        <Metric label="Pasajeros" value={daily.length} icon={UsersRound} />
        <Metric label="Solicitudes válidas" value={daily.filter(r => r.validation_status === 'valid').length} icon={ScanLine} />
        <Metric label="Pendientes de revisión" value={daily.filter(r => r.validation_status === 'pending_review').length} icon={ClipboardList} />
        <Metric label="Vans disponibles" value={available} icon={Truck} />
      </div>
      <div className="dashboard-grid">
        <Panel title="Mapa operativo" description="Recogidas y terminales de la jornada"
          action={<button className="button compact" onClick={() => setPage('plan')}>Ir a planificación <ArrowUpRight size={14} /></button>}>
          {previewMap ? <Suspense fallback={<div className="empty">Cargando mapa…</div>}>
              <RouteMap demo={demo && !hostedDemo} pins={previewMap.pins} lines={previewMap.lines} />
            </Suspense>
            : <div className="map-placeholder"><div className="map-empty"><span><Navigation size={24} /></span><strong>Jornada sin plan calculado</strong>
              <p>Las recogidas y los viajes se muestran después de planificar.</p></div></div>}
        </Panel>
        <Panel title="Jornada de servicio" description="Consulta el estado de la operación." action={<Activity size={18} className="muted" />}>
          <Field label="Cliente"><select value={client} onChange={e => setClient(e.target.value)}><option value="">Ambos clientes</option>
            {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></Field>
          <div className="operational-status"><span>Planificación</span><strong>{plan ? labels[plan.status] : 'Sin calcular'}</strong></div>
          <div className="operational-status"><span>Lotes activos</span><strong>{selectedBatches.length}</strong></div>
          <button className="button primary" onClick={() => setPage(selectedBatches.length ? 'review' : 'import')}>
            {selectedBatches.length ? 'Revisar solicitudes' : 'Importar nómina'} <ArrowRight size={16} />
          </button>
        </Panel>
      </div>
      <Panel title="Flota compartida" description="Gran América y Lo Blanco" action={<button className="button compact" onClick={() => setPage('fleet')}>Gestionar flota <ArrowUpRight size={14} /></button>}>
        <FleetCards vans={vans} drivers={drivers} />
      </Panel>
      {batchPicker}
    </>}
    {!busy && page === 'import' && demo && <div className="dispatch-grid">
      <div className="stack dispatch-intake">
        {uploadPanel}
        <button className="button" onClick={() => setPage('prepare')}><Settings2 size={16} />Ver factores de la prueba</button>
        <div className="dispatch-fleet"><Truck size={20} /><div><strong>{available} vans disponibles</strong><span>Flota de demostración</span></div></div>
        {!runningQuick && importFeedback}
      </div>
      <Panel title="Santiago de Chile" className="dispatch-city">
        <Suspense fallback={<div className="empty">Cargando mapa…</div>}><RouteMap demo={!hostedDemo} pins={[]} /></Suspense>
      </Panel>
    </div>}
    {!busy && page === 'import' && !demo && <>
      <Panel title="Factores de la operación" description="Revisa terminales, base, tiempos de viaje y reglas antes del cálculo.">
        <button className="button" onClick={() => setPage('prepare')}><Settings2 size={16} />Completar preparación</button>
      </Panel>
      {uploadPanel}{importFeedback}
      {batchPicker}<button className="button" onClick={() => setPage('review')}>Abrir solicitudes <ArrowRight size={16} /></button>
    </>}
    {!busy && page === 'review' && <>
      {hostedDemo && <div className="actions">
        <button className="button" onClick={() => setPage('import')}>Cargar otra nómina</button>
        <button className="button primary" disabled={runningQuick || !rides.length} onClick={() => setPage('prepare')}>
          Revisar preparación <ArrowRight size={16} />
        </button>
      </div>}
      {batchPicker}<ReviewTable api={api} customers={customers} terminals={terminals}
      rides={filteredRides} onSaved={ride => void saved(ride)} onLocate={id => { setGeoId(id); setPage('geo') }} /></>}
    {!busy && page === 'prepare' && <>
      {quickNotice && <Notice text={quickNotice} />}
      {batchPicker}
      <PreparationPanel api={api} customers={customers} terminals={terminals} vans={vans} drivers={drivers}
        rides={rides.filter(r => originalIds.has(r.batch_id))} reviews={reviews} date={date} session={connection.session}
        onTerminals={refreshTerminals} onLocations={loadLocations} onChange={() => { invalidatePlan(); setPlanInputs(undefined) }} onReview={() => setPage('review')}
        onGeo={() => setPage('geo')} onFleet={() => setPage('fleet')} onImport={() => setPage('import')}
        onCalculate={() => void runQuick(rides.filter(r => originalIds.has(r.batch_id) && r.service_date === date))}
        calculating={runningQuick} />
    </>}
    {!busy && page === 'geo' && <GeoPanel key={page} api={api} rides={filteredRides} selected={geoId} setSelected={setGeoId}
      terminals={terminals} updates={updateLocation} reviews={reviews} session={connection.session} onApproval={() => {
        invalidatePlan(); setPlanInputs(previous => previous && { ...previous, matrix: undefined })
      }} />}
    {!busy && page === 'fleet' && <>
      {hostedDemo ? <Panel title="Flota de demostración"><FleetCards vans={vans} drivers={drivers} /></Panel>
        : <FleetPanel api={api} vans={vans} drivers={drivers} onChange={refreshFleet} />}
      {!connection.session.demo && <Panel title="Base de salida compartida" description="Registra una sola base para las tres vans del cálculo automático.">
        {quickNotice && <Notice text={quickNotice} />}
        <form className="fields" onSubmit={event => void saveBase(event)}>
          <Field name="name" label="Nombre de la base" required />
          <Field name="latitude" label="Latitud" type="number" step="any" min={-90} max={90} required />
          <Field name="longitude" label="Longitud" type="number" step="any" min={-180} max={180} required />
          <button className="button" type="submit">Guardar base</button>
        </form>
      </Panel>}
    </>}
    {!busy && page === 'plan' && <>
      {!plan && stale && <Notice text="Cambió la configuración del plan. Recalcula para habilitar la descarga." />}
      {plan && <>{quickNotice && <Notice text={quickNotice} />}<Results plan={plan} api={api} vans={vans} drivers={drivers} rides={rides} terminals={terminals}
        customers={customers} reviews={reviews} demo={demo} onAdjust={demo ? () => {
          if (!advanced.current) return
          advanced.current.open = true
          advanced.current.querySelector('summary')?.focus()
          advanced.current.scrollIntoView({ block: 'start' })
        } : undefined} /></>}
      {demo ? <details className="dispatch-advanced" ref={advanced}>
        <summary><Settings2 size={18} /><span>Ajustar planificación</span></summary>
        <div className="stack">{dateControl}{planningTools}</div>
      </details> : planningTools}
      {!plan && <Panel title="Mapa de planificación" className={demo ? 'dispatch-city' : ''}>
        {demo && !selectedBatches.length && <div className="actions"><button className="button primary" onClick={() => setPage('import')}>Cargar nómina</button></div>}
        <Suspense fallback={<div className="empty">Cargando mapa…</div>}><RouteMap demo={demo && !hostedDemo} pins={[]} /></Suspense></Panel>}
    </>}
    {hostedDemo && <footer className="actions"><small>Los resultados pueden desaparecer al cerrar sesión o reiniciar el servidor.</small>
      <button className="button compact" onClick={() => void resetDemo()}>Restablecer demo</button></footer>}
  </Shell>
}
