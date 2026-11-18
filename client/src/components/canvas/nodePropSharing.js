import {isValidElement,cloneElement} from 'react'
// Only freshly constructed UI prop containers are traversed. Domain objects and arrays
// (nodes, assets, references, task state, provider capabilities) retain their identity.
export function shareNodeProps(value,previous,callback,path=[]){
 if(typeof value==='function')return callback(path)
 if(value===previous)return value
 if(isValidElement(value)){
  const old=isValidElement(previous)&&previous.type===value.type&&previous.key===value.key?previous:null
  const props=shareNodeProps(value.props,old?.props,callback,[...path,'props'])
  return old&&props===old.props?old:cloneElement(value,props)
 }
 if(!value||typeof value!=='object')return value
 const container=path.join('.')
 if(!['','prompt.props','prompt.props.generate','prompt.props.editor','prompt.props.generate.estimate'].includes(container)){
  if(Array.isArray(value)&&value.length===0&&Array.isArray(previous)&&previous.length===0)return previous
  return value
 }
 const array=Array.isArray(value)
 if(!array&&Object.getPrototypeOf(value)!==Object.prototype)return value
 const compatible=previous&&typeof previous==='object'&&Array.isArray(previous)===array
 const keys=Object.keys(value),out=array?[]:{}
 let same=!!compatible&&Object.keys(previous).length===keys.length
 for(const key of keys){out[key]=shareNodeProps(value[key],compatible?previous[key]:undefined,callback,[...path,key]);if(!compatible||out[key]!==previous[key])same=false}
 return same?previous:out
}
