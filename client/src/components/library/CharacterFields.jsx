import React from 'react'
import {CHARACTER_DESCRIPTION_MAX,descriptionLength} from '../../lib/characterRules'
export const DESCRIPTION_HINT='会写进生成提示词，描述外貌与服装等可见特征'
// Name + text description inputs shared by the library and the canvas “加入角色” dialog.
export function CharacterNameInput({value,onChange,error,onEnter,autoFocus=false,label='角色名称'}){
 return <div className="cl-field"><label>{label}<input autoFocus={autoFocus} aria-label={label} aria-invalid={!!error||undefined} aria-describedby={error?'cl-name-error':undefined} value={value} placeholder="例如：林" onChange={e=>onChange(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing&&onEnter){e.preventDefault();onEnter()}}}/></label>{error&&<small id="cl-name-error" className="cl-field-error" role="alert">{error}</small>}</div>
}
export function CharacterDescriptionInput({value,onChange}){
 const length=descriptionLength(value),over=length>CHARACTER_DESCRIPTION_MAX
 return <div className="cl-field"><label htmlFor="cl-description">文字描述</label><textarea id="cl-description" aria-label="文字描述" aria-describedby="cl-description-hint" aria-invalid={over||undefined} rows={4} value={value} placeholder={DESCRIPTION_HINT} onChange={e=>onChange(e.target.value)}/><small id="cl-description-hint" className={over?'cl-field-error':'cl-hint'}>{DESCRIPTION_HINT}<span aria-label={`已输入 ${length} 字，最多 ${CHARACTER_DESCRIPTION_MAX} 字`}> · {length}/{CHARACTER_DESCRIPTION_MAX}</span>{over&&'（超出上限）'}</small></div>
}
