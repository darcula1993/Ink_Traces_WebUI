const nodeLabel = (nodes,documents) => nodes.length===1 ? `节点“${documents.find(n=>n.id===nodes[0].id)?.title || nodes[0].before?.title || nodes[0].after?.title || '未命名'}”` : `${nodes.length} 个节点`
export function describeCanvasChange(delta,before,after) {
 if(delta.groups)return '调整节点分组'
 const added=delta.nodes.filter(n=>!n.fields&&!n.before),removed=delta.nodes.filter(n=>!n.fields&&!n.after),edited=delta.nodes.filter(n=>n.fields)
 if(added.length)return `添加${nodeLabel(added,after.nodes)}`
 if(removed.length)return `删除${nodeLabel(removed,before.nodes)}`
 const fields=edited.flatMap(n=>n.fields),label=nodeLabel(edited,after.nodes)
 if(fields.length&&fields.every(f=>['x','y'].includes(f.key)))return `移动${label}`
 if(fields.some(f=>f.key==='asset'||f.key==='selectedCandidateId'))return `切换${label}的素材版本`
 if(fields.length===1&&fields[0].key==='rating')return `修改${label}评级：${fields[0].after?`${fields[0].after} 星`:'未评级'}`
 if(fields.length===1&&fields[0].key==='title')return `重命名${label}`
 if(fields.length===1&&fields[0].key==='text')return `修改${label}的提示词`
 if(fields.length===1&&fields[0].key==='params.generate_audio')return `${fields[0].after===false?'关闭':'开启'}${label}的输出音频`
 const names={providerSelection:'节点接口',referenceOrder:'参考顺序',referenceMentions:'素材提及',rating:'评级','params.model':'模型','params.aspect_ratio':'画幅','params.ratio':'画幅','params.resolution':'分辨率','params.duration':'时长','params.video_mode':'视频模式','params.omni_reference_task_type':'任务类型','params.first_frame':'首帧','params.last_frame':'尾帧',referenceAssets:'参考素材',referenceGroups:'素材组'}
 if(fields.length)return `调整${label}的${[...new Set(fields.map(f=>names[f.key]||'参数'))].join('、')}`
 const addEdges=delta.edges.filter(e=>e.after),removeEdges=delta.edges.filter(e=>!e.after)
 if(addEdges.length&&!removeEdges.length)return `添加 ${addEdges.length} 条连接`
 if(removeEdges.length&&!addEdges.length)return `删除 ${removeEdges.length} 条连接`
 return '编辑画布'
}
