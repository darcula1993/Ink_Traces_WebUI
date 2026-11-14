import axios from 'axios'
const base='/api/canvas/library',data=async request=>(await request).data
export const listLibraryItems=(params,signal)=>data(axios.get(`${base}/items`,{params,signal}))
export const listLibraryTags=async()=>(await data(axios.get(`${base}/tags`))).tags
export const createLibraryTag=async title=>(await data(axios.post(`${base}/tags`,{title}))).tag
export const updateLibraryTag=(id,title)=>data(axios.patch(`${base}/tags/${id}`,{title}))
export const deleteLibraryTag=id=>data(axios.delete(`${base}/tags/${id}`))
export const setLibraryItemTags=(key,tag_ids)=>data(axios.patch(`${base}/items/${encodeURIComponent(key)}/tags`,{tag_ids}))
export const removeLibraryItem=key=>data(axios.delete(`${base}/items/${encodeURIComponent(key)}`))
export const saveLibraryItems=(projectId,items,folder_id=null)=>data(axios.post(`/api/canvas/projects/${projectId}/library-items/save`,{items,folder_id}))
export const resolveLibraryItems=(workflowId,items)=>data(axios.post(`/api/canvas/workflows/${workflowId}/library-references`,{items}))
export async function uploadLibraryFile(projectId,file,folderId){const body=new FormData();body.append('file',file);if(folderId)body.append('folder_id',folderId);return (await data(axios.post(`/api/canvas/projects/${projectId}/assets`,body))).asset}
export const libraryDownloadUrl=key=>`${base}/items/${encodeURIComponent(key)}/download`
// Every item matching the server-side filters, not only the loaded page (max 1000).
export const selectAllLibraryItems=(params,signal)=>data(axios.get(`${base}/item-selection`,{params,signal}))
const DELETE_CHUNK=500
const chunks=keys=>Array.from({length:Math.ceil(keys.length/DELETE_CHUNK)},(_,i)=>keys.slice(i*DELETE_CHUNK,(i+1)*DELETE_CHUNK))
const sum=(results,field)=>results.reduce((total,r)=>total+(r[field]||0),0)
function merge(results){return {items:sum(results,'items'),canvas_copies:sum(results,'canvas_copies'),affected_nodes:sum(results,'affected_nodes'),removed_nodes:sum(results,'removed_nodes'),archived_copies_retained:sum(results,'archived_copies_retained'),workflows:new Set(results.flatMap(r=>r.workflow_ids||[])).size||sum(results,'workflows'),workflow_ids:[...new Set(results.flatMap(r=>r.workflow_ids||[]))],missing:results.flatMap(r=>r.missing||[]),rejected:results.flatMap(r=>r.rejected||[]),deleted_keys:results.flatMap(r=>r.deleted_keys||[]),characters:mergeCharacters(results)}}
// Characters that reference the deleted local items (spec revision 2); confirming removes those references.
function mergeCharacters(results){const map=new Map();for(const c of results.flatMap(r=>r.characters||[])){const prev=map.get(c.id);map.set(c.id,{...c,asset_ids:[...new Set([...(prev?.asset_ids||[]),...(c.asset_ids||[])])]})}return [...map.values()]}
export async function previewLocalDelete(keys){const results=[];for(const part of chunks(keys))results.push(await data(axios.post(`${base}/items/delete-preview`,{keys:part})));return merge(results)}
// Each chunk is atomic on the server; a failed chunk reports what already succeeded.
export async function deleteLocalItems(keys){const results=[];for(const part of chunks(keys)){try{results.push(await data(axios.post(`${base}/items/bulk-delete`,{keys:part})))}catch(error){error.partial=merge(results);throw error}}return merge(results)}
