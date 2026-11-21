import { type Api, type Depot, type Driver, type Matrix, type Plan, type Point, type Preparation, type Review, type Ride, type Terminal, type Van } from './api'

export type PlanInputs = { date: string; matrix?: Matrix; requestIds: string[]; origins: Record<string, Point> }

export function overlappingRosters(rides: Ride[], date: string) {
  const seen = new Map<string, string>()
  return rides.some(ride => {
    if (ride.excluded || ride.direction !== 'inbound' || ride.service_date !== date || !ride.employee_code) return false
    const key = ride.customer_id + ':' + ride.employee_code.trim().toUpperCase()
    const previous = seen.get(key)
    seen.set(key, ride.batch_id)
    return previous !== undefined && previous !== ride.batch_id
  })
}

export function rosterDates(rides: Ride[]) {
  return [...new Set(rides.filter(ride => ride.direction === 'inbound' && !ride.excluded)
    .map(ride => ride.service_date).filter((date): date is string => !!date))]
}

export async function quickPlan({ api, rides, date, vans, drivers, terminals, roadAvailable, demo, onReviews }: {
  api: Api; rides: Ride[]; date: string; vans: Van[]; drivers: Driver[]; terminals: Terminal[];
  roadAvailable: boolean; demo?: boolean; onReviews: (reviews: Record<string, Review>) => void
}): Promise<{ plan?: Plan; inputs?: PlanInputs; notice: string }> {
  const inbound = rides.filter(ride => ride.direction === 'inbound' && !ride.excluded)
  const valid = inbound.filter(ride => ride.service_date === date && ride.validation_status === 'valid')
  const withTerminal = valid.filter(ride => terminals.some(terminal => terminal.id === ride.terminal_id &&
    terminal.latitude != null && terminal.longitude != null))
  if (withTerminal.length > 60) return { notice: 'Hay más de 60 recogidas por verificar. Selecciona un subconjunto en Planificación.' }
  const reviews = withTerminal.length
    ? await api.json<Record<string, Review>>('/v5/operator/locations/prepare', 'POST', withTerminal.map(ride => ride.id))
    : {}
  onReviews(reviews)
  const ready = withTerminal.filter(ride => reviews[ride.id]?.status === 'approved')
  const outstanding = [
    [inbound.length - valid.length, 'solicitudes pendientes de validación o fecha'],
    [valid.length - withTerminal.length, 'solicitudes sin terminal con coordenadas'],
    [withTerminal.length - ready.length, 'recogidas sin ubicación aprobada'],
  ].filter(([count]) => count).map(([count, label]) => count + ' ' + label)
  if (!ready.length || outstanding.length) return { notice: [...outstanding, 'Completa la preparación antes de ponderar toda la nómina.'].join(' · ') }
  if (ready.length > 60) return { notice: 'Hay más de 60 recogidas listas. Selecciona un subconjunto en Planificación.' }
  const crews = vans.filter(van => van.available && drivers.some(driver => driver.available && driver.vehicle_id === van.id))
  const config = await api.json<Preparation>('/v5/operator/preparation')
  const depots = await api.json<Depot[]>('/depots')
  const depot = depots.find(d => d.id === config.depot_id) ?? (depots.length === 1 ? depots[0] : undefined)
  if (!depot) return { notice: 'Selecciona la base de salida en Preparación antes de calcular.' }
  const catalog = await api.json<Matrix[]>('/v4/geo/matrix-catalog')
  const requestIds = ready.map(ride => ride.id)
  const keys = new Set(requestIds.map(id => 'pickup:' + id))
  function matchingOrigins(matrix: Matrix) {
    const ids = matrix.location_keys.filter(key => key.startsWith('origin:')).map(key => key.slice(7))
    return ids.length === 3 && ids.every(id => crews.some(van => van.id === id))
  }
  const reusable = catalog.filter(matrix => (matrix.mode === 'static_road' || (demo && matrix.simulation)) && matchingOrigins(matrix))
  let matrix = reusable.find(matrix => {
    const pickups = matrix.location_keys.filter(key => key.startsWith('pickup:'))
    const terminalKeys = [...new Set(ready.map(ride => 'terminal:' + ride.terminal_id))]
    return (!config.matrix_id || matrix.id === config.matrix_id) && terminalKeys.every(key => matrix.location_keys.includes(key))
      && pickups.length === keys.size && pickups.every(key => keys.has(key))
  })
  if (config.matrix_id && !matrix) return { notice: 'La matriz seleccionada no corresponde a esta nómina y flota. Actualiza la selección en Preparación.' }
  let origins: Record<string, Point> = {}
  if (matrix) {
    origins = await api.json<Record<string, Point>>('/v4/geo/matrices/' + matrix.id + '/origins')
    if (Object.values(origins).some(p => p.latitude !== depot.latitude || p.longitude !== depot.longitude)) {
      if (config.matrix_id) return { notice: 'Los orígenes de la matriz no corresponden a la base seleccionada.' }
      matrix = undefined
    }
  }
  if (!matrix) {
    const blockers = []
    if (crews.length !== 3) blockers.push('Configura tres vans disponibles con sus conductores, o selecciona la flota manualmente.')
    if (!roadAvailable) blockers.push('Falta un proveedor vial local autorizado o una matriz compatible.')
    if (blockers.length) return { notice: [...outstanding, ...blockers].join(' · ') }
    const { latitude, longitude } = depot
    origins = Object.fromEntries(crews.map(van => [van.id, { latitude, longitude }]))
    matrix = await api.json<Matrix>('/v4/geo/matrices', 'POST', { request_ids: requestIds, vehicle_origins: origins })
  }
  if (matrix.simulation && !demo) return { notice: 'La matriz obtenida es una simulación. Úsala únicamente desde Planificación manual.' }
  const plan = await api.json<Plan>('/v3/plans/preview', 'POST', {
    ...config.rules, service_date: date, original_batch_ids: [...new Set(ready.map(ride => ride.batch_id))],
    request_ids: requestIds, matrix_id: matrix.id, vehicle_ids: Object.keys(origins),
    vehicle_origins: Object.fromEntries(Object.entries(origins).map(([id, point]) => [id, { ...point, source: 'configuración operativa' }])),
  })
  return { plan, inputs: { date, matrix, requestIds, origins }, notice: outstanding.join(' · ') }
}
