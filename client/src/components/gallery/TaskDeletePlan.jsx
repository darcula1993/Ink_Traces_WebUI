import React from 'react'
import { taskDeletePlanLines } from './taskDeletePreview.js'
import '../library/library.css'

// GEN-RESULT-LIFECYCLE-20261119: the confirm dialog body for permanent task deletion; every affected canvas is named.
export default function TaskDeletePlan({ preview, count, label, scope }) {
  const workflows = preview.media.affected_workflows
  return (
    <div className="ul-delete-plan" role="status" data-testid="task-delete-plan">
      {taskDeletePlanLines(preview, { count: count ?? preview.tasks, label: label || '', scope: scope || '' }).map((line, index) => <p key={index}>{line}</p>)}
      {workflows.length > 0 && (
        <ul className="ul-delete-workflows" aria-label="受影响的画布">
          {workflows.map(w => <li key={w.workflow_id} data-workflow-id={w.workflow_id}><b>{w.project_title || '项目已删除'}</b> / <b>{w.workflow_title || w.workflow_id}</b>：{w.placeholder_nodes || 0} 个“已删除”占位，{w.stripped_nodes || 0} 个节点移除引用</li>)}
        </ul>
      )}
    </div>
  )
}
