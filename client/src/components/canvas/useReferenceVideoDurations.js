import {useEffect,useState} from 'react'
// Share metadata reads across downstream nodes. Successful URLs are immutable asset files.
const cache=new Map()
function subscribe(url) {
 let entry=cache.get(url)
 if(!entry){
  const media=document.createElement('video');let resolve
  entry={users:0,done:false,promise:new Promise(done=>resolve=done)};cache.set(url,entry)
  const finish=value=>{if(entry.done)return;entry.done=true;clearTimeout(timer);media.onloadedmetadata=null;media.onerror=null;media.removeAttribute('src');media.load();resolve(value)}
  const timer=setTimeout(()=>finish(null),8000)
  media.preload='metadata';media.muted=true;media.onloadedmetadata=()=>finish(Number.isFinite(media.duration)&&media.duration>0?media.duration:null);media.onerror=()=>finish(null)
  entry.cancel=()=>{finish(null);cache.delete(url)};media.src=url;media.load()
  if(cache.size>200)for(const [key,value] of cache){if(value.done&&!value.users&&key!==url){cache.delete(key);break}}
 }
 entry.users++
 return {promise:entry.promise,release:()=>{entry.users--;if(!entry.users&&!entry.done)entry.cancel()}}
}
export default function useReferenceVideoDurations(videos) {
 const key=videos.map(video=>`${video.id}:${video.url}:${video.duration||''}`).join('|'),[resolved,setResolved]=useState({key:'',values:{}})
 useEffect(()=>{
  let alive=true;const reads=videos.filter(v=>v.url&&!(Number(v.duration)>0)).map(v=>({video:v,...subscribe(v.url)}))
  Promise.all(reads.map(async read=>[read.video.url,await read.promise])).then(values=>{if(alive)setResolved({key,values:Object.fromEntries(values)})})
  return()=>{alive=false;reads.forEach(read=>read.release())}
 },[key])
 return videos.map(video=>({...video,duration:Number(video.duration)>0?Number(video.duration):resolved.key===key?resolved.values[video.url]:undefined}))
}
