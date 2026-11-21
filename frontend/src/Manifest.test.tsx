import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ImportPanel, ReviewTable } from './Manifest'
import type { Api, Ride } from './api'

afterEach(cleanup)
const customers = [{ id: 'gran_america', name: 'Gran América' }]
const fixture: Ride = {
  id: 'fixture', batch_id: 'batch', customer_id: 'gran_america', name: 'Pasajero de prueba',
  employee_code: 'TEST-1', address: 'Calle ficticia 101', commune: 'Zona de prueba', work_time: '05:00:00',
  end_time: null, service_date: '2026-11-20', terminal_id: null, direction: 'inbound',
  validation_status: 'pending_review', excluded: false,
  issues: [{ code: 'source_fixture', message: 'Verificar con la fuente', field: 'address' }],
}

test('validates dropped files and reports the upload result', async () => {
  const upload = vi.fn(async (_data: FormData, progress: (value: number) => void, _automatic: boolean) => {
    progress(100); return { batch: { records: 1, pending_review: 1, unclassified_rows: 0 }, requests: [] }
  })
  const imported = vi.fn()
  render(<ImportPanel api={{ upload } as unknown as Api} customers={customers} terminals={[]} date="2026-11-20" onImport={imported} onTerminals={vi.fn()} />)
  const input = screen.getByLabelText('Seleccionar archivo Excel')
  fireEvent.change(input, { target: { files: [new File(['x'], 'test.csv')] } })
  expect(screen.getByRole('alert').textContent).toContain('.xlsx')
  const file = new File(['x'], 'test.xlsx')
  fireEvent.drop(input.closest('label')!, { dataTransfer: { files: [file] } })
  await waitFor(() => expect(imported).toHaveBeenCalledTimes(1))
  expect(upload.mock.calls[0][0].get('file')).toBe(file)
  expect(upload.mock.calls[0][2]).toBe(true)
  expect(screen.getByText(/1 solicitudes importadas/)).toBeTruthy()
})

test('sends only edited fields and explicit confirmations', async () => {
  const json = vi.fn(async () => ({ ...fixture, commune: 'Zona nueva' }))
  const saved = vi.fn()
  render(<ReviewTable rides={[fixture]} customers={customers} terminals={[]} api={{ json } as unknown as Api}
    onSaved={saved} onLocate={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
  expect((screen.getByRole('checkbox', { name: 'Dirección' }) as HTMLInputElement).checked).toBe(false)
  fireEvent.change(screen.getByLabelText('Comuna', { exact: true }), { target: { value: 'Zona nueva' } })
  fireEvent.change(screen.getByLabelText('Motivo de revisión'), { target: { value: 'Verificación ficticia' } })
  fireEvent.click(screen.getByRole('button', { name: 'Guardar revisión' }))
  await waitFor(() => expect(saved).toHaveBeenCalled())
  expect(json).toHaveBeenCalledWith('/v2/requests/fixture', 'PATCH', {
    changes: { commune: 'Zona nueva' }, confirm_fields: [], reason: 'Verificación ficticia',
  })
})
