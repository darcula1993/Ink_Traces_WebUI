import React,{useEffect,useMemo,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import axios from 'axios'
import {X,RefreshCw,AlertTriangle} from 'lucide-react'
import {fetchCostLedger,describeBucket,describeNotBilled,ledgerTaskAmount,taskTime,placeIndex,taskPlace,NOT_BILLED_BUCKETS,basisLabel,typeLabel,BUCKET_ORDER,BUCKET_LABELS,LEDGER_DISCLAIMER,UNASSIGNED_PROJECT,REASON_LABELS,taskAmount,basisTitle} from '../../lib/costLedger'
import {evaluateBudgetProgress,formatBudgetUsd,parseBudgetInput,PROJECT_BUDGET_EVENT} from '../../lib/projectBudget'
import {requestTaskCenter,TASK_CENTER_MODES} from '../../lib/taskCenterLink'
import Select from '../ui/Select'
import './costLedger.css'

const VIEWS=[['canvas','按画布'],['type','按类型'],['date','按日期'],['tasks','明细']]
const STATUS_LABELS={succeeded:'已完成',failed:'失败',cancelled:'已取消',cancel_requested:'取消中',pending:'排队中',processing:'生成中',preparing:'准备中',submitting:'提交中'}
const ADAPTER_LABELS={ark:'BytePlus Ark',cupsy:'Cupsy',google:'Google'}
const taskSourceLabel=t=>{
 const source=t.profile_name||ADAPTER_LABELS[t.provider]||t.provider||''
 const model=t.model_label||(t.model&&!/^ep-/i.test(String(t.model))?t.model:'')
 return [source,model].filter(Boolean).join(' · ')||'—'
}

function Figure({totals,bucket}){
 const d=describeBucket(totals?.[bucket])
 if(d.empty)return <span className="cv-ledger-muted">—</span>
 return <span className="cv-ledger-figure"><span>{d.amount}</span>{d.unknown&&<span className="cv-ledger-unknown">{d.unknown}</span>}</span>
}
function NotBilledFigure({totals}){
 const d=describeNotBilled(totals?.failed,totals?.cancelled)
 if(d.empty)return <span className="cv-ledger-muted">—</span>
 return <span className="cv-ledger-figure"><span className="cv-ledger-muted">{d.amount}</span><span className="cv-ledger-count">{d.text}</span></span>
}
function Row({name,level=0,totals,meta}){
 return <tr className={`cv-ledger-level-${level}`}><th scope="row"><span className="cv-ledger-name" title={name}>{name}</span>{meta&&<span className="cv-ledger-tag">{meta}</span>}</th><td><Figure totals={totals} bucket="billable"/></td><td><Figure totals={totals} bucket="result_unknown"/></td><td><NotBilledFigure totals={totals}/></td><td><Figure totals={totals} bucket="active"/></td></tr>
}
function GroupTable({caption,children}){
 return <div className="cv-ledger-table-wrap"><table className="cv-ledger-table"><caption className="cv-ledger-sr">{caption}</caption><thead><tr><th scope="col">分组</th><th scope="col">已完成估算</th><th scope="col">结果未知（可能已计费）</th><th scope="col">失败/取消（通常不计费）</th><th scope="col">进行中</th></tr></thead><tbody>{children}</tbody></table></div>
}

export default function CostLedgerPanel({projectId,projectTitle,workflowId,workflowTitle,onClose}){
 const ref=useRef(null),[scope,setScope]=useState(projectId?'project':'all'),[from,setFrom]=useState(''),[to,setTo]=useState(''),[view,setView]=useState('canvas'),[state,setState]=useState({loading:true,data:null,error:''}),[reload,setReload]=useState(0)
 const [budgetInput,setBudgetInput]=useState(''),[budgetSaving,setBudgetSaving]=useState(false),[budgetError,setBudgetError]=useState(''),[budgetNotice,setBudgetNotice]=useState('')
 useEffect(()=>{const previous=document.activeElement;ref.current?.focus({preventScroll:true});return()=>{if(previous?.isConnected)previous.focus({preventScroll:true})}},[])
 useEffect(()=>{const onKey=event=>{if(event.defaultPrevented||event.key!=='Escape')return;if(!ref.current?.contains(document.activeElement)){event.preventDefault();onClose()}};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[onClose])
 useEffect(()=>{
  const controller=new AbortController()
  const query={from,to,projectId:scope==='project'?projectId:scope==='unassigned'?UNASSIGNED_PROJECT:undefined,workflowId:scope==='workflow'?workflowId:undefined}
  setState(s=>({...s,loading:true,error:''}))
  fetchCostLedger(query,controller.signal).then(data=>{
   setState({loading:false,data,error:''})
   if(projectId&&(scope==='project'||scope==='workflow')){
    setBudgetInput(data.budget_usd!=null?String(data.budget_usd):'')
    setBudgetError('')
   }
  }).catch(error=>{if(controller.signal.aborted)return;setState({loading:false,data:null,error:error.response?.data?.error||error.message||'读取费用失败'})})
  return()=>controller.abort()
 },[scope,from,to,projectId,workflowId,reload])
 const keys=event=>{event.stopPropagation();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')event.preventDefault();if(event.key==='Escape'){event.preventDefault();onClose()}if(event.key==='Tab'){const items=[...ref.current.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];if(!items.length)return;if(event.shiftKey&&[ref.current,items[0]].includes(document.activeElement)){event.preventDefault();items.at(-1).focus()}else if(!event.shiftKey&&document.activeElement===items.at(-1)){event.preventDefault();items[0].focus()}}}
 const data=state.data,totals=data?.totals
 const main=describeBucket(totals?.billable),places=placeIndex(data)
 const showProjectBudget=Boolean(projectId&&(scope==='project'||scope==='workflow'))
 const projectBillable=data?.project_billable||totals?.billable
 const budgetProgress=useMemo(()=>evaluateBudgetProgress({billable:projectBillable,budgetUsd:data?.budget_usd??null}),[projectBillable,data?.budget_usd])
 const saveBudget=async nextRaw=>{
  if(!projectId||budgetSaving)return
  const parsed=parseBudgetInput(nextRaw)
  if(!parsed.valid){setBudgetError(parsed.error);setBudgetNotice('');return}
  setBudgetSaving(true);setBudgetError('');setBudgetNotice('')
  try{
   const res=(await axios.put('/api/cost-ledger/budget',{project_id:projectId,budget_usd:parsed.value})).data
   const nextBudget=res.budget_usd??null
   setState(current=>current.data?{...current,data:{...current.data,budget_usd:nextBudget}}:current)
   setBudgetInput(nextBudget!=null?String(nextBudget):'')
   setBudgetNotice(nextBudget!=null?`已保存本项目预算提醒线 ${formatBudgetUsd(nextBudget)}（超额仅作软提醒，不阻断提交）`:'已清除本项目预算提醒线')
   window.dispatchEvent(new CustomEvent(PROJECT_BUDGET_EVENT,{detail:{projectId,budgetUsd:nextBudget}}))
  }catch(failure){
   setBudgetError(failure.response?.data?.error||failure.message||'保存预算提醒线失败')
  }finally{
   setBudgetSaving(false)
   requestAnimationFrame(()=>{if(ref.current&&!ref.current.contains(document.activeElement))ref.current.focus({preventScroll:true})})
  }
 }
 const scopeOptions=useMemo(()=>[
  ...(projectId?[{value:'project',label:`本项目${projectTitle?`：${projectTitle}`:''}`}]:[]),
  ...(workflowId?[{value:'workflow',label:`当前画布${workflowTitle?`：${workflowTitle}`:''}`}]:[]),
  {value:'unassigned',label:'未归属项目（旧工具任务）'},
  {value:'all',label:'全部任务'},
 ],[projectId,projectTitle,workflowId,workflowTitle])
 const openLedgerTask=task=>{
  if(!TASK_CENTER_MODES.includes(task?.type))return
  onClose?.()
  requestTaskCenter({taskId:task.id,type:task.type})
 }
 return createPortal(<div className="cv-ledger-backdrop"><section className="cv-ledger" role="dialog" aria-modal="true" aria-labelledby="cv-ledger-title" aria-describedby="cv-ledger-note" ref={ref} tabIndex={-1} onKeyDown={keys}>
  <header className="cv-ledger-header"><div><h1 id="cv-ledger-title">费用账本</h1><p id="cv-ledger-note" className="cv-ledger-note" data-testid="cost-ledger-disclaimer"><strong>{LEDGER_DISCLAIMER}</strong>。图像、图层、视频按 BytePlus 价格表估算（Cupsy 同价）；音频暂无价格资料，记为“未知”（不当作零），未知不计入合计。</p></div><button className="btn btn-icon btn-outlined btn-lg" aria-label="关闭费用账本" title="关闭" onClick={onClose}><X size={18}/></button></header>
  <div className="cv-ledger-filters">
   <label>范围<Select ariaLabel="统计范围" className="cv-ledger-scope-select" value={scope} onChange={setScope} options={scopeOptions}/></label>
   <label>开始日期<input type="date" aria-label="开始日期" value={from} max={to||undefined} onChange={e=>setFrom(e.target.value)}/></label>
   <label>结束日期<input type="date" aria-label="结束日期" value={to} min={from||undefined} onChange={e=>setTo(e.target.value)}/></label>
   <button className="btn btn-outlined btn-sm" onClick={()=>setReload(n=>n+1)} disabled={state.loading} aria-label="刷新费用"><RefreshCw size={14}/>刷新</button>
  </div>
  {state.error&&<p role="alert" className="cv-ledger-error">{state.error}</p>}
  {state.loading&&!data&&<p role="status" className="cv-ledger-muted">正在统计…</p>}
  {data&&<>
   {showProjectBudget&&<section className={`cv-ledger-budget is-${budgetProgress.status}`} aria-label="项目预算软提醒线" data-testid="cost-ledger-budget">
    <div className="cv-ledger-budget-head">
     <div className="cv-ledger-budget-meta">
      <strong>本项目预算提醒线（软提醒，不阻断提交）</strong>
      <span data-testid="cost-ledger-budget-summary">{budgetProgress.summaryText}</span>
      {budgetProgress.unknownNote&&<em className="cv-ledger-unknown" data-testid="cost-ledger-budget-unknown">{budgetProgress.unknownNote}</em>}
     </div>
     <form className="cv-ledger-budget-form" onSubmit={e=>{e.preventDefault();saveBudget(budgetInput)}}>
      <label className="cv-ledger-budget-field"><span>阈值（USD）</span><input type="number" inputMode="decimal" min="0.01" max="100000" step="0.01" placeholder="例如 5.00" aria-label="项目预算提醒线（USD）" value={budgetInput} disabled={budgetSaving} onChange={e=>{setBudgetInput(e.target.value);if(budgetError)setBudgetError('')}}/></label>
      <button type="submit" className="btn btn-primary btn-sm" disabled={budgetSaving}>{budgetSaving?'保存中…':'保存阈值'}</button>
      {budgetProgress.configured&&<button type="button" className="btn btn-outlined btn-sm" disabled={budgetSaving} onClick={()=>saveBudget(null)}>清除阈值</button>}
     </form>
    </div>
    {budgetProgress.configured&&<div className="cv-ledger-budget-track" role="progressbar" aria-label="已完成估算占预算提醒线比例" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(budgetProgress.percent)}><div className={`cv-ledger-budget-fill is-${budgetProgress.status}`} style={{width:`${budgetProgress.percent}%`}}/></div>}
    {budgetProgress.exceeded&&<p className="cv-ledger-budget-warn" role="status"><AlertTriangle size={13} aria-hidden="true"/>当前已完成估算已超出本项目预算提醒线（仅供参考，不阻断后续提交）。</p>}
    {budgetError&&<p className="cv-ledger-error cv-ledger-budget-msg" role="alert">{budgetError}</p>}
    {budgetNotice&&!budgetError&&<p className="cv-ledger-budget-notice cv-ledger-budget-msg" role="status">{budgetNotice}</p>}
   </section>}
   <div className="cv-ledger-summary" aria-live="polite" aria-busy={state.loading}>
    <div className="cv-ledger-card is-main" data-testid="cost-ledger-total"><span>已完成任务 · 估算合计</span><strong>{main.empty?'—':main.amount}</strong><em>{main.empty?'无任务':`已知 ${totals.billable.known_count} 条${totals.billable.unknown_count?` · 未知 ${totals.billable.unknown_count} 条（不计入）`:''}`}</em></div>
    {['result_unknown','failed','cancelled','active'].map(bucket=>{const d=NOT_BILLED_BUCKETS.includes(bucket)?{...describeNotBilled(totals[bucket]),unknown:''}:describeBucket(totals[bucket]);return <div key={bucket} className={`cv-ledger-card is-${bucket}`} data-testid={`cost-ledger-${bucket}`}><span>{BUCKET_LABELS[bucket]}</span><strong>{d.empty?'—':d.amount}</strong><em>{d.empty?'无任务':`${totals[bucket].count} 条${d.unknown?` · ${d.unknown}`:''}`}</em></div>})}
   </div>
   {Object.keys(totals.billable.unknown_reasons||{}).length>0&&<p className="cv-ledger-muted cv-ledger-reasons">未知原因：{Object.entries(totals.billable.unknown_reasons).map(([k,v])=>`${REASON_LABELS[k]||k} ${v} 条`).join('；')}</p>}
   <div className="cv-ledger-tabs" role="tablist" aria-label="分组方式">{VIEWS.map(([key,label])=><button key={key} role="tab" id={`cv-ledger-tab-${key}`} aria-selected={view===key} aria-controls="cv-ledger-view" tabIndex={view===key?0:-1} onClick={()=>setView(key)} onKeyDown={e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const i=VIEWS.findIndex(v=>v[0]===view),next=VIEWS[(i+(e.key==='ArrowRight'?1:-1)+VIEWS.length)%VIEWS.length][0];setView(next);requestAnimationFrame(()=>document.getElementById(`cv-ledger-tab-${next}`)?.focus())}}>{label}</button>)}</div>
   <div id="cv-ledger-view" role="tabpanel" aria-labelledby={`cv-ledger-tab-${view}`} className="cv-ledger-view">
    {data.tasks_total===0&&<p className="cv-ledger-muted">所选范围内没有生成任务。</p>}
    {data.tasks_total>0&&view==='canvas'&&<GroupTable caption="按项目、画布、节点分组">{data.projects.flatMap(p=>[<Row key={p.id} name={p.title} totals={p.totals} meta={p.deleted?'已删除':''}/>,...p.workflows.flatMap(w=>[<Row key={`${p.id}/${w.id}`} level={1} name={w.title} totals={w.totals} meta={w.deleted?'已删除':''}/>,...w.nodes.map(n=><Row key={`${w.id}/${n.node_id||''}`} level={2} name={n.node_id?(n.title||`${typeLabel(n.type)}节点`):'节点未知'} totals={n.totals} meta={`${typeLabel(n.type)}${n.missing?' · 已移除':''}`}/>)])])}</GroupTable>}
    {data.tasks_total>0&&view==='type'&&<GroupTable caption="按任务类型分组">{data.types.map(t=><Row key={t.type} name={typeLabel(t.type)} totals={t.totals}/>)}</GroupTable>}
    {data.tasks_total>0&&view==='date'&&<GroupTable caption="按日期分组">{data.dates.map(d=><Row key={d.date} name={d.date} totals={d.totals}/>)}</GroupTable>}
    {data.tasks_total>0&&view==='tasks'&&<div className="cv-ledger-table-wrap"><table className="cv-ledger-table is-tasks"><caption className="cv-ledger-sr">任务明细</caption><thead><tr><th scope="col">任务</th><th scope="col">类型</th><th scope="col">项目 / 画布</th><th scope="col">接口 / 模型</th><th scope="col">状态</th><th scope="col">估算</th><th scope="col">提交时间</th></tr></thead><tbody>{data.tasks.map(t=><tr key={t.id} data-task-id={t.id}><th scope="row">{TASK_CENTER_MODES.includes(t.type)?<button type="button" className="cv-ledger-task-link" data-testid={`ledger-task-link-${t.id}`} aria-label={`在${typeLabel(t.type)}任务中心查看任务 #${t.id}`} title={`跳转到${typeLabel(t.type)}任务中心查看 #${t.id}`} onClick={()=>openLedgerTask(t)}>#{t.id}</button>:`#${t.id}`}</th><td>{typeLabel(t.type)}</td><td><span className="cv-ledger-place" title={taskPlace(t,places)}>{taskPlace(t,places)}</span></td><td><span className="cv-ledger-place" title={taskSourceLabel(t)}>{taskSourceLabel(t)}</span></td><td><span className={`cv-ledger-status is-${t.bucket}`} title={BUCKET_LABELS[t.bucket]}>{STATUS_LABELS[t.status]||t.status}{t.bucket==='result_unknown'?' · 结果未知':''}</span></td><td><span className={NOT_BILLED_BUCKETS.includes(t.bucket)?'cv-ledger-muted':t.estimate_usd?'':'cv-ledger-unknown'}>{ledgerTaskAmount(t)}</span>{basisLabel(t)&&<span className="cv-ledger-tag" title={basisTitle(t)||undefined}>{basisLabel(t)}</span>}</td><td><time dateTime={t.created_at||t.date}>{taskTime(t)}</time></td></tr>)}</tbody></table>{data.tasks_truncated&&<p className="cv-ledger-muted">仅显示最近 {data.tasks.length} 条，合计覆盖全部 {data.tasks_total} 条。</p>}</div>}
   </div>
  </>}
 </section></div>,document.body)
}
