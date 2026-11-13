import React,{useEffect,useRef,useState} from 'react'
import {Play,Pause,Volume2,VolumeX} from 'lucide-react'

// UI-ITER-R2A #5: themed in-node player (play/pause, seek, time, volume) replacing native controls.
// Every control is a real button or range input, so Tab/Space/Enter/arrow keys work and the
// canvas never starts a node drag from them. Motion is limited to CSS transitions that are
// switched off under prefers-reduced-motion.
const clock=value=>{if(!Number.isFinite(value)||value<0)value=0;const s=Math.floor(value);return s>=3600?`${Math.floor(s/3600)}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`:`${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`}
export default function MediaPlayer({kind,src,title,onMetadata,autoPlay=false,onFail}){
 const media=useRef(null),[playing,setPlaying]=useState(false),[time,setTime]=useState(0),[duration,setDuration]=useState(0),[volume,setVolume]=useState(1),[muted,setMuted]=useState(false),[error,setError]=useState('')
 const label=kind==='video'?'视频':'音频'
 useEffect(()=>{setPlaying(false);setTime(0);setDuration(0);setError('')},[src])
 useEffect(()=>()=>media.current?.pause(),[])
 const toggle=()=>{const element=media.current;if(!element)return;if(element.paused||element.ended)element.play()?.catch?.(()=>setError(`${label}无法播放`));else element.pause()}
 const metadata=event=>{const element=event.currentTarget;setDuration(Number.isFinite(element.duration)?element.duration:0);onMetadata?.(element)}
 const events={src,preload:'metadata',onPlay:()=>setPlaying(true),onPause:()=>setPlaying(false),onEnded:()=>setPlaying(false),onTimeUpdate:event=>setTime(event.currentTarget.currentTime),onLoadedMetadata:metadata,onDurationChange:event=>{const d=event.currentTarget.duration;if(Number.isFinite(d))setDuration(d)},onVolumeChange:event=>{setVolume(event.currentTarget.volume);setMuted(event.currentTarget.muted)},onError:()=>{setError(`${label}加载失败，浏览器可能不支持此格式`);onFail?.()},autoPlay}
 const seek=event=>{const element=media.current,value=Number(event.target.value);if(element&&Number.isFinite(element.duration)){element.currentTime=value;setTime(value)}}
 const changeVolume=event=>{const element=media.current,value=Number(event.target.value);if(!element)return;element.volume=value;element.muted=value===0}
 const silent=muted||volume===0,progress=duration?Math.min(100,time/duration*100):0
 return <div className={`cv-media-player is-${kind} ${playing?'is-playing':''}`} data-testid="canvas-media-player">
  {kind==='video'?<video ref={media} className="cv-media" playsInline {...events}/>:<audio ref={media} {...events}/>}
  {kind==='video'&&!playing&&<button type="button" className="cv-media-player-center" tabIndex={-1} aria-hidden="true" onClick={toggle}><Play size={22} aria-hidden="true"/></button>}
  {kind==='audio'&&<span className="cv-media-player-title" title={title}>{title}</span>}
  <div className="cv-media-player-bar" role="group" aria-label={`${label}播放控制 ${title}`}>
   <button type="button" className="cv-media-player-toggle" aria-label={`${playing?'暂停':'播放'}${label}`} title={playing?'暂停':'播放'} onClick={toggle}>{playing?<Pause size={14} aria-hidden="true"/>:<Play size={14} aria-hidden="true"/>}</button>
   <input type="range" className="cv-media-player-progress" aria-label={`${label}进度`} aria-valuetext={`${clock(time)} / ${clock(duration)}`} min="0" max={duration||0} step="0.1" value={Math.min(time,duration||0)} disabled={!duration} onChange={seek} style={{'--cv-progress':`${progress}%`}}/>
   <span className="cv-media-player-time" aria-hidden="true">{clock(time)} / {clock(duration)}</span>
   <button type="button" className="cv-media-player-mute" aria-label={silent?'取消静音':'静音'} title={silent?'取消静音':'静音'} onClick={()=>{const element=media.current;if(!element)return;if(silent){element.muted=false;if(element.volume===0)element.volume=1}else element.muted=true}}>{silent?<VolumeX size={14} aria-hidden="true"/>:<Volume2 size={14} aria-hidden="true"/>}</button>
   <input type="range" className="cv-media-player-volume" aria-label={`${label}音量`} min="0" max="1" step="0.05" value={silent?0:volume} onChange={changeVolume} style={{'--cv-progress':`${(silent?0:volume)*100}%`}}/>
  </div>
  {error&&<span className="cv-media-player-error" role="alert">{error}</span>}
 </div>
}
