import axios from 'axios'
// Global character library (not project scoped); see the character library API contract.
const base='/api/characters',data=async request=>(await request).data
// Text field “文字描述” (spec revision 11-14: `description`, ≤300; the old `notes` field is rejected by the server).
export const DESCRIPTION_FIELD='description'
export const characterDescription=c=>c?.[DESCRIPTION_FIELD]??''
const one=body=>body?.character||body
export const listCharacters=async signal=>{const body=await data(axios.get(base,{signal}));return Array.isArray(body)?body:body.characters||[]}
export const getCharacter=async id=>one(await data(axios.get(`${base}/${id}`)))
export const createCharacter=async({name,description=''})=>one(await data(axios.post(base,{name,[DESCRIPTION_FIELD]:description})))
export const updateCharacter=async(id,patch)=>{const body={...patch};if('description' in body){body[DESCRIPTION_FIELD]=body.description;if(DESCRIPTION_FIELD!=='description')delete body.description}return one(await data(axios.patch(`${base}/${id}`,body)))}
export const deleteCharacter=id=>data(axios.delete(`${base}/${id}`))
export async function uploadCharacterImage(id,file){const body=new FormData();body.append('file',file);return data(axios.post(`${base}/${id}/images`,body))}
// asset_ref is the library catalog selection {source,id} (local/library/workflow/task/cupsy).
export const addLibraryImage=(id,selection)=>data(axios.post(`${base}/${id}/images`,{source:'library',asset_ref:selection}))
export const addCanvasImage=(id,workflowId,assetId)=>data(axios.post(`${base}/${id}/images`,{source:'canvas',workflow_id:workflowId,asset_id:assetId}))
export const deleteCharacterImage=(id,assetId)=>data(axios.delete(`${base}/${id}/images/${encodeURIComponent(assetId)}`))
export const reorderCharacterImages=(id,order)=>updateCharacter(id,{image_order:order})
export async function uploadVoiceAudio(id,file){const body=new FormData();body.append('file',file);return data(axios.post(`${base}/${id}/voice-audio`,body))}
export const addLibraryVoiceAudio=(id,selection)=>data(axios.post(`${base}/${id}/voice-audio`,{source:'library',asset_ref:selection}))
export const clearVoice=id=>updateCharacter(id,{voice:null})
// Reads the media duration in the browser (seconds) so over-long audio is rejected before upload.
export function audioDuration(src){return new Promise((resolve,reject)=>{const audio=new Audio(),url=src instanceof Blob?URL.createObjectURL(src):src,done=fn=>value=>{audio.removeAttribute('src');if(src instanceof Blob)URL.revokeObjectURL(url);fn(value)};audio.preload='metadata';audio.onloadedmetadata=done(()=>resolve(audio.duration));audio.onerror=done(()=>reject(new Error('无法读取音频时长，请确认文件是 wav 或 mp3')));audio.src=url})}
