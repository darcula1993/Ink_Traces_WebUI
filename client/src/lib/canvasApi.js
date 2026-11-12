import {isServerTaskStatus,isTerminalTaskStatus} from './taskStatus.js'
import axios from 'axios'
import {resolveNodeInputs} from './canvasReferences'
import {isSeedream55,imageParameterIssues,imageRequestFields} from './imageGenerationRules.js'
import { CUPSY_AUDIO_MODEL } from './generationSettings.js'

import {effectiveVideoModel,videoCapabilities,videoRatio,videoParameterError} from './videoGenerationRules.js'

const base = '/api/canvas'
const workflowUrl = id => `${base}/workflows/${encodeURIComponent(id)}`
const projectUrl = id => `${base}/projects/${encodeURIComponent(id)}`
const data = async promise => (await promise).data
export const getCanvasImageMetadata=async(workflowId,assetId,signal)=>(await data(axios.get(`${workflowUrl(workflowId)}/assets/${encodeURIComponent(assetId)}/metadata`,{signal}))).metadata
export const listCanvasProjects = async () => (await data(axios.get(`${base}/projects`))).projects
export const createCanvasProject = async title => (await data(axios.post(`${base}/projects`, { title }))).project
export const renameCanvasProject = async (id, title) => (await data(axios.patch(projectUrl(id), { title }))).project
export const listCanvasWorkflows = async id => (await data(axios.get(`${projectUrl(id)}/workflows`))).workflows
export const createCanvasWorkflow = async (id, title) => (await data(axios.post(`${projectUrl(id)}/workflows`, { title }))).workflow
export const getCanvasWorkflow = async id => (await data(axios.get(workflowUrl(id)))).workflow
export const saveCanvasWorkflow = async (id, value) => (await data(axios.put(workflowUrl(id), value))).workflow

export const getProjectGenerationSettings = async id => (await data(axios.get(`${projectUrl(id)}/generation-settings`))).settings
export const saveProjectGenerationSettings = async (id, settings) => (await data(axios.put(`${projectUrl(id)}/generation-settings`, settings))).settings
export const selectedProvider = (capabilities,choice,kind) => choice ? capabilities[kind]?.find(p=>p.provider===choice.provider&&(p.profile_id||null)===(choice.profile_id||null)) : null
export const projectProvider = (capabilities,settings,kind) => selectedProvider(capabilities,settings?.providers?.[kind],kind)
export const nodeProvider = (capabilities,settings,node) => node?.providerSelection ? selectedProvider(capabilities,node.providerSelection,node.type) : projectProvider(capabilities,settings,node?.type)
const selectionKey=choice=>choice?`${choice.provider}:${choice.profile_id||''}`:'inherit'

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

export async function getCanvasCapabilities() {
  const [image, video, audio, saved] = await Promise.all([
    data(axios.get('/api/provider')), data(axios.get('/api/video/provider')), data(axios.get('/api/audio/provider')),
    data(axios.get('/api/provider-profiles')),
  ])
  const available = info => Object.entries(info.providers || {}).filter(([, value]) => value.available)
  const legacy = {
    image: available(image).map(([id, p]) => ({ id, provider: id, name: `${p.name || id}（原配置）`, model: p.model, capability_model: p.capability_model })),
    video: available(video).map(([id, p]) => ({ id, provider: id, name: `${id === 'ark' ? 'BytePlus Ark' : 'Cupsy'}（原配置）`, models: (p.models || []).map(model => ({ id: model, name: model })) })),
    audio: available(audio).map(([id, p]) => ({ id, provider: id, name: 'Cupsy（原配置）', model: p.models?.[0] || CUPSY_AUDIO_MODEL })),
  }
  const profiles = (saved.profiles || []).filter(p => p.enabled && p.has_api_key).sort((a, b) => Number(b.is_default) - Number(a.is_default))
  return Object.fromEntries(['image', 'video', 'audio'].map(kind => [kind, [
    ...profiles.filter(p => p.kind === kind).map(p => ({
      id: `profile:${p.id}`, provider: p.adapter, profile_id: p.id,
      name: `${p.name}${p.is_default ? ' · 默认' : ''}`, revision: p.revision,
      capability_model: p.adapter==='ark' && p.settings.model===image.providers?.ark?.model ? image.providers.ark.capability_model : p.settings.model,
      model: kind === 'video' ? (p.adapter === 'cupsy' ? p.settings.model || 'seedance-2.5' : 'seedance-2.0') : p.settings.model || (kind === 'audio' ? CUPSY_AUDIO_MODEL : image.providers?.[p.adapter]?.model),
      ...(kind === 'video' ? { models: (video.providers?.[p.adapter]?.models || (p.adapter === 'cupsy' ? ['seedance-2.5', 'seedance-2.5-moderated'] : ['seedance-2.0', 'seedance-2.5'])).map(id => ({ id, name: id })) } : {}),
    })), ...legacy[kind],
  ]]))
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

async function referenceFiles(workflowId, assets) {
  return Promise.all(assets.map(async asset => {
    if (!asset.url?.startsWith(`${workflowUrl(workflowId)}/assets/`) || !['image', 'video', 'audio'].includes(asset.kind)) invalid('参考素材必须先保存到当前画布')
    try {
      const response = await axios.get(asset.url, { responseType: 'blob' })
      return { asset, blob: response.data }
    } catch {
      invalid(`无法读取参考素材“${asset.name || asset.id}”，尚未提交生成`)
    }
  }))
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
  const settings = savedNode.providerSelection ? null : await getProjectGenerationSettings(workflow.project_id).catch(() => invalid('无法读取项目默认接口，尚未提交生成'))
  const provider = nodeProvider(capabilities, settings, savedNode)
  if (!provider) invalid(savedNode.providerSelection?'节点所选接口已停用或不可用，请重新选择':'尚未配置可用的项目默认接口，请选择节点接口或项目默认接口')
  const images = assets.filter(a => a.kind === 'image')
  const videos = assets.filter(a => a.kind === 'video')
  const audios = assets.filter(a => a.kind === 'audio')
  if (assets.some(a => !['image', 'video', 'audio'].includes(a.kind))) invalid('不支持的参考素材类型')
  let path
  const adapter = provider.provider || provider.id
  const fields = { prompt, canvas_workflow_id: workflowId, canvas_node_id:node.id, canvas_workflow_revision:workflow.revision, ...(settings?{project_settings_revision:settings.revision}:{}), provider: adapter, ...(provider.profile_id ? { profile_id: provider.profile_id } : {}) }
  if (node.type === 'image') {
    if (videos.length || audios.length) invalid('图像生成只接受图片参考；请调整素材或素材组')
    let references=images
    if(params.background&&params.background!=='default'&&adapter==='ark'&&!isSeedream55(provider.capability_model||provider.model)&&images.length===1){const metadata=await getCanvasImageMetadata(workflowId,images[0].id).catch(()=>invalid('无法读取参考图片 Alpha 信息，尚未提交生成'));references=[{...images[0],...metadata}]}
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
    Object.assign(fields, { model: provider.model, output_format: 'mp3', sample_rate: 48000, enable_subtitle: true, reference_mode: images.length ? 'image' : audios.length ? 'audio' : 'none' })
    path = '/api/audio/generate'
  } else invalid('该节点不支持生成')

  const files = await referenceFiles(workflowId, assets)
  let body = fields
  if (files.length) {
    body = new FormData()
    for (const [name, value] of Object.entries(fields)) if (value !== undefined) body.append(name, String(value))
    for (const { asset, blob } of files) {
      const field = node.type === 'image' ? 'images' : node.type === 'audio' ? 'references' : { image: 'ref_images', video: 'ref_videos', audio: 'ref_audios' }[asset.kind]
      if (node.type === 'video' && fields.video_mode === 'keyframe') {
        for (const [role, name] of [['first_frame','image'], ['last_frame','last_image']]) if ((role === 'first_frame' ? frames.first?.id : frames.last?.id) === asset.id) body.append(name, blob, asset.name || 'frame.png')
        continue
      }
      body.append(field, blob, asset.name || `reference.${asset.kind === 'image' ? 'png' : asset.kind === 'video' ? 'mp4' : 'wav'}`)
    }
  }
  // A network error after this point may still have created a billed task.
  // Callers must retain an unknown state, never automatically resubmit.
  const result = await data(axios.post(path, body, { timeout: 300000 }))
  const id = result.db_task_id || result.task_id
  if (!Number.isInteger(id) || id <= 0) throw new Error('提交结果未返回本地任务编号，请在任务记录中核查')
  // A created task is always in flight; a non-vocabulary status is not stored.
  return { id, status: isServerTaskStatus(result.status) && !isTerminalTaskStatus(result.status) ? result.status : 'pending', ...(result.status && !isServerTaskStatus(result.status) ? { invalidStatus: String(result.status) } : {}) }
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
export const listPendingCanvasDeletions = async () => (await data(axios.get(`${base}/deletions`))).deletions
export async function downloadProjectFolder(id,folderId,title) {
  const response=await fetch(`${projectUrl(id)}/folders/${encodeURIComponent(folderId)}/download`)
  if(!response.ok){let message='文件夹下载失败，请重试';try{message=(await response.json()).error||message}catch{}throw new Error(message)}
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=`${title}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
