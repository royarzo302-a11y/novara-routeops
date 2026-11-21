import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chromium } from 'playwright-core'

assert(process.env.CHROME_BIN, 'Define CHROME_BIN')
const url = process.env.NOVARA_TEST_UI ?? 'http://localhost:5174/'
const evidence = process.env.NOVARA_UX_EVIDENCE
async function waitForMap(page, container = '.map-view') {
  if (process.env.NOVARA_VERIFY_LIVE_MAP !== '1') return
  await page.waitForFunction(selector => {
    const tiles = [...document.querySelectorAll(selector + ' .leaflet-tile')]
    return tiles.length > 0 && tiles.every(tile => tile.classList.contains('leaflet-tile-loaded'))
  }, container)
}
const chrome = await chromium.launch({ executablePath: process.env.CHROME_BIN })
try {
  const page = await chrome.newPage({ acceptDownloads: true, viewport: { width: 1440, height: 900 } })
  await page.route('**/v5/operator/demo/roster', async route => {
    const response = await route.fetch({ url: route.request().url() + '?seed=0' })
    await route.fulfill({ response })
  })
  await page.goto(url)
  if (process.env.NOVARA_VERIFY_LIVE_MAP === '1') {
    await waitForMap(page)
    await page.getByRole('link', { name: 'Stadia Maps' }).waitFor()
    await page.getByRole('link', { name: 'OpenStreetMap' }).waitFor()
  }
  await page.getByRole('heading', { name: 'Planifica tus rutas' }).waitFor()
  if (evidence) await page.screenshot({ path: evidence + '/desktop-intake.png', animations: 'disabled' })
  const fileInput = page.getByLabel('Seleccionar archivo Excel')
  await fileInput.focus()
  assert(await fileInput.evaluate(input => input.matches(':focus-visible')))
  await fileInput.setInputFiles({ name: 'ejemplo.csv', mimeType: 'text/csv', buffer: Buffer.from('fixture') })
  await page.getByRole('alert').getByText(/Selecciona un Excel/).waitFor()
  const blocked = await chrome.newPage()
  await blocked.route('https://tiles.stadiamaps.com/**', route => route.fulfill({
    status: 403,
    headers: { 'Access-Control-Allow-Origin': '*' },
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lwoAAAAASUVORK5CYII=', 'base64'),
  }))
  await blocked.goto(url)
  await blocked.getByText(/Fondo cartográfico no disponible/).waitFor()
  assert.equal(await blocked.locator('.leaflet-tile-loaded').count(), 0)
  await blocked.close()
  let release
  const hold = new Promise(resolve => { release = resolve })
  await page.route('**/v3/plans/preview', async route => { await hold; await route.continue() }, { times: 1 })
  await page.getByRole('button', { name: 'Probar con nómina incluida' }).click()
  await page.getByRole('button', { name: 'Ponderar rutas' }).click()
  await page.getByText('Calculando rutas…', { exact: true }).waitFor()
  if (evidence) await page.screenshot({ path: evidence + '/desktop-loading.png', animations: 'disabled' })
  release()
  const results = page.locator('#plan-results')
  const selection = page.getByRole('region', { name: 'Solicitudes para planificar' })
  const download = page.getByRole('button', { name: 'Descargar Excel' })
  await results.getByText('8 recogidas', { exact: true }).waitFor()
  await results.getByText('2 viajes', { exact: true }).waitFor()
  await results.locator('.leaflet-container').waitFor()
  if (evidence) await waitForMap(page, '#plan-results')
  if (evidence) await page.screenshot({ path: evidence + '/desktop-results.png', animations: 'disabled' })
  assert.equal(await selection.isVisible(), false)
  const legend = results.locator('[aria-label="Vans en el mapa"]')
  await legend.getByRole('button', { name: /Van / }).first().click()
  assert.equal(await results.locator('.trip-list details').count(), 1)
  await legend.getByRole('button', { name: 'Todas' }).click()
  await results.getByRole('button', { name: /Pasajero de prueba/ }).first().click()
  await page.locator('.leaflet-popup-content').getByText(/Pasajero de prueba/).waitFor()
  if (process.env.NOVARA_DEMO_SCREENSHOT) {
    await results.scrollIntoViewIfNeeded()
    await page.screenshot({ path: process.env.NOVARA_DEMO_SCREENSHOT })
  }

  await results.getByRole('button', { name: 'Ajustar plan' }).click()
  await selection.getByText('8 seleccionadas de 8 solicitudes válidas.').waitFor()
  assert(await page.getByLabel('Matriz disponible').inputValue())
  await selection.getByRole('checkbox', { name: /Pasajero de prueba 8/ }).uncheck()
  await page.getByText('Cambió la configuración del plan. Recalcula para habilitar la descarga.').waitFor()
  assert.equal(await results.count(), 0)
  assert.equal(await download.count(), 0)
  await page.getByRole('button', { name: 'Recalcular rutas' }).click()
  await results.getByText('7 recogidas', { exact: true }).waitFor()
  const downloading = page.waitForEvent('download')
  await download.click()
  const file = await downloading
  const workbook = spawnSync('../.venv/bin/python', ['-c', `
import sys
from openpyxl import load_workbook
with open(sys.argv[1], "rb") as file:
    book = load_workbook(file, read_only=True)
    rows = list(book["Vista previa"].values)
    assert len(rows[3:]) == 7
    names = {row[11] for row in rows[3:]}
    assert "Pasajero de prueba 8" not in names
    assert all(row[11] and row[12] and row[13] and row[14] and row[15] for row in rows[3:])
`, await file.path()])
  assert.equal(workbook.status, 0, workbook.stderr.toString())

  await page.getByLabel('Latitud de salida').first().fill('-33.44')
  assert.equal(await download.count(), 0)
  await page.getByRole('button', { name: 'Importar Excel', exact: true }).click()
  await page.getByRole('button', { name: 'Probar con nómina incluida' }).click()
  await page.getByRole('button', { name: 'Ponderar rutas' }).click()
  await results.getByText('8 recogidas', { exact: true }).waitFor()
  await results.getByRole('button', { name: 'Ajustar plan' }).click()
  const lots = page.getByRole('region', { name: 'Lotes de trabajo' }).getByRole('checkbox')
  await lots.nth(1).click()
  await page.getByText(/Hay personas repetidas en lotes originales/).waitFor()
  assert.equal(await download.count(), 0)
  assert(await page.getByRole('button', { name: 'Recalcular rutas' }).isDisabled())
  const mobile = await chrome.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' })
  await mobile.goto(url)
  await mobile.getByRole('heading', { name: 'Planifica tus rutas' }).waitFor()
  await mobile.getByRole('button', { name: 'Probar con nómina incluida' }).waitFor()
  if (evidence) await waitForMap(mobile)
  assert(await mobile.evaluate(() => document.documentElement.scrollWidth === innerWidth))
  if (evidence) await mobile.screenshot({ path: evidence + '/mobile-intake.png', animations: 'disabled' })
  await mobile.route('**/v3/plans/preview', async route => {
    const response = await route.fetch()
    const plan = await response.json()
    plan.status = 'partial'
    plan.unassigned = [{ request_id: plan.trips[0].stops.pop().request_id, reason: 'joint_constraints' }]
    await route.fulfill({ response, json: plan })
  }, { times: 1 })
  await mobile.getByRole('button', { name: 'Probar con nómina incluida' }).click()
  await mobile.getByRole('button', { name: 'Ponderar rutas' }).click()
  await mobile.getByText(/Parcial · Simulación/).waitFor()
  await mobile.getByRole('link', { name: /1 sin asignar/ }).waitFor()
  await mobile.getByText('Restricciones conjuntas de flota, zona u horario').waitFor()
  assert(await mobile.evaluate(() => document.documentElement.scrollWidth === innerWidth))
  if (evidence) {
    await mobile.locator('#plan-results .leaflet-container').waitFor()
    await waitForMap(mobile, '#plan-results')
    await mobile.screenshot({ path: evidence + '/mobile-partial.png', animations: 'disabled', fullPage: true })
  }
  const imported = mobile.waitForResponse(response => response.url().endsWith('/v5/operator/ingestions/automatic')
    && response.request().method() === 'POST' && response.ok())
  await mobile.getByRole('button', { name: 'Simular otra jornada' }).click()
  const next = await (await imported).json()
  assert(new Set(next.requests.map(ride => ride.commune)).size >= 5)
  await mobile.getByRole('button', { name: 'Ponderar rutas' }).click()
  await mobile.getByRole('heading', { name: 'Rutas de la jornada' }).waitFor()
  await mobile.getByRole('link', { name: 'OSRM / FOSSGIS' }).waitFor()
  await mobile.close()
  console.log('Demo verificada: 8 recogidas iniciales, invalidación y Excel con las 7 restantes.')
} finally {
  await chrome.close()
}
