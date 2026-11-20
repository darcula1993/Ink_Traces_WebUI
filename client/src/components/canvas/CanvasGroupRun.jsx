import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import ConfirmDialog from '../ui/ConfirmDialog'
import {previewGroupRun, createGroupRun, listActiveGroupRuns, getGroupRun, cancelGroupRun, confirmGroupRun, groupRunError, isActiveRun, estimateText, totalText, runProgressText, runBadgeText, nodeRunMarks, owningRun, confirmRows, latestRunsByGroup, NODE_STATUS_LABELS, skipReasonText, nodeReasonText} from '../../lib/canvasGroupRun'
import './groupRun.css'

// GROUP-RUN-20261115 B5: run state lives on the server; this only polls it (3s while a run is active) and
// shows it. Opening the canvas restores active runs from GET group-runs?active=1 (runs keep going with the page closed).
const POLL_MS = 3000
const typeLabel = {image: '图像', video: '视频', audio: '音频'}

export function useGroupRunController({workflowId, save, getRevision, titleOf, groupTitleOf, showError}) {
  const [runs, setRuns] = useState(() => new Map()), [dialog, setDialog] = useState(null), [cancelTarget, setCancelTarget] = useState(null), [bannerError, setBannerError] = useState({})
  const owner = useRef(workflowId), runsRef = useRef(runs); owner.current = workflowId; runsRef.current = runs
  const put = useCallback(run => { if (run && run.workflow_id === owner.current) setRuns(current => new Map(current).set(run.group_id, run)) }, [])
  useEffect(() => {
    setRuns(new Map()); setDialog(null); setCancelTarget(null); setBannerError({})
    if (!workflowId) return
    listActiveGroupRuns(workflowId).then(items => { if (owner.current === workflowId) setRuns(latestRunsByGroup(items)) }).catch(() => {})
  }, [workflowId])
  const refresh = useCallback(async () => {
    const wid = owner.current
    if (!wid) return
    try {
      const active = await listActiveGroupRuns(wid), ids = new Set(active.map(run => run.id))
      if (owner.current !== wid) return
      active.forEach(put)
      const gone = [...runsRef.current.values()].filter(run => isActiveRun(run) && !ids.has(run.id))
      for (const run of gone) { const final = await getGroupRun(wid, run.id).catch(() => null); if (owner.current === wid && final) put(final) }
    } catch { /* keep the last known state; next tick retries */ }
  }, [put])
  const hasActive = [...runs.values()].some(isActiveRun)
  useEffect(() => {
    if (!workflowId || !hasActive) return
    let stopped = false
    const tick = async () => { if (!stopped) await refresh() }
    const timer = setInterval(tick, POLL_MS)
    return () => { stopped = true; clearInterval(timer) }
  }, [workflowId, hasActive, refresh])

  const list = useMemo(() => [...runs.values()], [runs])
  const marks = useMemo(() => nodeRunMarks(list), [list])

  async function start(group) {
    if (!workflowId) return
    try {
      await save()
      const preview = await previewGroupRun(workflowId, group.id, getRevision())
      setDialog({group, preview, notice: ''})
    } catch (failure) {
      const error = groupRunError(failure)
      if (error.code === 'run_active' && error.body.run_id) getGroupRun(workflowId, error.body.run_id).then(put).catch(() => {})
      showError(error.message)
    }
  }
  async function create() {
    const {group, preview} = dialog
    try {
      const run = await createGroupRun(workflowId, {groupId: group.id, revision: preview.revision, previewToken: preview.preview_token})
      put(run); setDialog(null)
    } catch (failure) {
      const error = groupRunError(failure)
      if (error.code === 'preview_stale' && error.body.preview) setDialog(value => value && {...value, preview: error.body.preview})
      else if (error.code === 'revision_mismatch') {
        try { await save(); const fresh = await previewGroupRun(workflowId, group.id, getRevision()); setDialog(value => value && {...value, preview: fresh}) } catch (inner) { throw new Error(groupRunError(inner).message) }
      } else if (error.code === 'run_active') {
        if (error.body.run_id) getGroupRun(workflowId, error.body.run_id).then(put).catch(() => {})
        setDialog(null); showError(error.message); return
      }
      throw new Error(error.message)
    }
  }
  async function cancel() {
    const run = cancelTarget
    try { put(await cancelGroupRun(workflowId, run.id)); setCancelTarget(null) }
    catch (failure) {
      const error = groupRunError(failure)
      if (error.code === 'run_finished') { getGroupRun(workflowId, run.id).then(put).catch(() => {}); setCancelTarget(null); showError(error.message); return }
      throw new Error(error.message)
    }
  }
  async function confirm(run) {
    setBannerError(value => ({...value, [run.id]: ''}))
    try { put(await confirmGroupRun(workflowId, run.id, run.confirm?.confirm_token)) }
    catch (failure) {
      const error = groupRunError(failure)
      if (error.body.run) put(error.body.run)
      else getGroupRun(workflowId, run.id).then(put).catch(() => {})
      setBannerError(value => ({...value, [run.id]: error.message}))
    }
  }
  const dismiss = run => setRuns(current => { const next = new Map(current); if (next.get(run.group_id)?.id === run.id) next.delete(run.group_id); return next })

  const element = <>
    {dialog && <GroupRunConfirmDialog group={dialog.group} preview={dialog.preview} titleOf={titleOf} onClose={() => setDialog(null)} onConfirm={create}/>}
    {cancelTarget && <ConfirmDialog className="canvas-studio-confirm" title={`取消节点组“${groupTitleOf(cancelTarget.group_id)}”的运行？`} confirmLabel="取消整组" cancelLabel="继续运行" danger onClose={() => setCancelTarget(null)} onConfirm={cancel}>
      <p>只停止<strong>尚未提交</strong>的节点；已提交的任务会继续跑完并照常写回结果（可在单个节点上另行取消）。</p>
    </ConfirmDialog>}
    {list.some(run => run.status === 'awaiting_confirm') && <div className="cv-group-run-banners">{list.filter(run => run.status === 'awaiting_confirm').map(run => <GroupRunBanner key={run.id} run={run} title={groupTitleOf(run.group_id)} titleOf={titleOf} error={bannerError[run.id]} onConfirm={() => confirm(run)} onCancel={() => setCancelTarget(run)}/>)}</div>}
  </>
  return {runs: list, runFor: groupId => runs.get(groupId) || null, marks, owningRun: nodeId => owningRun(list, nodeId), start, requestCancel: run => setCancelTarget(run), dismiss, refresh, element}
}

export function GroupRunConfirmDialog({group, preview, titleOf, onClose, onConfirm}) {
  const nodes = preview.nodes || [], skipped = preview.skipped || [], rerun = nodes.filter(node => node.has_result).length
  return <ConfirmDialog className="canvas-studio-confirm cv-group-run-confirm" title={`运行节点组“${group.title}”内全部 ${nodes.length} 个节点？`} confirmLabel={`确认并按顺序提交 ${nodes.length} 个节点`} onClose={onClose} onConfirm={onConfirm}>
    <div data-testid="group-run-preview">
      <p>按上下游顺序运行：同层节点同时提交，下游等上游成功后再用其新结果提交；上游失败或取消时其下游不提交；出现结果未知即停止整组。不会自动重试。</p>
      <ol className="cv-group-run-list" aria-label="运行顺序与每节点预估">
        {nodes.map(node => <li key={node.node_id} data-node-id={node.node_id}>
          <span className="cv-group-run-level" title="运行层级：同层节点同时提交">第 {node.level + 1} 层</span>
          <span className="cv-group-run-name">{node.title || titleOf(node.node_id)}<small>{typeLabel[node.type] || node.type}</small></span>
          {node.has_result && <span className="cv-group-run-tag" title="已有结果的节点也会重跑；旧结果保留为候选">已有结果，将重跑</span>}
          <span className={`cv-group-run-cost ${node.estimate?.known ? '' : 'is-unknown'}`}>{estimateText(node.estimate)}</span>
        </li>)}
      </ol>
      {skipped.length > 0 && <><p className="cv-group-run-sub">跳过 {skipped.length} 个节点：</p><ul className="cv-group-run-list is-skipped" aria-label="跳过的节点">{skipped.map(node => <li key={node.node_id}><span className="cv-group-run-name">{titleOf(node.node_id)}</span><span>{skipReasonText(node.reason)}</span></li>)}</ul></>}
      <p>合计预估：<strong data-testid="group-run-total">{totalText(preview.total)}</strong>（按现有费率估算，非实际扣费）</p>
      {rerun > 0 && <p>其中 {rerun} 个节点已有结果，将重新生成并再次计费；旧结果保留为候选。</p>}
      <p className="cv-group-run-sub">下游实际提交前会按真实输入重算费用；超出本次确认值或变为未知时暂停，等你再次确认。</p>
    </div>
  </ConfirmDialog>
}

export function GroupRunBanner({run, title, titleOf, error, onConfirm, onCancel}) {
  const rows = confirmRows(run)
  return <section className="cv-group-run-banner" role="alert" aria-label={`节点组 ${title} 等待确认新预估`} data-run-id={run.id} onPointerDown={event => event.stopPropagation()}>
    <header><strong>节点组“{title}”已暂停：{rows.length} 个节点重算后的费用超出确认值或变为未知</strong></header>
    <ul>{rows.map(row => <li key={row.nodeId}><span className="cv-group-run-name">{titleOf(row.nodeId)}</span><span>确认时 {estimateText(row.confirmed)}</span><span>→ 新预估 <b className={row.next?.known ? '' : 'is-unknown'}>{estimateText(row.next)}</b></span><span className="cv-group-run-delta">{row.deltaText}</span></li>)}</ul>
    {error && <p className="cv-group-run-error" role="status">{error}</p>}
    <footer><button type="button" className="btn btn-secondary btn-sm" onClick={onCancel}>取消整组</button><button type="button" className="btn btn-primary btn-sm" disabled={!run.confirm?.confirm_token} onClick={onConfirm}>确认新预估并继续</button></footer>
  </section>
}

// Group header badge: progress n/N, state and stop reason; tooltip lists each member's run state.
export function GroupRunBadge({run, titleOf}) {
  if (!run) return null
  const text = runBadgeText(run), full = runProgressText(run), detail = [full, ...(run.nodes || []).map(node => `${titleOf(node.node_id)}：${NODE_STATUS_LABELS[node.status] || node.status}${nodeReasonText(node) ? `（${nodeReasonText(node)}）` : ''}`)].join('\n')
  return <span className="cv-group-run-status" role="status" data-run-status={run.status} aria-label={full} title={detail || text}>{text}</span>
}
