import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright-core'

const base = process.env.NOVARA_TEST_UI ?? 'http://127.0.0.1:8174'
const password = process.env.NOVARA_DEMO_PASSWORD
assert(password && process.env.CHROME_BIN, 'Define NOVARA_DEMO_PASSWORD y CHROME_BIN.')
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN })
try {
  const page = await browser.newPage({ acceptDownloads: true })
  const external = []
  page.on('request', req => {
    if (/^https?:/.test(req.url()) && new URL(req.url()).origin !== new URL(base).origin) external.push(new URL(req.url()).hostname)
  })
  await page.goto(base)
  await page.getByLabel('Clave de la demo').fill(password)
  await page.getByRole('button', { name: 'Entrar a la demo' }).click()
  await page.getByRole('heading', { name: 'Planifica tus rutas' }).waitFor()
  await page.getByRole('button', { name: 'Preparación', exact: true }).click()
  await page.getByText('Factores fijos', { exact: true }).waitFor()
  assert(await page.getByLabel('Base de salida compartida').isDisabled())
  assert(await page.getByLabel('Máximo a bordo (min)').isDisabled())
  assert.equal(await page.getByLabel('Máximo a bordo (min)').inputValue(), '60')
  assert.equal(await page.getByRole('button', { name: 'Guardar factores' }).count(), 0)
  if (process.env.NOVARA_UX_EVIDENCE) {
    await page.setViewportSize({ width: 1440, height: 1050 })
    await page.screenshot({ path: process.env.NOVARA_UX_EVIDENCE + '/preparation-desktop.png', fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth))
    await page.screenshot({ path: process.env.NOVARA_UX_EVIDENCE + '/preparation-mobile.png', fullPage: true })
    await page.setViewportSize({ width: 1440, height: 900 })
  }
  await page.getByRole('button', { name: 'Importar Excel', exact: true }).click()

  for (const [slug, commune] of [['gran-america', 'Pudahuel'], ['lo-blanco', 'Maipú']]) {
    const downloaded = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Descargar demo-' + slug + '.xlsx' }).click()
    const sample = await downloaded
    await page.getByLabel('Seleccionar archivo Excel').setInputFiles({
      name: sample.suggestedFilename(), mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: await readFile(await sample.path()),
    })
    const pending = page.getByRole('row').filter({ hasText: 'Sin comuna' })
    await pending.getByRole('button', { name: 'Editar' }).click()
    await page.getByRole('textbox', { name: 'Comuna', exact: true }).fill(commune)
    const corrected = page.waitForResponse(response => response.request().method() === 'PATCH')
    await page.getByRole('button', { name: 'Guardar revisión' }).click()
    assert.equal((await corrected).status(), 200)
    await pending.waitFor({ state: 'hidden' })
    if (slug === 'gran-america') await page.getByRole('button', { name: 'Cargar otra nómina' }).click()
  }
  await page.getByRole('button', { name: 'Revisar preparación' }).click()
  await page.getByRole('heading', { name: 'Antes de ponderar' }).waitFor()
  const solving = page.waitForResponse(response => response.url().endsWith('/api/v3/plans/preview'))
  const before = performance.now()
  await page.getByRole('button', { name: 'Ponderar rutas' }).click()
  const response = await solving
  const elapsed = Math.round(performance.now() - before)
  const plan = await response.json()
  assert.equal(response.status(), 200)
  assert.equal(plan.simulation, true)
  assert.equal(plan.trips.reduce((n, trip) => n + trip.stops.length, 0) + plan.unassigned.length, 16)
  assert.deepEqual(new Set(plan.trips.map(trip => trip.customer_id)), new Set(['gran_america', 'lo_blanco']))
  await page.getByRole('heading', { name: 'Viajes calculados' }).waitFor()
  await page.locator('.pin-icon').first().waitFor()
  if (process.env.NOVARA_UX_EVIDENCE) {
    await page.screenshot({ path: process.env.NOVARA_UX_EVIDENCE + '/planning-desktop.png', fullPage: true })
  }
  const exported = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Descargar Excel' }).click()
  assert.equal((await exported).suggestedFilename(), 'novara-vista-previa.xlsx')
  assert.match(page.url(), /\/planificacion$/)
  await page.reload()
  await page.getByRole('heading', { name: 'Prepara tus rutas' }).waitFor()
  assert.equal(await page.getByLabel('Clave de la demo').count(), 0)
  assert.deepEqual(external, [])
  console.log(JSON.stringify({ solicitudes: 16, viajes: plan.trips.length, no_asignados: plan.unassigned.length, jornada_ms: elapsed }))
} finally {
  await browser.close()
}
