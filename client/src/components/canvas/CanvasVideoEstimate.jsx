import React from 'react'
import {estimateBytePlusVideoCost,formatUsdEstimate,estimateImageParamsCost,describeImageEstimate,formatImageUsd} from '../../lib/byteplusPricing'
import {effectiveVideoModel,videoRatio,videoParameterError} from '../../lib/videoGenerationRules'
import useReferenceVideoDurations from './useReferenceVideoDurations'
// Generation-node cost estimate (video and image; audio has no price data). Never shows $0 for unknown.
// CANVAS-LAYOUT-1-20261117: the estimate is a hook so the card's small 生成 button can show the same text in its
// tooltip / accessible name as the right panel shows beside its 生成 button.
export function useCanvasEstimate({node,provider,references=[],imageIssue=''}) {
 const params=node?.params||{},video=node?.type==='video'
 const model=effectiveVideoModel(params.model,provider?.models),ratio=videoRatio(model,params.video_mode,references.some(a=>a.kind==='image'),params.ratio||'16:9').value
 const supported=!!provider?.models?.some(item=>item.id===model),error=video?videoParameterError({model,ratio,resolution:params.resolution||'720p',duration:params.duration??5}):''
 const videos=useReferenceVideoDurations(video&&supported&&!error&&params.video_mode!=='keyframe'?references.filter(asset=>asset.kind==='video'):[])
 if(node?.type==='image'){
  const result=estimateImageParamsCost({provider,params,references,issue:imageIssue})
  if(!result.known){const reason=`${result.reason}，暂不估价；不代表免费`;return {known:false,text:'费用待估',title:reason,label:`费用待估：${reason}`,testId:'canvas-cost-estimate'}}
  const detail=describeImageEstimate(result.estimate),amount=formatImageUsd(result.estimate.minimumCost)
  return {known:true,text:`预估 ${amount} USD`,title:detail,label:`预估费用 ${amount} USD。${detail}`,testId:'canvas-cost-estimate'}
 }
 if(!video)return {known:false,text:'费用待估',title:'暂无音频接口的价格资料，暂不估价；不代表免费',label:undefined,testId:'canvas-cost-estimate'}
 if(!provider||!supported||error){const title=!provider?'项目接口未配置或尚未就绪，暂不估价':!supported?'当前接口不支持此模型，暂不估价':`${error}，暂不估价`;return {known:false,text:'费用待估',title,label:undefined,testId:'canvas-video-estimate'}}
 const estimate=estimateBytePlusVideoCost({model,provider:provider.provider,resolution:params.resolution||'720p',ratio,duration:params.duration??5,fast:false,referenceVideos:videos})
 const output=estimate.minimumOutputSeconds===estimate.maximumOutputSeconds?`${estimate.minimumOutputSeconds}s`:`${estimate.minimumOutputSeconds}–${estimate.maximumOutputSeconds}s`
 const assumptions=[`${model} · ${estimate.width}×${estimate.height} · ${estimate.fps}fps · 输出 ${output}`,estimate.hasVideo?`参考视频 ${estimate.inputVideoSeconds}s${estimate.inputDurationAssumed?'（未知时长按每段5s估算）':''}`:'无参考视频',estimate.ratioAssumed?'Adaptive 按16:9估算':'', '按现有费率估算，非实际扣费'].filter(Boolean).join('；')
 return {known:true,text:`预估 ${formatUsdEstimate(estimate)} USD`,title:assumptions,label:`预估费用 ${formatUsdEstimate(estimate)} USD。${assumptions}`,testId:'canvas-video-estimate'}
}
// Card button tooltip / accessible name: an unknown cost reads "费用未知", never zero.
export const estimateSpeech=estimate=>estimate.known?estimate.text:'费用未知'
export default function CanvasVideoEstimate({estimate}) {
 return <span className="cv-video-estimate" data-testid={estimate.testId} title={estimate.title} aria-label={estimate.label}>{estimate.text}</span>
}
