import useImageDimensionDraft from '../image-parameters/useImageDimensionDraft'
import useCanvasImageMetadata from './useCanvasImageMetadata'
import useTaskEcho from './useTaskEcho'
import {imageParameterIssues} from '../../lib/imageGenerationRules'
import {isBusyTaskStatus,isFailureTaskStatus} from '../../lib/taskStatus'
import {resolveKeyframeRoles} from '../../lib/canvasReferences'
import {effectiveVideoModel,videoCapabilities,videoRatio} from '../../lib/videoGenerationRules'
import {canvasAudioParams,canvasAudioIssue} from '../../lib/generationSettings'
import {taskFailure} from '../../lib/canvasTaskEcho'

const EMPTY={}
// Reasons that are known without the selected-node checks (group run, task in flight, interface). Unselected cards use
// them for their 生成 button; the full reason is checked after the click selects the node (same flow as the panel).
export function quickGenerationBlock(node,provider,blockedReason=''){
 const task=node?.task
 return blockedReason||(isBusyTaskStatus(task?.status)?(task.status==='unknown'||(task.status==='submitting'&&!task.id)?'提交结果未知：请先核查并关联已有任务，不会重新生成':'任务进行中，完成后才能再次生成'):!provider?(node?.providerSelection?'节点所选接口已停用或不可用，请重新选择接口':'请先为节点选择接口'):'')
}
// CANVAS-LAYOUT-1-20261117: "can this node be generated, and why not" for the selected generation node, split out
// of the retired CanvasNodePanel unchanged so the right panel's 生成 button and the card's small 生成 button share
// one disabled reason (CANVAS-INPUT-20261114 #6) and one set of parameter checks.
export default function useNodeGeneration({node,provider,inputAssets=[],workflowId,blockedReason='',resultUnknown=false,mentionIssues=[],onPatch}) {
 const generation=!!node&&['image','video','audio'].includes(node.type)
 const params=node?.params||EMPTY,task=node?.task
 const model=effectiveVideoModel(params.model,provider?.models),spec=videoCapabilities(model)
 const inputImages=inputAssets.filter(asset=>asset.kind==='image')
 const ratio=videoRatio(model,params.video_mode,inputImages.length>0,params.ratio||'16:9')
 const unsupported=node?.type==='video'&&!!provider&&!!params.model&&!provider.models?.some(item=>item.id===params.model)
 const frames=node?resolveKeyframeRoles(node,inputAssets):{issues:[]}
 const imageAdapter=provider?.provider||provider?.id
 const imageMetadata=useCanvasImageMetadata(workflowId,inputImages,node?.type==='image')
 const imageDimensions=useImageDimensionDraft(params,patch=>node&&onPatch(node.id,{params:{...params,...patch}}),node?.id)
 const imageIssues=node?.type==='image'&&provider?imageParameterIssues(imageAdapter,params,imageMetadata.references,provider.capability_model||provider.model):[]
 const imageInvalid=node?.type==='image'&&(imageIssues.length>0||(['ark','cupsy'].includes(imageAdapter)&&!!imageDimensions.error))
 const audioParams=canvasAudioParams(params),audioIssue=node?.type==='audio'?canvasAudioIssue(params,{image:inputAssets.filter(a=>a.kind==='image').length,audio:inputAssets.filter(a=>a.kind==='audio').length}):null
 const failure=!!task&&isFailureTaskStatus(task.status)
 // NODE-ECHO-20261115: failure class from the task detail (FAILURE-CLASS contract); absent → nothing extra shown.
 const taskDetail=useTaskEcho(task,failure&&generation),failureClass=failure?taskFailure(task.failure||taskDetail?.failure,{resultUnknown,status:task.status}):null
 const selection=node?.providerSelection
 const disabledReason=!generation?'':blockedReason||(isBusyTaskStatus(task?.status)?(task.status==='unknown'||(task.status==='submitting'&&!task.id)?'提交结果未知：请先核查并关联已有任务，不会重新生成':'任务进行中，完成后才能再次生成'):!provider?(selection?'节点所选接口已停用或不可用，请重新选择接口':'请先为节点选择接口'):unsupported?'当前接口不支持原模型，请选择受支持的模型':imageInvalid?(imageIssues.join('；')||imageDimensions.error||'图片参数不适用于当前接口'):audioIssue?audioIssue:mentionIssues.length?mentionIssues.join('；'):'')
 const estimateReferences=node?.type==='image'?imageMetadata.references:inputAssets
 const imageIssue=node?.type==='image'?(imageIssues[0]||(['ark','cupsy'].includes(imageAdapter)&&imageDimensions.error)||''):''
 // Image parameter checks need the reference metadata; a card click waits for it before deciding.
 const ready=node?.type!=='image'||!workflowId||imageMetadata.references.every(reference=>!reference.metadataLoading)
 return {ready,generation,params,model,spec,ratio,unsupported,frames,inputImages,imageAdapter,imageMetadata,imageDimensions,imageIssues,imageInvalid,audioParams,audioIssue,failure,failureClass,disabledReason,estimateReferences,imageIssue}
}
