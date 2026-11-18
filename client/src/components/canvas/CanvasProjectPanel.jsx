import React,{useRef,useState} from 'react'
import {ChevronDown,MoreHorizontal,Plus,Check} from 'lucide-react'
import SidebarEditableName from './SidebarEditableName'
import ProjectOverview from './ProjectOverview'
import CostLedgerPanel from './CostLedgerPanel'
import './sidebarMenus.css'
import SidebarNodeList from './SidebarNodeList'
import {menuPosition} from './SidebarMenu'
import SidebarMenu from './SidebarNavigationMenu'

// CANVAS-LAYOUT-2-20261118: split out of CanvasSidebar. The project/canvas breadcrumb with its menus
// (recent projects, canvases, more: projects, cost ledger, pending deletions, delete). Menus are clamped to
// the closest `[data-panel-bounds]` container (rail panel), falling back to the old `nav`.
export function CanvasProjectHeader({projects,projectId,workflows,workflow,disabled,onProject,onWorkflow,onNewProject,onNewWorkflow,onRenameProject,onRenameProjectDirect,onRenameWorkflow,onDeleteProject,onDeleteWorkflow,onPendingDeletions,navigationError=''}) {
 const [menu,setMenu]=useState(null),[overview,setOverview]=useState(null),[ledger,setLedger]=useState(false)
 const rootRef=useRef(null)
 const closeOverview=()=>{setOverview(null);requestAnimationFrame(()=>rootRef.current?.querySelector('[aria-label="选择项目"]')?.focus({preventScroll:true}))}
 const project=projects.find(p=>p.id===projectId)
 const command=fn=>()=>{setMenu(null);fn?.()}
 const openMenu=(type,event)=>{const position=menuPosition(event),container=event.currentTarget.closest('[data-panel-bounds]')||event.currentTarget.closest('nav'),bounds=container.getBoundingClientRect(),width=type==='more'?225:267;position.x=Math.max(bounds.left+8,Math.min(position.x,bounds.right-width-8));setMenu(menu?.type===type?null:{type,position,maxWidth:Math.max(140,bounds.width-16)})}
 const showProjects=()=>setOverview('all')
 const stamp=item=>Date.parse(item.updated_at||item.created_at||'')||0,recent=projects.slice().sort((a,b)=>stamp(b)-stamp(a)).slice(0,5)
 return <div ref={rootRef} className="cv-sidebar-top"><div className="cv-sidebar-breadcrumb"><SidebarEditableName key={projectId} name="项目" onRename={onRenameProjectDirect} className="cv-project-name" aria-label="选择项目" data-project-id={projectId||''} title={project?.title||'全部项目'} disabled={disabled} onClick={showProjects}>{project?.title||'项目'}</SidebarEditableName><button className="cv-project-switch" aria-label="切换项目" title="最近项目" aria-haspopup="menu" aria-expanded={menu?.type==='projects'} disabled={disabled} onClick={e=>openMenu('projects',e)}><ChevronDown size={14}/></button><div className="cv-sidebar-workflow"><SidebarEditableName key={workflow?.id} name="画布" onRename={onRenameWorkflow} className="cv-workflow-name" aria-label="选择画布" data-workflow-id={workflow?.id||''} title={workflow?.title||'选择画布'} aria-haspopup="menu" aria-expanded={menu?.type==='workflow'} disabled={disabled} onClick={e=>openMenu('workflow',e)}><span>{workflow?.title||'选择画布'}</span><ChevronDown size={12}/></SidebarEditableName></div><button className="cv-sidebar-more" aria-label="更多操作" title="更多操作" aria-haspopup="menu" aria-expanded={menu?.type==='more'} disabled={disabled} onClick={e=>openMenu('more',e)}><MoreHorizontal size={18}/></button></div>
 {menu?.type==='workflow'&&<SidebarMenu label="画布列表" position={menu.position} maxWidth={menu.maxWidth} onClose={()=>setMenu(null)} className="cv-workflow-dropdown"><div className="cv-workflow-menu-heading"><span>画布</span><button role="menuitem" aria-label="新建画布" title="新建画布" disabled={disabled} onClick={command(onNewWorkflow)}><Plus size={22}/></button></div>{workflows.map(item=><button role="menuitemradio" data-workflow-id={item.id} key={item.id} aria-checked={item.id===workflow?.id} disabled={disabled} onClick={command(()=>onWorkflow(item.id))}><span>{item.title}</span>{item.id===workflow?.id&&<Check size={20} aria-hidden="true"/>}</button>)}{!workflows.length&&<p className="cv-menu-empty">暂无画布，请点击 + 创建</p>}</SidebarMenu>}
 {menu?.type==='projects'&&<SidebarMenu label="最近项目" position={menu.position} maxWidth={menu.maxWidth} onClose={()=>setMenu(null)} className="cv-workflow-dropdown"><div className="cv-sidebar-menu-heading">最近项目</div>{recent.map(item=><button role="menuitemradio" key={item.id} data-project-id={item.id} aria-checked={item.id===projectId} disabled={disabled} title={item.title} onClick={command(()=>onProject(item.id))}><span>{item.title}</span>{item.id===projectId&&<Check size={18} aria-hidden="true"/>}</button>)}<hr/><button role="menuitem" disabled={disabled} onClick={command(showProjects)}>全部项目…</button></SidebarMenu>}
 {menu?.type==='more'&&<SidebarMenu label="更多操作" position={menu.position} maxWidth={menu.maxWidth} onClose={()=>setMenu(null)}><div className="cv-sidebar-menu-heading" id="cv-more-project">项目</div><div role="group" aria-labelledby="cv-more-project"><button role="menuitem" disabled={disabled} onClick={command(showProjects)}>全部项目</button><button role="menuitem" disabled={disabled} onClick={command(onNewProject)}>创建新项目</button><button role="menuitem" disabled={disabled||!projectId} onClick={command(onRenameProject)}>命名项目</button><button role="menuitem" onClick={command(()=>setLedger(true))}>费用（估算）</button><hr/><button role="menuitem" className="is-danger" disabled={disabled||!projectId} onClick={command(onDeleteProject)}>删除项目</button></div><div className="cv-sidebar-menu-heading" id="cv-more-workflow">画布</div><div role="group" aria-labelledby="cv-more-workflow"><button role="menuitem" disabled={disabled} onClick={command(onPendingDeletions)}>待完成删除</button><hr/><button role="menuitem" className="is-danger" disabled={disabled||!workflow} onClick={command(onDeleteWorkflow)}>删除画布</button></div></SidebarMenu>}
 {overview&&<ProjectOverview projects={projects} currentProjectId={projectId} disabled={disabled} onClose={closeOverview} onSelect={onProject} onCreate={onNewProject} navigationError={navigationError}/>}
 {ledger&&<CostLedgerPanel projectId={projectId} projectTitle={project?.title} workflowId={workflow?.id} workflowTitle={workflow?.title} onClose={()=>setLedger(false)}/>}
 </div>
}

// Rail panel "项目/画布": breadcrumb + this canvas's node / node-group list (same props as the old sidebar).
export default function CanvasProjectPanel({edges=[],groups=[],nodes=[],selected,selectedIds,disabled,onLocateGroup,onRenameGroup,onUngroup,onLocate,onSelect,onCopy,onDelete,onRenameNode,onRating,...header}) {
 return <div className="cv-panel-project" data-panel-bounds=""><CanvasProjectHeader disabled={disabled} {...header}/>
 <SidebarNodeList edges={edges} groups={groups} onLocateGroup={onLocateGroup} onRenameGroup={onRenameGroup} onUngroup={onUngroup} nodes={nodes} selected={selected} selectedIds={selectedIds} disabled={disabled} onLocate={onLocate} onSelect={onSelect} onCopy={onCopy} onDelete={onDelete} onRename={onRenameNode} onRating={onRating}/>
 <footer className="cv-panel-footer"><span>{`共 ${nodes.length} 节点`}</span></footer></div>
}
