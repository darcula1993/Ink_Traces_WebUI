import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

function authConfig() {
  const configPath = path.resolve(process.cwd(), '../config.json')
  return JSON.parse(fs.readFileSync(configPath, 'utf8')).auth
}

function sortJsonValue(value) {
  if (Array.isArray(value)) return value.map(sortJsonValue)
  if (!value || typeof value !== 'object') return value
  return Object.keys(value).sort().reduce((sorted, key) => {
    sorted[key] = sortJsonValue(value[key])
    return sorted
  }, {})
}

async function login(page, {
  mockTasks = true,
  mockGroups = true,
  initialWorkspaceState = {},
  onWorkspacePut = null,
} = {}) {
  const workspaceState = new Map(Object.entries(initialWorkspaceState))
  await page.route('**/api/workspace/state/*', async route => {
    const key = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop())
    if (route.request().method() === 'GET') {
      const value = workspaceState.get(key)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          state: value === undefined ? null : {
            key,
            value: sortJsonValue(value),
            revision: 1,
            updated_at: new Date().toISOString(),
          },
        }),
      })
      return
    }
    if (route.request().method() === 'PUT') {
      const { value } = route.request().postDataJSON()
      workspaceState.set(key, value)
      onWorkspacePut?.(key, value)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          state: { key, value: sortJsonValue(value), revision: 1, updated_at: new Date().toISOString() },
        }),
      })
      return
    }
    await route.fallback()
  })
  if (mockTasks) {
    await page.route('**/api/tasks?*', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, tasks: [], total: 0 }),
    }))
  }
  if (mockGroups) {
    await page.route('**/api/favorite-groups?*', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, groups: [] }),
    }))
  }
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
  return workspaceState
}

test('workspace persistence ignores server JSON key ordering', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Persistence only needs one browser run')
  const workspacePuts = []
  await login(page, {
    initialWorkspaceState: {
      img_tabs: [{
        watermark: false,
        outputFormat: 'png',
        uploadedImages: [],
        sessionId: null,
        chatMode: false,
        thinkLevel: 'minimal',
        useSearch: false,
        resolution: '1K',
        aspectRatio: '1:1',
        prompt: '',
        id: 1,
      }],
      vid_tabs: [{
        refAudios: [],
        refVideos: [],
        refImages: [],
        lastFrame: null,
        firstFrame: null,
        search: false,
        mode: 'keyframe',
        returnLastFrame: false,
        audio: true,
        fast: false,
        resolution: '720p',
        duration: 5,
        ratio: 'adaptive',
        prompt: '',
        id: 1,
      }],
    },
    onWorkspacePut: (key) => workspacePuts.push(key),
  })

  await page.waitForTimeout(1_600)
  expect(workspacePuts.filter(key => key === 'img_tabs')).toHaveLength(0)
  expect(workspacePuts.filter(key => key === 'vid_tabs')).toHaveLength(0)
})

test('workspace adapts without horizontal overflow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The current workspace redesign targets desktop')
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
    expect(materials.canvas).toContain('blur')

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
  await expect(page.getByLabel('搜索任务画廊')).toBeVisible()
  await expect(page.getByTestId('new-draft-card')).toHaveCount(0)
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(0)
  await expect(page.getByText('没有符合条件的任务')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成图片' })).toBeEnabled()

  await page.getByRole('group', { name: '任务视图' }).getByRole('button', { name: '进行中' }).click()
  await expect(page.getByText('没有符合条件的任务')).toBeVisible()
  await expect(page.getByRole('button', { name: /加载更多/ })).toHaveCount(0)
  await page.getByRole('group', { name: '任务视图' }).getByRole('button', { name: '全部' }).click()

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '视频', exact: true }).click()
  await expect(page.getByText('生成设置', { exact: true })).toBeVisible()
  await expect(page.getByLabel('视频提示词')).toBeEnabled()
  await expect(page.getByRole('button', { name: '生成视频' })).toBeEnabled()

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

test('task gallery favorites persist and details open in a large modal', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Gallery interaction only needs one desktop run')
  const preview = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  const task = {
    id: 42,
    type: 'image',
    status: 'succeeded',
    prompt: '收藏交互测试任务',
    params: { aspect_ratio: '16:9', resolution: '2K', output_format: 'png' },
    provider: 'ark',
    favorite: false,
    favorite_groups: [],
    progress: 100,
    created_at: '2026-07-12T08:30:00+00:00',
    result: { local_images: [preview], local_refs: [] },
  }
  const nextTask = {
    ...task,
    id: 43,
    prompt: '未加载分页中的任务',
    favorite: true,
    favorite_groups: [],
    created_at: '2026-07-12T08:31:00+00:00',
  }
  let bulkDeletedIds = []
  let selectionQuery = ''
  const favoriteGroups = [{ id: 7, name: '角色设计', color: 'cyan', position: 0, task_count: 0 }]

  await page.route('**/api/tasks?*', route => {
    const wantsTrash = new URL(route.request().url()).searchParams.get('deleted') === 'true'
    const visible = wantsTrash ? Boolean(task.deleted_at) : !task.deleted_at
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, tasks: visible ? [task] : [], total: visible ? 3 : 0 }),
    })
  })
  await page.route('**/api/tasks/selection?*', route => {
    selectionQuery = new URL(route.request().url()).searchParams.get('q') || ''
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, ids: [42, 43, 44], total: 3 }),
    })
  })
  await page.route('**/api/tasks/42/favorite', async route => {
    const body = route.request().postDataJSON()
    task.favorite = body.favorite
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, favorite: task.favorite, task }),
    })
  })
  await page.route('**/api/favorite-groups?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, groups: favoriteGroups }),
  }))
  await page.route('**/api/tasks/42/favorite-groups', async route => {
    const { group_ids: groupIds } = route.request().postDataJSON()
    task.favorite = true
    task.favorite_groups = favoriteGroups.filter(group => groupIds.includes(group.id))
    favoriteGroups[0].task_count = task.favorite_groups.length ? 1 : 0
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task }),
    })
  })
  await page.route('**/api/tasks/42', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, task }),
  }))
  await page.route('**/api/tasks/43', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, task: nextTask }),
  }))
  await page.route(/\/api\/tasks\/(42|43)\/navigation(?:\?|$)/, route => {
    const taskId = Number(new URL(route.request().url()).pathname.split('/').at(-2))
    const navigation = taskId === 42
      ? { position: 1, total: 3, previous_id: null, next_id: 43, first_id: 42, last_id: 44 }
      : { position: 2, total: 3, previous_id: 42, next_id: 44, first_id: 42, last_id: 44 }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, navigation }),
    })
  })
  await page.route('**/api/tasks/bulk-delete', async route => {
    bulkDeletedIds = route.request().postDataJSON().ids
    task.deleted_at = new Date().toISOString()
    task.status = 'succeeded'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, deleted: bulkDeletedIds.length, deleted_ids: bulkDeletedIds, missing_ids: [] }),
    })
  })
  await page.route('**/api/tasks/42/restore', async route => {
    task.deleted_at = null
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task }),
    })
  })

  const workspaceState = await login(page, { mockTasks: false, mockGroups: false })
  const historyCard = page.getByTestId('task-gallery-card').filter({ hasText: task.prompt })
  await expect(historyCard).toBeVisible()
  await historyCard.getByRole('button', { name: '收藏任务' }).click()
  await expect(historyCard.getByRole('button', { name: '取消收藏任务' })).toBeVisible()

  await page.getByRole('group', { name: '任务视图' }).getByRole('button', { name: '收藏' }).click()
  await expect(historyCard).toBeVisible()
  await historyCard.click()
  const modal = page.getByRole('dialog', { name: '任务详情' })
  await expect(modal).toBeVisible()
  await expect(modal.getByText(task.prompt)).toBeVisible()
  await modal.getByRole('checkbox', { name: '角色设计' }).click()
  await expect(modal.getByRole('checkbox', { name: '角色设计' })).toHaveAttribute('aria-checked', 'true')
  await expect(modal.getByRole('link', { name: '下载任务结果' })).toHaveAttribute(
    'download',
    'ink-traces-image-task-42-20260712083000-output-01.png',
  )
  await modal.getByRole('button', { name: '下一个任务' }).click()
  await expect(modal.getByText(nextTask.prompt)).toBeVisible()
  await expect(modal.getByText('2 / 3')).toBeVisible()
  await modal.getByRole('button', { name: '上一个任务' }).click()
  await expect(modal.getByText(task.prompt)).toBeVisible()
  await modal.screenshot({ path: testInfo.outputPath('desktop-task-detail-modal.png') })
  await modal.getByRole('button', { name: '关闭任务详情' }).click()

  await page.getByRole('button', { name: '筛选收藏分组' }).click()
  const groupMenu = page.getByRole('menu', { name: '收藏分组' })
  await expect(groupMenu).toBeVisible()
  await expect(groupMenu.getByRole('menuitemradio', { name: /角色设计/ })).toBeVisible()
  await groupMenu.screenshot({ path: testInfo.outputPath('desktop-favorite-group-menu.png') })
  await page.getByRole('button', { name: '筛选收藏分组' }).click()

  await page.getByRole('button', { name: '任务卡片布局' }).click()
  const layoutMenu = page.getByRole('menu', { name: '任务卡片布局设置' })
  await expect(layoutMenu).toBeVisible()
  await layoutMenu.getByRole('menuitemradio', { name: 'Compact' }).click()
  await layoutMenu.getByRole('menuitemradio', { name: 'Clean' }).click()
  await expect(page.locator('.task-gallery')).toHaveAttribute('data-card-size', 'compact')
  await expect(page.locator('.task-gallery')).toHaveAttribute('data-card-details', 'clean')
  await expect(page.locator('.task-card-details')).toHaveCount(0)
  await expect.poll(() => workspaceState.get('gallery_preferences')).toEqual({
    cardSize: 'compact',
    cardDetails: 'clean',
    sort: 'newest',
  })
  await page.locator('.canvas-pane').screenshot({ path: testInfo.outputPath('desktop-task-gallery-compact-clean.png') })

  await page.getByLabel('搜索任务画廊').fill('收藏交互')
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(1)
  await page.getByRole('button', { name: '批量选择任务' }).click()
  await expect(page.getByTestId('selection-summary')).toContainText('已选 0')
  await page.getByRole('button', { name: '全选当前分类' }).click()
  const selectedCard = page.getByTestId('task-gallery-card').first()
  await expect(selectedCard).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('selection-summary')).toContainText('已选 3')
  await page.locator('.canvas-pane').screenshot({ path: testInfo.outputPath('desktop-task-gallery-selection.png') })
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: '将已选任务移到回收站' }).click()
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(0)
  expect(bulkDeletedIds).toEqual([42, 43, 44])
  expect(selectionQuery).toBe('收藏交互')

  await page.getByRole('group', { name: '任务视图' }).getByRole('button', { name: '回收站' }).click()
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(1)
  await page.getByTestId('task-gallery-card').click()
  await page.getByRole('dialog', { name: '任务详情' }).getByRole('button', { name: '恢复任务' }).click()
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(0)
})

test('code rain loading canvas renders active pixels', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Canvas pixel check only needs one desktop run')
  await login(page)

  const submittedBodies = []
  const submittedTasks = []
  await page.route('**/api/generate', async route => {
    const taskId = 999 + submittedTasks.length
    const body = route.request().postDataJSON()
    submittedBodies.push(body)
    submittedTasks.unshift({
      id: taskId,
      type: 'image',
      status: 'processing',
      prompt: body.prompt,
      params: { aspect_ratio: body.aspect_ratio, resolution: body.resolution, output_format: 'png' },
      provider: 'ark',
      favorite: false,
      favorite_groups: [],
      progress: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      result: {},
    })
    await new Promise(resolve => setTimeout(resolve, 250))
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queued: true, task_id: taskId, status: 'pending' }),
    })
  })
  await page.route('**/api/tasks?*', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        tasks: submittedTasks,
        total: submittedTasks.length,
      }),
  }))

  const generateButton = page.getByRole('button', { name: '生成图片' })
  await expect(generateButton).toBeEnabled()
  await page.getByLabel('图片提示词').fill('A precise interface loading-state test')
  const watermarkSwitch = page.getByRole('switch', { name: '添加水印' })
  const hasWatermarkControl = await watermarkSwitch.isVisible()
  if (hasWatermarkControl && await watermarkSwitch.getAttribute('aria-checked') === 'false') await watermarkSwitch.click()
  await generateButton.click()
  await expect(generateButton).toBeEnabled()
  await generateButton.click()
  await expect(generateButton).toBeEnabled()
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(2)
  const loadingCard = page.getByTestId('task-gallery-card').first()
  await expect(loadingCard.locator('canvas')).toBeVisible()
  await expect(loadingCard.locator('.status-pill')).toContainText(/提交中|准备中|排队中|生成中/)
  await page.waitForTimeout(500)

  const pixelStats = await loadingCard.locator('canvas').evaluate(canvas => {
    const context = canvas.getContext('2d')
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
    let lit = 0
    let green = 0
    let whiteHeads = 0
    const verticalBands = new Set()
    for (let index = 0; index < pixels.length; index += 4) {
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

  expect(pixelStats.width).toBeGreaterThan(180)
  expect(pixelStats.height).toBeGreaterThan(120)
  expect(pixelStats.lit).toBeGreaterThan(45)
  expect(pixelStats.green).toBeGreaterThan(20)
  expect(pixelStats.whiteHeads).toBeGreaterThan(3)
  expect(pixelStats.verticalBands).toBeGreaterThanOrEqual(5)
  expect(submittedBodies).toHaveLength(2)
  if (hasWatermarkControl) expect(submittedBodies.every(body => body.watermark === true)).toBe(true)

  await loadingCard.screenshot({ path: testInfo.outputPath('code-rain-loading-card.png') })
})

test('video generation creates a new task on every click', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Concurrent submission only needs one desktop run')
  await login(page)

  const submittedBodies = []
  const submittedTasks = []
  await page.route('**/api/video/generate', async route => {
    const taskId = 2001 + submittedTasks.length
    const body = route.request().postDataJSON()
    submittedBodies.push(body)
    submittedTasks.unshift({
      id: taskId,
      type: 'video',
      status: 'processing',
      prompt: body.prompt,
      params: { ratio: body.ratio, resolution: body.resolution, duration: body.duration },
      provider: 'ark',
      favorite: false,
      favorite_groups: [],
      progress: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      result: {},
    })
    await new Promise(resolve => setTimeout(resolve, 250))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task_id: `external-${taskId}`, db_task_id: taskId, provider: 'ark' }),
    })
  })
  await page.route('**/api/tasks?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, tasks: submittedTasks, total: submittedTasks.length }),
  }))

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '视频', exact: true }).click()
  await page.getByLabel('视频提示词').fill('A concurrent video task test')
  const generateButton = page.getByRole('button', { name: '生成视频' })
  await generateButton.click()
  await expect(generateButton).toBeEnabled()
  await generateButton.click()
  await expect(generateButton).toBeEnabled()
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(2)
  expect(submittedBodies).toHaveLength(2)
})

test('large reference assets persist through backend workspace state', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Persistence only needs one browser run')
  await login(page)

  const onePixelPng = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    'base64',
  )
  const workspaceAssetUrl = '/api/workspace/assets/img_tabs/test-reference.png'
  let submittedImageTabs = null
  let normalizedImageTabs = null
  let submittedStateBytes = 0
  let workspaceUploadCount = 0
  let workspaceUploadBytes = 0
  let submittedGeneration = null
  await page.route('**/api/workspace/assets/img_tabs', async route => {
    workspaceUploadCount += 1
    workspaceUploadBytes += route.request().postDataBuffer()?.length || 0
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        asset: {
          url: workspaceAssetUrl,
          name: 'large-reference.png',
          mime_type: 'image/png',
          size_bytes: onePixelPng.length + 300 * 1024,
        },
      }),
    })
  })
  await page.route('**/api/generate', async route => {
    submittedGeneration = route.request().postDataJSON()
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task_id: 901, status: 'pending' }),
    })
  })
  await page.route('**/api/workspace/state/img_tabs', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          state: normalizedImageTabs ? { key: 'img_tabs', value: normalizedImageTabs, revision: 1 } : null,
        }),
      })
      return
    }
    submittedStateBytes = route.request().postDataBuffer()?.length || 0
    submittedImageTabs = route.request().postDataJSON().value
    normalizedImageTabs = submittedImageTabs.map(tab => ({
      ...tab,
      uploadedImages: (tab.uploadedImages || []).map(image => ({
        ...image,
        file: null,
        preview: workspaceAssetUrl,
      })),
    }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, state: { key: 'img_tabs', value: normalizedImageTabs, revision: 1 } }),
    })
  })
  await page.route(`**${workspaceAssetUrl}`, route => route.fulfill({
    status: 200,
    contentType: 'image/png',
    body: onePixelPng,
  }))
  const transfer = await page.evaluateHandle(({ base64, targetSize }) => {
    const binary = atob(base64)
    const bytes = new Uint8Array(targetSize)
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(new File([bytes], 'large-reference.png', { type: 'image/png' }))
    return dataTransfer
  }, { base64: onePixelPng.toString('base64'), targetSize: onePixelPng.length + 300 * 1024 })
  const dropZone = page.getByTestId('reference-drop-zone')
  await dropZone.dispatchEvent('dragenter', { dataTransfer: transfer })
  await expect(dropZone).toHaveAttribute('data-dragging', 'true')
  await dropZone.screenshot({ path: testInfo.outputPath('reference-drop-active.png') })
  await dropZone.dispatchEvent('dragover', { dataTransfer: transfer })
  await dropZone.dispatchEvent('drop', { dataTransfer: transfer })
  await expect(dropZone).toHaveAttribute('data-dragging', 'false')
  await transfer.dispose()
  await expect(page.getByAltText('参考图片 1')).toBeVisible()

  await expect.poll(() => submittedImageTabs?.[0]?.uploadedImages?.[0]?.preview || '')
    .toBe(workspaceAssetUrl)
  expect(submittedImageTabs[0].uploadedImages[0].file).toBeNull()
  expect(workspaceUploadCount).toBe(1)
  expect(workspaceUploadBytes).toBeGreaterThan(300 * 1024)
  expect(submittedStateBytes).toBeLessThan(100_000)
  await expect(page.getByAltText('参考图片 1')).toHaveAttribute('src', workspaceAssetUrl)

  await page.getByLabel('图片提示词').fill('Reuse the uploaded workspace asset')
  await page.getByRole('button', { name: '生成图片' }).click()
  await expect.poll(() => submittedGeneration?.image_urls || []).toEqual([workspaceAssetUrl])
  expect(workspaceUploadCount).toBe(1)

  await page.reload()
  await expect(page.locator('.workspace-main')).toBeVisible()
  await expect(page.getByAltText('参考图片 1')).toHaveAttribute('src', workspaceAssetUrl)

  const fallbackSize = await page.evaluate(() => localStorage.getItem('img_tabs')?.length || 0)
  expect(fallbackSize).toBeLessThan(100_000)
})
