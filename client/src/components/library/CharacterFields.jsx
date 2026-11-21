import React from 'react'
import {Images,X} from 'lucide-react'
import {CHARACTER_DESCRIPTION_MAX,CHARACTER_IMAGE_LIMIT,CHARACTER_KINDS,descriptionLength,normalizeCharacterKind} from '../../lib/characterRules'
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
// V24-W2-CHAR-CARD-20261121: initial reference image picker in the create-character dialog (multi-select, preview, remove).
export function CharacterInitialImagesField({images=[],boundKeys,failedKey=null,disabled=false,canPick=false,onPick,onRemove,onPreview,pickButtonRef}){
 const full=images.length>=CHARACTER_IMAGE_LIMIT
 return <div className="cl-field cl-create-images-field" data-testid="create-character-images">
  <div className="cl-field-head">
   <span className="cl-field-label">初始参考图（可选）</span>
   <span className="cl-create-images-meta">
    <span className="cl-count-pill" aria-label={`已选 ${images.length} 张，最多 ${CHARACTER_IMAGE_LIMIT} 张`}>{images.length}/{CHARACTER_IMAGE_LIMIT}</span>
    {canPick&&<button ref={pickButtonRef} type="button" className="btn btn-secondary btn-sm cl-pick-lib-btn" data-testid="create-character-pick-images" disabled={disabled||full} onClick={onPick}><Images size={14} aria-hidden="true"/>从素材库选择</button>}
   </span>
  </div>
  <small className="cl-hint">最多选 {CHARACTER_IMAGE_LIMIT} 张，保存时一步绑定；第一张作为角色卡首图。</small>
  {images.length>0&&<ol className="cl-create-images" aria-label="已选初始参考图">{images.map((item,index)=>{
   const bound=Boolean(boundKeys?.has(item.key)),failed=failedKey===item.key
   const label=item.asset?.name||`参考图 ${index+1}`
   return <li key={item.key} className={`cl-create-image${index===0?' is-cover':''}${bound?' is-bound':''}${failed?' is-failed':''}`} data-picked-image={item.key}>
    <button type="button" className="cl-create-image-thumb" aria-label={`预览初始参考图 第 ${index+1} 张 ${label}`} title={`${label}（点击查看大图）`} onClick={()=>onPreview?.(item)}>
     <img src={item.thumbnail_url||item.asset?.url} alt=""/>
    </button>
    <span className={`cl-create-image-badge${index===0?' is-cover':''}`} aria-hidden="true">{index===0?'首图':index+1}</span>
    {bound&&<span className="cl-create-image-bound" aria-label="已绑定">已绑定</span>}
    {!bound&&<button type="button" className="cl-create-image-remove" aria-label={`移除初始参考图 ${label}`} title={`移除 ${label}`} disabled={disabled} onClick={()=>onRemove?.(item.key)}><X size={12} aria-hidden="true"/></button>}
   </li>
  })}</ol>}
 </div>
}
