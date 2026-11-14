// Character naming rules shared with the server contract (CHARACTER-LIBRARY-20261114).
export const CHARACTER_IMAGE_LIMIT=8
export const CHARACTER_NAME_MAX=24
export const CHARACTER_DESCRIPTION_MAX=300
export const CHARACTER_VOICE_MAX_SECONDS=30
const FORBIDDEN=/[@[\]()（）]/
export const normalizeCharacterName=name=>String(name??'').trim()
export const characterNameKey=name=>normalizeCharacterName(name).toLowerCase()
// Returns a Chinese reason, or '' when the name is acceptable. `others` are existing characters (excluding the one being renamed).
export function characterNameError(name,others=[]){
 const value=normalizeCharacterName(name),length=[...value].length
 if(!length)return '请输入角色名称'
 if(length>CHARACTER_NAME_MAX)return `角色名称最多 ${CHARACTER_NAME_MAX} 个字（当前 ${length} 个）`
 if(/\s/.test(value))return '角色名称不能包含空格或换行'
 const bad=value.match(FORBIDDEN)
 if(bad)return `角色名称不能包含“${bad[0]}”（@、[]、()、（）用于提示词引用）`
 if(/^(图片|视频|音频)\d+$/.test(value))return `“${value}”与参考编号写法冲突，请换一个名称`
 const key=value.toLowerCase(),clash=others.find(c=>characterNameKey(c.name)===key)
 if(clash)return `已有同名角色“${clash.name}”（名称不区分大小写），请换一个名称`
 return ''
}
export const descriptionLength=text=>[...String(text??'')].length
// Server errors: 409 means a name clash; other 4xx carry a Chinese message.
export function characterErrorMessage(error,fallback='操作失败'){
 const status=error?.response?.status,text=error?.response?.data?.error
 if(status===409)return text||'已有同名角色，请换一个名称'
 return text||error?.message||fallback
}
export const voiceIsAudio=voice=>voice?.type==='audio'&&!!voice.url
