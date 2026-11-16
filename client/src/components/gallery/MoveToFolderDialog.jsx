import React, { useEffect, useRef, useState } from 'react'
import LibraryDialog from '../library/LibraryDialog'
import { ROOT, canCreateIn, createMediaFolder, currentTarget, folderLabel, folderTargetIssue, folderTree, listMediaFolders, moveMediaToFolder } from './taskLibrary.js'
import '../library/library.css'
import './taskLibrary.css'

// LIBRARY-GLOBAL-20261116 S4b: replaces “加入本地素材” in the task center. Results already live in the
// global media library (生成历史); this only changes their folder. A folder can be created on the spot.
export default function MoveToFolderDialog({ media, onClose, onDone }) {
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  // V2-FIX F7: start from the folder the results are in now; mixed or unknown folders start unselected.
  const [target, setTarget] = useState(() => currentTarget(media))
  const [newTitle, setNewTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [outcome, setOutcome] = useState('')
  const alive = useRef(true)
  const kinds = media.map(entry => entry.kind).filter(Boolean)
  const message = e => e?.response?.data?.error || e?.message || '操作失败'
  useEffect(() => {
    alive.current = true
    const controller = new AbortController()
    listMediaFolders(controller.signal)
      .then(list => { if (alive.current) setFolders(list) })
      .catch(e => { if (alive.current && !controller.signal.aborted) setError(message(e)) })
      .finally(() => { if (alive.current) setLoading(false) })
    return () => { alive.current = false; controller.abort() }
  }, [])
  // The 移动 button disappears with the outcome: keep focus (and Escape/Tab) inside the dialog on 完成.
  const outcomeRef = useRef(null)
  useEffect(() => { if (outcome) outcomeRef.current?.closest('[role=dialog]')?.querySelector('footer button')?.focus({ preventScroll: true }) }, [outcome])
  const selected = target === ROOT || target === null ? null : folders.find(folder => folder.id === target)
  const issue = target === null ? (currentTarget(media) === null && media.length > 1 ? '所选结果位于不同文件夹，请选择目标文件夹' : '请选择目标文件夹') : folderTargetIssue(selected, kinds)
  const parent = canCreateIn(selected) ? selected : null

  async function create() {
    const title = newTitle.trim()
    if (!title || busy) return
    setBusy(true); setError('')
    try {
      const folder = await createMediaFolder(title, parent?.id || null)
      if (!alive.current) return
      setFolders(list => [...list, folder]); setTarget(folder.id); setNewTitle('')
    } catch (e) { if (alive.current) setError(message(e)) } finally { if (alive.current) setBusy(false) }
  }
  async function move() {
    if (issue || !media.length) return
    setBusy(true); setError('')
    try {
      const moved = await moveMediaToFolder(media.map(entry => entry.id), target)
      if (!alive.current) return
      const text = `已把 ${moved} 项结果移动到“${folderLabel(folders, target)}”`
      setOutcome(text); onDone?.({ moved, folderId: target, text })
    } catch (e) { if (alive.current) setError(message(e)) } finally { if (alive.current) setBusy(false) }
  }

  return (
    <LibraryDialog title="移动到文件夹" className="ul-subdialog-top" busy={busy} error={error} onClose={onClose} onConfirm={outcome ? null : move} disabled={loading || !media.length || !!issue} confirmLabel="移动" cancelLabel={outcome ? '完成' : '取消'}>
      {outcome ? <p ref={outcomeRef} role="status" data-testid="move-to-folder-outcome"><strong>{outcome}</strong></p> : <>
        <p>把所选 {media.length} 项生成结果移动到素材库中的文件夹。只改变所在位置，不复制文件；任务记录保持不变。</p>
        {loading ? <p role="status">正在载入文件夹…</p> : (
          <div role="radiogroup" aria-label="目标文件夹" className="task-move-folders">
            <label><input type="radio" name="task-move-target" checked={target === ROOT} onChange={() => setTarget(ROOT)} /> 根目录</label>
            {folderTree(folders).map(({ folder }) => {
              const blocked = folderTargetIssue(folder, kinds)
              return (
                <label key={folder.id} title={blocked || undefined} className={blocked ? 'is-blocked' : undefined}>
                  <input type="radio" name="task-move-target" checked={target === folder.id} disabled={!!blocked} onChange={() => setTarget(folder.id)} />
                  {' '}{folderLabel(folders, folder.id)}{folder.system_key ? <small className="ul-muted">（系统）</small> : null}
                </label>
              )
            })}
          </div>
        )}
        {issue && <p className="ul-muted" role="status">{issue}</p>}
        <label>创建文件夹
          <input aria-label="新文件夹名称" placeholder={parent ? `在“${parent.title}”下新建` : '在根目录新建'} value={newTitle} disabled={busy || loading} onChange={e => setNewTitle(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); create() } }} />
          <button type="button" disabled={busy || loading || !newTitle.trim()} onClick={create}>创建并选中</button>
        </label>
      </>}
    </LibraryDialog>
  )
}
