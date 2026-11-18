import {VIDEO_MODEL_CAPABILITIES,SEEDANCE_25,SEEDANCE_25_MODERATED} from './generationSettings.js'

export const VIDEO_RATIOS = ['adaptive','16:9','4:3','1:1','3:4','9:16','21:9']
export const VIDEO_AUTO_DURATION = -1
export const effectiveVideoModel = (model,models=[]) => model || models[0]?.id || ''
export const videoCapabilities = model => VIDEO_MODEL_CAPABILITIES[model===SEEDANCE_25_MODERATED?SEEDANCE_25:model]
export const videoDurations = model => {
 const spec=videoCapabilities(model)
 return spec?[...Array.from({length:spec.maxDuration-spec.minDuration+1},(_,i)=>spec.minDuration+i),VIDEO_AUTO_DURATION]:[]
}
// NODE-TOOLBAR-VERSIONS-20261118 (user 11-18): a NEW video generation node starts at 480p, or at the lowest resolution
// the model supports when 480p is not among them. Only for new nodes; saved nodes keep their own value (and the old
// `|| '720p'` fallback for nodes without one is unchanged).
export const DEFAULT_VIDEO_RESOLUTION='480p'
export function defaultVideoResolution(model,models=[]) {
 const list=videoCapabilities(effectiveVideoModel(model,models))?.resolutions||[]
 if(!list.length||list.includes(DEFAULT_VIDEO_RESOLUTION))return DEFAULT_VIDEO_RESOLUTION
 const height=value=>{const m=/^(\d+)/.exec(String(value));return m?Number(m[1]):Infinity}
 return [...list].sort((a,b)=>height(a)-height(b))[0]
}
export function videoRatio(model,mode,hasFrames,ratio='16:9') {
 const locked=[SEEDANCE_25,SEEDANCE_25_MODERATED].includes(model)&&mode==='keyframe'&&hasFrames
 return {locked,value:locked?'adaptive':ratio}
}
export function videoParameterError({model,duration=5,resolution='720p',ratio='16:9'}) {
 const spec=videoCapabilities(model)
 if(!spec)return '当前视频模型能力未知，请选择受支持的模型'
 const seconds=Number(duration)
 if(!Number.isInteger(seconds)||(seconds!==VIDEO_AUTO_DURATION&&(seconds<spec.minDuration||seconds>spec.maxDuration)))return `视频时长应为 ${spec.minDuration}–${spec.maxDuration} 秒的整数或 Auto`
 if(!spec.resolutions.includes(resolution))return '所选视频分辨率不受支持'
 if(!VIDEO_RATIOS.includes(ratio))return '所选视频画幅不受支持'
 return ''
}
