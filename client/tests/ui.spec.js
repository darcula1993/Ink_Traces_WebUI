import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

function authConfig() {
  const configPath = path.resolve(process.cwd(), '../config.json')
  return JSON.parse(fs.readFileSync(configPath, 'utf8')).auth
}

async function login(page) {
  await page.goto('/')
  const username = page.locator('input[name="username"]')
  const workspace = page.locator('.workspace-main')
  const destination = await Promise.race([
    username.waitFor({ state: 'visible' }).then(() => 'login'),
    workspace.waitFor({ state: 'visible' }).then(() => 'workspace'),
  ])
  if (destination === 'login') {
    const auth = authConfig()
    await username.fill(auth.username)
    await page.locator('input[name="password"]').fill(auth.password)
    await page.locator('form button[type="submit"]').click()
  }
  await expect(workspace).toBeVisible()
}

test('workspace adapts without horizontal overflow', async ({ page }, testInfo) => {
  await login(page)
  await expect(page.locator('.inspector-pane')).toBeVisible()

  if (testInfo.project.name === 'desktop') {
    const materials = await page.evaluate(() => {
      const sidebarStyle = getComputedStyle(document.querySelector('.prompt-pane'))
      const sidebarChannels = sidebarStyle.backgroundColor.match(/[\d.]+/g)
      return {
        header: getComputedStyle(document.querySelector('.app-header')).backdropFilter,
        sidebar: sidebarStyle.backdropFilter,
        sidebarAlpha: Number(sidebarChannels?.[3] ?? 1),
        canvas: getComputedStyle(document.querySelector('.canvas-pane')).backdropFilter,
        ambientTracks: document.querySelectorAll('.glass-code-track').length,
      }
    })
    expect(materials.header).toContain('blur')
    expect(materials.sidebar).toContain('blur')
    expect(materials.sidebarAlpha).toBeLessThan(0.3)
    expect(materials.ambientTracks).toBeGreaterThanOrEqual(2)
    expect(materials.canvas).toBe('none')

    await page.mouse.move(80, 80)
    await page.waitForTimeout(50)
    const firstHighlight = await page.locator('.app-shell').evaluate(shell => shell.style.getPropertyValue('--glass-light-x'))
    await page.mouse.move(1180, 720)
    await page.waitForTimeout(50)
    const secondHighlight = await page.locator('.app-shell').evaluate(shell => shell.style.getPropertyValue('--glass-light-x'))
    expect(firstHighlight).not.toBe(secondHighlight)
  }

  const watermarkSwitch = page.getByRole('switch', { name: '添加水印' })
  if (await watermarkSwitch.isVisible()) {
    const initialState = await watermarkSwitch.getAttribute('aria-checked')
    await watermarkSwitch.click()
    await expect(watermarkSwitch).toHaveAttribute('aria-checked', initialState === 'true' ? 'false' : 'true')
  }

  await page.screenshot({
    path: testInfo.outputPath(`${testInfo.project.name}-image-workspace.png`),
    fullPage: testInfo.project.name === 'mobile',
  })

  const imageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(imageOverflow).toBeLessThanOrEqual(1)

  await page.getByRole('button', { name: '提示词库', exact: true }).click()
  await expect(page.getByLabel('搜索提示词')).toBeVisible()
  if (testInfo.project.name === 'desktop') {
    await page.screenshot({ path: testInfo.outputPath('desktop-liquid-glass-drawer.png') })
  }
  await page.getByRole('button', { name: '关闭提示词库' }).click()
  await expect(page.getByLabel('搜索提示词')).toBeHidden()
  await page.getByRole('button', { name: '任务历史' }).click()
  await expect(page.getByLabel('搜索任务')).toBeVisible()
  await page.getByRole('button', { name: '关闭任务历史' }).click()
  await expect(page.getByLabel('搜索任务')).toBeHidden()

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '视频', exact: true }).click()
  await expect(page.getByText('生成设置', { exact: true })).toBeVisible()

  const videoOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(videoOverflow).toBeLessThanOrEqual(1)

  await page.screenshot({
    path: testInfo.outputPath(`${testInfo.project.name}-video-workspace.png`),
    fullPage: testInfo.project.name === 'mobile',
  })
})

test('login keeps content legible on a glass layer', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Login material only needs one desktop run')
  await page.route('**/api/auth/check', route => route.fulfill({ status: 401, contentType: 'application/json', body: '{}' }))
  await page.goto('/')
  await expect(page.getByLabel('用户名')).toBeVisible()
  const material = await page.locator('.liquid-login').evaluate(panel => getComputedStyle(panel).backdropFilter)
  expect(material).toContain('blur')
  await page.screenshot({ path: testInfo.outputPath('desktop-liquid-glass-login.png') })
})

test('code rain loading canvas renders active pixels', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Canvas pixel check only needs one desktop run')
  await login(page)

  let submittedBody
  await page.route('**/api/generate', async route => {
    submittedBody = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queued: true, task_id: 999, status: 'pending' }),
    })
  })
  await page.route('**/api/tasks/999', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task: { id: 999, status: 'processing', progress: 0, result: {} } }),
    })
  })

  await page.getByLabel('图片提示词').fill('A precise interface loading-state test')
  const watermarkSwitch = page.getByRole('switch', { name: '添加水印' })
  const hasWatermarkControl = await watermarkSwitch.isVisible()
  if (hasWatermarkControl && await watermarkSwitch.getAttribute('aria-checked') === 'false') await watermarkSwitch.click()
  await page.getByRole('button', { name: '生成图片' }).click()
  await expect(page.getByText('正在生成')).toBeVisible()
  await page.waitForTimeout(500)

  const pixelStats = await page.locator('.canvas-pane canvas').evaluate(canvas => {
    const context = canvas.getContext('2d')
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
    let lit = 0
    let green = 0
    let whiteHeads = 0
    const verticalBands = new Set()
    for (let index = 0; index < pixels.length; index += 16) {
      const red = pixels[index]
      const greenChannel = pixels[index + 1]
      const blue = pixels[index + 2]
      if (red + greenChannel + blue > 36) lit += 1
      if (greenChannel > red * 1.25 && greenChannel > blue * 1.15 && greenChannel > 40) {
        green += 1
        const pixelIndex = index / 4
        const row = Math.floor(pixelIndex / canvas.width)
        verticalBands.add(Math.min(7, Math.floor(row / canvas.height * 8)))
      }
      if (red > 130 && greenChannel > 170 && blue > 130) whiteHeads += 1
    }
    return { lit, green, whiteHeads, verticalBands: verticalBands.size, width: canvas.width, height: canvas.height }
  })

  expect(pixelStats.width).toBeGreaterThan(300)
  expect(pixelStats.height).toBeGreaterThan(200)
  expect(pixelStats.lit).toBeGreaterThan(100)
  expect(pixelStats.green).toBeGreaterThan(50)
  expect(pixelStats.whiteHeads).toBeGreaterThan(8)
  expect(pixelStats.verticalBands).toBeGreaterThanOrEqual(6)
  if (hasWatermarkControl) expect(submittedBody.watermark).toBe(true)

  await page.locator('.canvas-pane').screenshot({ path: testInfo.outputPath('code-rain-loading.png') })
})

test('large reference assets survive reload through IndexedDB', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Persistence only needs one browser run')
  await login(page)

  const onePixelPng = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    'base64',
  )
  const largePng = Buffer.concat([onePixelPng, Buffer.alloc(300 * 1024)])

  const transfer = await page.evaluateHandle(({ base64 }) => {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(new File([bytes], 'large-reference.png', { type: 'image/png' }))
    return dataTransfer
  }, { base64: largePng.toString('base64') })
  const dropZone = page.getByTestId('reference-drop-zone')
  await dropZone.dispatchEvent('dragenter', { dataTransfer: transfer })
  await expect(dropZone).toHaveAttribute('data-dragging', 'true')
  await dropZone.screenshot({ path: testInfo.outputPath('reference-drop-active.png') })
  await dropZone.dispatchEvent('dragover', { dataTransfer: transfer })
  await dropZone.dispatchEvent('drop', { dataTransfer: transfer })
  await expect(dropZone).toHaveAttribute('data-dragging', 'false')
  await transfer.dispose()
  await expect(page.getByAltText('参考图片 1')).toBeVisible()

  await expect.poll(async () => page.evaluate(async () => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open('ink-traces-workspace', 1)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    return new Promise((resolve, reject) => {
      const request = database.transaction('state', 'readonly').objectStore('state').get('img_tabs')
      request.onsuccess = () => resolve(request.result?.[0]?.uploadedImages?.[0]?.file?.size || 0)
      request.onerror = () => reject(request.error)
    })
  })).toBeGreaterThan(300 * 1024)

  await page.reload()
  await expect(page.locator('.workspace-main')).toBeVisible()
  await expect.poll(async () => page.getByAltText('参考图片 1').getAttribute('src')).toContain('data:image/png;base64,')

  const fallbackSize = await page.evaluate(() => localStorage.getItem('img_tabs')?.length || 0)
  expect(fallbackSize).toBeLessThan(100_000)
})
