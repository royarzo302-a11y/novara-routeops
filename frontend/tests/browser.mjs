import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { chromium } from 'playwright-core'

const url = process.env.NOVARA_TEST_UI ?? 'http://localhost:5173'
const token = process.env.NOVARA_BROWSER_TEST_TOKEN
const chrome = process.env.CHROME_BIN
const output = process.env.NOVARA_BROWSER_ARTIFACTS ?? '/tmp/novara-ui-evidence'
assert(token && chrome, 'Set NOVARA_BROWSER_TEST_TOKEN and CHROME_BIN')
await mkdir(output, { recursive: true })
const fixture = output + '/nomina-ficticia.xlsx'
const excel = spawnSync('../.venv/bin/python', ['-c', `
import sys
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = "Acercamiento"
ws.append(["Fecha", "Hora Inicio", "Código", "Nombres", "Dirección", "Comuna", "Teléfono"])
ws.append(["2026-11-20", "04:30", "SIM-001", "Pasajero ficticio", "Calle Ficticia 101", None, "970000001"])
wb.save(sys.argv[1])
`, fixture])
assert.equal(excel.status, 0, excel.stderr.toString())
const browser = await chromium.launch({ executablePath: chrome, headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
  const unexpectedRequests = []
  const browserErrors = []
  page.on('request', request => {
    if (new URL(request.url()).origin !== new URL(url).origin && !request.url().startsWith('blob:')) unexpectedRequests.push(true)
  })
  page.on('pageerror', error => browserErrors.push(error.name))
  await page.goto(url)
  await page.waitForSelector('h1')
  await page.keyboard.press('Tab')
  assert(await page.evaluate(() => document.activeElement.matches(':focus-visible')))
  await page.screenshot({ path: output + '/desktop-locked.png' })
  await page.getByLabel('Token de operador').fill('fixture-invalid-token')
  await page.getByRole('button', { name: 'Conectar sesión' }).click()
  await page.getByRole('alert').getByText(/token no es válido/).waitFor()
  await page.getByLabel('Token de operador').fill('NOVARA_GEO_TOKEN=' + token)
  await page.getByRole('button', { name: 'Conectar sesión' }).click()
  await page.getByRole('button', { name: 'Cerrar sesión' }).waitFor()
  await page.getByRole('button', { name: 'Importar Excel' }).click()
  await page.getByLabel('Importación manual').check()
  await page.getByLabel('Fecha operativa').fill('2026-11-20')
  await page.getByLabel('Fecha esperada').fill('2026-11-20')
  await page.getByText('Registrar un terminal para este cliente').click()
  await page.getByLabel('Nombre de terminal').fill('Terminal ficticio')
  await page.getByLabel('Latitud del terminal').fill('-33.45')
  await page.getByLabel('Longitud del terminal').fill('-70.61')
  await page.getByRole('button', { name: 'Guardar terminal' }).click()
  await page.waitForFunction(() => document.querySelector('select[name=terminal_id]')?.value)
  await page.getByLabel('Seleccionar archivo Excel').setInputFiles(fixture)
  await page.getByRole('button', { name: 'Procesar Excel' }).click()
  await page.getByText(/1 solicitudes importadas/).waitFor()
  await page.getByRole('button', { name: 'Abrir solicitudes' }).click()
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  await page.getByRole('textbox', { name: 'Comuna', exact: true }).fill('Comuna de prueba')
  await page.getByLabel('Motivo de revisión').fill('Corrección de prueba')
  await page.getByRole('button', { name: 'Guardar revisión' }).click()
  await page.getByText('Válida', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Ubicación', exact: true }).click()
  await page.getByRole('button', { name: 'Buscar candidatos' }).click()
  await page.getByText('Requiere revisión', { exact: true }).waitFor()
  await page.getByLabel('Candidato', { exact: true }).selectOption('fixture-1')
  await page.getByLabel('Motivo de aprobación').fill('Ubicación ficticia confirmada')
  await page.getByRole('button', { name: 'Aprobar ubicación' }).click()
  await page.getByText('Aprobada', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Flota', exact: true }).click()
  const vanForm = page.getByRole('region', { name: 'Registrar van' })
  const driverForm = page.getByRole('region', { name: 'Asignar conductor' })
  for (let i = 1; i <= 3; i++) {
    await vanForm.getByLabel('Identificador de van', { exact: true }).fill('Van ficticia ' + i)
    await page.getByRole('button', { name: 'Registrar van' }).click()
    await page.getByText('Van guardada.', { exact: true }).waitFor()
    const option = driverForm.getByLabel('Van asignada').locator('option').filter({ hasText: 'Van ficticia ' + i })
    await driverForm.getByLabel('Van asignada').selectOption(await option.getAttribute('value'))
    await driverForm.getByLabel('Identificador de conductor').fill('Conductor ficticio ' + i)
    await page.getByRole('button', { name: 'Registrar conductor' }).click()
    await page.getByText('Conductor guardado.', { exact: true }).waitFor()
  }
  await page.getByRole('button', { name: 'Planificación', exact: true }).click()
  await page.getByRole('checkbox', { name: /Pasajero ficticio/ }).check()
  for (const input of await page.getByLabel('Latitud de salida').all()) await input.fill('-33.44')
  for (const input of await page.getByLabel('Longitud de salida').all()) await input.fill('-70.61')
  await page.getByRole('button', { name: 'Generar matriz' }).click()
  await page.getByText(/Simulación.*tramos inaccesibles/).waitFor()
  await page.getByRole('button', { name: 'Ejecutar planificación' }).click()
  await page.getByText('Vista previa de la jornada', { exact: true }).waitFor()
  await page.getByText(/Completa · Simulación/).waitFor()
  await page.getByText('Conexiones ilustrativas · Sin geometría vial', { exact: true }).waitFor()
  await page.locator('.pin-icon').first().waitFor()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Descargar Excel' }).click()
  const file = await download
  assert.equal(file.suggestedFilename(), 'novara-vista-previa.xlsx')
  await file.saveAs(output + '/plan-ficticio.xlsx')
  await page.locator('#plan-results').evaluate(node => node.scrollIntoView({ block: 'start' }))
  await page.screenshot({ path: output + '/desktop-plan.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: 'Resumen', exact: true }).click()
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.screenshot({ path: output + '/mobile-dashboard.png', fullPage: true })
  assert.deepEqual(unexpectedRequests, [])
  assert.deepEqual(browserErrors, [])
  assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0)
  await page.getByRole('button', { name: 'Planificación', exact: true }).click()
  await page.getByText('Vista previa de la jornada', { exact: true }).waitFor()
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.getByLabel('Matriz disponible').selectOption({ index: 1 })
  await page.route('**/api/v3/plans/preview', async route => {
    const response = await route.fetch()
    const plan = await response.json()
    plan.status = 'partial'
    plan.unassigned = [{ request_id: 'sim-segunda', reason: 'unreachable_location' }]
    await route.fulfill({ response, json: plan })
  })
  await page.getByRole('button', { name: 'Ejecutar planificación' }).click()
  await page.getByText(/Parcial · Simulación/).waitFor()
  await page.getByText('Ubicación inaccesible').waitFor()
  await page.locator('#plan-results').screenshot({ path: output + '/mobile-partial.png' })
  await page.getByRole('button', { name: 'Cerrar sesión' }).click()
  await page.getByLabel('Token de operador').waitFor()
  assert.equal(await page.getByText('Pasajero ficticio', { exact: true }).count(), 0)
  console.log('Browser flow passed: access, upload, review, geocoding, fleet, matrix, routes, map, Excel.')
} finally {
  await browser.close()
}
