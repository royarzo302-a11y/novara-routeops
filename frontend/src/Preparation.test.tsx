import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { PreparationPanel } from './Preparation'
import type { Api, Driver, Preparation, Ride } from './api'

afterEach(cleanup)
const config: Preparation = {
  depot_id: 'base1', terminal_ids: { gran_america: 'terminal' }, matrix_id: null, locked: false,
  rules: { preparation_seconds: 600, boarding_seconds: 60, arrival_buffer_minutes: 10, max_early_arrival_minutes: 30, max_onboard_minutes: 60, search_seconds: 3 },
}
function setup(locked = false) {
  const json = vi.fn(async (path: string, method?: string, body?: unknown) => {
    if (method === 'PUT') return { ...body as object, locked }
    if (path.endsWith('/preparation')) return { ...config, locked }
    if (path === '/depots') return [{ id: 'base1', name: 'Base uno' }, { id: 'base2', name: 'Base dos' }]
    return []
  })
  const vans = [1, 2, 3].map(i => ({ id: 'v' + i, identifier: 'Van ' + i, capacity: 12, available: true, allowed_communes: [] }))
  const calculate = vi.fn()
  render(<PreparationPanel api={{ json } as unknown as Api} customers={[{ id: 'gran_america', name: 'Gran América' }]}
    terminals={[{ id: 'terminal', name: 'Terminal', customer_id: 'gran_america', latitude: -33.4, longitude: -70.6 }]}
    vans={vans} drivers={vans.map(v => ({ vehicle_id: v.id, available: true })) as Driver[]}
    rides={[{ id: 'ride', terminal_id: 'terminal', direction: 'inbound', excluded: false, service_date: '2026-11-21', validation_status: 'valid' } as Ride]}
    reviews={{}} date="2026-11-21" session={{ authenticated: true, road_available: true, geocoder_available: false }}
    onTerminals={vi.fn()} onLocations={vi.fn(async () => {})} onChange={vi.fn()} onReview={vi.fn()}
    onGeo={vi.fn()} onFleet={vi.fn()} onImport={vi.fn()} onCalculate={calculate} calculating={false} />)
  return { json, calculate }
}

test('requires saving edited factors before calculating and persists the explicit base', async () => {
  const { json, calculate } = setup()
  await screen.findByRole('button', { name: 'Guardar factores' })
  const button = screen.getByRole('button', { name: 'Ponderar rutas' }) as HTMLButtonElement
  expect(button.disabled).toBe(false)
  fireEvent.change(screen.getByLabelText('Base de salida compartida'), { target: { value: 'base2' } })
  fireEvent.change(screen.getByLabelText('Máximo a bordo (min)'), { target: { value: '45' } })
  expect(button.disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Guardar factores' }))
  await waitFor(() => expect(button.disabled).toBe(false))
  expect(json).toHaveBeenCalledWith('/v5/operator/preparation', 'PUT', expect.objectContaining({
    depot_id: 'base2', rules: expect.objectContaining({ max_onboard_minutes: 45 }),
  }))
  fireEvent.click(button)
  expect(calculate).toHaveBeenCalledOnce()
})

test('shows fixed demo factors without edit or registration actions', async () => {
  setup(true)
  await screen.findByText('Factores fijos')
  expect((screen.getByLabelText('Máximo a bordo (min)') as HTMLInputElement).closest('fieldset')!.disabled).toBe(true)
  expect(screen.queryByRole('button', { name: 'Guardar factores' })).toBeNull()
  expect(screen.queryByText('Registrar un terminal o una base')).toBeNull()
})
