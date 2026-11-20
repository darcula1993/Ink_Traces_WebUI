import axios from 'axios'
// LIBRARY-GLOBAL-20261116 S4a: the global media library (one library for every project; folders only, no tags).
// Contract: task log “S1 接口契约” — routes under /api/canvas/media.
const media='/api/canvas/media',data=async request=>(await request).data
export const MEDIA_SELECT_MAX=5000,MEDIA_CHUNK=500
const chunks=(ids,size=MEDIA_CHUNK)=>Array.from({length:Math.ceil(ids.length/size)},(_,i)=>ids.slice(i*size,(i+1)*size))

// Filters: {folder_id:undefined(all)|'root'|id, include_subfolders, kind, q, sort}. Page is 1-based.
export const mediaParams=({folder_id,include_subfolders,kind,q,sort}={})=>({...(folder_id?{folder_id}:{}),...(folder_id&&include_subfolders?{include_subfolders:1}:{}),...(kind&&kind!=='all'?{kind}:{}),...(q?{q}:{}),...(sort&&sort!=='newest'?{sort}:{})})
export const listMedia=(filters,{page=1,limit=40}={},signal)=>data(axios.get(media,{params:{...mediaParams(filters),page,limit},signal}))
export const selectMediaIds=(filters,signal)=>data(axios.get(`${media}/ids`,{params:mediaParams(filters),signal}))
export const getMediaReferences=(id,signal)=>data(axios.get(`${media}/${encodeURIComponent(id)}/references`,{signal}))
export async function uploadMedia(file,{folderId=null,origin='upload'}={}){const body=new FormData();body.append('file',file);if(folderId)body.append('folder_id',folderId);if(origin!=='upload')body.append('origin',origin);return data(axios.post(media,body))}
export const mediaDownloadUrl=id=>`${media}/${encodeURIComponent(id)}?download=1`
// refs: media ids (or legacy refs). Items: {ref,status:'ok'|'deleted'|'missing',media_id,media?}.
export async function lookupMedia(refs){const items=[];for(const part of chunks(refs))items.push(...(await data(axios.post(`${media}/lookup`,{refs:part}))).items);return items}
export async function moveMedia(ids,folderId){const moved=[];for(const part of chunks(ids))moved.push(...(await data(axios.post(`${media}/move`,{ids:part,folder_id:folderId||null}))).media);return moved}

export const listMediaFolders=async()=>(await data(axios.get(`${media}/folders`))).folders
export const createMediaFolder=async({title,parent_id=null,icon})=>(await data(axios.post(`${media}/folders`,{title,parent_id:parent_id||null,...(icon?{icon}:{})}))).folder
export const updateMediaFolder=async(id,patch)=>(await data(axios.patch(`${media}/folders/${id}`,patch))).folder
export const deleteMediaFolder=id=>data(axios.delete(`${media}/folders/${id}`))

export const listMediaGroups=async()=>(await data(axios.get(`${media}/groups`))).groups
export const getMediaGroup=(id,{includeDeleted=true}={})=>data(axios.get(`${media}/groups/${id}`,{params:includeDeleted?{}:{include_deleted:0}}))
export const createMediaGroup=async(title,media_ids)=>(await data(axios.post(`${media}/groups`,{title,media_ids}))).group
export const updateMediaGroup=async(id,patch)=>(await data(axios.patch(`${media}/groups/${id}`,patch))).group
export const deleteMediaGroup=id=>data(axios.delete(`${media}/groups/${id}`))

// Delete preview / delete accept ≤500 ids per request; larger selections are merged here.
const LISTS=['items','missing','characters','media_groups','task_ids','deleted_ids']
function mergeWorkflows(results){const map=new Map();for(const w of results.flatMap(r=>r.affected_workflows||[])){const prev=map.get(w.workflow_id);map.set(w.workflow_id,prev?{...prev,placeholder_nodes:(prev.placeholder_nodes||0)+(w.placeholder_nodes||0),stripped_nodes:(prev.stripped_nodes||0)+(w.stripped_nodes||0)}:{...w})}return [...map.values()]}
function mergeCharacters(results){const map=new Map();for(const c of results.flatMap(r=>r.characters||[])){const prev=map.get(c.id);map.set(c.id,{...c,asset_ids:[...new Set([...(prev?.asset_ids||[]),...(c.asset_ids||[])])]})}return [...map.values()]}
export function mergeDeleteResults(results){
 const merged=Object.fromEntries(LISTS.map(k=>[k,results.flatMap(r=>r[k]||[])]))
 merged.task_ids=[...new Set(merged.task_ids)]
 merged.media_groups=[...new Map(merged.media_groups.map(g=>[g.id,g])).values()]
 merged.characters=mergeCharacters(results)
 merged.affected_workflows=mergeWorkflows(results)
 merged.asset_groups=results.reduce((n,r)=>n+(r.asset_groups||0),0)
 merged.files_removed=results.reduce((n,r)=>n+(r.files_removed||0),0)
 // Canvas callers refresh the open canvas when its id is listed (CanvasStudio.afterLibraryDelete).
 merged.workflow_ids=merged.affected_workflows.map(w=>w.workflow_id)
 merged.deleted_keys=merged.deleted_ids
 return merged
}
export async function previewMediaDelete(ids){const results=[];for(const part of chunks(ids))results.push(await data(axios.post(`${media}/delete-preview`,{ids:part})));return mergeDeleteResults(results)}
// Each chunk is atomic on the server; a failed chunk reports what already succeeded.
export async function deleteMedia(ids){const results=[];for(const part of chunks(ids)){try{results.push(await data(axios.post(`${media}/delete`,{ids:part})))}catch(error){error.partial=mergeDeleteResults(results);throw error}}return mergeDeleteResults(results)}

// ---- legacy routes still used outside the library until S4b/S5 switch over (old/new coexist) ----
export const resolveLibraryItems=(workflowId,items)=>data(axios.post(`/api/canvas/workflows/${workflowId}/library-references`,{items}))
// LOCAL-FROM-RESULT-20261116 “加入本地素材”; S4b/S5 replace it with “移动到文件夹”.
export const addResultsToLocal=items=>data(axios.post('/api/canvas/library/local/from-results',{items}))
