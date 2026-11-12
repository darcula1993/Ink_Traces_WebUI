import React from 'react'
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const list = value => Array.isArray(value) ? value : []
const text = value => typeof value === 'string' ? value : ''

export default function LayerOcrDetails({value,notify}) {
 if(value == null)return <small>此图层没有文字识别结果</small>
 // Older saved documents may contain malformed provider metadata. Do not mutate it:
 // structured display uses safe entries, while raw JSON remains available to inspect/copy.
 const fullText = record(value) ? text(value.text) : ''
 const lines = record(value) ? list(value.lines).filter(record) : []
 const malformed = !record(value) || (value.lines !== undefined && !Array.isArray(value.lines)) ||
   (record(value) && list(value.lines).some(line => !record(line) || (line.runs !== undefined && !Array.isArray(line.runs)) ||
     (record(line) && list(line.runs).some(run => !record(run) || typeof run.text !== 'string' || (run.style !== undefined && !record(run.style))))))
 async function copy(content){try{await navigator.clipboard.writeText(content);notify?.('已复制文字识别信息')}catch{notify?.('复制失败，请选择文本后复制','error')}}
 return <details className="layer-ocr">
  <summary>文字识别</summary>
  <small>位置以输出底图为坐标系；样式为近似识别，图层仍是像素图。</small>
  {malformed && <p role="status">部分历史OCR结构无效，已跳过无法展示的内容；原始结构仍可查看。</p>}
  <textarea aria-label="识别文字内容" readOnly value={fullText} style={{width:'100%',minHeight:80}}/>
  <button type="button" onClick={()=>copy(fullText)}>复制文字</button>
  {lines.map((line,i)=>{
   const runs=list(line.runs).filter(record)
   return <details key={i}><summary>第 {i+1} 行：{runs.map(run=>text(run.text)).join('')}</summary>
    <p>像素坐标：{JSON.stringify(record(line.bounding_box)?line.bounding_box.absolute??null:null)}</p>
    <p>归一化坐标：{JSON.stringify(record(line.bounding_box)?line.bounding_box.normalized??null:null)}</p>
    {runs.map((run,j)=><div key={j}><p>{text(run.text)}</p><dl>
     {Object.entries(record(run.style)?run.style:{}).map(([key,val])=><React.Fragment key={key}><dt>{key}</dt><dd>{typeof val==='boolean'?(val?'是':'否'):typeof val==='object'?JSON.stringify(val):String(val)}</dd></React.Fragment>)}
    </dl></div>)}
   </details>
  })}
  <details><summary>原始OCR结构</summary><button type="button" onClick={()=>copy(JSON.stringify(value,null,2))}>复制OCR JSON</button><pre style={{whiteSpace:'pre-wrap',maxHeight:200,overflow:'auto'}}>{JSON.stringify(value,null,2)}</pre></details>
 </details>
}
