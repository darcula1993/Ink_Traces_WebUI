import React from 'react'
import { X, CheckCircle2, AlertTriangle, Ban, HelpCircle, Bell } from 'lucide-react'
import './taskDoneNotices.css'

const ICONS = { succeeded: CheckCircle2, failed: AlertTriangle, cancelled: Ban, unknown: HelpCircle }

// TASK-DONE-NOTIFY-20261114: in-page completion reminders (newest first). Clicking a
// reminder locates its node without zooming; the optional prompt asks once about
// system notifications and never opens the browser permission dialog by itself.
export default function TaskDoneNotices({ notices, onLocate, onDismiss, ask, onEnable, onDecline }) {
  if (!notices.length && !ask) return null
  return <div className="cv-done-notices" onPointerDown={event => event.stopPropagation()}>
    <div role="status" aria-live="polite" className="cv-done-list">
      {notices.map(notice => {
        const Icon = ICONS[notice.kind] || CheckCircle2
        return <div key={notice.key} className={`cv-done-notice is-${notice.kind}`} data-testid="task-done-notice" data-task-id={notice.taskId}>
          <button type="button" className="cv-done-main" title={notice.error ? `${notice.text}：${notice.error}（点击定位节点）` : `${notice.text}（点击定位节点）`} aria-label={`${notice.text}，定位到节点`} onClick={() => onLocate(notice)}>
            <Icon size={14} aria-hidden="true"/><span>{notice.text}</span>
          </button>
          <button type="button" className="cv-done-close" aria-label="关闭完成提醒" title="关闭完成提醒" onClick={() => onDismiss(notice.key)}><X size={13}/></button>
        </div>
      })}
    </div>
    {ask && <div className="cv-done-ask" role="group" aria-label="系统通知">
      <Bell size={14} aria-hidden="true"/><span>页面在后台时也用系统通知提醒任务完成？</span>
      <button type="button" className="btn btn-primary" onClick={onEnable}>开启</button>
      <button type="button" className="btn" onClick={onDecline}>不用了</button>
    </div>}
  </div>
}
