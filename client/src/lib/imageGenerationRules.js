export const isSeedream55=model=>typeof model==='string'&&['dola-seedream-5-5-261028','dola-seedream-5-5','seedream-5-5','seedream-5.5'].includes(model.toLowerCase())
import {SEEDREAM_SIZE_PRESETS,validateSeedreamCustomSize,alignSeedreamDimension} from './generationSettings.js'
// Image adapters: BytePlus Ark and Cupsy only; unknown providers report an issue.
export const IMAGE_RATIOS={ark:['auto',...Object.keys(SEEDREAM_SIZE_PRESETS['1K']),'custom'],cupsy:['1:1','4:3','3:4','16:9','9:16','custom']}
export const CUPSY_IMAGE_SIZES={'1K':{'1:1':[1024,1024],'4:3':[1152,864],'3:4':[864,1152],'16:9':[1280,720],'9:16':[720,1280]},'2K':{'1:1':[2048,2048],'4:3':[2304,1728],'3:4':[1728,2304],'16:9':[2560,1440],'9:16':[1440,2560]}}
export const imageDefaults=provider=>({ratio:'1:1',resolution:'1K',custom_width:1024,custom_height:1024,lock_aspect_ratio:false,output_format:'png',background:'default',watermark:false})
export const imageCapabilities=(provider,model)=>({ratios:IMAGE_RATIOS[provider]||[],resolutions:provider==='ark'&&isSeedream55(model)?['1K','1.5K','2K']:['1K','2K'],formats:['png','jpeg'],custom:provider==='ark'||provider==='cupsy',background:provider==='ark',maxReferences:10,sizeMap:provider==='ark'?(isSeedream55(model)?SEEDREAM_SIZE_PRESETS:Object.fromEntries(Object.entries(SEEDREAM_SIZE_PRESETS).filter(([key])=>key!=='1.5K'))):provider==='cupsy'?CUPSY_IMAGE_SIZES:{}})
export const imageEffectiveParams=(provider,params={})=>({...imageDefaults(provider),...params,ratio:params.ratio||'1:1',resolution:params.resolution||'1K'})
export function imageParameterIssues(provider,params={},references=[],model){
 if(!IMAGE_RATIOS[provider])return ['请选择可用的图片接口']
 const p=imageEffectiveParams(provider,params),spec=imageCapabilities(provider,model),issues=[]
 if(!spec.ratios.includes(p.ratio))issues.push(`当前接口不支持画幅 ${p.ratio}`)
 if(p.ratio==='custom'&&spec.custom){const issue=validateSeedreamCustomSize(params.custom_width,params.custom_height);if(issue)issues.push(issue)}else if(!spec.resolutions.includes(p.resolution))issues.push(`当前接口不支持分辨率 ${p.resolution}`)
 if(!spec.formats.includes(p.output_format))issues.push(`当前接口不支持 ${p.output_format} 格式`)
 if(!(provider==='ark'&&isSeedream55(model)?['default','auto','transparent','opaque']:['default','transparent','opaque']).includes(p.background))issues.push('背景设置无效')
 if(typeof p.watermark!=='boolean')issues.push('水印设置必须为布尔值')
 if(p.background!=='default'){
  if(provider!=='ark')issues.push('背景控制仅支持 Ark')
  else if(!isSeedream55(model)&&references.length!==1)issues.push('背景控制需要且只能使用一张带 Alpha 通道的参考图')
  else if(!isSeedream55(model)&&references[0]?.has_alpha!==true)issues.push(references[0].metadataLoading?'正在读取参考图片 Alpha 信息':'参考图片没有可确认的 Alpha 通道，请更换参考或使用默认背景')
  if(p.background==='transparent'&&p.output_format!=='png')issues.push('透明背景必须使用 PNG 格式')
 }
 if(references.length>spec.maxReferences)issues.push(`当前接口最多支持 ${spec.maxReferences} 张参考图`)
 return [...new Set(issues)]
}
export function imageRequestFields(provider,params={},model){
 const p=imageEffectiveParams(provider,params),custom=p.ratio==='custom'&&imageCapabilities(provider).custom
 return {aspect_ratio:p.ratio,...(custom?{custom_width:p.custom_width,custom_height:p.custom_height}:{resolution:p.resolution}),output_format:p.output_format,background:p.background,watermark:p.watermark,...(model?{model}:{})}
}
export function imageSizePatch(provider,params,patch,model){
 if(patch.ratio==='custom')return {custom_width:params.custom_width??1024,custom_height:params.custom_height??1024,...patch}
 const next={...params,...patch},dimensions=imageCapabilities(provider,model).sizeMap[next.resolution||'1K']?.[next.ratio||'1:1']
 return dimensions&&('ratio'in patch||'resolution'in patch)?{...patch,custom_width:dimensions[0],custom_height:dimensions[1]}:patch
}
export function imageDimensionPatch(params,field,value){
 const p=imageEffectiveParams('ark',params),other=field==='custom_width'?'custom_height':'custom_width',ratio=p.custom_width/p.custom_height
 return {ratio:'custom',custom_width:p.custom_width,custom_height:p.custom_height,[field]:value,...(p.lock_aspect_ratio&&Number.isFinite(ratio)&&ratio>0?{[other]:alignSeedreamDimension(field==='custom_width'?value/ratio:value*ratio)}:{})}
}
export const imageSizeSummary=(provider,params={})=>{const p=imageEffectiveParams(provider,params);return p.ratio==='custom'?`${p.custom_width}×${p.custom_height}`:`${p.ratio==='auto'?'Auto':p.ratio} · ${p.resolution}`}
// The legacy image tool stores camelCase form state, not canvas node params.
export const imageTabParams=(provider,tab)=>({ratio:tab.aspectRatio,resolution:tab.resolution,custom_width:tab.customWidth,custom_height:tab.customHeight,lock_aspect_ratio:!!tab.customAspectLocked,output_format:tab.outputFormat||'png',background:provider==='ark'?tab.background||'default':'default',watermark:!!tab.watermark})
const tabKeys={ratio:'aspectRatio',resolution:'resolution',custom_width:'customWidth',custom_height:'customHeight',lock_aspect_ratio:'customAspectLocked',output_format:'outputFormat',background:'background',watermark:'watermark'}
export const imageTabPatch=patch=>Object.fromEntries(Object.entries(patch).filter(([key])=>tabKeys[key]).map(([key,value])=>[tabKeys[key],value]))
export function sanitizeImageParamsForProvider(provider,params={},model='',references=[]){
 const p=imageEffectiveParams(provider,params),spec=imageCapabilities(provider,model),defaults=imageDefaults(provider),modern=provider==='ark'&&isSeedream55(model)
 const next={...p}
 if(spec.ratios.length&&!spec.ratios.includes(next.ratio))next.ratio=defaults.ratio
 if(next.ratio!=='custom'&&spec.resolutions.length&&!spec.resolutions.includes(next.resolution))next.resolution=defaults.resolution
 if(spec.formats.length&&!spec.formats.includes(next.output_format))next.output_format=defaults.output_format
 const validBackgrounds=provider!=='ark'?['default']:modern?['default','auto','transparent','opaque']:['default','transparent','opaque']
 if(!validBackgrounds.includes(next.background))next.background='default'
 if(provider==='ark'&&!modern&&next.background!=='default'){
  const hasSingleAlpha=references.length===1&&references[0]?.has_alpha===true
  if(!hasSingleAlpha)next.background='default'
 }
 if(next.background==='transparent'&&next.output_format!=='png')next.output_format='png'
 if(next.ratio!=='custom'){
  const dimensions=spec.sizeMap[next.resolution]?.[next.ratio]
  if(dimensions&&(next.ratio!==p.ratio||next.resolution!==p.resolution)){next.custom_width=dimensions[0];next.custom_height=dimensions[1]}
 }
 const changed=['ratio','resolution','custom_width','custom_height','output_format','background'].some(key=>next[key]!==p[key])
 return {params:next,changed}
}
export function sanitizeImageTabForProvider(provider,tab={},model='',references=[]){
 const raw={ratio:tab.aspectRatio,resolution:tab.resolution,custom_width:tab.customWidth,custom_height:tab.customHeight,lock_aspect_ratio:!!tab.customAspectLocked,output_format:tab.outputFormat||'png',background:tab.background||'default',watermark:!!tab.watermark}
 const {params,changed}=sanitizeImageParamsForProvider(provider,raw,model,references)
 const tabPatch=imageTabPatch({
  ratio:params.ratio,
  resolution:params.resolution,
  custom_width:params.custom_width,
  custom_height:params.custom_height,
  output_format:params.output_format,
  background:params.background,
 })
 const tabChanged=tabPatch.aspectRatio!==tab.aspectRatio||tabPatch.resolution!==tab.resolution||tabPatch.outputFormat!==(tab.outputFormat||'png')||tabPatch.background!==(tab.background||'default')
 return {patch:tabPatch,params,changed:changed||tabChanged}
}
