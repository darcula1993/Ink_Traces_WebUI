import React,{useEffect,useRef,useState} from 'react'
import {ChevronDown,ChevronRight,MoreHorizontal,Plus,Check} from 'lucide-react'
import SidebarEditableName from './SidebarEditableName'
import ProjectOverview from './ProjectOverview'
import CostLedgerPanel from './CostLedgerPanel'
import './sidebarMenus.css'
import SidebarNodeList from './SidebarNodeList'
import {menuPosition} from './SidebarMenu'
import SidebarMenu from './SidebarNavigationMenu'

function WorkflowNameEditor({initialValue,onCommit,onCancel}) {
 const [draft,setDraft]=useState(initialValue||'')
 const [saving,setSaving]=useState(false)
 const [error,setError]=useState('')
 const inputRef=useRef(null),pending=useRef(false)
 const commit=async()=>{
  if(pending.current)return
  if(!draft.trim()){setError('名称不能为空');return}
  pending.current=true;setSaving(true);setError('')
  try{await onCommit(draft.trim())}
  catch(failure){setError(failure?.response?.data?.error||failure.message||'保存失败，请重试');requestAnimationFrame(()=>inputRef.current?.focus())}
  finally{pending.current=false;setSaving(false)}
 }
 return <span className="cv-sidebar-name-editor cv-workflow-name-editor"><input ref={inputRef} autoFocus aria-label="重命名画布" aria-invalid={!!error} maxLength={100} value={draft} disabled={saving} onFocus={e=>e.target.select()} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{e.stopPropagation();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();return}if(e.key==='Enter'){e.preventDefault();commit()}if(e.key==='Escape'&&!saving){e.preventDefault();onCancel(true)}}} onBlur={()=>{if(!pending.current)onCancel(false)}}/>{error&&<span role="alert">{error}</span>}</span>
}

function clampMenuPosition(event,width) {
 const position=menuPosition(event)
 const container=event.currentTarget.closest('[data-panel-bounds]')||event.currentTarget.closest('nav')
 if(!container)return {position,maxWidth:width}
 const bounds=container.getBoundingClientRect()
 position.x=Math.max(bounds.left+8,Math.min(position.x,bounds.right-width-8))
 return {position,maxWidth:Math.max(140,bounds.width-16)}
}

// LEFT-CANVAS-PANEL-20261120: compact project header row (current project name + recent switcher + more menu).
export function CanvasProjectHeader({projects=[],projectId,workflow,disabled,onProject,onNewProject,onRenameProject,onRenameProjectDirect,onDeleteProject,onDeleteWorkflow,onPendingDeletions,onBulkDeleteProjects,navigationError=''}) {
 const [menu,setMenu]=useState(null),[overview,setOverview]=useState(null),[ledger,setLedger]=useState(false)
 const rootRef=useRef(null)
 const closeOverview=()=>{setOverview(null);requestAnimationFrame(()=>rootRef.current?.querySelector('[aria-label="选择项目"]')?.focus({preventScroll:true}))}
 const project=projects.find(p=>p.id===projectId)
 const command=fn=>()=>{setMenu(null);fn?.()}
 const openMenu=(type,event)=>{
  const {position,maxWidth}=clampMenuPosition(event,type==='more'?225:248)
  setMenu(current=>current?.type===type?null:{type,position,maxWidth})
 }
 const showProjects=()=>setOverview('all')
 const stamp=item=>Date.parse(item.updated_at||item.created_at||'')||0
 const recent=projects.slice().sort((a,b)=>stamp(b)-stamp(a)).slice(0,5)
 return <div ref={rootRef} className="cv-project-row">
  <SidebarEditableName key={projectId} name="项目" onRename={onRenameProjectDirect} className="cv-project-name" aria-label="选择项目" data-project-id={projectId||''} title={project?.title||'全部项目'} disabled={disabled} onClick={showProjects}>{project?.title||'项目'}</SidebarEditableName>
  <div className="cv-project-row-actions">
   <button type="button" className="cv-project-switch" aria-label="切换项目" title="最近项目" aria-haspopup="menu" aria-expanded={menu?.type==='projects'} disabled={disabled} onClick={e=>openMenu('projects',e)}><ChevronDown size={14} aria-hidden="true"/></button>
   <button type="button" className="cv-sidebar-more" aria-label="更多操作" title="更多操作" aria-haspopup="menu" aria-expanded={menu?.type==='more'} disabled={disabled} onClick={e=>openMenu('more',e)}><MoreHorizontal size={16} aria-hidden="true"/></button>
  </div>
  {menu?.type==='projects'&&<SidebarMenu label="最近项目" position={menu.position} maxWidth={menu.maxWidth} onClose={()=>setMenu(null)} className="cv-workflow-dropdown"><div className="cv-sidebar-menu-heading">最近项目</div>{recent.map(item=><button role="menuitemradio" key={item.id} data-project-id={item.id} aria-checked={item.id===projectId} disabled={disabled} title={item.title} onClick={command(()=>onProject(item.id))}><span>{item.title}</span>{item.id===projectId&&<Check size={16} aria-hidden="true"/>}</button>)}<hr/><button role="menuitem" disabled={disabled} onClick={command(showProjects)}>全部项目…</button></SidebarMenu>}
  {menu?.type==='more'&&<SidebarMenu label="更多操作" position={menu.position} maxWidth={menu.maxWidth} onClose={()=>setMenu(null)}><div className="cv-sidebar-menu-heading" id="cv-more-project">项目</div><div role="group" aria-labelledby="cv-more-project"><button role="menuitem" disabled={disabled} onClick={command(showProjects)}>全部项目</button><button role="menuitem" disabled={disabled} onClick={command(onNewProject)}>创建新项目</button><button role="menuitem" disabled={disabled||!projectId} onClick={command(onRenameProject)}>命名项目</button><button role="menuitem" onClick={command(()=>setLedger(true))}>费用（估算）</button><hr/><button role="menuitem" className="is-danger" disabled={disabled||!projectId} onClick={command(onDeleteProject)}>删除项目</button></div><div className="cv-sidebar-menu-heading" id="cv-more-workflow">画布</div><div role="group" aria-labelledby="cv-more-workflow"><button role="menuitem" disabled={disabled} onClick={command(onPendingDeletions)}>待完成删除</button><hr/><button role="menuitem" className="is-danger" disabled={disabled||!workflow} onClick={command(()=>onDeleteWorkflow?.(workflow))}>删除画布</button></div></SidebarMenu>}
  {overview&&<ProjectOverview projects={projects} currentProjectId={projectId} disabled={disabled} onClose={closeOverview} onSelect={onProject} onCreate={onNewProject} onBulkDelete={onBulkDeleteProjects} navigationError={navigationError}/>}
  {ledger&&<CostLedgerPanel projectId={projectId} projectTitle={project?.title} workflowId={workflow?.id} workflowTitle={workflow?.title} onClose={()=>setLedger(false)}/>}
 </div>
}

// LEFT-CANVAS-PANEL-20261120: ImagineArt-inspired left panel with Linear dark palette:
// compact project row + collapsible "画布" list (flat pill rows) + 1px divider + collapsible "节点" section.
export default function CanvasProjectPanel({edges=[],groups=[],nodes=[],selected,selectedIds,disabled,onLocateGroup,onRenameGroup,onUngroup,onLocate,onSelect,onCopy,onDelete,onRenameNode,onRating,onToggleFinalized,workflows=[],workflow,onWorkflow,onNewWorkflow,onRenameWorkflow,onDuplicateWorkflow,onDeleteWorkflow,...header}) {
 const [pagesOpen,setPagesOpen]=useState(true)
 const [nodesOpen,setNodesOpen]=useState(true)
 const [onlyFinalized,setOnlyFinalized]=useState(false)
 const [workflowMenu,setWorkflowMenu]=useState(null)
 const [renamingId,setRenamingId]=useState(null)
 const panelRef=useRef(null),menuJustClosed=useRef(null)
 const finalizedCount=nodes.filter(node=>node.finalized===true).length
 useEffect(()=>{setOnlyFinalized(false)},[workflow?.id])

 const focusWorkflow=id=>requestAnimationFrame(()=>{
  const selector=`button[data-workflow-id="${typeof CSS!=='undefined'&&CSS.escape?CSS.escape(String(id)):String(id)}"]`
  panelRef.current?.querySelector(selector)?.focus({preventScroll:true})
 })
 const openWorkflowMenu=(event,item)=>{
  event.preventDefault();event.stopPropagation()
  if(disabled)return
  if(event.type!=='contextmenu'&&menuJustClosed.current===item.id){menuJustClosed.current=null;return}
  const {position,maxWidth}=clampMenuPosition(event,196)
  setWorkflowMenu(current=>current?.id===item.id&&event.type!=='contextmenu'?null:{id:item.id,position,maxWidth})
 }
 const activeMenuWorkflow=workflows.find(item=>item.id===workflowMenu?.id)

 return <div ref={panelRef} className="cv-panel-project" data-panel-bounds="">
  <CanvasProjectHeader disabled={disabled} workflow={workflow} onDeleteWorkflow={onDeleteWorkflow} {...header}/>

  <section className={`cv-panel-section cv-pages-section${pagesOpen?' is-open':' is-collapsed'}`} aria-labelledby="cv-section-pages-title">
   <div className="cv-section-head">
    <h3 id="cv-section-pages-title" className="cv-section-title" onClick={()=>setPagesOpen(v=>!v)}>画布</h3>
    <div className="cv-section-actions">
     <button type="button" className="cv-section-btn" aria-label="新建画布" title="新建画布" disabled={disabled} onClick={onNewWorkflow}><Plus size={15} aria-hidden="true"/></button>
     <button type="button" className="cv-section-btn" aria-label={pagesOpen?'折叠画布列表':'展开画布列表'} title={pagesOpen?'折叠画布列表':'展开画布列表'} aria-expanded={pagesOpen} aria-controls="cv-pages-list" onClick={()=>setPagesOpen(v=>!v)}>{pagesOpen?<ChevronDown size={15} aria-hidden="true"/>:<ChevronRight size={15} aria-hidden="true"/>}</button>
    </div>
   </div>
   {pagesOpen&&<div id="cv-pages-list" className="cv-workflow-list">
    {workflows.map(item=>{
     const isActive=item.id===workflow?.id
     const displayTitle=(isActive&&workflow?.title)?workflow.title:item.title
     const isMenuOpen=workflowMenu?.id===item.id
     const isRenaming=renamingId===item.id
     return <div key={item.id} className={`cv-workflow-item${isActive?' is-active':''}${isMenuOpen?' is-menu-open':''}`} onContextMenu={e=>openWorkflowMenu(e,item)}>
      {isRenaming?<WorkflowNameEditor initialValue={displayTitle} onCommit={async next=>{await onRenameWorkflow?.(next,item.id);setRenamingId(null);focusWorkflow(item.id)}} onCancel={restore=>{setRenamingId(null);if(restore)focusWorkflow(item.id)}}/>:<>
       <button type="button" className="cv-workflow-item-main" data-workflow-id={item.id} aria-label={isActive?'选择画布':undefined} aria-current={isActive?'page':undefined} title={displayTitle} disabled={disabled} onClick={()=>{if(!isActive)onWorkflow?.(item.id)}} onDoubleClick={e=>{if(disabled||!isActive)return;e.preventDefault();setWorkflowMenu(null);setRenamingId(item.id)}}><span>{displayTitle}</span></button>
       <div className="cv-workflow-item-actions">
        <button type="button" aria-label={`画布操作 ${displayTitle}`} title="画布操作" aria-haspopup="menu" aria-expanded={isMenuOpen} disabled={disabled} onPointerDown={()=>{menuJustClosed.current=isMenuOpen?item.id:null}} onClick={e=>openWorkflowMenu(e,item)}><MoreHorizontal size={15} aria-hidden="true"/></button>
       </div>
      </>}
     </div>
    })}
    {!workflows.length&&<p className="cv-workflow-empty">暂无画布</p>}
   </div>}
  </section>

  <section className={`cv-panel-section cv-nodes-section${nodesOpen?' is-open':' is-collapsed'}`} aria-labelledby="cv-section-nodes-title">
   <div className="cv-section-head">
    <h3 id="cv-section-nodes-title" className="cv-section-title" onClick={()=>setNodesOpen(v=>!v)}><span>节点</span><span className="cv-section-count" aria-label={`共 ${nodes.length} 节点`}>{nodes.length}</span></h3>
    <div className="cv-section-actions">
     <button type="button" className={`cv-final-filter-btn${onlyFinalized?' is-active':''}`} data-testid="sidebar-final-filter" aria-pressed={onlyFinalized} title={onlyFinalized?'显示全部节点':'仅显示已标为定稿的节点'} onClick={()=>{setOnlyFinalized(v=>!v);if(!nodesOpen)setNodesOpen(true)}}>仅看定稿 ({finalizedCount})</button>
     <button type="button" className="cv-section-btn" aria-label={nodesOpen?'折叠节点列表':'展开节点列表'} title={nodesOpen?'折叠节点列表':'展开节点列表'} aria-expanded={nodesOpen} aria-controls="cv-nodes-section-body" onClick={()=>setNodesOpen(v=>!v)}>{nodesOpen?<ChevronDown size={15} aria-hidden="true"/>:<ChevronRight size={15} aria-hidden="true"/>}</button>
    </div>
   </div>
   {nodesOpen&&<div id="cv-nodes-section-body" className="cv-nodes-section-body">
    <SidebarNodeList edges={edges} groups={groups} onLocateGroup={onLocateGroup} onRenameGroup={onRenameGroup} onUngroup={onUngroup} nodes={nodes} selected={selected} selectedIds={selectedIds} disabled={disabled} onLocate={onLocate} onSelect={onSelect} onCopy={onCopy} onDelete={onDelete} onRename={onRenameNode} onRating={onRating} onToggleFinalized={onToggleFinalized} onlyFinalized={onlyFinalized} onOnlyFinalizedChange={setOnlyFinalized}/>
   </div>}
  </section>

  {workflowMenu&&activeMenuWorkflow&&<SidebarMenu label="画布操作" position={workflowMenu.position} maxWidth={workflowMenu.maxWidth} onClose={()=>setWorkflowMenu(null)}>
   <button role="menuitem" disabled={disabled} onClick={()=>{const id=activeMenuWorkflow.id;setWorkflowMenu(null);setRenamingId(id)}}>重命名画布</button>
   {onDuplicateWorkflow&&<button role="menuitem" disabled={disabled} onClick={()=>{const target=activeMenuWorkflow;setWorkflowMenu(null);onDuplicateWorkflow(target)}}>复制画布</button>}
   <hr/>
   <button role="menuitem" className="is-danger" disabled={disabled} onClick={()=>{const target=activeMenuWorkflow;setWorkflowMenu(null);onDeleteWorkflow?.(target)}}>删除画布</button>
  </SidebarMenu>}
 </div>
}
