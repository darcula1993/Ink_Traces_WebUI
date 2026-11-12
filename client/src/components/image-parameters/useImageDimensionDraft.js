import {useEffect,useRef,useState} from 'react'
import {imageDimensionPatch} from '../../lib/imageGenerationRules'
export default function useImageDimensionDraft(params,onChange,owner){
 const values=()=>({custom_width:String(params.custom_width??1024),custom_height:String(params.custom_height??1024)})
 const [draft,setDraft]=useState(values),dirty=useRef(new Set())
 useEffect(()=>{setDraft(values());dirty.current.clear()},[owner,params.custom_width,params.custom_height])
 const valid=value=>/^[1-9]\d*$/.test(value)&&Number.isSafeInteger(Number(value))&&Number(value)<=2147483647
 return {
  draft,
  sync:patch=>{dirty.current.clear();setDraft(current=>({...current,...Object.fromEntries(['custom_width','custom_height'].filter(key=>patch[key]!==undefined).map(key=>[key,String(patch[key])]))}))},
  error:Object.values(draft).some(value=>!valid(value))?'宽高草稿必须为有效正整数；空值不会保存，请完成输入。':'',
  change:(field,value)=>{dirty.current.add(field);setDraft(current=>({...current,[field]:value}))},
  commit:field=>{if(dirty.current.has(field)&&valid(draft[field])){dirty.current.delete(field);onChange(imageDimensionPatch(params,field,Number(draft[field])))}}
 }
}
