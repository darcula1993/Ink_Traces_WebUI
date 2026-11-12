// Stop on the first uncertain POST. Never resend a successful or failed upload automatically.
export async function uploadBatch(files,upload){
 let completed=0
 for(const file of files){try{await upload(file);completed++}catch(error){return{completed,failed:file.name,remaining:files.length-completed-1,uncertain:!error?.response||error.response.status>=500,error}}}
 return{completed,remaining:0}
}
export const uploadSummary=result=>`已完成 ${result.completed} 项${result.failed?`；${result.uncertain?'未确认':'失败'}：${result.failed}；未处理 ${result.remaining} 项${result.uncertain?'；请刷新核查后再决定是否重新上传':''}`:''}`
