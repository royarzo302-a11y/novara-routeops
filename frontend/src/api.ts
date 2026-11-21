export type Customer = { id: string; name: string }
export type Point = { latitude: number; longitude: number }
export type Depot = Point & { id: string; name: string }
export type Terminal = { id: string; customer_id: string; name: string } & Partial<Point>
export type Van = { id: string; identifier: string; capacity: number; available: boolean; allowed_communes: string[] }
export type Driver = { id: string; identifier: string; vehicle_id: string; available: boolean; available_from: string; available_until: string; max_trips: number }
export type Batch = { id: string; customer_id: string; expected_service_date: string | null; archive_date: string | null; role: string; records: number; pending_review: number; unclassified_rows: number; service_dates?: string[]; created_at?: string }
export type Ride = {
  id: string; batch_id: string; customer_id: string; name: string | null; employee_code: string | null;
  address: string | null; commune: string | null; work_time: string | null; end_time: string | null;
  service_date: string | null; terminal_id: string | null; direction: string; excluded: boolean;
  validation_status: string; issues: { code: string; message: string; field: string | null }[];
}
export type Ingestion = { batch: Batch; requests: Ride[] }
export type Review = {
  status: string; address: { normalized_address: string; issues: string[] } | null;
  candidates: (Point & { id: string; context_match: boolean })[]; approved_point: Point | null;
}
export type Matrix = { id: string; provider: string; map_version: string; mode: string; simulation: boolean; generated_at: string; location_keys: string[]; unreachable_pairs: number }
export type Stop = { request_id: string; sequence: number; pickup_at: string; onboard_seconds: number }
export type Trip = { vehicle_id: string; driver_id: string; customer_id: string; terminal_id: string; trip_number: number; arrival_at: string; dispatch_at: string; duration_seconds: number; stops: Stop[]; empty_travel_seconds: number; route_meters: number }
export type Plan = { service_date: string; status: string; simulation: boolean | null; matrix_mode: string | null; matrix_id: string | null; matrix_source?: string | null; trips: Trip[]; unassigned: { request_id: string; reason: string }[] }
export type Session = { authenticated: boolean; geocoder_available: boolean; road_available: boolean; demo?: boolean }
export type PlanningRules = { preparation_seconds: number; boarding_seconds: number; arrival_buffer_minutes: number; max_early_arrival_minutes: number; max_onboard_minutes: number; search_seconds: number }
export type Preparation = { depot_id: string | null; terminal_ids: Record<string, string>; matrix_id: string | null; rules: PlanningRules; locked: boolean }

const root = '/api'
export const hostedDemo = import.meta.env.VITE_NOVARA_HOSTED_DEMO === '1'
function message(status: number, payload?: { detail?: unknown }) {
  if (status === 401 && !hostedDemo) return 'El token no es válido. Revisa el valor de NOVARA_GEO_TOKEN en el archivo .env.'
  if (typeof payload?.detail === 'string') return payload.detail
  return 'La API devolvió un error (' + status + '). Revisa los campos e inténtalo de nuevo.'
}

export function apiClient(token: string) {
  const headers = token ? { Authorization: 'Bearer ' + token } : undefined
  function saveFile(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function request(path: string, method = 'GET', body?: unknown) {
    let response: Response
    try {
      response = await fetch(root + path, {
        method, headers: { ...headers, ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined, cache: 'no-store',
      })
    } catch { throw new Error('No hay conexión con el servidor. Reintenta en un momento.') }
    if (!response.ok) throw new Error(message(response.status, await response.json().catch(() => null)))
    return response
  }
  return {
    async sample() {
      const response = await request(hostedDemo ? '/demo/rosters/rapida' : '/v5/operator/demo/roster')
      return new File([await response.blob()], 'nomina-demo-santiago.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    },
    async downloadRoster(slug: 'gran-america' | 'lo-blanco') {
      const response = await request('/demo/rosters/' + slug)
      saveFile(await response.blob(), 'demo-' + slug + '.xlsx')
    },
    async json<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
      const response = await request(path, method, body)
      return response.json()
    },
    async download(plan: Plan) {
      const response = await request('/v5/operator/plans/export', 'POST', plan)
      saveFile(await response.blob(), 'novara-vista-previa.xlsx')
    },
    upload(data: FormData, progress: (value: number) => void, automatic = false) {
      return new Promise<Ingestion>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', root + (automatic ? '/v5/operator/ingestions/automatic' : '/v2/ingestions'))
        if (headers) xhr.setRequestHeader('Authorization', headers.Authorization)
        xhr.responseType = 'json'
        xhr.timeout = 120000
        xhr.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)) }
        xhr.onload = () => xhr.status === 201 ? resolve(xhr.response) : reject(new Error(message(xhr.status, xhr.response)))
        xhr.onerror = xhr.ontimeout = () => reject(new Error('La carga no terminó. Comprueba la conexión antes de reintentar.'))
        xhr.send(data)
      })
    },
  }
}
export type Api = ReturnType<typeof apiClient>
export const clock = (value?: string | null) => value?.split('T').at(-1)?.slice(0, 5) || '—'
export const labels: Record<string, string> = {
  complete: 'Completa', partial: 'Parcial', infeasible: 'Sin viajes factibles', search_limit: 'Límite de búsqueda',
  valid: 'Válida', pending_review: 'Pendiente', excluded: 'Excluida', pending: 'Sin resolver', approved: 'Aprobada',
  review_required: 'Requiere revisión', different_date: 'Otra fecha de servicio', unsupported_direction: 'Sentido aún no admitido',
  missing_schedule: 'Sin horario de ingreso', missing_pickup: 'Recogida fuera de la matriz o sin aprobar', missing_terminal: 'Terminal sin coordenadas',
  duplicate_identity: 'Identidad duplicada', no_compatible_vehicle: 'No hay van compatible disponible', unreachable_location: 'Ubicación inaccesible',
  joint_constraints: 'Restricciones conjuntas de flota, zona u horario',
  incomplete_address: 'Dirección incompleta', ambiguous_address: 'Dirección ambigua', missing_context: 'Falta contexto geográfico',
}
