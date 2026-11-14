import React,{useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {X,RefreshCw} from 'lucide-react'
import {fetchCostLedger,describeBucket,taskAmount,basisLabel,typeLabel,BUCKET_ORDER,BUCKET_LABELS,LEDGER_DISCLAIMER,UNASSIGNED_PROJECT,REASON_LABELS} from '../../lib/costLedger'
import './costLedger.css'

const VIEWS=[['canvas','按画布'],['type','按类型'],['date','按日期'],['tasks','明细']]
const STATUS_LABELS={succeeded:'已完成',failed:'失败',cancelled:'已取消',cancel_requested:'取消中',pending:'排队中',processing:'生成中',preparing:'准备中',submitting:'提交中'}

function Figure({totals,bucket}){
 const d=describeBucket(totals?.[bucket])
 if(d.empty)return <span className="cv-ledger-muted">—</span>
 return <span className="cv-ledger-figure"><span>{d.amount}</span>{d.unknown&&<span className="cv-ledger-unknown">{d.unknown}</span>}</span>
}
function failedOrCancelled(totals){
 const merge=['failed','cancelled'].map(b=>totals?.[b]).filter(Boolean)
 return merge.reduce((sum,t)=>({count:sum.count+t.count,known_count:sum.known_count+t.known_count,unknown_count:sum.unknown_count+t.unknown_count,known_usd_min:sum.known_usd_min+t.known_usd_min,known_usd_max:sum.known_usd_max+t.known_usd_max}),{count:0,known_count:0,unknown_count:0,known_usd_min:0,known_usd_max:0})
}
function Row({name,level=0,totals,meta}){
 return <tr className={`cv-ledger-level-${level}`}><th scope="row"><span className="cv-ledger-name" title={name}>{name}</span>{meta&&<span className="cv-ledger-tag">{meta}</span>}</th><td><Figure totals={totals} bucket="billable"/></td><td><Figure totals={totals} bucket="result_unknown"/></td><td><Figure totals={{x:failedOrCancelled(totals)}} bucket="x"/></td><td><Figure totals={totals} bucket="active"/></td></tr>
}
function GroupTable({caption,children}){
 return <div className="cv-ledger-table-wrap"><table className="cv-ledger-table"><caption className="cv-ledger-sr">{caption}</caption><thead><tr><th scope="col">分组</th><th scope="col">已完成估算</th><th scope="col">结果未知（可能已计费）</th><th scope="col">失败/取消（通常不计费）</th><th scope="col">进行中</th></tr></thead><tbody>{children}</tbody></table></div>
}

export default function CostLedgerPanel({projectId,projectTitle,workflowId,workflowTitle,onClose}){
 const ref=useRef(null),[scope,setScope]=useState(projectId?'project':'all'),[from,setFrom]=useState(''),[to,setTo]=useState(''),[view,setView]=useState('canvas'),[state,setState]=useState({loading:true,data:null,error:''}),[reload,setReload]=useState(0)
 useEffect(()=>{const previous=document.activeElement;ref.current?.focus({preventScroll:true});return()=>{if(previous?.isConnected)previous.focus({preventScroll:true})}},[])
 useEffect(()=>{
  const controller=new AbortController()
  const query={from,to,projectId:scope==='project'?projectId:scope==='unassigned'?UNASSIGNED_PROJECT:undefined,workflowId:scope==='workflow'?workflowId:undefined}
  setState(s=>({...s,loading:true,error:''}))
  fetchCostLedger(query,controller.signal).then(data=>setState({loading:false,data,error:''})).catch(error=>{if(controller.signal.aborted)return;setState({loading:false,data:null,error:error.response?.data?.error||error.message||'读取费用失败'})})
  return()=>controller.abort()
 },[scope,from,to,projectId,workflowId,reload])
 const keys=event=>{event.stopPropagation();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s')event.preventDefault();if(event.key==='Escape'){event.preventDefault();onClose()}if(event.key==='Tab'){const items=[...ref.current.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];if(!items.length)return;if(event.shiftKey&&[ref.current,items[0]].includes(document.activeElement)){event.preventDefault();items.at(-1).focus()}else if(!event.shiftKey&&document.activeElement===items.at(-1)){event.preventDefault();items[0].focus()}}}
 const data=state.data,totals=data?.totals
 const main=describeBucket(totals?.billable)
 return createPortal(<div className="cv-ledger-backdrop"><section className="cv-ledger" role="dialog" aria-modal="true" aria-labelledby="cv-ledger-title" aria-describedby="cv-ledger-note" ref={ref} tabIndex={-1} onKeyDown={keys}>
  <header className="cv-ledger-header"><div><h1 id="cv-ledger-title">费用账本</h1><p id="cv-ledger-note" className="cv-ledger-note" data-testid="cost-ledger-disclaimer"><strong>{LEDGER_DISCLAIMER}</strong>。视频按 BytePlus 费率估算（Cupsy 同价）；图像、音频暂无价格资料记为未知，未知不计入合计。</p></div><button className="btn btn-icon btn-outlined btn-lg" aria-label="关闭费用账本" title="关闭" onClick={onClose}><X size={18}/></button></header>
  <div className="cv-ledger-filters">
   <label>范围<select aria-label="统计范围" value={scope} onChange={e=>setScope(e.target.value)}>{projectId&&<option value="project">本项目{projectTitle?`：${projectTitle}`:''}</option>}{workflowId&&<option value="workflow">当前画布{workflowTitle?`：${workflowTitle}`:''}</option>}<option value="unassigned">未归属项目（旧工具任务）</option><option value="all">全部任务</option></select></label>
   <label>开始日期<input type="date" aria-label="开始日期" value={from} max={to||undefined} onChange={e=>setFrom(e.target.value)}/></label>
   <label>结束日期<input type="date" aria-label="结束日期" value={to} min={from||undefined} onChange={e=>setTo(e.target.value)}/></label>
   <button className="btn btn-outlined btn-sm" onClick={()=>setReload(n=>n+1)} disabled={state.loading} aria-label="刷新费用"><RefreshCw size={14}/>刷新</button>
  </div>
  {state.error&&<p role="alert" className="cv-ledger-error">{state.error}</p>}
  {state.loading&&!data&&<p role="status" className="cv-ledger-muted">正在统计…</p>}
  {data&&<>
   <div className="cv-ledger-summary" aria-live="polite" aria-busy={state.loading}>
    <div className="cv-ledger-card is-main" data-testid="cost-ledger-total"><span>已完成任务 · 估算合计</span><strong>{main.empty?'—':main.amount}</strong><em>{main.empty?'无任务':`已知 ${totals.billable.known_count} 条${totals.billable.unknown_count?` · 未知 ${totals.billable.unknown_count} 条（不计入）`:''}`}</em></div>
    {['result_unknown','failed','cancelled','active'].map(bucket=>{const d=describeBucket(totals[bucket]);return <div key={bucket} className={`cv-ledger-card is-${bucket}`} data-testid={`cost-ledger-${bucket}`}><span>{BUCKET_LABELS[bucket]}</span><strong>{d.empty?'—':d.amount}</strong><em>{d.empty?'无任务':`${totals[bucket].count} 条${d.unknown?` · ${d.unknown}`:''}`}</em></div>})}
   </div>
   {Object.keys(totals.billable.unknown_reasons||{}).length>0&&<p className="cv-ledger-muted cv-ledger-reasons">未知原因：{Object.entries(totals.billable.unknown_reasons).map(([k,v])=>`${REASON_LABELS[k]||k} ${v} 条`).join('；')}</p>}
   <div className="cv-ledger-tabs" role="tablist" aria-label="分组方式">{VIEWS.map(([key,label])=><button key={key} role="tab" id={`cv-ledger-tab-${key}`} aria-selected={view===key} aria-controls="cv-ledger-view" tabIndex={view===key?0:-1} onClick={()=>setView(key)} onKeyDown={e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const i=VIEWS.findIndex(v=>v[0]===view),next=VIEWS[(i+(e.key==='ArrowRight'?1:-1)+VIEWS.length)%VIEWS.length][0];setView(next);requestAnimationFrame(()=>document.getElementById(`cv-ledger-tab-${next}`)?.focus())}}>{label}</button>)}</div>
   <div id="cv-ledger-view" role="tabpanel" aria-labelledby={`cv-ledger-tab-${view}`} className="cv-ledger-view">
    {data.tasks_total===0&&<p className="cv-ledger-muted">所选范围内没有生成任务。</p>}
    {data.tasks_total>0&&view==='canvas'&&<GroupTable caption="按项目、画布、节点分组">{data.projects.flatMap(p=>[<Row key={p.id} name={p.title} totals={p.totals} meta={p.deleted?'已删除':''}/>,...p.workflows.flatMap(w=>[<Row key={`${p.id}/${w.id}`} level={1} name={w.title} totals={w.totals} meta={w.deleted?'已删除':''}/>,...w.nodes.map(n=><Row key={`${w.id}/${n.node_id||''}`} level={2} name={n.node_id?(n.title||`${typeLabel(n.type)}节点`):'节点未知'} totals={n.totals} meta={`${typeLabel(n.type)}${n.missing?' · 已移除':''}`}/>)])])}</GroupTable>}
    {data.tasks_total>0&&view==='type'&&<GroupTable caption="按任务类型分组">{data.types.map(t=><Row key={t.type} name={typeLabel(t.type)} totals={t.totals}/>)}</GroupTable>}
    {data.tasks_total>0&&view==='date'&&<GroupTable caption="按日期分组">{data.dates.map(d=><Row key={d.date} name={d.date} totals={d.totals}/>)}</GroupTable>}
    {data.tasks_total>0&&view==='tasks'&&<div className="cv-ledger-table-wrap"><table className="cv-ledger-table is-tasks"><caption className="cv-ledger-sr">任务明细</caption><thead><tr><th scope="col">任务</th><th scope="col">类型</th><th scope="col">接口 / 模型</th><th scope="col">状态</th><th scope="col">估算</th><th scope="col">日期</th></tr></thead><tbody>{data.tasks.map(t=><tr key={t.id} data-task-id={t.id}><th scope="row">#{t.id}</th><td>{typeLabel(t.type)}</td><td>{[t.provider,t.model].filter(Boolean).join(' / ')||'—'}</td><td><span className={`cv-ledger-status is-${t.bucket}`} title={BUCKET_LABELS[t.bucket]}>{STATUS_LABELS[t.status]||t.status}{t.bucket==='result_unknown'?' · 结果未知':''}</span></td><td><span className={t.estimate_usd?'':'cv-ledger-unknown'}>{taskAmount(t)}</span>{basisLabel(t)&&<span className="cv-ledger-tag">{basisLabel(t)}</span>}</td><td>{t.date}</td></tr>)}</tbody></table>{data.tasks_truncated&&<p className="cv-ledger-muted">仅显示最近 {data.tasks.length} 条，合计覆盖全部 {data.tasks_total} 条。</p>}</div>}
   </div>
  </>}
 </section></div>,document.body)
}
