import {isServerTaskStatus,isTerminalTaskStatus} from './taskStatus.js'
import axios from 'axios'
import {normalizeSavedWorkflow} from './canvasTaskPolling.js'
import {resolveNodeInputs} from './canvasReferences.js'
import {isSeedream55,imageParameterIssues,imageRequestFields} from './imageGenerationRules.js'
import { CUPSY_AUDIO_MODEL, canvasAudioParams, canvasAudioIssue, videoModelLabel } from './generationSettings.js'
import {nodeProvider,selectionKey,normalizeProviderPreferences} from './canvasProviderSelection.js'
import {isMediaAsset,markDeletedMedia,markTrashedMedia} from './canvasMediaStatus.js'
import {assertMediaAvailable} from './canvasMedia.js'

import {effectiveVideoModel,videoCapabilities,videoRatio,videoParameterError} from './videoGenerationRules.js'

const base = '/api/canvas'
const workflowUrl = id => `${base}/workflows/${encodeURIComponent(id)}`
const projectUrl = id => `${base}/projects/${encodeURIComponent(id)}`
const data = async promise => (await promise).data
// LIBRARY-GLOBAL S5 (aligned with S2/S1b): the same route also accepts a library media id.
export const getCanvasImageMetadata=async(workflowId,asset,signal)=>{const id=typeof asset==='string'?asset:asset?.id;return (await data(axios.get(`${workflowUrl(workflowId)}/assets/${encodeURIComponent(id)}/metadata`,{signal}))).metadata}
export const listCanvasProjects = async () => (await data(axios.get(`${base}/projects`))).projects
export const createCanvasProject = async title => (await data(axios.post(`${base}/projects`, { title }))).project
export const renameCanvasProject = async (id, title) => (await data(axios.patch(projectUrl(id), { title }))).project
export const listCanvasWorkflows = async id => (await data(axios.get(`${projectUrl(id)}/workflows`))).workflows
export const createCanvasWorkflow = async (id, title) => (await data(axios.post(`${projectUrl(id)}/workflows`, { title }))).workflow
export const duplicateCanvasWorkflow = async (id, title) => (await data(axios.post(`${workflowUrl(id)}/duplicate`, title ? { title } : {}))).workflow
export const getCanvasWorkflow = async id => (await data(axios.get(workflowUrl(id)))).workflow
// CANVAS-WRITEBACK-20261114 C: a PUT whose base revision is only behind server
// write-backs is merged by the server and answered with {merged:true, revision, document}
// (accepted at the top level or inside `workflow`).
export const saveCanvasWorkflow = async (id, value) => normalizeSavedWorkflow(id, await data(axios.put(workflowUrl(id), value)))
// FIX-B2-20261114 #2: page-exit flush. The same PUT as saveCanvasWorkflow (same body, same revision), sent
// with fetch keepalive so the browser completes it after pagehide. Bodies over KEEPALIVE_MAX_BYTES are not
// accepted by browsers for keepalive; the caller then keeps the regular save path.
export const KEEPALIVE_MAX_BYTES = 60 * 1024
export const keepaliveBodyFits = body => new Blob([body]).size <= KEEPALIVE_MAX_BYTES
export async function saveCanvasWorkflowKeepalive(id, body) {
  const response = await fetch(workflowUrl(id), { method: 'PUT', body, keepalive: true, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' } })
  let result = null
  try { result = await response.json() } catch { result = null }
  if (!response.ok) {
    const error = new Error(result?.error || `保存失败（${response.status}）`)
    error.status = response.status; error.response = { status: response.status, data: result }
    throw error
  }
  return normalizeSavedWorkflow(id, result || {})
}
// D: idempotent compensation; the server writes terminal results into the document
// (no Provider call) and returns {revision, nodes:{node_id: written-back fields}}.
export const TASK_SYNC_BATCH = 100
export async function syncCanvasTasks(workflowId, taskIds) {
  const ids = [...new Set(taskIds.map(Number).filter(id => Number.isInteger(id) && id > 0))]
  let revision = null
  const nodes = {}
  for (let index = 0; index < ids.length; index += TASK_SYNC_BATCH) {
    const result = await data(axios.post(`${workflowUrl(workflowId)}/task-sync`, { task_ids: ids.slice(index, index + TASK_SYNC_BATCH) }))
    if (Number.isInteger(result.revision)) revision = Math.max(revision ?? 0, result.revision)
    Object.assign(nodes, result.nodes || {})
  }
  return { revision, nodes }
}
// VERSION-SNAPSHOT-20261123: legacy fallback lookup for historical versions without an inline node snapshot.
export const VERSION_SNAPSHOT_BATCH = 100
export async function fetchVersionSnapshots(workflowId, mediaIds) {
  if (!workflowId || !Array.isArray(mediaIds)) return {}
  const ids = [...new Set(mediaIds.filter(id => typeof id === 'string' && /^[0-9a-f]{32}$/.test(id)))]
  if (!ids.length) return {}
  const snapshots = {}
  for (let index = 0; index < ids.length; index += VERSION_SNAPSHOT_BATCH) {
    const result = await data(axios.post(`${workflowUrl(workflowId)}/version-snapshots`, { media_ids: ids.slice(index, index + VERSION_SNAPSHOT_BATCH) }))
    if (result?.snapshots && typeof result.snapshots === 'object' && !Array.isArray(result.snapshots)) Object.assign(snapshots, result.snapshots)
  }
  return snapshots
}

export {selectedProvider,nodeProvider,defaultProviderSelection} from './canvasProviderSelection.js'
// Last interface chosen per node type; server workspace state keeps it consistent across devices.
const PREFERENCES_URL = '/api/workspace/state/canvas_provider_preferences'
export const getCanvasProviderPreferences = async () => normalizeProviderPreferences((await data(axios.get(PREFERENCES_URL))).state?.value)
export const saveCanvasProviderPreferences = async value => normalizeProviderPreferences((await data(axios.put(PREFERENCES_URL, { value }))).state?.value)

async function upload(url, file) {
  const body = new FormData()
  body.append('file', file, file.name || 'media')
  return (await data(axios.post(url, body))).asset
}
export const uploadCanvasMedia = (id, file) => upload(`${workflowUrl(id)}/assets`, file)
export const listProjectAssets = async id => (await data(axios.get(`${projectUrl(id)}/assets`))).assets
export const uploadProjectAsset = (id, file) => upload(`${projectUrl(id)}/assets`, file)
export const listProjectAssetGroups = async id => (await data(axios.get(`${projectUrl(id)}/asset-groups`))).groups
export const createProjectAssetGroup = async (id, title, assetIds) => (await data(axios.post(`${projectUrl(id)}/asset-groups`, { title, asset_ids: assetIds }))).group
export const resolveCanvasReferences = (id, selection) => data(axios.post(`${workflowUrl(id)}/reference-assets`, selection))

// CHARACTER-LIBRARY-20261114 C: the global character library and the import of a character's
// reference images / voice into the current canvas (idempotent on the server: same content → same
// canvas asset). The result is only used to write ordinary references and prompt text; character
// metadata never goes into a generation request.
export const listCharacters = async () => (await data(axios.get('/api/characters'))).characters || []
export async function importCharacterAssets(workflowId, characterId, { imageIds = [], voice = false } = {}) {
  const result = await data(axios.post(`${workflowUrl(workflowId)}/character-assets`, { character_id: characterId, image_ids: imageIds, ...(voice ? { voice: true } : {}) }))
  const assets = Array.isArray(result.assets) ? result.assets : imageIds.map(id => result.mapping?.[id])
  if (assets.length !== imageIds.length || assets.some(asset => !asset?.id || asset.kind !== 'image')) throw new Error('角色卡参考图导入结果无效，未插入角色卡')
  if (voice && (!result.voice?.id || result.voice.kind !== 'audio')) throw new Error('角色卡参考音频导入结果无效，未插入角色卡')
  return { assets, voice: voice ? result.voice : null }
}

export function buildCapabilities(image, video, audio, saved) {
  const available = info => Object.entries(info?.providers || {}).filter(([, value]) => value.available && !value.managed_by_profiles)
  const legacy = {
    image: available(image).map(([id, p]) => ({ id, provider: id, name: `${p.name || id}（原配置）`, model: p.model, capability_model: p.capability_model })),
    video: available(video).map(([id, p]) => ({ id, provider: id, name: `${id === 'ark' ? 'BytePlus Ark' : 'Cupsy'}（原配置）`, models: (p.models || []).map(model => ({ id: model, name: videoModelLabel(model) })) })),
    audio: available(audio).map(([id, p]) => ({ id, provider: id, name: 'Cupsy（原配置）', model: p.models?.[0] || CUPSY_AUDIO_MODEL })),
  }
  const profiles = (saved?.profiles || []).filter(p => p.enabled && p.has_api_key).sort((a, b) => Number(b.is_default) - Number(a.is_default))
  return Object.fromEntries(['image', 'video', 'audio'].map(kind => {
    const kindProfiles = profiles.filter(p => p.kind === kind).map(p => {
      const settings = p.settings || {}
      const imageDefault = p.adapter === 'cupsy' ? 'seedream-5.0-pro' : 'seedream-5-0-pro'
      const explicitCapability = kind === 'image' && p.adapter === 'ark' ? String(settings.capability_model || '').trim() : ''
      const capabilityModel = explicitCapability
        ? explicitCapability
        : p.capability_model !== undefined && p.capability_model !== null
          ? p.capability_model
          : p.adapter === 'ark' && settings.model && settings.model === image?.providers?.ark?.model
            ? image.providers.ark.capability_model
            : kind === 'image'
              ? (settings.model || imageDefault)
              : settings.model
      return {
        id: `profile:${p.id}`, provider: p.adapter, profile_id: p.id, is_default: !!p.is_default,
        ...(p.source_key ? { source_key: p.source_key } : {}),
        name: `${p.name}${p.is_default ? ' · 默认' : ''}`, revision: p.revision,
        capability_model: capabilityModel,
        model: kind === 'video' ? (p.adapter === 'cupsy' ? settings.model || 'seedance-2.5' : 'seedance-2.0') : (settings.model || (kind === 'audio' ? CUPSY_AUDIO_MODEL : imageDefault)),
        ...(kind === 'video' ? { models: (video?.providers?.[p.adapter]?.models || (p.adapter === 'cupsy' ? ['seedance-2.5', 'seedance-2.5-moderated'] : ['seedance-2.0', 'seedance-2.5'])).map(id => ({ id, name: videoModelLabel(id) })) } : {}),
      }
    })
    const importedAdapters = new Set(kindProfiles.filter(p => p.source_key === `config:${kind}:${p.provider}`).map(p => p.provider))
    return [kind, [...kindProfiles, ...legacy[kind].filter(item => !importedAdapters.has(item.provider))]]
  }))
}

export async function getToolCapabilities() {
  const [image, video, audio, saved] = await Promise.all([
    data(axios.get('/api/provider')), data(axios.get('/api/video/provider')), data(axios.get('/api/audio/provider')),
    data(axios.get('/api/provider-profiles')),
  ])
  return { capabilities: buildCapabilities(image, video, audio, saved), image, video, audio, saved }
}

export async function getCanvasCapabilities() {
  return (await getToolCapabilities()).capabilities
}

function invalid(message) {
  const error = new Error(message)
  error.validation = true
  throw error
}

// No traversal execution: edges only resolve the selected, already existing input.
export function canvasInputs(node, nodes, edges) {
  const result = resolveNodeInputs(node,nodes,edges)
  if(result.issues.length) invalid(result.issues[0])
  return {prompt:result.prompt,assets:result.assets,frames:result.frames}
}

// GEN-RESULT-LIFECYCLE-20261119 (plan A): references are submitted by library id (no browser download and
// re-upload); the server resolves each id to the library file, refuses unknown/deleted/trashed/mistyped ones
// before creating a task, and keeps a hard-link snapshot in the task. Field, order and filename are exactly
// what the old multipart upload sent, so the Provider request is unchanged.
function referenceEntries(workflowId, assets) {
  return assets.map(asset => {
    // LIBRARY-GLOBAL S5: references are library media (/api/canvas/media/<id>); old canvas assets stay readable until migrated.
    if (!(isMediaAsset(asset) || asset.url?.startsWith(`${workflowUrl(workflowId)}/assets/`)) || !['image', 'video', 'audio'].includes(asset.kind)) invalid('参考素材必须先保存到当前画布')
    return asset
  })
}
export function referenceMediaField(nodeType, videoMode, frames, assets) {
  const entries = []
  for (const asset of assets) {
    const field = nodeType === 'image' ? 'images' : nodeType === 'audio' ? 'references' : { image: 'ref_images', video: 'ref_videos', audio: 'ref_audios' }[asset.kind]
    if (nodeType === 'video' && videoMode === 'keyframe') {
      for (const [role, name] of [['first_frame', 'image'], ['last_frame', 'last_image']]) if ((role === 'first_frame' ? frames.first?.id : frames.last?.id) === asset.id) entries.push({ field: name, id: asset.id, filename: asset.name || 'frame.png' })
      continue
    }
    entries.push({ field, id: asset.id, filename: asset.name || `reference.${asset.kind === 'image' ? 'png' : asset.kind === 'video' ? 'mp4' : 'wav'}` })
  }
  return entries
}

export async function submitCanvasGeneration(workflowId, node, nodes, edges) {
  const { prompt, assets, frames } = canvasInputs(node, nodes, edges)
  if (!prompt) invalid('请填写生成提示词')
  const capabilities = await getCanvasCapabilities().catch(() => invalid('无法读取生成服务配置，尚未提交生成'))
  const params = node.params || {}
  const workflow = await getCanvasWorkflow(workflowId).catch(() => invalid('无法读取画布所属项目，尚未提交生成'))
  const savedNode=workflow.document.nodes.find(item=>item.id===node.id)
  if(!savedNode||savedNode.type!==node.type)invalid('节点已不存在或类型已改变，请重新载入画布')
  if(selectionKey(savedNode.providerSelection)!==selectionKey(node.providerSelection))invalid('节点接口已被其他窗口修改，请重新载入画布后确认；尚未提交生成')
  if(!savedNode.providerSelection)invalid('请先为节点选择接口')
  const provider = nodeProvider(capabilities, savedNode)
  if (!provider) invalid('节点所选接口已停用或不可用，请重新选择')
  const images = assets.filter(a => a.kind === 'image')
  const videos = assets.filter(a => a.kind === 'video')
  const audios = assets.filter(a => a.kind === 'audio')
  if (assets.some(a => !['image', 'video', 'audio'].includes(a.kind))) invalid('不支持的参考素材类型')
  let path
  const adapter = provider.provider || provider.id
  const fields = { prompt, canvas_workflow_id: workflowId, canvas_node_id:node.id, ...(node.title ? { result_name: String(node.title) } : {}), canvas_workflow_revision:workflow.revision, provider: adapter, ...(savedNode.providerSelection?.profile_id && provider.profile_id ? { profile_id: provider.profile_id } : {}) }
  if (node.type === 'image') {
    if (videos.length || audios.length) invalid('图像生成只接受图片参考；请调整素材或素材组')
    let references=images
    if(params.background&&params.background!=='default'&&adapter==='ark'&&!isSeedream55(provider.capability_model||provider.model)&&images.length===1){const metadata=await getCanvasImageMetadata(workflowId,images[0]).catch(()=>invalid('无法读取参考图片 Alpha 信息，尚未提交生成'));references=[{...images[0],...metadata}]}
    const issues=imageParameterIssues(adapter,params,references,provider.capability_model||provider.model);if(issues.length)invalid(issues.join('；'))
    Object.assign(fields,imageRequestFields(adapter,params,provider.model))
    path = '/api/generate'
  } else if (node.type === 'video') {
    if(params.generate_audio!==undefined&&typeof params.generate_audio!=='boolean')invalid('输出音频必须是布尔值，请重新设置')
    const model = effectiveVideoModel(params.model,provider.models)
    if (!provider.models?.some(m => m.id === model)) invalid('当前服务不支持所选视频模型')
    const spec = videoCapabilities(model)
    const ratio=videoRatio(model,params.video_mode,images.length>0,params.ratio||'16:9').value
    const parameterError=videoParameterError({model,duration:params.duration??5,resolution:params.resolution||'720p',ratio})
    if(parameterError)invalid(parameterError)
    const duration = Number(params.duration ?? 5)
    if (images.length > spec.maxRefImages || videos.length > spec.maxRefVideos || audios.length > spec.maxRefAudios) invalid('参考素材数量超过所选视频模型上限')
    if (model === 'seedance-2.0' && audios.length && !images.length && !videos.length) invalid('Seedance 2.0 使用音频参考时还需要图片或视频')
    Object.assign(fields, { model, ratio, resolution: params.resolution || '720p', duration, video_mode: params.video_mode || 'reference', generate_audio: params.generate_audio ?? true, output_format: 'mp4' })
    if (!['reference', 'keyframe'].includes(fields.video_mode)) invalid('不支持的视频模式')
    if (adapter === 'cupsy' && fields.video_mode === 'reference') {
      fields.omni_reference_task_type = params.omni_reference_task_type || 'auto'
      if (!['auto', 'reference', 'edit', 'extend'].includes(fields.omni_reference_task_type)) invalid('不支持的任务类型')
    }
    path = '/api/video/generate'
  } else if (node.type === 'audio') {
    if (videos.length || (images.length && audios.length) || images.length > 1 || audios.length > 3) invalid('音频参考支持 1 张图片或最多 3 段音频，不能混用；请调整素材组')
    if (prompt.length > 3000) invalid('音频提示词不能超过 3000 个字符')
    // V140 #13: output parameters come from node.params (defaults: model-chosen voice, mp3, 48000, subtitles on).
    const audio = canvasAudioParams(params), issue = canvasAudioIssue(params, { image: images.length, audio: audios.length })
    if (issue) invalid(issue)
    Object.assign(fields, { model: provider.model, output_format: audio.output_format, sample_rate: audio.sample_rate, enable_subtitle: audio.enable_subtitle, reference_mode: images.length ? 'image' : audios.length || audio.speaker ? 'audio' : 'none', ...(audio.speaker ? { speaker: audio.speaker } : {}) })
    path = '/api/audio/generate'
  } else invalid('该节点不支持生成')

  await assertMediaAvailable(assets, invalid)
  const references = referenceEntries(workflowId, assets)
  let body = fields
  if (references.length) {
    body = new FormData()
    for (const [name, value] of Object.entries(fields)) if (value !== undefined) body.append(name, String(value))
    body.append('reference_media', JSON.stringify(referenceMediaField(node.type, fields.video_mode, frames, references)))
  }
  // A network error after this point may still have created a billed task.
  // Callers must retain an unknown state, never automatically resubmit.
  let result
  try { result = await data(axios.post(path, body, { timeout: 300000 })) } catch (error) {
    // The server refused a reference before creating any task (400): show it like the old pre-upload check.
    const code = error?.response?.status === 400 && error.response.data?.code
    if (code === 'media_deleted' || code === 'media_trashed') {
      const asset = references.find(item => item.id === error.response.data.reference_id)
      if (asset && isMediaAsset(asset)) { if (code === 'media_trashed') markTrashedMedia([asset.id]); else markDeletedMedia([asset.id]) }
      invalid(error.response.data.error)
    }
    if (code === 'media_not_found' || code === 'reference_kind_mismatch' || code === 'invalid_reference') invalid(error.response.data.error)
    throw error
  }
  const id = result.db_task_id || result.task_id
  if (!Number.isInteger(id) || id <= 0) throw new Error('提交结果未返回本地任务编号，请在任务记录中核查')
  // A created task is always in flight; a non-vocabulary status is not stored.
  return { id, status: isServerTaskStatus(result.status) && !isTerminalTaskStatus(result.status) ? result.status : 'pending', ...(result.status && !isServerTaskStatus(result.status) ? { invalidStatus: String(result.status) } : {}) }
}

// Task detail without importing results (result_unknown fallback for older status previews).
export async function getTaskDetail(taskId) {
  const { task } = await data(axios.get(`/api/tasks/${taskId}`))
  return { id: task.id, status: task.status, error: task.error, resultUnknown: task.status === 'failed' && task.result?.result_unknown === true }
}

export async function cancelCanvasTask(taskId) {
  const id = Number(taskId)
  if (!Number.isInteger(id) || id <= 0) invalid('任务编号无效，无法取消')
  const result = await data(axios.post(`/api/tasks/${encodeURIComponent(id)}/cancel`))
  const rawStatus = result.task?.status ?? result.status
  const status = isServerTaskStatus(rawStatus) ? rawStatus : null
  return {
    id: Number(result.task?.id || id),
    status,
    invalidStatus: status ? null : (rawStatus ? String(rawStatus) : null),
    error: result.task?.error || null,
    resultUnknown: status === 'failed' && result.task?.result?.result_unknown === true,
    task: result.task || null,
  }
}

export async function getCanvasTask(workflowId, taskId) {
  const { task } = await data(axios.get(`/api/tasks/${taskId}`))
  let assets = []
  if (task.status === 'succeeded') assets = (await data(axios.post(`${workflowUrl(workflowId)}/task-results`, { task_id: taskId }))).assets
  return { id: task.id, type: task.type, status: task.status, error: task.error, resultUnknown: task.status === 'failed' && task.result?.result_unknown === true, assets }
}

export const TASK_STATUS_BATCH = 100
// One lightweight request per 100 tasks. Missing ids are returned separately so
// callers can keep per-node isolation instead of failing the whole batch.
export async function getTaskStatuses(ids) {
  const unique = [...new Set(ids.map(Number).filter(id => Number.isInteger(id) && id > 0))]
  const tasks = [], missing = [], failed = []
  for (let index = 0; index < unique.length; index += TASK_STATUS_BATCH) {
    const chunk = unique.slice(index, index + TASK_STATUS_BATCH)
    try {
      const result = await data(axios.get('/api/tasks/status', { params: { ids: chunk.join(',') } }))
      tasks.push(...(result.tasks || []))
      missing.push(...(result.missing_ids || []).map(Number))
    } catch { failed.push(...chunk) }
  }
  return { tasks, missing, failed }
}

export const listProjectAssetTree = async id => data(axios.get(`${projectUrl(id)}/assets`))
export const listProjectFolders = async id => (await data(axios.get(`${projectUrl(id)}/folders`))).folders
export const createProjectFolder = async (id,title,parent_id=null) => (await data(axios.post(`${projectUrl(id)}/folders`,{title,parent_id}))).folder
export const updateProjectFolder = async (id,folderId,value) => (await data(axios.patch(`${projectUrl(id)}/folders/${encodeURIComponent(folderId)}`,value))).folder
export const deleteProjectFolder = (id,folderId) => data(axios.delete(`${projectUrl(id)}/folders/${encodeURIComponent(folderId)}`))
export const updateProjectAsset = (id,assetId,value) => data(axios.patch(`${projectUrl(id)}/assets/${encodeURIComponent(assetId)}`,value))
export const deleteCanvasObject = (kind,id,cleanup_assets=false) => data(axios.delete(kind==='project'?projectUrl(id):workflowUrl(id),{data:{cleanup_assets}}))
export const previewBulkDeleteProjects = ids => data(axios.post(`${base}/projects/bulk-delete-preview`, { ids }))
export const bulkDeleteProjects = (ids, cleanup_assets = false) => data(axios.post(`${base}/projects/bulk-delete`, { ids, cleanup_assets }))
export const listPendingCanvasDeletions = async () => (await data(axios.get(`${base}/deletions`))).deletions
export async function downloadProjectFolder(id,folderId,title) {
  const response=await fetch(`${projectUrl(id)}/folders/${encodeURIComponent(folderId)}/download`)
  if(!response.ok){let message='文件夹下载失败，请重试';try{message=(await response.json()).error||message}catch{}throw new Error(message)}
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`${title}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
