import {useEffect,useState} from 'react'
import {getCanvasImageMetadata} from '../../lib/canvasApi'
export default function useCanvasImageMetadata(workflowId,assets,enabled){
 const [state,setState]=useState({key:'',values:{},error:''}),key=`${workflowId}:${assets.map(a=>a.id).join(',')}`
 useEffect(()=>{if(!enabled||!workflowId)return;const controller=new AbortController();setState({key,values:{},error:''});Promise.all(assets.map(async asset=>{try{return [asset.id,await getCanvasImageMetadata(workflowId,asset.id,controller.signal)]}catch(e){if(controller.signal.aborted)return null;return [asset.id,{error:e?.response?.data?.error||'无法读取图片信息'}]}})).then(entries=>{if(controller.signal.aborted)return;const values=Object.fromEntries(entries.filter(Boolean));setState({key,values,error:Object.values(values).some(v=>v.error)?'部分参考图片信息不可用，背景与参考尺寸功能受限；可使用默认背景。':''})});return()=>controller.abort()},[key,enabled])
 return {references:assets.map(asset=>({...asset,...(state.key===key?state.values[asset.id]:{}),metadataLoading:state.key!==key||!state.values[asset.id]})),error:state.key===key?state.error:''}
}
