import React,{useEffect,useRef,useState} from 'react'
import {Copy,Play,PanelRightClose,PanelRightOpen,Pencil,FileText,Image,Film,Music,Layers,FolderInput,UserPlus,Search,Sparkles,ChevronRight,Plug,Cpu,Clock3,Mic,Trash2,LayoutGrid} from 'lucide-react'
import LibraryUploadMenu from '../library/LibraryUploadMenu'
import ImageOutputControls from '../image-parameters/ImageOutputControls'
import ReferenceThumbnails from './ReferenceThumbnails'
import CanvasVideoEstimate from './CanvasVideoEstimate'
import ConfirmDialog from '../ui/ConfirmDialog'
import CanvasGroupColors from './CanvasGroupColors'
import PromptLibraryPicker from './PromptLibraryPicker'
import {GroupRunBadge} from './CanvasGroupRun'
import {isActiveRun} from '../../lib/canvasGroupRun'
import {isBusyTaskStatus,isFailureTaskStatus} from '../../lib/taskStatus'
import {imageSizeSummary} from '../../lib/imageGenerationRules'
import {videoDurations,VIDEO_RATIOS} from '../../lib/videoGenerationRules'
import {selectionOptionId,toSelection} from '../../lib/canvasProviderSelection'
import {AUDIO_SPEAKERS,AUDIO_OUTPUT_FORMATS,AUDIO_SAMPLE_RATES} from '../../lib/generationSettings'
import {positionalMentionRebinds} from '../../lib/canvasReferences'
import {FAILURE_ACTION_LABELS} from '../../lib/canvasTaskEcho'
import {formatCostRange} from '../../lib/canvasBatchRun'
import './propertiesPanel.css'
import './propertiesForm.css'

// CANVAS-LAYOUT-1-20261117 (user decision 11-17; replaces the 11-13 "panel below the preview" and the 11-14 "panel
// always below the node"): one fixed column right of the canvas. Its content follows the selection; generation is
// only started from buttons (no keyboard shortcut, user decision Q7). Width/collapse are per-browser preferences.
const WIDTH_KEY='ink-traces.canvas.properties-width.v1',COLLAPSED_KEY='ink-traces.canvas.properties-collapsed.v1'
export const PANEL_MIN=288,PANEL_MAX=440
export const defaultPanelWidth=viewport=>viewport>=1920?360:viewport>=1440?320:288
const clamp=value=>Math.max(PANEL_MIN,Math.min(PANEL_MAX,value))
const readStored=(key)=>{try{return localStorage.getItem(key)}catch{return null}}
const writeStored=(key,value)=>{try{if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value)}catch{/* storage unavailable: keep the in-memory value */}}
export function usePropertiesPanelPrefs(){
 const viewport=()=>typeof window==='undefined'?1440:window.innerWidth
 const [saved,setSaved]=useState(()=>{const value=Number(readStored(WIDTH_KEY));return Number.isFinite(value)&&value>=PANEL_MIN&&value<=PANEL_MAX?value:null})
 const [collapsed,setCollapsedState]=useState(()=>readStored(COLLAPSED_KEY)==='1')
 const [fallback,setFallback]=useState(()=>defaultPanelWidth(viewport()))
 useEffect(()=>{const resize=()=>setFallback(defaultPanelWidth(viewport()));window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize)},[])
 const setWidth=value=>{if(value===null){setSaved(null);writeStored(WIDTH_KEY,null);return}const next=clamp(Math.round(value));setSaved(next);writeStored(WIDTH_KEY,String(next))}
 const setCollapsed=value=>{setCollapsedState(value);writeStored(COLLAPSED_KEY,value?'1':'0')}
 return {width:saved??fallback,collapsed,setWidth,setCollapsed}
}

const KIND_LABEL={text:'文本',image:'画面',video:'视频',audio:'音频'}
const KIND_ICON={text:FileText,image:Image,video:Film,audio:Music,asset:Layers}
const Section=({id,title,children,className='',actions=null})=><section className={`cv-prop-section ${className}`} aria-labelledby={id}><div className="cv-prop-section-head"><h3 id={id}>{title}</h3>{actions&&<div className="cv-prop-section-actions">{actions}</div>}</div>{children}</section>

// PROPS-PANEL-REDESIGN-20261118 (user 11-18, ImageArt-style Properties column): one column, label above a full-width
// 36px control, optional decorative prefix (aria-hidden; the control keeps its own aria-label). Presentation only.
const Field=({label,hint,prefix,className='',children})=><label className={`cv-pf-field ${prefix?'has-prefix':''} ${className}`}><span className="cv-pf-label">{label}{hint&&<small>{hint}</small>}</span>{children}{prefix&&<span className="cv-pf-prefix" aria-hidden="true">{prefix}</span>}</label>
const Toggle=({label,className='',children})=><label className={`cv-pf-toggle ${className}`}><span>{label}</span>{children}</label>
// Aspect-ratio box glyph (decorative): 16:9 draws a wide box, 9:16 a tall one, auto/custom a dashed square.
export function RatioGlyph({value}) {
 const m=/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(String(value||''));let w=12,h=12
 if(m){const a=Number(m[1]),b=Number(m[2]);if(a>=b){w=14;h=Math.max(5,Math.round(14*b/a))}else{h=14;w=Math.max(5,Math.round(14*a/b))}}
 return <span className={`cv-pf-ratio ${m?'':'is-free'}`} style={{width:w,height:h}}/>
}
// 高级 group: collapsed by default; the open/closed choice is a per-browser preference. It opens by itself when a
// hidden field becomes the one that matters (自定义尺寸 chosen, or a parameter issue to fix). Content stays mounted
// (hidden) so drafts and validation messages are kept.
const ADVANCED_KEY='ink-traces.canvas.properties-advanced.v1'
function PropAdvanced({summary,autoOpen,children}) {
 const [open,setOpen]=useState(()=>readStored(ADVANCED_KEY)==='1'),seen=useRef(false),id=useRef(`cv-pf-advanced-${Math.random().toString(36).slice(2,8)}`).current
 useEffect(()=>{if(autoOpen&&!seen.current)setOpen(true);seen.current=!!autoOpen},[autoOpen])
 const toggle=()=>{const next=!open;setOpen(next);writeStored(ADVANCED_KEY,next?'1':'0')}
 return <div className={`cv-pf-advanced ${open?'is-open':''}`}>
  <button type="button" className="cv-pf-advanced-toggle" aria-expanded={open} aria-controls={id} title={open?'收起高级参数':'展开高级参数'} onClick={toggle}><ChevronRight size={14} aria-hidden="true" className="cv-pf-chevron"/><span>高级</span>{!open&&summary&&<small>{summary}</small>}</button>
  <div id={id} className="cv-pf-advanced-body" hidden={!open}>{children}</div>
 </div>
}
const imagePrefix=(name,value)=>name==='ratio'?<span className="cv-pf-prefix" aria-hidden="true"><RatioGlyph value={value}/></span>:null

export default function CanvasPropertiesPanel({prefs,content,onFocusCanvas}) {
 const asideRef=useRef(null),gesture=useRef(null),[dragging,setDragging]=useState(false)
 const {width,collapsed,setWidth,setCollapsed}=prefs
 const keyDown=event=>{
  if(event.defaultPrevented||(event.ctrlKey||event.metaKey))return
  // Esc: a native select keeps its own list handling; otherwise focus goes back to the selection (never cleared).
  if(event.key==='Escape'&&!event.target.closest?.('[role=dialog],details[open]')){event.preventDefault();onFocusCanvas?.()}
 }
 if(collapsed)return <aside ref={asideRef} className="cv-properties is-collapsed" aria-label="属性面板（已收起）" data-testid="properties-panel"><button type="button" className="btn btn-icon btn-sm" aria-label="展开属性面板" title="展开属性面板" aria-expanded="false" onClick={()=>setCollapsed(false)}><PanelRightOpen size={15}/></button></aside>
 const resizeKey=event=>{const step=event.shiftKey?40:10;if(event.key==='ArrowLeft'){event.preventDefault();setWidth(width+step)}else if(event.key==='ArrowRight'){event.preventDefault();setWidth(width-step)}else if(event.key==='Home'){event.preventDefault();setWidth(PANEL_MAX)}else if(event.key==='End'){event.preventDefault();setWidth(PANEL_MIN)}}
 return <aside ref={asideRef} className={`cv-properties ${dragging?'is-resizing':''}`} style={{width}} aria-label={content.label?`属性面板：${content.label}`:'属性面板'} data-testid="properties-panel" data-panel-node-id={content.nodeId||undefined} data-panel-kind={content.kind} onKeyDown={keyDown}>
  <div className="cv-properties-resize" role="separator" aria-orientation="vertical" aria-label="调整属性面板宽度" aria-valuemin={PANEL_MIN} aria-valuemax={PANEL_MAX} aria-valuenow={width} tabIndex={0} title="拖动调整宽度，双击复位" onKeyDown={resizeKey} onDoubleClick={()=>setWidth(null)}
   onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);gesture.current={x:event.clientX,width};setDragging(true)}}
   onPointerMove={event=>{if(gesture.current)setWidth(gesture.current.width+gesture.current.x-event.clientX)}}
   onPointerUp={()=>{gesture.current=null;setDragging(false)}} onPointerCancel={()=>{gesture.current=null;setDragging(false)}}/>
  <header className="cv-properties-head">{content.head}<button type="button" className="btn btn-icon btn-sm cv-properties-collapse" aria-label="收起属性面板" title="收起属性面板" aria-expanded="true" onClick={()=>setCollapsed(true)}><PanelRightClose size={15}/></button></header>
  <div className="cv-properties-body">{content.body}</div>
  {content.footer&&<footer className="cv-properties-footer">{content.footer}</footer>}
 </aside>
}

// ---- content builders (pure render helpers; state they need is owned by CanvasStudio or the small components below)

export function canvasContent({nodes}) {
 const busy=nodes.filter(node=>isBusyTaskStatus(node.task?.status)).length,failed=nodes.filter(node=>node.task&&isFailureTaskStatus(node.task.status)).length
 return {kind:'canvas',label:'画布',head:<h2 className="cv-properties-title">画布</h2>,body:<div className="cv-prop-stats" data-testid="properties-canvas"><dl><div><dt>节点</dt><dd>{nodes.length}</dd></div><div><dt>进行中任务</dt><dd>{busy}</dd></div><div><dt>失败</dt><dd>{failed}</dd></div></dl><p className="cv-prop-hint">选择节点以编辑接口与参数</p></div>}
}

export function multiContent({nodes,plan,onLocate,onMakeGroup,onRun,groupDisabled,runDisabledReason}) {
 const counts=Object.entries(nodes.reduce((all,node)=>{const key=node.type==='asset'?'素材':KIND_LABEL[node.type]||node.type;all[key]=(all[key]||0)+1;return all},{}))
 const generation=nodes.some(node=>['image','video','audio'].includes(node.type))
 const reasonId='cv-run-selected-reason',reason=generation?(runDisabledReason||(plan&&!plan.ready.length?'所选节点中没有可运行的生成节点':'')):''
 return {kind:'multi',label:`已选 ${nodes.length} 个节点`,head:<h2 className="cv-properties-title">已选 {nodes.length} 个节点</h2>,
  body:<div data-testid="properties-multi">
   <p className="cv-prop-hint">{counts.map(([kind,count])=>`${kind} ${count}`).join(' · ')} · 拖动任一标题一起移动</p>
   {generation&&plan&&<Section id="cv-prop-batch" title="运行预览"><p data-testid="batch-preview-summary">可运行 {plan.ready.length} 个，跳过 {plan.skipped.length} 个{plan.ready.length?` · 合计预估 ${plan.total.text}`:''}</p>
    {plan.ready.length>0&&<ul className="cv-prop-list">{plan.ready.map(({node,cost})=><li key={node.id}><button type="button" className="cv-prop-link" title="定位节点" onClick={()=>onLocate(node.id)}>{node.title}</button><span>{cost.known?formatCostRange(cost.min,cost.max):'费用未知'}</span></li>)}</ul>}
    {plan.skipped.length>0&&<><p>跳过：</p><ul className="cv-prop-list" data-testid="batch-preview-skipped">{plan.skipped.map(({node,reason})=><li key={node.id}><button type="button" className="cv-prop-link" title="定位节点" onClick={()=>onLocate(node.id)}>{node.title}</button><span>{reason}</span></li>)}</ul></>}
    <p className="cv-prop-hint">每个节点创建一个独立任务；不会自动运行下游节点。</p></Section>}
   <div className="cv-prop-actions"><button type="button" className="btn btn-secondary btn-sm" disabled={groupDisabled} onClick={onMakeGroup}>创建节点组</button></div>
  </div>,
  footer:generation?<>{plan&&plan.ready.length>0&&<div className="cv-pf-estimate"><span>合计预估</span><span>{plan.total.text}</span></div>}{reason&&<span id={reasonId} className="cv-sr-only">{reason}</span>}<button type="button" className="btn btn-primary btn-block cv-pf-primary cv-run-selected" aria-describedby={reason?reasonId:undefined} title={reason?`无法运行：${reason}`:'一次提交所选节点中输入已就绪的生成节点，每个节点独立任务，不连锁下游'} disabled={!!reason} onClick={onRun}><Play size={14} aria-hidden="true"/>运行所选</button></>:null}
}

export function groupContent({group,nodes,run,titleOf,disabled,onRename,onColor,onUngroup,onRun,onCancelRun}) {
 const active=isActiveRun(run),runnable=nodes.some(node=>group.nodeIds.includes(node.id)&&['image','video','audio'].includes(node.type))
 return {kind:'group',label:`节点组 ${group.title}`,head:<h2 className="cv-properties-title">{group.title}</h2>,
  body:<div data-testid="properties-group"><p className="cv-prop-hint">节点组 · {group.nodeIds.length} 个节点</p><GroupRunBadge run={run} titleOf={titleOf}/>
   <div className="cv-prop-actions"><button type="button" className="btn btn-secondary btn-sm" onClick={()=>onRename(group)}>重命名</button><CanvasGroupColors group={group} disabled={disabled} onChange={onColor}/><button type="button" className="btn btn-ghost btn-sm" onClick={()=>onUngroup(group)}>解散组</button></div></div>,
  footer:onRun&&runnable?(active?<button type="button" className="btn btn-secondary btn-block cv-pf-primary" title="只停止尚未提交的节点，已提交任务照常跑完写回" onClick={()=>onCancelRun(run)}>取消整组</button>:<button type="button" className="btn btn-primary btn-block cv-pf-primary" disabled={disabled} title="按依赖顺序逐个提交组内生成节点；每个节点独立任务" onClick={()=>onRun(group)}><Play size={14} aria-hidden="true"/>运行组</button>):null}
}

const NodeHead=({node,label,onChange,children})=>{const Icon=KIND_ICON[node.type]||Layers;return <><span className="cv-properties-kind-box"><Icon size={14} aria-hidden="true" className="cv-properties-kind"/></span><input className="cv-panel-title" aria-label={node.type==='asset'?'素材名称':'节点名称'} title={`${label}：${node.title}`} value={node.title} onChange={event=>onChange({title:event.target.value})}/>{children}</>}

export function textContent({node,usedBy,onChange,onEditPrompt}) {
 const length=[...(node.text||'')].length
 return {kind:'text',nodeId:node.id,label:node.title,head:<NodeHead node={node} label="文本" onChange={onChange}/>,
  body:<div data-testid="properties-text"><dl className="cv-prop-stats"><div><dt>字数</dt><dd>{length}</dd></div><div><dt>使用</dt><dd>被 {usedBy} 个节点使用</dd></div></dl><p className="cv-prop-hint">文本节点的内容在卡片中编辑；作为提示词输入口为第二期。</p><div className="cv-prop-actions"><button type="button" className="btn btn-secondary btn-sm" onClick={onEditPrompt}><Pencil size={13} aria-hidden="true"/>编辑文本</button></div></div>}
}

export function assetContent({node,dimensions,deleted,onChange,onCopy,onRevealInLibrary,onMoveToFolder,onAddToCharacter,onReplace,onReplaceFromLibrary,onRemove}) {
 const kind=node.asset?.kind,kindLabel={image:'图片',video:'视频',audio:'音频'}[kind]||'素材'
 const size=kind==='image'&&dimensions?`${dimensions.width} × ${dimensions.height}`:kind==='video'&&dimensions?`${dimensions.width} × ${dimensions.height}`:''
 const duration=Number(node.asset?.duration)>0?`${Math.round(Number(node.asset.duration)*10)/10}s`:''
 return {kind:'asset',nodeId:node.id,label:node.title,head:<NodeHead node={node} label="素材" onChange={onChange}><button type="button" className="btn btn-icon btn-sm" aria-label="复制" title="复制节点" onClick={onCopy}><Copy size={13}/></button></NodeHead>,
  body:<div data-testid="properties-asset"><dl className="cv-prop-stats"><div><dt>类型</dt><dd>{kindLabel}</dd></div>{size&&<div><dt>尺寸</dt><dd>{size}</dd></div>}{duration&&<div><dt>时长</dt><dd>{duration}</dd></div>}</dl>
   {deleted?<><p className="cv-reference-warning" role="status">素材已在素材库中删除</p><div className="cv-prop-actions">{onReplaceFromLibrary&&<button type="button" className="btn btn-secondary btn-sm" onClick={onReplaceFromLibrary}>从素材库替换</button>}{onReplace&&<button type="button" className="btn btn-secondary btn-sm" onClick={onReplace}>上传替换</button>}<button type="button" className="btn btn-ghost btn-sm" onClick={onRemove}>移除节点</button></div></>
   :<div className="cv-prop-actions">{onRevealInLibrary&&<button type="button" className="btn btn-secondary btn-sm" onClick={onRevealInLibrary}><Search size={13} aria-hidden="true"/>在素材库中显示</button>}{onMoveToFolder&&<button type="button" className="btn btn-secondary btn-sm" aria-haspopup="dialog" onClick={onMoveToFolder}><FolderInput size={13} aria-hidden="true"/>移动到文件夹</button>}{onAddToCharacter&&<button type="button" className="btn btn-secondary btn-sm" aria-haspopup="dialog" onClick={onAddToCharacter}><UserPlus size={13} aria-hidden="true"/>加入角色卡</button>}</div>}
  </div>}
}

export function generationContent(props) {
 const {node,onChange,onCopy}=props,label=KIND_LABEL[node.type]
 return {kind:'generation',nodeId:node.id,label:node.title,
  head:<NodeHead node={node} label={label} onChange={onChange}><button type="button" className="btn btn-icon btn-sm" aria-label="复制" title="复制节点" onClick={onCopy}><Copy size={13}/></button></NodeHead>,
  body:<GenerationBody {...props}/>,
  footer:<GenerateBar {...props}/>}
}

function GenerateBar({node,gen,estimate,onGenerate}) {
 const label=KIND_LABEL[node.type],reasonId=`cv-generate-reason-${node.id}`,reason=gen.disabledReason
 return <div className="cv-generation-actions"><div className="cv-pf-estimate"><span>费用估算</span><CanvasVideoEstimate estimate={estimate}/></div>{reason&&<span id={reasonId} className="cv-sr-only" data-testid="generate-disabled-reason">{reason}</span>}<button type="button" className="btn btn-primary btn-block cv-pf-primary cv-generate" aria-label={`生成${label}`} title={reason?`无法生成：${reason}`:`生成${label}`} aria-describedby={reason?reasonId:undefined} disabled={!!reason} onClick={onGenerate}><Sparkles size={14} aria-hidden="true"/>生成</button></div>
}

function GenerationBody({node,provider,providerOptions=[],gen,editor,inputAssets=[],resultUnknown,errorMessage='',mentionNotice,onChange,onGenerate,onReorderReferences,onClearReferences,portWarnings=[],overLimitCount=0,onRemoveOverLimit,onUpload,onLibrary,onLinkTask,onOpenTask,onDismissStale,onNotice,onEditPrompt,onOrganizeGroup}) {
 const [taskNumber,setTaskNumber]=useState(''),[copied,setCopied]=useState(false),[regenerateConfirm,setRegenerateConfirm]=useState(false),outputRef=useRef(null)
 const {params,model,spec,ratio,unsupported,frames,imageAdapter,imageMetadata,imageDimensions,imageIssues,imageInvalid,audioParams,audioIssue,failure,failureClass,disabledReason}=gen
 const task=node.task,selection=node.providerSelection,selectionId=selectionOptionId(selection)
 const setParam=(key,value)=>onChange({params:{...params,[key]:value}})
 const recovery=task&&(task.status==='unknown'||task.status==='submitting'&&!task.id)
 const outputSummary=node.type==='audio'?`${AUDIO_SPEAKERS.find(item=>item.value===audioParams.speaker)?.label||audioParams.speaker} · ${AUDIO_OUTPUT_FORMATS.find(item=>item.value===audioParams.output_format)?.label||audioParams.output_format} · ${audioParams.sample_rate/1000}kHz`:node.type==='image'?imageSizeSummary(imageAdapter,params):`${ratio.value} · ${params.resolution||'720p'} · ${(params.duration??5)===-1?'Auto':`${params.duration??5}s`}`
 const showOutput=()=>{const box=outputRef.current;box?.scrollIntoView?.({block:'nearest'});box?.querySelector('select,input,button')?.focus({preventScroll:true})}
 const rebind=positionalMentionRebinds(node,inputAssets).map(item=>`${item.token} 已改为指向 ${item.name}`).join('；'),rebindText=mentionNotice||rebind
 const issueText=editor?.mentionError||editor?.mentionIssues.join('；')
 return <div className="cv-generation-body" data-testid="properties-generation">
  {(failure||node.upstreamStale||recovery)&&<Section id={`cv-prop-status-${node.id}`} title="状态">
   {failure&&<div className={`cv-task-failure ${resultUnknown||task.status==='unknown'?'is-unknown':''}`} role={errorMessage&&errorMessage===task.error?undefined:'alert'} data-testid="node-task-error"><strong>{resultUnknown?'结果未知，可能已计费':task.status==='unknown'?'提交结果未知':(failureClass?.label||'生成失败')}{(resultUnknown||task.status==='unknown')&&<span> · 请求可能已发出，请先核查；不会自动重试</span>}</strong>{failureClass?.hint&&<p className="cv-task-failure-hint" data-testid="panel-failure-hint" data-failure-category={failureClass.category||undefined}>{failureClass.hint}</p>}<p title={task.error||undefined}>{task.error||'服务端未返回失败原因'}</p>{failureClass&&failureClass.action!=='none'&&<div className="cv-task-failure-actions">{failureClass.action==='regenerate_confirm'&&<button type="button" className="btn btn-secondary btn-sm" data-testid="panel-failure-action" data-action="regenerate_confirm" disabled={!!disabledReason} title={disabledReason?`无法生成：${disabledReason}`:'重新生成会提交新任务并再次计费，需先确认'} onClick={()=>setRegenerateConfirm(true)}>{FAILURE_ACTION_LABELS.regenerate_confirm}</button>}{failureClass.action==='edit_params'&&<button type="button" className="btn btn-secondary btn-sm" data-testid="panel-failure-action" data-action="edit_params" onClick={showOutput}>{FAILURE_ACTION_LABELS.edit_params}</button>}{failureClass.action==='check_task'&&task.id&&<button type="button" className="btn btn-secondary btn-sm" data-testid="panel-failure-action" data-action="check_task" onClick={()=>onOpenTask?.(task)}>{FAILURE_ACTION_LABELS.check_task}</button>}</div>}{task.id&&<span className="cv-task-check">任务 #{task.id} · 可在任务记录中按编号核查<button type="button" title="复制任务编号" aria-label={`复制任务编号 ${task.id}`} onClick={()=>{navigator.clipboard?.writeText(String(task.id)).then(()=>setCopied(true)).catch(()=>{})}}><Copy size={12}/>{copied?'已复制':'复制编号'}</button></span>}</div>}
   {node.upstreamStale&&<div className="cv-stale-notice" role="status"><span>上游已更新：此节点的结果基于旧输入，重新生成成功后标记消失；不会自动生成。</span>{onDismissStale&&<button type="button" onClick={onDismissStale}>忽略标记</button>}</div>}
   {recovery&&<div className="cv-task-recovery"><span>请核查并关联已有任务，不会重新生成。</span><label>本地任务编号<input type="number" min="1" value={taskNumber} onChange={e=>setTaskNumber(e.target.value)}/></label><button type="button" disabled={!taskNumber} onClick={()=>onLinkTask(taskNumber)}>关联已有任务</button></div>}
  </Section>}
  <Section id={`cv-prop-provider-${node.id}`} title="生成设置" className="cv-pf-section">
   <Field label="接口" prefix={<Plug size={14}/>}><select className="cv-prop-select cv-node-provider" aria-label="节点生成接口" title={provider?.name?`接口：${provider.name}`:'请选择接口'} value={selectionId} onChange={event=>{const chosen=providerOptions.find(option=>option.id===event.target.value);if(chosen)onChange({providerSelection:toSelection(chosen)})}}>{!selectionId&&<option value="" disabled>请选择接口</option>}{selectionId&&!provider&&<option value={selectionId}>原接口已停用或不可用</option>}{providerOptions.map(option=><option key={option.id} value={option.id}>{option.name}</option>)}</select></Field>
   {!provider&&<div className="cv-reference-warning" role="status">{selection?'节点所选接口已停用或不可用，请重新选择。':'请先为节点选择接口。'}</div>}
   {node.type==='video'&&<>
    {provider?.models?.length>0&&<Field label="模型" prefix={<Cpu size={14}/>}><select className="cv-prop-select" aria-label="视频模型" title={provider.models.find(m=>m.id===model)?.name||model} value={model} onChange={e=>setParam('model',e.target.value)}>{unsupported&&<option value={params.model}>原模型不支持，请选择</option>}{provider.models.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>}
    <Field label="模式"><select className="cv-prop-select" aria-label="视频生成模式" title="生成模式" value={params.video_mode||'reference'} onChange={e=>setParam('video_mode',e.target.value)}><option value="reference">全能参考</option><option value="keyframe">首尾帧</option></select></Field>
    {unsupported&&<span role="status" className="cv-reference-warning">当前接口不支持原模型，请选择受支持的模型；原参数已保留。</span>}
   </>}
  </Section>
  <section ref={outputRef} className="cv-prop-section cv-pf-section cv-output-parameters" role="group" aria-label="输出参数设置" aria-describedby={`cv-prop-output-summary-${node.id}`}><div className="cv-prop-section-head"><h3>输出参数 <small id={`cv-prop-output-summary-${node.id}`} className="cv-output-summary">{outputSummary}</small></h3></div>
   {node.type==='audio'?<div className="cv-pf-fields cv-audio-output">
    <Field label="声线" prefix={<Mic size={14}/>}><select aria-label="音频预设声线" value={audioParams.speaker} onChange={e=>setParam('speaker',e.target.value)}>{!AUDIO_SPEAKERS.some(item=>item.value===audioParams.speaker)&&<option value={audioParams.speaker}>原声线不支持，请选择</option>}{AUDIO_SPEAKERS.map(item=><option key={item.value||'auto'} value={item.value}>{item.label}</option>)}</select></Field>
    <Field label="格式"><select aria-label="音频格式" value={audioParams.output_format} onChange={e=>setParam('output_format',e.target.value)}>{AUDIO_OUTPUT_FORMATS.map(item=><option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
    <Field label="采样率"><select aria-label="音频采样率" value={audioParams.sample_rate} onChange={e=>setParam('sample_rate',Number(e.target.value))}>{AUDIO_SAMPLE_RATES.map(rate=><option key={rate} value={rate}>{rate} Hz</option>)}</select></Field>
    <Toggle label="生成字幕"><input type="checkbox" className="cv-pf-switch" aria-label="生成字幕" checked={audioParams.enable_subtitle===true} onChange={e=>setParam('enable_subtitle',e.target.checked)}/></Toggle>
    <small className="cv-audio-note">时长由内容决定，最长 120 秒。预设声线不能与图片参考同时使用。</small>
   </div>
   :node.type==='image'?<div className="cv-image-parameters"><ImageOutputControls variant="panel" fieldPrefix={imagePrefix} Advanced={PropAdvanced} provider={imageAdapter} params={params} model={provider?.capability_model||provider?.model} references={imageMetadata.references} dimensions={imageDimensions} issues={imageIssues} metadataError={imageMetadata.error} onChange={patch=>onChange({params:{...params,...patch}})}/></div>
   :<div className="cv-pf-fields">
    <Field label="画幅" prefix={<RatioGlyph value={ratio.value}/>}><select aria-label="视频画幅" disabled={ratio.locked} title={ratio.locked?'Seedance 2.5 首尾帧自动保持首帧比例':undefined} value={ratio.value} onChange={e=>setParam('ratio',e.target.value)}>{VIDEO_RATIOS.map(v=><option key={v} value={v}>{v==='adaptive'?'自动匹配':v}</option>)}</select></Field>
    <Field label="分辨率"><select aria-label="视频分辨率" value={params.resolution||'720p'} onChange={e=>setParam('resolution',e.target.value)}>{(spec?.resolutions||[params.resolution||'720p']).map(v=><option key={v}>{v}</option>)}</select></Field>
    <Field label="时长" prefix={<Clock3 size={14}/>}><select aria-label="视频时长" value={params.duration??5} onChange={e=>setParam('duration',Number(e.target.value))}>{!videoDurations(model).includes(Number(params.duration??5))&&<option value={params.duration??5}>原时长不支持，请选择</option>}{videoDurations(model).map(v=><option key={v} value={v}>{v===-1?'Auto':`${v}s`}</option>)}</select></Field>
    {provider?.provider==='cupsy'&&<Field label="任务类型"><select aria-label="任务类型" disabled={params.video_mode==='keyframe'} title={params.video_mode==='keyframe'?'仅全能参考模式使用任务类型':'选择生成任务类型'} value={params.omni_reference_task_type||'auto'} onChange={e=>setParam('omni_reference_task_type',e.target.value)}><option value="auto">自动</option><option value="reference">参考生成</option><option value="edit">视频编辑</option><option value="extend">视频延长</option></select></Field>}
    <Toggle label="输出音频"><input type="checkbox" className="cv-pf-switch" aria-label="输出音频" checked={params.generate_audio===undefined||params.generate_audio===true} onChange={e=>setParam('generate_audio',e.target.checked)}/></Toggle>{params.generate_audio!==undefined&&typeof params.generate_audio!=='boolean'&&<span role="alert">输出音频设置无效，请重新勾选或关闭。</span>}
   </div>}
  {audioIssue&&<div className="cv-reference-warning" role="status" data-testid="audio-param-issue">{audioIssue}</div>}{imageInvalid&&<div className="cv-reference-warning" role="status">图片参数不适用于当前接口。<button type="button" onClick={showOutput}>处理输出参数</button></div>}
  </section>
  <Section id={`cv-prop-refs-${node.id}`} title={`参考${inputAssets.length?`（${inputAssets.length}）`:''}`} className="cv-pf-section cv-pf-refs" actions={<LibraryUploadMenu onLibrary={onLibrary} onUpload={onUpload}/>}>
   {inputAssets.length>0?<ReferenceThumbnails assets={inputAssets} frames={frames} onReorder={onReorderReferences}/>:<p className="cv-prop-hint">连线或添加素材作为参考</p>}
   {portWarnings.length>0&&<div className="cv-reference-warning cv-port-limit" role="status" data-testid="reference-over-limit"><span>{portWarnings.join('；')}。超出的参考已标红，生成已禁用；不会自动删除。</span>{overLimitCount>0&&onRemoveOverLimit&&<button type="button" className="btn btn-secondary btn-sm" onClick={onRemoveOverLimit}>移除超出的 {overLimitCount} 个参考</button>}</div>}
   {node.referenceGroups?.map(group=><small key={group.id}>旧素材组：{group.title}</small>)}
   {node.type==='video'&&params.video_mode==='keyframe'&&frames.issues.length>0&&<div className="cv-panel-frames">{frames.issues.map(issue=><span key={issue} role="status">{issue}</span>)}</div>}
   {(inputAssets.length>0||onOrganizeGroup)&&<div className="cv-pf-buttons">{onOrganizeGroup&&<button type="button" className="btn btn-secondary btn-sm" onClick={onOrganizeGroup}><LayoutGrid size={13} aria-hidden="true"/>整理首尾帧组</button>}{inputAssets.length>0&&<button type="button" className="btn btn-ghost btn-sm" onClick={onClearReferences}><Trash2 size={13} aria-hidden="true"/>清空所有参考</button>}</div>}
  </Section>
  {/* NODE-TOOLBAR-VERSIONS-20261118 (user 11-18): the 版本 section moved out of the panel. Version switching is the
     node toolbar's 历史版本 popover; 在素材库中显示 / 移动到文件夹 / 全部版本移动到文件夹 are in the node 更多 menu. */}
  <Section id={`cv-prop-prompt-${node.id}`} title="提示词" className="cv-pf-section cv-pf-prompt">
   <div className="cv-pf-buttons"><button type="button" className="btn btn-secondary btn-sm" onClick={onEditPrompt}><Pencil size={13} aria-hidden="true"/>编辑提示词</button><PromptLibraryPicker getTextarea={()=>document.querySelector(`.cv-node[data-node-id="${CSS.escape(node.id)}"] textarea.cv-card-prompt`)} value={node.text||''} onInsertFallback={text=>{editor?.setMentionError('');onChange({text})}}/></div>
   {editor?.characterBusy&&<div className="cv-reference-note" role="status" data-testid="character-busy">正在导入角色卡“{editor.characterBusy}”的参考素材…</div>}
   {editor?.notices.map(notice=><div key={notice.id} className="cv-stale-notice" role="status" data-testid="character-notice" data-status={notice.status}><span>{notice.text}</span>{notice.status==='updated'?<button type="button" disabled={!!editor.characterBusy} title="重新导入该角色卡的参考并替换【人物】块中该角色卡的内容；不会自动生成" onClick={()=>editor.syncCharacter(notice.id)}>同步角色卡</button>:<button type="button" onClick={()=>editor.dismissCharacter(notice.id)}>不再提示</button>}</div>)}
   {editor?.libraryUnknown&&<div className="cv-reference-note" role="status">无法读取角色卡库，暂不能检查角色卡是否已更新</div>}
   {issueText&&<div id={`cv-prompt-issue-${node.id}`} className="cv-reference-warning" role="alert">{issueText}</div>}
   {rebindText&&<div className="cv-reference-note" role="status" data-testid="mention-rebind-note">{rebindText}（按参考顺序解释，可撤销或重新 @ 选择）</div>}
  </Section>
  {regenerateConfirm&&<ConfirmDialog className="canvas-studio-confirm" title="确认重新生成？" danger confirmLabel="确认重新生成（会再次计费）" onClose={()=>setRegenerateConfirm(false)} onConfirm={()=>{setRegenerateConfirm(false);onGenerate()}}><p>{failureClass?.hint||'上次生成失败。'}</p><p>重新生成会按当前提示词与参数<strong>提交新任务并再次计费</strong>；不会自动重试。</p></ConfirmDialog>}
 </div>
}
