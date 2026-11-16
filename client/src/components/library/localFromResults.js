// LOCAL-FROM-RESULT-20261116: generation results → 本地素材 request refs and reply summary (pure, node-testable).
// Folders belong to projects and 本地素材 has none: the final contract (task log “接口契约”, A 核实①)
// drops folder_id, so the dialog offers tags only.

const taskId=value=>{const id=Number(value);if(!Number.isSafeInteger(id)||id<1)throw new Error('任务编号无效');return id}
// 生成历史 catalog item: selection.id is the task output (task_assets id).
export const libraryTaskRef=item=>({source:'task',task_id:taskId(item.task_id),output:String(item.selection.id)})
// Task card / task detail: task_id only; the server adds every local output of the task.
export const taskRef=id=>({source:'task',task_id:taskId(id)})
// Canvas node result or kept version (a canvas asset imported from the task).
export const canvasAssetRef=(workflowId,assetId)=>({source:'canvas_asset',workflow_id:String(workflowId),asset_id:String(assetId)})

export const isTaskItem=item=>item?.selection?.source==='task'
export const tagUnion=items=>[...new Map(items.flatMap(i=>i.tags||[]).map(t=>[t.id,t])).values()]

// Skipped entries carry only {ref, reason}; name them by their source.
export const refLabel=ref=>ref?.source==='task'?`任务 #${ref.task_id}`:ref?.source==='canvas_asset'?'画布结果':'结果'
export function summarizeFromResults(result){
 const items=Array.isArray(result?.items)?result.items:[],skipped=Array.isArray(result?.skipped)?result.skipped:[]
 const created=items.filter(i=>i.status==='created'),existing=items.filter(i=>i.status==='existing')
 const parts=[]
 if(created.length)parts.push(`已加入 ${created.length} 项到本地素材`)
 if(existing.length)parts.push(`${existing.length} 项已在本地素材（未重复复制，标签已合并）`)
 if(skipped.length)parts.push(`${skipped.length} 项未加入`)
 return {created,existing,skipped,text:parts.join('；')||'没有可加入的结果'}
}
