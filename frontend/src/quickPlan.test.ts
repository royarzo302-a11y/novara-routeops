import { expect, test, vi } from 'vitest'
import { quickPlan } from './quickPlan'
import type { Api, Driver, Ride } from './api'

const ride = { id: 'r1', batch_id: 'b1', customer_id: 'gran_america', employee_code: 'TEST-1', direction: 'inbound', excluded: false, service_date: '2026-11-21', validation_status: 'valid', terminal_id: 't1' } as Ride
const vans = [1, 2, 3].map(i => ({ id: 'v' + i, identifier: 'Van ' + i, available: true, capacity: 12, allowed_communes: [] }))
const drivers = vans.map(v => ({ vehicle_id: v.id, available: true })) as Driver[]
const terminal = { id: 't1', customer_id: 'gran_america', name: 'Terminal', latitude: -33.4, longitude: -70.6 }
const review = { status: 'approved', approved_point: { latitude: -33.41, longitude: -70.61 } }
const rules = { max_onboard_minutes: 42, boarding_seconds: 90 }
const bases = [1, 2, 3].map(i => ({ id: 'base' + i, latitude: -33.4 - i / 100, longitude: -70.6 }))

test('uses the saved base among several and forwards the saved rules', async () => {
  const json = vi.fn(async (path: string, _method?: string, body?: unknown) => {
    if (path.endsWith('/locations/prepare')) return { r1: review }
    if (path.endsWith('/preparation')) return { depot_id: 'base2', rules, terminal_ids: {}, matrix_id: null }
    if (path === '/depots') return bases
    if (path.endsWith('/matrix-catalog')) return []
    if (path.endsWith('/matrices')) return { id: 'matrix', simulation: false }
    if (path.endsWith('/preview')) return { status: 'complete', ...body as object }
    throw new Error('Unexpected path: ' + path)
  })
  const result = await quickPlan({ api: { json } as unknown as Api, rides: [ride], date: '2026-11-21', vans, drivers, terminals: [terminal], roadAvailable: true, onReviews: vi.fn() })
  expect(result.plan?.status).toBe('complete')
  expect(result.inputs?.origins.v1).toEqual({ latitude: bases[1].latitude, longitude: bases[1].longitude })
  const preview = json.mock.calls.find(([path]) => path.endsWith('/preview'))![2]
  expect(preview).toMatchObject(rules)
})

test('blocks a partial roster instead of silently dropping missing destinations', async () => {
  const json = vi.fn(async () => ({ r1: review }))
  const result = await quickPlan({ api: { json } as unknown as Api, rides: [ride, { ...ride, id: 'r2', terminal_id: null }], date: '2026-11-21', vans, drivers, terminals: [terminal], roadAvailable: true, onReviews: vi.fn() })
  expect(result.plan).toBeUndefined()
  expect(result.notice).toContain('1 solicitudes sin terminal')
  expect(json.mock.calls).toHaveLength(1)
})
