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

async function dropFiles(locator, files) {
  await locator.evaluate((element, fileSpecs) => {
    const transfer = new DataTransfer()
    for (const spec of fileSpecs) {
      transfer.items.add(new File([spec.contents || 'test-media'], spec.name, { type: spec.type }))
    }
    for (const type of ['dragenter', 'dragover', 'drop']) {
      element.dispatchEvent(new DragEvent(type, {
        bubbles: true,
        cancelable: true,
        dataTransfer: transfer,
      }))
    }
  }, files)
}

async function pasteFiles(page, files) {
  await page.evaluate(fileSpecs => {
    const transfer = new DataTransfer()
    for (const spec of fileSpecs) {
      transfer.items.add(new File([spec.contents || 'test-media'], spec.name, { type: spec.type }))
    }
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: transfer })
    document.dispatchEvent(event)
  }, files)
}

async function dragReference(source, target) {
  const targetHandle = await target.elementHandle()
  await source.evaluate((sourceElement, targetElement) => {
    const transfer = new DataTransfer()
    sourceElement.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: transfer }))
    targetElement.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: transfer }))
    targetElement.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: transfer }))
    targetElement.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }))
    sourceElement.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true, dataTransfer: transfer }))
  }, targetHandle)
  await targetHandle.dispose()
}

test('workspace persistence ignores server JSON key ordering', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Persistence only needs one browser run')
  const workspacePuts = []
  await login(page, {
    initialWorkspaceState: {
      img_tabs: [{
        watermark: false,
        outputFormat: 'png',
        background: 'default',
        uploadedImages: [],
        sessionId: null,
        chatMode: false,
        thinkLevel: 'minimal',
        useSearch: false,
        resolution: '1K',
        aspectRatio: '1:1',
        customWidth: 1024,
        customHeight: 1024,
        customAspectLocked: false,
        customAspectRatio: 1,
        prompt: '',
        id: 1,
      }],
      vid_tabs: [{
        refAudios: [],
        refVideos: [],
        refImages: [],
        lastFrame: null,
        firstFrame: null,
        mode: 'keyframe',
        returnLastFrame: false,
        audio: true,
        fast: false,
        outputFormat: 'mp4',
        resolution: '720p',
        duration: 5,
        ratio: 'adaptive',
        model: 'seedance-2.0',
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

test('transparent background controls and Layer Studio workspace', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Layer Studio is desktop-first')
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mNkYPj/n4GBgYGJAQoAHgQCAf2gKJYAAAAASUVORK5CYII=', 'base64')
  let project = null
  let savedLayerDocument = null

  await page.route('**/api/images/inspect', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, image: { format: 'png', width: 2, height: 2, pixels: 4, has_alpha: true } }),
  }))
  await page.route('**/api/layer/projects/7', async route => {
    if (route.request().method() === 'PUT') {
      savedLayerDocument = route.request().postDataJSON().document
      project = { ...project, document: savedLayerDocument, document_revision: project.document_revision + 1 }
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, project }),
    })
  })
  await page.route('**/api/layer/projects', async route => {
    if (route.request().method() === 'POST') {
      project = {
        id: 7,
        name: 'studio-source',
        document: {},
        document_revision: 1,
        revisions: [],
        current_task: { id: 77, type: 'layer', status: 'pending', progress: 0, prompt: 'Separate subject and background', params: { size: 'auto' } },
      }
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, project_id: 7, task_id: 77, project }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, projects: project ? [project] : [] }),
    })
  })
  await page.route('**/api/layer/projects/7/source', route => route.fulfill({ status: 200, contentType: 'image/png', body: png }))
  await page.route('**/api/tasks/77/file/*', route => route.fulfill({ status: 200, contentType: 'image/png', body: png }))

  await login(page)
  await page.getByLabel('选择参考图片').setInputFiles({ name: 'alpha.png', mimeType: 'image/png', buffer: png })
  await expect(page.getByLabel('图片背景')).toBeEnabled()
  await page.getByLabel('图片背景').selectOption('transparent')
  await expect(page.getByLabel('图片输出格式')).toHaveValue('png')
  await expect(page.getByLabel('图片输出格式')).toBeDisabled()

  await page.getByRole('button', { name: '图层' }).click()
  const studio = page.getByTestId('layer-studio')
  await expect(studio).toBeVisible()
  await page.locator('.layer-studio-empty input[type="file"]').setInputFiles({ name: 'studio-source.png', mimeType: 'image/png', buffer: png })
  await page.getByLabel('图层分解提示词').fill('Separate subject and background')
  await page.getByRole('button', { name: '分解图层' }).click()
  await expect(page.getByText('正在构建图层')).toBeVisible()

  const layout = await page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect()
    const canvas = rect('.layer-studio-canvas')
    const right = rect('.layer-studio-right')
    const dock = rect('.layer-prompt-dock')
    const command = rect('.layer-studio-commandbar')
    return {
      canvasRight: canvas.right,
      rightLeft: right.left,
      canvasBottom: canvas.bottom,
      dockTop: dock.top,
      commandBottom: command.bottom,
      canvasTop: canvas.top,
    }
  })
  expect(Math.abs(layout.canvasRight - layout.rightLeft)).toBeLessThanOrEqual(1)
  expect(Math.abs(layout.canvasBottom - layout.dockTop)).toBeLessThanOrEqual(1)
  expect(Math.abs(layout.commandBottom - layout.canvasTop)).toBeLessThanOrEqual(1)
  await studio.screenshot({ path: testInfo.outputPath('layer-studio-processing.png') })

  project = {
    ...project,
    current_task: { ...project.current_task, status: 'succeeded', progress: 100 },
    document_revision: 2,
    document: {
      canvas: { width: 2, height: 2, background: 'transparent' },
      selected_layer_id: '77:1',
      task_id: 77,
      layers: [{
        id: '77:0', z_index: 0, name: 'Base', description: '',
        local_url: '/api/tasks/77/file/base.png', thumbnail_url: '/api/tasks/77/file/base_thumb.png',
        x: 0, y: 0, display_width: 2, display_height: 2, rotation: 0,
        opacity: 1, visible: true, locked: true, size: '2x2',
      }, {
        id: '77:1', z_index: 1, name: 'Subject', description: 'movable layer',
        local_url: '/api/tasks/77/file/layer_01.png', thumbnail_url: '/api/tasks/77/file/layer_01_thumb.png',
        x: 0, y: 0, display_width: 1, display_height: 1, rotation: 0,
        opacity: 1, visible: true, locked: false, size: '1x1',
      }],
    },
    revisions: [{ id: 1, task_id: 77, prompt: project.current_task.prompt, size: 'auto', document: {} }],
  }
  await expect(page.getByText('Base', { exact: true })).toBeVisible({ timeout: 6_000 })
  await expect(page.getByText('Subject', { exact: true })).toBeVisible()
  await expect.poll(() => page.locator('.layer-studio-canvas canvas').first().evaluate(canvas => {
    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    return Array.from(pixels).some(value => value !== 0)
  })).toBe(true)

  const canvasBox = await page.locator('.layer-studio-canvas').boundingBox()
  const startX = canvasBox.x + canvasBox.width / 2 - 120
  const startY = canvasBox.y + canvasBox.height / 2 - 120
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.waitForTimeout(100)
  await page.mouse.move(startX + 70, startY + 45, { steps: 8 })
  await page.waitForTimeout(100)
  await page.mouse.up()
  await expect(page.locator('.layer-studio-canvas')).toHaveAttribute('data-pan-x', '0')
  await expect.poll(() => Number(savedLayerDocument?.layers?.find(layer => layer.id === '77:1')?.x) || 0).toBeGreaterThan(0)
  expect(savedLayerDocument.layers.find(layer => layer.id === '77:0').x).toBe(0)
  await studio.screenshot({ path: testInfo.outputPath('layer-studio-editor.png') })
})

test('Seedance 2.5 exposes model capabilities and submits its stable alias', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Video model controls only need one browser run')
  await page.addInitScript(() => {
    Date.now = () => Date.parse('2026-08-22T00:00:00Z')
  })
  let submitted = null
  await page.route('**/api/video/generate', async route => {
    submitted = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task_id: 'remote-25', db_task_id: 2500, provider: 'ark' }),
    })
  })
  await login(page)

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '视频', exact: true }).click()
  await expect(page.getByTestId('video-cost-estimate')).toHaveText('$0.76')
  await page.getByLabel('视频模型').selectOption('seedance-2.5')
  await expect(page.getByLabel('视频模型')).toHaveValue('seedance-2.5')
  await expect(page.getByTestId('video-cost-estimate')).toHaveText('$0.92~$6.93')
  await expect(page.getByLabel('视频分辨率').locator('option')).toHaveText(['480p', '720p', '1080p'])
  await expect(page.getByLabel('视频时长').locator('option[value="30"]')).toHaveText('30s')
  await expect(page.getByLabel('视频时长')).toHaveValue('-1')
  await expect(page.getByLabel('视频输出格式')).toBeVisible()
  await expect(page.getByRole('switch', { name: '快速模式' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '快速优化' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '提示词助手' })).toHaveCount(0)

  await page.getByLabel('视频画幅').selectOption('21:9')
  await page.getByLabel('视频时长').selectOption('30')
  await expect(page.getByTestId('video-cost-estimate')).toHaveText('$6.97')
  await page.getByLabel('视频分辨率').selectOption('1080p')
  await expect(page.getByTestId('video-cost-estimate')).toHaveText('$12.36')
  await page.getByLabel('视频输出格式').selectOption('mov')
  await page.getByLabel('视频提示词').fill('A continuous cinematic shot through a neon city')
  await page.getByRole('button', { name: '生成视频' }).click()

  await expect.poll(() => submitted).not.toBeNull()
  expect(submitted.model).toBe('seedance-2.5')
  expect(submitted.duration).toBe(30)
  expect(submitted.resolution).toBe('1080p')
  expect(submitted.ratio).toBe('21:9')
  expect(submitted.output_format).toBe('mov')

  await page.getByLabel('视频生成模式').selectOption('reference')
  await expect(page.getByText('图片 · 30')).toBeVisible()
  await expect(page.getByText('视频 · 10')).toBeVisible()
  await expect(page.getByText('音频 · 10')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-seedance-2.5.png') })
})

test('prompt mention menu inserts current image, video, and audio references at the caret', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Prompt mention interactions only need one browser run')
  const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  await login(page, {
    initialWorkspaceState: {
      img_tabs: [{
        id: 1,
        prompt: '',
        uploadedImages: [
          { name: 'subject.png', preview: pixel },
          { name: 'style.png', preview: pixel },
        ],
      }],
      vid_tabs: [{
        id: 1,
        prompt: '',
        provider: 'ark',
        model: 'seedance-2.5',
        mode: 'reference',
        refImages: [{ name: 'scene.png', preview: pixel }],
        refVideos: [{ uid: 'video-1', name: 'motion.mp4', url: '/uploads/motion.mp4', thumbnail: pixel, uploading: false }],
        refAudios: [{ name: 'rhythm.wav' }],
      }],
      audio_form: {
        prompt: '',
        referenceMode: 'audio',
        speaker: '',
        references: [{ cupsyAssetId: 31, kind: 'audio', name: 'voice.wav', preview: '/api/cupsy/assets/31/content' }],
      },
    },
  })

  const imagePrompt = page.getByLabel('图片提示词')
  await imagePrompt.fill('first line\nsecond line')
  const imageEditorMetrics = await imagePrompt.evaluate(element => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    scrollTop: element.scrollTop,
  }))
  expect(imageEditorMetrics.clientHeight).toBeGreaterThan(300)
  expect(imageEditorMetrics.scrollHeight).toBeLessThanOrEqual(imageEditorMetrics.clientHeight)
  expect(imageEditorMetrics.scrollTop).toBe(0)
  await imagePrompt.fill('front  back')
  await imagePrompt.evaluate(element => {
    element.focus()
    element.setSelectionRange(6, 6)
  })
  await page.keyboard.type('@')
  const imageMenu = page.getByRole('listbox', { name: '参考素材' })
  await expect(imageMenu).toBeVisible()
  await expect(imageMenu.getByRole('option')).toHaveCount(2)
  await expect(imageMenu.getByRole('option').nth(0)).toContainText('Image1')
  await expect(imageMenu.getByRole('option').nth(0)).toContainText('subject.png')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(imagePrompt).toHaveValue('front [Image2] back')

  await dragReference(page.getByRole('button', { name: /调整参考图片 1 顺序/ }), page.getByTestId('image-reference-item-1'))
  await expect(imagePrompt).toHaveValue('front [Image2] back')
  await imagePrompt.fill('@')
  await expect(page.getByRole('listbox', { name: '参考素材' }).getByRole('option').nth(0)).toContainText('style.png')
  await page.keyboard.press('Escape')

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '视频', exact: true }).click()
  const videoPrompt = page.getByLabel('视频提示词')
  await videoPrompt.fill('first line\nsecond line')
  const videoEditorMetrics = await videoPrompt.evaluate(element => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    scrollTop: element.scrollTop,
  }))
  expect(videoEditorMetrics.clientHeight).toBeGreaterThan(300)
  expect(videoEditorMetrics.scrollHeight).toBeLessThanOrEqual(videoEditorMetrics.clientHeight)
  expect(videoEditorMetrics.scrollTop).toBe(0)
  await videoPrompt.fill('@')
  const videoMenu = page.getByRole('listbox', { name: '参考素材' })
  await expect(videoMenu.getByRole('option')).toHaveCount(3)
  await expect(videoMenu.getByRole('option').nth(0)).toContainText('Image1')
  await expect(videoMenu.getByRole('option').nth(1)).toContainText('Video1')
  await expect(videoMenu.getByRole('option').nth(2)).toContainText('Audio1')
  await page.screenshot({ path: testInfo.outputPath('desktop-prompt-mention-menu.png') })
  await videoMenu.getByRole('option').nth(1).click()
  await expect(videoPrompt).toHaveValue('[Video1]')

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '音频', exact: true }).click()
  const audioPrompt = page.getByLabel('音频提示词')
  await audioPrompt.fill('@aud')
  const audioMenu = page.getByRole('listbox', { name: '参考素材' })
  await expect(audioMenu.getByRole('option')).toHaveCount(1)
  await expect(audioMenu.getByRole('option')).toContainText('Audio1')
  await page.keyboard.press('Tab')
  await expect(audioPrompt).toHaveValue('[Audio1]')
  await page.screenshot({ path: testInfo.outputPath('desktop-prompt-mentions.png') })
})

test('reusing a video task restores all reference assets and their Cupsy roles', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Task reuse only needs one browser run')
  const task = {
    id: 701,
    type: 'video',
    status: 'succeeded',
    prompt: 'Reuse every bound reference',
    provider: 'cupsy',
    progress: 100,
    created_at: '2026-08-22T12:00:00+00:00',
    params: {
      model: 'seedance-2.5',
      ratio: '16:9',
      duration: 8,
      resolution: '1080p',
      video_mode: 'reference',
      generate_audio: true,
    },
    result: {
      local_video: '/api/tasks/701/file/video.mp4',
      local_refs: [
        '/api/cupsy/assets/11/content',
        '/api/cupsy/assets/12/content',
        '/api/cupsy/assets/13/content',
      ],
      local_ref_types: ['image', 'video', 'audio'],
      local_ref_roles: ['reference_image', 'reference_video', 'reference_audio'],
      local_ref_names: ['subject.png', 'motion.mp4', 'rhythm.wav'],
      local_ref_asset_ids: [11, 12, 13],
    },
  }
  let submitted = ''
  await page.route('**/api/tasks?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, tasks: [task], total: 1 }),
  }))
  await page.route('**/api/tasks/701', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, task }),
  }))
  await page.route('**/api/cupsy/assets/11/content', route => route.fulfill({
    status: 200,
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  }))
  await page.route('**/api/video/generate', route => {
    submitted = route.request().postDataBuffer().toString('utf8')
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, db_task_id: 702, task_id: 'remote-702' }),
    })
  })
  await login(page, {
    mockTasks: false,
    initialWorkspaceState: { appMode: 'video' },
  })

  await page.getByTestId('task-gallery-card').click()
  const detailModal = page.getByRole('dialog', { name: '任务详情' })
  await detailModal.getByRole('button', { name: '复用任务参数' }).click()
  await expect(page.getByLabel('视频提示词')).toHaveValue(task.prompt)
  await expect(page.getByLabel('视频生成模式')).toHaveValue('reference')
  await expect(page.getByTestId('video-reference-image-item-0')).toBeVisible()
  await expect(page.getByTestId('video-reference-video-item-0')).toBeVisible()
  await expect(page.getByTestId('video-reference-audio-item-0')).toBeVisible()
  await expect(page.getByRole('button', { name: '播放参考视频 1' })).toBeEnabled()

  await detailModal.getByRole('button', { name: '关闭任务详情' }).click()
  await page.getByRole('button', { name: '生成视频' }).click()
  await expect.poll(() => submitted).not.toBe('')
  expect(submitted).toContain('{"id":11,"role":"reference_image"}')
  expect(submitted).toContain('{"id":12,"role":"reference_video"}')
  expect(submitted).toContain('{"id":13,"role":"reference_audio"}')
})

test('Seed Audio workspace submits Cupsy full-scene audio parameters', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Audio workspace is desktop focused')
  let submitted = null
  await page.route('**/api/audio/provider', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      current: 'cupsy',
      providers: { cupsy: { available: true, source_ready: true, models: ['seed-audio-1.0'] } },
      capabilities: {
        formats: ['mp3', 'wav', 'ogg_opus'],
        sample_rates: [8000, 16000, 24000, 32000, 44100, 48000],
      },
    }),
  }))
  await page.route('**/api/audio/generate', route => {
    submitted = route.request().postDataJSON()
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queued: true, task_id: 2800, provider: 'cupsy' }),
    })
  })
  await login(page)

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '音频', exact: true }).click()
  await expect(page.getByText('音频参数')).toBeVisible()
  await expect(page.getByLabel('音频端点')).toHaveValue('cupsy')
  await expect(page.getByLabel('音频模型')).toHaveValue('seed-audio-1.0')
  await page.getByLabel('音频输出格式').selectOption('wav')
  await page.getByLabel('音频采样率').selectOption('48000')
  await page.getByRole('group', { name: '音频参考模式' }).getByRole('button', { name: '音频', exact: true }).click()
  await page.getByLabel('音频预设声线').selectOption('kian')
  await page.getByLabel('音频提示词').fill('A calm host introduces a midnight technology program over a restrained ambient score.')
  await page.getByRole('button', { name: '生成音频' }).click()

  await expect.poll(() => submitted).not.toBeNull()
  expect(submitted).toMatchObject({
    model: 'seed-audio-1.0',
    output_format: 'wav',
    sample_rate: 48000,
    reference_mode: 'audio',
    speaker: 'kian',
    enable_subtitle: true,
    watermark: false,
  })
  await page.screenshot({ path: testInfo.outputPath('desktop-seed-audio.png') })
})

test('Cupsy endpoint reuses active Assets from the solid asset manager', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Cupsy asset manager is desktop focused')
  let submitted = null
  await page.route('**/api/video/provider', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      current: 'ark',
      fast_available: true,
      providers: {
        ark: { available: true, models: ['seedance-2.0', 'seedance-2.5'] },
        cupsy: { available: true, source_ready: true, models: ['seedance-2.5', 'seedance-2.5-moderated'] },
      },
    }),
  }))
  await page.route('**/api/video/generate', route => {
    submitted = route.request().postDataJSON()
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queued: true, db_task_id: 2600, provider: 'cupsy' }),
    })
  })
  await page.route('**/api/cupsy/assets', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      configured: true,
      source_ready: true,
      assets: [{
        id: 17,
        provider: 'cupsy',
        external_asset_id: 'asset_remote_17',
        asset_uri: 'asset://asset_remote_17',
        kind: 'image',
        status: 'active',
        name: 'reference.png',
        mime_type: 'image/png',
        size_bytes: 1234,
        content_url: '/api/cupsy/assets/17/content',
      }],
    }),
  }))
  await page.route('**/api/cupsy/assets/17/content', route => route.fulfill({
    status: 200,
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  }))
  await login(page, { initialWorkspaceState: { appMode: 'video' } })

  await page.getByLabel('视频端点').selectOption('cupsy')
  await expect(page.getByLabel('视频模型')).toHaveValue('seedance-2.5')
  await expect(page.getByLabel('视频模型')).toBeEnabled()
  await expect(page.getByLabel('视频分辨率').locator('option')).toHaveText(['480p', '720p', '1080p'])
  await expect(page.getByLabel('视频模型').locator('option')).toHaveText([
    'Seedance 2.5',
    '2.5 · 加强审核',
  ])
  await page.getByLabel('视频模型').selectOption('seedance-2.5-moderated')
  await expect(page.getByLabel('视频时长').locator('option[value="-1"]')).toHaveText('Auto')
  await page.getByLabel('视频时长').selectOption('-1')
  await expect(page.getByTestId('video-cost-estimate')).toHaveText('$0.92~$6.93')
  await page.getByLabel('视频提示词').fill('A restrained cinematic product shot')
  await page.getByRole('button', { name: '生成视频' }).click()
  await expect.poll(() => submitted).not.toBeNull()
  expect(submitted.model).toBe('seedance-2.5-moderated')
  expect(submitted.duration).toBe(-1)
  await page.getByLabel('视频生成模式').selectOption('reference')
  await page.getByRole('button', { name: '素材库' }).click()
  const dialog = page.getByRole('dialog', { name: 'Cupsy 素材库' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveCSS('background-color', 'rgb(12, 16, 20)')
  await dialog.getByRole('button', { name: '引用' }).click()
  await expect(page.getByRole('button', { name: '打开视频参考图片 1' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-cupsy-assets.png') })
})

test('Seedance 2.5 reference video preserves explicit ratio and duration', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Reference video parameters only need one desktop run')
  let submitted = null
  await page.route('**/api/video/generate', async route => {
    submitted = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task_id: 'remote-edit-25', db_task_id: 2501, provider: 'ark' }),
    })
  })
  await login(page, {
    initialWorkspaceState: {
      appMode: 'video',
      vid_activeTab: 1,
      vid_tabs: [{
        id: 1,
        prompt: 'Use video 1 as a motion reference to create a new neon city scene',
        model: 'seedance-2.5',
        ratio: '16:9',
        duration: 28,
        resolution: '480p',
        outputFormat: 'mp4',
        fast: false,
        audio: true,
        returnLastFrame: false,
        mode: 'reference',
        firstFrame: null,
        lastFrame: null,
        refImages: [],
        refVideos: [{
          uid: 'edit-video',
          name: 'reference.mp4',
          url: '/api/upload_video/reference.mp4',
          thumbnail: null,
          duration: 27.8,
          uploading: false,
          progress: 100,
        }],
        refAudios: [],
      }],
    },
  })

  await expect(page.getByLabel('视频画幅')).toBeEnabled()
  await expect(page.getByLabel('视频画幅')).toHaveValue('16:9')
  await expect(page.getByLabel('视频时长')).toBeEnabled()
  await expect(page.getByLabel('视频时长')).toHaveValue('28')
  await expect(page.getByLabel('视频时长').locator('option[value="-1"]')).toHaveText('Auto · 编辑跟随输入')

  await page.getByRole('button', { name: '生成视频' }).click()
  await expect.poll(() => submitted).not.toBeNull()
  expect(submitted.model).toBe('seedance-2.5')
  expect(submitted.ratio).toBe('16:9')
  expect(submitted.duration).toBe(28)
})

test('workspace adapts without horizontal overflow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The current workspace redesign targets desktop')
  await login(page)
  await expect(page.locator('.inspector-pane')).toBeVisible()

  const alignedSelects = await page.locator('.inspector-field-row > .field-select').evaluateAll(elements => (
    elements.map(element => {
      const bounds = element.getBoundingClientRect()
      return { width: Math.round(bounds.width), right: Math.round(bounds.right) }
    })
  ))
  expect(new Set(alignedSelects.map(select => select.width)).size).toBe(1)
  expect(new Set(alignedSelects.map(select => select.right)).size).toBe(1)

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
    expect(materials.sidebarAlpha).toBeGreaterThan(0.25)
    expect(materials.sidebarAlpha).toBeLessThan(0.6)
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
  await expect(page.getByText('还没有图片任务')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成图片' })).toBeEnabled()

  await page.getByRole('group', { name: '任务视图' }).getByRole('button', { name: '进行中' }).click()
  await expect(page.getByText('没有正在生成的任务')).toBeVisible()
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

test('PNG Info applies reusable parameters without changing provider or model', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'PNG Info only needs one desktop run')
  await page.route('**/api/provider', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, current_provider: 'ark' }),
  }))
  await page.route('**/api/model', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, current_model: 'ignored-model', available_models: [] }),
  }))
  await page.route('**/api/png-info', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      image: { name: 'portable.png', width: 1024, height: 1536, size_bytes: 1280 },
      metadata: {
        source: 'ink_traces',
        prompt: 'Imported PNG prompt',
        params: {
          aspect_ratio: '9:16',
          resolution: '2K',
          output_format: 'jpeg',
          watermark: true,
          use_search: true,
          think_level: 'high',
        },
        chunks: { ink_traces: '{"schema":"ink-traces/png-info/v1"}' },
      },
    }),
  }))
  await login(page)

  await expect(page.getByLabel('图片端点')).toHaveValue('ark')
  await expect(page.getByLabel('图片模型')).toHaveValue('seedream-5-0-pro')
  const modelBefore = await page.getByLabel('图片模型').inputValue()
  const providerBefore = await page.getByLabel('图片端点').inputValue()
  await page.getByRole('button', { name: 'PNG Info' }).click()
  const dialog = page.getByRole('dialog', { name: 'PNG Info' })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('选择 PNG 文件').setInputFiles({
    name: 'portable.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  })
  await expect(dialog.getByText('Imported PNG prompt')).toBeVisible()
  await expect(dialog.getByText('9:16')).toBeVisible()
  await dialog.screenshot({ path: testInfo.outputPath('desktop-png-info-modal.png') })
  await dialog.getByRole('button', { name: '发送到图片生成' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByLabel('图片提示词')).toHaveValue('Imported PNG prompt')
  await expect(page.locator('.inspector-header')).toContainText('9:16 · 2K')
  await expect(page.getByRole('switch', { name: '添加水印' })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByLabel('图片模型')).toHaveValue(modelBefore)
  await expect(page.getByLabel('图片端点')).toHaveValue(providerBefore)
})

test('image endpoint and model selectors live in the parameter inspector', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Image parameter controls only need one desktop run')
  let provider = 'ark'
  let model = 'gemini-3.1-flash-image-preview'
  const providerChanges = []
  const modelChanges = []
  const providers = {
    ark: { name: 'BytePlus Ark', model: 'seedream-5-0-pro', available: true },
    vertex: { name: 'Vertex AI', model: 'gemini-3.1-flash-image-preview', available: true },
  }
  const models = [
    { id: 'gemini-3.1-flash-image-preview', name: 'Gemini 3.1 Flash' },
    { id: 'gemini-3-pro-image-preview', name: 'Gemini 3 Pro' },
  ]

  await page.route('**/api/provider', async route => {
    if (route.request().method() === 'POST') {
      provider = route.request().postDataJSON().provider
      providerChanges.push(provider)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, provider, model: providers[provider].model }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, current_provider: provider, current_model: providers[provider].model, providers }),
    })
  })
  await page.route('**/api/model', async route => {
    if (route.request().method() === 'POST') {
      model = route.request().postDataJSON().model
      modelChanges.push(model)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, model }) })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, current_model: model, available_models: models }),
    })
  })

  await login(page)
  await expect(page.locator('.header-model-label, .header-provider-label')).toHaveCount(0)
  await expect(page.getByLabel('图片端点')).toHaveValue('ark')
  await expect(page.getByLabel('图片模型')).toBeDisabled()
  await expect(page.getByLabel('图片模型').locator('option')).toHaveText(['Seedream 5.0 Pro'])

  await page.getByLabel('图片端点').selectOption('vertex')
  await expect.poll(() => providerChanges).toEqual(['vertex'])
  await expect(page.getByLabel('图片模型')).toBeEnabled()
  await expect(page.getByLabel('图片模型').locator('option')).toHaveText(['Gemini 3.1 Flash', 'Gemini 3 Pro'])
  await page.getByLabel('图片模型').selectOption('gemini-3-pro-image-preview')
  await expect.poll(() => modelChanges).toEqual(['gemini-3-pro-image-preview'])
  await expect(page.getByLabel('图片模型')).toHaveValue('gemini-3-pro-image-preview')

  await page.getByLabel('图片端点').selectOption('ark')
  await expect.poll(() => providerChanges).toEqual(['vertex', 'ark'])
  await expect(page.getByLabel('图片模型')).toBeDisabled()
  await expect(page.getByLabel('图片模型')).toHaveValue('seedream-5-0-pro')
})

test('Seedream supports validated custom dimensions and automatic sizing', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Seedream sizing only needs one desktop run')
  test.setTimeout(90_000)
  const submittedBodies = []
  const referenceUrl = '/api/workspace/assets/img_tabs/size-reference.png'
  await page.route(`**${referenceUrl}`, route => route.fulfill({
    status: 200,
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600"><rect width="800" height="600" fill="#111"/></svg>',
  }))
  await page.route('**/api/provider', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, current_provider: 'ark' }),
  }))
  await page.route('**/api/model', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, current_model: 'ignored-model', available_models: [] }),
  }))
  await page.route('**/api/generate', route => {
    submittedBodies.push(route.request().postDataJSON())
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queued: true, task_id: 1200 + submittedBodies.length, status: 'pending' }),
    })
  })
  await login(page, {
    initialWorkspaceState: {
      img_tabs: [{
        id: 1,
        prompt: '',
        aspectRatio: 'custom',
        resolution: '1K',
        customWidth: 2048,
        customHeight: 1024,
        uploadedImages: [{ name: 'size-reference.png', preview: referenceUrl }],
      }],
    },
  })

  await page.getByLabel('图片提示词').fill('Seedream custom size validation')
  const aspectRatio = page.getByLabel('画幅')
  await expect(aspectRatio).toHaveValue('custom')
  await aspectRatio.selectOption('custom')
  await expect(page.getByLabel('图片分辨率')).toBeHidden()
  const customWidth = page.getByLabel('自定义图片宽度')
  const customHeight = page.getByLabel('自定义图片高度')
  await expect(customWidth).toBeVisible()
  await expect(customHeight).toBeVisible()
  const referenceSizes = page.getByLabel('参考素材尺寸', { exact: true })
  await expect(referenceSizes.locator('option')).toContainText(['正在读取参考素材尺寸', '1. size-reference.png · 800×600'])
  await expect(referenceSizes).toHaveValue('')
  await referenceSizes.selectOption('0')
  await expect(customWidth).toHaveValue('1152')
  await expect(customHeight).toHaveValue('864')
  await customWidth.fill('512')
  await customHeight.fill('512')
  await expect(page.locator('.inspector-pane').getByRole('alert')).toContainText('总像素')
  const generateButton = page.getByRole('button', { name: '生成图片' })
  await expect(generateButton).toBeEnabled()
  await generateButton.click()
  expect(submittedBodies).toHaveLength(0)

  await customWidth.fill('2048')
  await customHeight.fill('1024')
  await page.getByRole('button', { name: '交换宽高' }).click()
  await expect(customWidth).toHaveValue('1024')
  await expect(customHeight).toHaveValue('2048')
  await page.getByRole('button', { name: '交换宽高' }).click()
  await expect(customWidth).toHaveValue('2048')
  await expect(customHeight).toHaveValue('1024')

  const aspectLockButton = page.getByRole('button', { name: /宽高比/ })
  await aspectLockButton.click()
  await expect(aspectLockButton).toHaveAttribute('aria-pressed', 'true')
  await customWidth.fill('1537')
  await expect(customHeight).toHaveValue('768')
  await expect(page.locator('.inspector-pane').getByRole('alert')).toContainText('16 的倍数')
  await page.getByRole('button', { name: '对齐到 16 px' }).click()
  await expect(customWidth).toHaveValue('1536')
  await expect(customHeight).toHaveValue('768')
  await customHeight.fill('1024')
  await expect(customWidth).toHaveValue('2048')
  await expect(page.locator('.inspector-header')).toContainText('2048×1024')
  await page.locator('.inspector-pane').screenshot({ path: testInfo.outputPath('desktop-seedream-custom-size.png') })
  await generateButton.click()
  await expect.poll(() => submittedBodies.length).toBe(1)
  expect(submittedBodies[0]).toMatchObject({
    aspect_ratio: 'custom',
    custom_width: 2048,
    custom_height: 1024,
  })
  expect(submittedBodies[0]).not.toHaveProperty('resolution')

  await aspectRatio.selectOption('auto')
  await expect(customWidth).toBeVisible()
  await expect(customHeight).toBeVisible()
  await page.getByLabel('图片分辨率').selectOption('2K')
  await expect(page.locator('.inspector-header')).toContainText('Auto · 2K')
  await generateButton.click()
  await expect.poll(() => submittedBodies.length).toBe(2)
  expect(submittedBodies[1]).toMatchObject({ aspect_ratio: 'auto', resolution: '2K' })
  expect(submittedBodies[1]).not.toHaveProperty('custom_width')
  expect(submittedBodies[1]).not.toHaveProperty('custom_height')

  await aspectRatio.selectOption('16:9')
  await expect(customWidth).toHaveValue('2816')
  await expect(customHeight).toHaveValue('1584')
  await customWidth.fill('2800')
  await expect(aspectRatio).toHaveValue('custom')
  await expect(customHeight).toHaveValue('1568')
  await expect(page.getByLabel('图片分辨率')).toBeHidden()
})

test('task navigation retries a transient network failure without UI noise', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Navigation retry only needs one desktop run')
  const preview = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  const task = {
    id: 77,
    type: 'image',
    status: 'succeeded',
    prompt: 'Navigation retry task',
    params: { aspect_ratio: '1:1', resolution: '1K', output_format: 'png' },
    provider: 'ark',
    favorite: false,
    favorite_groups: [],
    progress: 100,
    created_at: '2026-07-17T08:00:00+00:00',
    result: { local_images: [preview], local_refs: [] },
  }
  let navigationAttempts = 0
  await page.route('**/api/tasks?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, tasks: [task], total: 2 }),
  }))
  await page.route('**/api/tasks/77', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, task }),
  }))
  await page.route(/\/api\/tasks\/77\/navigation(?:\?|$)/, route => {
    navigationAttempts += 1
    if (navigationAttempts === 1) return route.abort('connectionfailed')
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        navigation: { position: 1, total: 2, previous_id: null, next_id: 78, first_id: 77, last_id: 78 },
      }),
    })
  })
  await login(page, { mockTasks: false })

  await page.getByTestId('task-gallery-card').click()
  const modal = page.getByRole('dialog', { name: '任务详情' })
  await expect(modal.getByText('1 / 2')).toBeVisible()
  expect(navigationAttempts).toBe(2)
  await expect(page.getByText('任务导航加载失败')).toHaveCount(0)
})

test('task gallery favorites persist and details open in a large modal', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Gallery interaction only needs one desktop run')
  test.setTimeout(120_000)
  const preview = `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="800" height="1200" viewBox="0 0 800 1200">
      <rect width="800" height="1200" fill="#07110d"/>
      <rect x="48" y="48" width="704" height="1104" rx="18" fill="#10251d" stroke="#5bf2ab" stroke-width="8"/>
      <circle cx="400" cy="420" r="210" fill="#1d5541"/>
      <path d="M180 940 L400 610 L620 940 Z" fill="#44c98b"/>
      <text x="400" y="1080" fill="#dfffee" font-size="54" text-anchor="middle" font-family="monospace">REFERENCE 01</text>
    </svg>
  `)}`
  const outputPreview = '/api/tasks/42/file/image_0.png'
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
    result: {
      local_images: [outputPreview],
      local_refs: [preview],
      source_urls: ['https://media.invalid/generated-image-42.png?token=endpoint-result'],
    },
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
      body: JSON.stringify({
        success: true,
        tasks: visible ? [task] : [],
        total: visible ? (wantsTrash ? 1 : 3) : 0,
      }),
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
  await page.route('**/api/tasks/42/file/image_0.png*', route => route.fulfill({
    status: 200,
    contentType: 'image/svg+xml',
    body: decodeURIComponent(preview.split(',', 2)[1]),
  }))

  const workspaceState = await login(page, { mockTasks: false, mockGroups: false })
  const historyCard = page.getByTestId('task-gallery-card').filter({ hasText: task.prompt })
  await expect(historyCard).toBeVisible()
  await historyCard.hover()
  await expect(historyCard.getByRole('button', { name: '删除任务' })).toBeVisible()
  await historyCard.getByRole('button', { name: '收藏任务' }).click()
  await expect(historyCard.getByRole('button', { name: '取消收藏任务' })).toBeVisible()

  await page.getByRole('group', { name: '任务视图' }).getByRole('button', { name: '收藏' }).click()
  await expect(historyCard).toBeVisible()
  await historyCard.click()
  const modal = page.getByRole('dialog', { name: '任务详情' })
  await expect(modal).toBeVisible()
  await expect(modal.getByText('1 / 3')).toBeVisible()
  await expect(modal.getByText(task.prompt)).toBeVisible()
  await expect(modal.getByAltText('任务输出')).toHaveAttribute(
    'src',
    '/api/tasks/42/file/image_0.png?png_info=1',
  )
  const sourceUrl = modal.getByRole('link', { name: 'https://media.invalid/generated-image-42.png?token=endpoint-result' })
  await expect(modal.getByText('端点图像 URL')).toBeVisible()
  await expect(sourceUrl).toHaveAttribute('href', 'https://media.invalid/generated-image-42.png?token=endpoint-result')
  await expect(sourceUrl).toHaveAttribute('target', '_blank')
  await expect.poll(async () => (await modal.boundingBox()).width).toBeGreaterThan(1340)
  const modalBeforeDrag = await modal.boundingBox()
  const dragHandle = modal.getByTestId('task-detail-drag-handle')
  const dragHandleBox = await dragHandle.boundingBox()
  await page.mouse.move(dragHandleBox.x + dragHandleBox.width * 0.62, dragHandleBox.y + dragHandleBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(dragHandleBox.x + dragHandleBox.width * 0.62 + 28, dragHandleBox.y + dragHandleBox.height / 2 + 20, { steps: 6 })
  await page.mouse.up()
  await expect.poll(async () => (await modal.boundingBox()).x).toBeGreaterThan(modalBeforeDrag.x + 10)
  await modal.getByRole('button', { name: '打开参考素材 1' }).click()
  const referenceModal = page.getByRole('dialog', { name: '参考素材预览' })
  await expect(referenceModal).toBeVisible()
  await expect(referenceModal.getByAltText('参考素材全图 1')).toBeVisible()
  await referenceModal.screenshot({ path: testInfo.outputPath('desktop-reference-preview-modal.png') })
  await page.keyboard.press('Escape')
  await expect(referenceModal).toBeHidden()
  await expect(modal).toBeVisible()
  await modal.getByRole('checkbox', { name: '角色设计' }).click()
  await expect(modal.getByRole('checkbox', { name: '角色设计' })).toHaveAttribute('aria-checked', 'true')
  await modal.getByRole('button', { name: '下载任务结果' }).click()
  const downloadMenu = modal.getByRole('menu', { name: '图片下载选项' })
  await expect(downloadMenu).toBeVisible()
  await expect(downloadMenu.getByRole('menuitem', { name: '带生成参数' })).toHaveAttribute(
    'download',
    'ink-traces-image-task-42-20260712083000-output-01.png',
  )
  await expect(downloadMenu.getByRole('menuitem', { name: '带生成参数' })).toHaveAttribute(
    'href',
    '/api/tasks/42/download/image_0.png',
  )
  await expect(downloadMenu.getByRole('menuitem', { name: '原始生成图' })).toHaveAttribute(
    'download',
    'ink-traces-image-task-42-20260712083000-output-01-original.png',
  )
  await expect(downloadMenu.getByRole('menuitem', { name: '原始生成图' })).toHaveAttribute(
    'href',
    '/api/tasks/42/download/image_0.png?raw=1',
  )
  await modal.getByRole('button', { name: '下载任务结果' }).click()
  await expect(downloadMenu).toBeHidden()
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
  await layoutMenu.getByRole('menuitemradio', { name: '紧凑' }).click()
  await layoutMenu.getByRole('menuitemradio', { name: '纯预览' }).click()
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

test('task gallery filters and compares selected results', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Desktop gallery workflow')
  const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  const sourceTasks = [
    {
      id: 301, type: 'image', status: 'succeeded', prompt: 'Neon editorial portrait', provider: 'ark',
      params: { model: 'seedream-a', resolution: '1K', aspect_ratio: '1:1', output_format: 'png' },
      result: { local_images: [pixel], local_thumbnails: [pixel] }, created_at: '2026-08-14T08:00:00Z',
    },
    {
      id: 302, type: 'image', status: 'succeeded', prompt: 'Glass product study', provider: 'ark',
      params: { model: 'seedream-b', resolution: '2K', aspect_ratio: '16:9', output_format: 'png' },
      result: { local_images: [pixel], local_thumbnails: [pixel] }, created_at: '2026-08-13T08:00:00Z',
    },
    {
      id: 303, type: 'image', status: 'failed', prompt: 'Failed Cupsy study', provider: 'cupsy',
      params: { model: 'seedream-c', resolution: '1K' }, result: {}, error: 'provider failed',
      created_at: '2026-08-12T08:00:00Z',
    },
  ]
  const listRequests = []
  await page.route('**/api/tasks/filter-options?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, providers: ['ark', 'cupsy'], models: ['seedream-a', 'seedream-b', 'seedream-c'] }),
  }))
  await page.route('**/api/tasks/selection?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, ids: [301, 302], total: 2 }),
  }))
  await page.route(/\/api\/tasks\/\d+$/, route => {
    const id = Number(new URL(route.request().url()).pathname.split('/').pop())
    const task = sourceTasks.find(item => item.id === id)
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, task }) })
  })
  await page.route('**/api/tasks?*', route => {
    const url = new URL(route.request().url())
    listRequests.push(Object.fromEntries(url.searchParams.entries()))
    const tasks = sourceTasks.filter(task => (
      (!url.searchParams.get('provider') || task.provider === url.searchParams.get('provider')) &&
      (!url.searchParams.get('status') || task.status === url.searchParams.get('status'))
    ))
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, tasks, total: tasks.length }),
    })
  })

  await login(page, { mockTasks: false, initialWorkspaceState: { appMode: 'image' } })
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(3)
  await expect(page.getByText('完成', { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: '筛选任务' }).click()
  await page.getByLabel('按任务端点筛选').selectOption('ark')
  await page.getByLabel('按任务状态筛选').selectOption('succeeded')
  await expect(page.getByTestId('task-gallery-card')).toHaveCount(2)
  await expect.poll(() => listRequests.at(-1)?.provider).toBe('ark')
  await expect.poll(() => listRequests.at(-1)?.status).toBe('succeeded')
  await expect(page.getByLabel('已应用筛选')).toContainText('BytePlus Ark')
  await expect(page.getByLabel('已应用筛选')).toContainText('已完成')

  await page.getByRole('button', { name: '批量选择任务' }).click()
  const cards = page.getByTestId('task-gallery-card')
  await cards.nth(0).click()
  await cards.nth(1).click()
  await page.getByRole('button', { name: '对比已选任务' }).click()
  const compare = page.getByRole('dialog', { name: '任务对比' })
  await expect(compare).toBeVisible()
  await expect(compare.getByText('TASK #301')).toBeVisible()
  await expect(compare.getByText('TASK #302')).toBeVisible()
  await compare.getByLabel('同步缩放').fill('1.5')
  await expect(compare.getByText('150%')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-task-compare.png') })
})

test('code rain loading canvas renders active pixels', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Canvas pixel check only needs one desktop run')
  await login(page)

  const referencePreview = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
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
      result: { local_refs: [referencePreview] },
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
  await page.route(/\/api\/tasks\/(\d+)$/, route => {
    const taskId = Number(new URL(route.request().url()).pathname.split('/').pop())
    const task = submittedTasks.find(item => item.id === taskId)
    return route.fulfill({
      status: task ? 200 : 404,
      contentType: 'application/json',
      body: JSON.stringify(task ? { success: true, task } : { success: false, error: '任务不存在' }),
    })
  })

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
  await loadingCard.click()
  const activeTaskModal = page.getByRole('dialog', { name: '任务详情' })
  await expect(activeTaskModal.getByRole('button', { name: '打开参考素材 1' })).toBeVisible()
  await activeTaskModal.getByRole('button', { name: '关闭任务详情' }).click()
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

test('video parameter references open image, video, and audio previews', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Reference media preview only needs one desktop run')
  const preview = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
  const videoUrl = '/api/upload_video/reference.mp4'
  const audioUrl = '/api/workspace/assets/vid_tabs/reference.wav'
  await page.route(`**${videoUrl}`, route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }))
  await page.route(`**${audioUrl}`, route => route.fulfill({ status: 200, contentType: 'audio/wav', body: '' }))
  await login(page, {
    initialWorkspaceState: {
      appMode: 'video',
      vid_activeTab: 1,
      vid_tabs: [{
        id: 1,
        prompt: '',
        ratio: 'adaptive',
        duration: 5,
        resolution: '720p',
        fast: false,
        audio: true,
        returnLastFrame: false,
        mode: 'reference',
        firstFrame: null,
        lastFrame: null,
        refImages: [{ name: 'reference.png', preview }],
        refVideos: [{ uid: 'video-1', name: 'reference.mp4', url: videoUrl, thumbnail: preview, uploading: false, progress: 100 }],
        refAudios: [{ name: 'reference.wav', preview: audioUrl, mimeType: 'audio/wav' }],
      }],
    },
  })

  await page.getByRole('button', { name: '打开视频参考图片 1' }).click()
  const imageDialog = page.getByRole('dialog', { name: '参考图片预览' })
  await expect(imageDialog.locator('img')).toHaveAttribute('src', preview)
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: '播放参考视频 1' }).click()
  const videoDialog = page.getByRole('dialog', { name: '参考视频播放' })
  await expect(videoDialog.getByTestId('reference-video-player')).toHaveAttribute('src', videoUrl)
  await videoDialog.screenshot({ path: testInfo.outputPath('desktop-reference-video-player.png') })
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: '播放参考音频 1' }).click()
  const audioDialog = page.getByRole('dialog', { name: '参考音频播放' })
  await expect(audioDialog.getByTestId('reference-audio-player')).toHaveAttribute('src', audioUrl)
  await audioDialog.screenshot({ path: testInfo.outputPath('desktop-reference-audio-player.png') })
  await page.keyboard.press('Escape')
})

test('all video reference types accept dropped and pasted files', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Video reference ingestion targets the desktop workspace')
  await page.route('**/api/upload_video', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        url: `/api/upload_video/${Date.now()}.mp4`,
        filepath: `/tmp/${Date.now()}.mp4`,
      }),
    })
  })
  await login(page, { initialWorkspaceState: { appMode: 'video' } })

  await dropFiles(page.getByTestId('video-first-frame-drop-zone'), [
    { name: 'dropped-first.png', type: 'image/png' },
  ])
  await expect(page.getByAltText('首帧')).toBeVisible()
  await pasteFiles(page, [{ name: 'pasted-last.png', type: 'image/png' }])
  await expect(page.getByAltText('尾帧')).toBeVisible()

  await page.getByLabel('视频生成模式').selectOption('reference')
  await dropFiles(page.getByTestId('video-reference-images-drop-zone'), [
    { name: 'dropped-image.png', type: 'image/png' },
  ])
  await dropFiles(page.getByTestId('video-reference-videos-drop-zone'), [
    { name: 'dropped-video.mp4', type: 'video/mp4' },
  ])
  await dropFiles(page.getByTestId('video-reference-audios-drop-zone'), [
    { name: 'dropped-audio.mp3', type: 'audio/mpeg' },
  ])
  await expect(page.getByTestId('video-reference-image-item-0')).toBeVisible()
  await expect(page.getByTestId('video-reference-video-item-0')).toBeVisible()
  await expect(page.getByTestId('video-reference-audio-item-0')).toBeVisible()

  await pasteFiles(page, [
    { name: 'pasted-image.png', type: 'image/png' },
    { name: 'pasted-video.mov', type: 'video/quicktime' },
    { name: 'pasted-audio.wav', type: 'audio/wav' },
  ])
  await expect(page.getByTestId('video-reference-image-item-1')).toBeVisible()
  await expect(page.getByTestId('video-reference-video-item-1')).toBeVisible()
  await expect(page.getByTestId('video-reference-audio-item-1')).toBeVisible()
})

test('reference materials can be reordered and generation preserves that order', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Reference sorting targets the desktop workspace')
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    'base64',
  )
  const assets = {
    imageFirst: '/api/workspace/assets/img_tabs/image-first.png',
    imageSecond: '/api/workspace/assets/img_tabs/image-second.png',
    videoImageFirst: '/test-assets/video-image-first.png',
    videoImageSecond: '/test-assets/video-image-second.png',
    audioFirst: '/test-assets/audio-first.wav',
    audioSecond: '/test-assets/audio-second.wav',
    videoFirst: '/api/upload_video/video-first.mp4',
    videoSecond: '/api/upload_video/video-second.mp4',
  }
  for (const url of [assets.imageFirst, assets.imageSecond, assets.videoImageFirst, assets.videoImageSecond]) {
    await page.route(`**${url}`, route => route.fulfill({ status: 200, contentType: 'image/png', body: png }))
  }
  for (const url of [assets.audioFirst, assets.audioSecond]) {
    await page.route(`**${url}`, route => route.fulfill({ status: 200, contentType: 'audio/wav', body: 'audio' }))
  }

  let imageSubmission = null
  let videoSubmission = ''
  await page.route('**/api/generate', route => {
    imageSubmission = route.request().postDataJSON()
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, queued: true, task_id: 1401, status: 'pending' }),
    })
  })
  await page.route('**/api/video/generate', route => {
    videoSubmission = route.request().postDataBuffer().toString('latin1')
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, task_id: 'video-order-1', db_task_id: 1402 }),
    })
  })
  await login(page, {
    initialWorkspaceState: {
      appMode: 'image',
      img_activeTab: 1,
      img_tabs: [{
        id: 1,
        prompt: '',
        background: 'default',
        uploadedImages: [
          { name: 'image-first.png', preview: assets.imageFirst },
          { name: 'image-second.png', preview: assets.imageSecond },
        ],
      }],
      vid_activeTab: 1,
      vid_tabs: [{
        id: 1,
        prompt: '',
        mode: 'reference',
        refImages: [
          { name: 'video-image-first.png', preview: assets.videoImageFirst },
          { name: 'video-image-second.png', preview: assets.videoImageSecond },
        ],
        refVideos: [
          { uid: 'video-first', name: 'video-first.mp4', url: assets.videoFirst, uploading: false },
          { uid: 'video-second', name: 'video-second.mp4', url: assets.videoSecond, uploading: false },
        ],
        refAudios: [
          { name: 'audio-first.wav', preview: assets.audioFirst },
          { name: 'audio-second.wav', preview: assets.audioSecond },
        ],
      }],
    },
  })

  await dragReference(page.getByRole('button', { name: /调整参考图片 1 顺序/ }), page.getByTestId('image-reference-item-1'))
  await expect(page.getByAltText('参考图片 1')).toHaveAttribute('src', assets.imageSecond)
  await page.getByLabel('图片提示词').fill('Reference order test')
  await page.getByRole('button', { name: '生成图片' }).click()
  await expect.poll(() => imageSubmission?.image_urls).toEqual([assets.imageSecond, assets.imageFirst])

  await page.getByRole('group', { name: '生成模式' }).getByRole('button', { name: '视频', exact: true }).click()
  await dragReference(page.getByRole('button', { name: /调整视频参考图片 1 顺序/ }), page.getByTestId('video-reference-image-item-1'))
  await dragReference(page.getByRole('button', { name: /调整参考视频 1 顺序/ }), page.getByTestId('video-reference-video-item-1'))
  const audioTarget = page.getByTestId('video-reference-audio-item-1')
  await audioTarget.scrollIntoViewIfNeeded()
  await dragReference(page.getByRole('button', { name: /调整参考音频 1 顺序/ }), audioTarget)

  await page.getByRole('button', { name: '打开视频参考图片 1' }).click()
  await expect(page.getByRole('dialog', { name: '参考图片预览' })).toContainText('video-image-second.png')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '播放参考视频 1' }).click()
  await expect(page.getByRole('dialog', { name: '参考视频播放' })).toContainText('video-second.mp4')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '播放参考音频 1' }).click()
  await expect(page.getByRole('dialog', { name: '参考音频播放' })).toContainText('audio-second.wav')
  await page.keyboard.press('Escape')

  await page.getByLabel('视频提示词').fill('Video reference order test')
  await page.getByRole('button', { name: '生成视频' }).click()
  await expect.poll(() => videoSubmission).not.toBe('')
  expect(videoSubmission.indexOf('video-image-second.png')).toBeLessThan(videoSubmission.indexOf('video-image-first.png'))
  expect(videoSubmission.indexOf('audio-second.wav')).toBeLessThan(videoSubmission.indexOf('audio-first.wav'))
  expect(videoSubmission.indexOf(assets.videoSecond)).toBeLessThan(videoSubmission.indexOf(assets.videoFirst))
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
  const addReferenceButton = page.getByRole('button', { name: '添加参考图片' })
  const plusAlignment = await addReferenceButton.evaluate(button => {
    const buttonRect = button.getBoundingClientRect()
    const iconRect = button.querySelector('svg').getBoundingClientRect()
    return {
      x: Math.abs((buttonRect.left + buttonRect.width / 2) - (iconRect.left + iconRect.width / 2)),
      y: Math.abs((buttonRect.top + buttonRect.height / 2) - (iconRect.top + iconRect.height / 2)),
    }
  })
  expect(plusAlignment.x).toBeLessThanOrEqual(1)
  expect(plusAlignment.y).toBeLessThanOrEqual(1)

  await expect.poll(() => submittedImageTabs?.[0]?.uploadedImages?.[0]?.preview || '')
    .toBe(workspaceAssetUrl)
  expect(submittedImageTabs[0].uploadedImages[0].file).toBeNull()
  expect(workspaceUploadCount).toBe(1)
  expect(workspaceUploadBytes).toBeGreaterThan(300 * 1024)
  expect(submittedStateBytes).toBeLessThan(100_000)
  await expect(page.getByAltText('参考图片 1')).toHaveAttribute('src', workspaceAssetUrl)

  await page.getByRole('button', { name: '打开参考图片 1' }).click()
  const imagePreview = page.getByRole('dialog', { name: '参考图片预览' })
  await expect(imagePreview).toBeVisible()
  await expect(imagePreview.locator('img')).toHaveAttribute('src', workspaceAssetUrl)
  await imagePreview.screenshot({ path: testInfo.outputPath('desktop-parameter-image-preview.png') })
  await page.keyboard.press('Escape')
  await expect(imagePreview).toBeHidden()

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
