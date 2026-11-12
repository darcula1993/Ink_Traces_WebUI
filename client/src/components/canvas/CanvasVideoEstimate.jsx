import React from 'react'
import {estimateBytePlusVideoCost,formatUsdEstimate} from '../../lib/byteplusPricing'
import {effectiveVideoModel,videoRatio,videoParameterError} from '../../lib/videoGenerationRules'
import useReferenceVideoDurations from './useReferenceVideoDurations'
export default function CanvasVideoEstimate({node,provider,references=[]}) {
 if(node.type!=='video')return <span className="cv-video-estimate" data-testid="canvas-cost-estimate" title={`暂无${node.type==='image'?'图像':'音频'}接口的价格资料，暂不估价；不代表免费`}>费用待估</span>
 return <VideoEstimate node={node} provider={provider} references={references}/>
}
function VideoEstimate({node,provider,references}) {
 const params=node.params||{},model=effectiveVideoModel(params.model,provider?.models),ratio=videoRatio(model,params.video_mode,references.some(a=>a.kind==='image'),params.ratio||'16:9').value
 const supported=provider?.models?.some(item=>item.id===model),error=videoParameterError({model,ratio,resolution:params.resolution||'720p',duration:params.duration??5})
 const videos=useReferenceVideoDurations(supported&&!error&&params.video_mode!=='keyframe'?references.filter(asset=>asset.kind==='video'):[])
 if(!provider||!supported||error)return <span className="cv-video-estimate" data-testid="canvas-video-estimate" title={!provider?'项目接口未配置或尚未就绪，暂不估价':!supported?'当前接口不支持此模型，暂不估价':`${error}，暂不估价`}>费用待估</span>
 const estimate=estimateBytePlusVideoCost({model,provider:provider.provider,resolution:params.resolution||'720p',ratio,duration:params.duration??5,fast:false,referenceVideos:videos})
 const output=estimate.minimumOutputSeconds===estimate.maximumOutputSeconds?`${estimate.minimumOutputSeconds}s`:`${estimate.minimumOutputSeconds}–${estimate.maximumOutputSeconds}s`
 const assumptions=[`${model} · ${estimate.width}×${estimate.height} · ${estimate.fps}fps · 输出 ${output}`,estimate.hasVideo?`参考视频 ${estimate.inputVideoSeconds}s${estimate.inputDurationAssumed?'（未知时长按每段5s估算）':''}`:'无参考视频',estimate.ratioAssumed?'Adaptive 按16:9估算':'', '按现有费率估算，非实际扣费'].filter(Boolean).join('；')
 return <span className="cv-video-estimate" data-testid="canvas-video-estimate" title={assumptions} aria-label={`预估费用 ${formatUsdEstimate(estimate)} USD。${assumptions}`}>预估 {formatUsdEstimate(estimate)} USD</span>
}
