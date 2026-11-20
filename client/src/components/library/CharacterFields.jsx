import React from 'react'
import {CHARACTER_DESCRIPTION_MAX,CHARACTER_KINDS,descriptionLength,normalizeCharacterKind} from '../../lib/characterRules'
export const DESCRIPTION_HINT='会写进生成提示词，描述外貌与服装等可见特征'
export const PROP_DESCRIPTION_HINT='会写进生成提示词，描述物件外形、材质与细节等可见特征'
// Name, kind (人物 / 物件) + text description inputs shared by the library and the canvas “加入角色卡” dialog.
export function CharacterKindSelect({value='character',onChange,disabled=false}){
 const current=normalizeCharacterKind(value)
 return <div className="cl-field cl-kind-field"><span className="cl-field-label">模板类型</span><div className="cl-kind-group" role="radiogroup" aria-label="角色卡类型">{CHARACTER_KINDS.map(item=><button key={item.value} type="button" role="radio" aria-checked={current===item.value} disabled={disabled} onClick={()=>onChange(item.value)}>{item.label}</button>)}</div><small className="cl-hint">{current==='prop'?'@引用展开为外形、材质与细节':'@引用展开为五官、发型与服装'}</small></div>
}
export function CharacterNameInput({value,onChange,error,onEnter,autoFocus=false,disabled=false,label='角色卡名称',kind='character'}){
 return <div className="cl-field cl-name-field"><label>{label}<input autoFocus={autoFocus} disabled={disabled} aria-label={label} aria-invalid={!!error||undefined} aria-describedby={error?'cl-name-error':undefined} value={value} placeholder={normalizeCharacterKind(kind)==='prop'?'例如：青铜灯笼':'例如：林'} onChange={e=>onChange(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing&&onEnter){e.preventDefault();onEnter()}}}/></label>{error&&<small id="cl-name-error" className="cl-field-error" role="alert">{error}</small>}</div>
}
export function CharacterDescriptionInput({value,onChange,disabled=false,kind='character'}){
 const length=descriptionLength(value),over=length>CHARACTER_DESCRIPTION_MAX
 const hint=normalizeCharacterKind(kind)==='prop'?PROP_DESCRIPTION_HINT:DESCRIPTION_HINT
 return <div className="cl-field cl-desc-field"><div className="cl-field-head"><label htmlFor="cl-description">文字描述</label><span className={`cl-char-count${over?' is-over':''}`} aria-label={`已输入 ${length} 字，最多 ${CHARACTER_DESCRIPTION_MAX} 字`}>{length}/{CHARACTER_DESCRIPTION_MAX}{over&&'（超出上限）'}</span></div><textarea id="cl-description" disabled={disabled} aria-label="文字描述" aria-describedby="cl-description-hint" aria-invalid={over||undefined} rows={3} value={value} placeholder={hint} onChange={e=>onChange(e.target.value)}/><small id="cl-description-hint" className={over?'cl-field-error':'cl-hint'}>{hint}</small></div>
}
