import React, {useEffect, useRef, useState} from 'react'
import { X, CheckCircle2, AlertTriangle, Ban, HelpCircle, Bell } from 'lucide-react'
import {noticeLifetime, pageInForeground} from '../../lib/taskDoneNotify'
import './taskDoneNotices.css'

const ICONS = { succeeded: CheckCircle2, failed: AlertTriangle, cancelled: Ban, unknown: HelpCircle }

// Whether the page is visible and focused; reminders only count down while it is.
function useForeground() {
  const [foreground, setForeground] = useState(() => pageInForeground())
  useEffect(() => {
    const update = () => setForeground(pageInForeground())
    document.addEventListener('visibilitychange', update); window.addEventListener('focus', update); window.addEventListener('blur', update)
    return () => { document.removeEventListener('visibilitychange', update); window.removeEventListener('focus', update); window.removeEventListener('blur', update) }
  }, [])
  return foreground
}

// FIX-B2B-20261114: each reminder dismisses itself after noticeLifetime(kind) of visible time;
// hovering or keyboard focus pauses the countdown, and the remaining time resumes afterwards.
function Notice({ notice, paused, onLocate, onDismiss }) {
  const Icon = ICONS[notice.kind] || CheckCircle2
  const [hold, setHold] = useState(false)
  const remaining = useRef(noticeLifetime(notice.kind))
  const dismiss = useRef(onDismiss); dismiss.current = onDismiss
  useEffect(() => {
    if (paused || hold) return
    const started = Date.now()
    const timer = setTimeout(() => dismiss.current(notice.key), remaining.current)
    return () => { clearTimeout(timer); remaining.current = Math.max(1000, remaining.current - (Date.now() - started)) }
  }, [paused, hold, notice.key])
  const task = Number.isFinite(notice.taskId) ? `任务 #${notice.taskId}` : ''
  const title = `${notice.text}${task ? `（${task}）` : ''}${notice.error ? `：${notice.error}` : ''}（点击定位节点）`
  return <div className={`cv-done-notice is-${notice.kind}`} data-testid="task-done-notice" data-task-id={notice.taskId}
    onPointerEnter={() => setHold(true)} onPointerLeave={() => setHold(false)}
    onFocus={() => setHold(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setHold(false) }}>
    <button type="button" className="cv-done-main" title={title} aria-label={`${notice.text}，定位到节点${task ? `（${task}）` : ''}`} onClick={() => onLocate(notice)}>
      <Icon size={14} aria-hidden="true"/><span className="cv-done-text">{notice.text}</span>{task && <small className="cv-done-task" aria-hidden="true">#{notice.taskId}</small>}
    </button>
    <button type="button" className="cv-done-close" aria-label="关闭完成提醒" title="关闭完成提醒" onClick={() => onDismiss(notice.key)}><X size={13}/></button>
  </div>
}

// TASK-DONE-NOTIFY-20261114: in-page completion reminders (newest first). Clicking a
// reminder locates its node without zooming; the optional prompt asks once about
// system notifications and never opens the browser permission dialog by itself.
// FIX-B2B-20261114: shown at the top-right of the canvas, below the node panel layer, so
// they never cover the panel's cost estimate or generate button; they carry the task
// number to tell same-named nodes apart and dismiss themselves.
export default function TaskDoneNotices({ notices, onLocate, onDismiss, ask, onEnable, onDecline }) {
  const foreground = useForeground()
  if (!notices.length && !ask) return null
  return <div className="cv-done-notices" onPointerDown={event => event.stopPropagation()}>
    <div role="status" aria-live="polite" className="cv-done-list">
      {notices.map(notice => <Notice key={notice.key} notice={notice} paused={!foreground} onLocate={onLocate} onDismiss={onDismiss}/>)}
    </div>
    {ask && <div className="cv-done-ask" role="group" aria-label="系统通知">
      <Bell size={14} aria-hidden="true"/><span>页面在后台时也用系统通知提醒任务完成？</span>
      <button type="button" className="btn btn-primary" onClick={onEnable}>开启</button>
      <button type="button" className="btn" onClick={onDecline}>不用了</button>
    </div>}
  </div>
}
