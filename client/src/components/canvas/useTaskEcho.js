// NODE-ECHO-20261115: on-demand task detail for a generation node's latest task (created/completed
// times, submission cost snapshot, failure class). Runtime cache only: nothing is written to the
// canvas document, so it never marks the canvas unsaved. Fetched once per task phase
// (active / each terminal status) with a small concurrency cap; failures just hide the echo.
import { useEffect, useState } from 'react'
import axios from 'axios'
import { echoPhase } from '../../lib/canvasTaskEcho'

const cache = new Map() // taskId -> {phase, detail, promise}
const queue = []
const MAX_CONCURRENT = 3
let running = 0

function pump() {
  while (running < MAX_CONCURRENT && queue.length) {
    const job = queue.shift()
    running++
    axios.get(`/api/tasks/${job.id}`).then(response => job.resolve(response.data?.task || null), () => job.resolve(null)).finally(() => { running--; pump() })
  }
}

function load(id, phase) {
  const entry = cache.get(id)
  if (entry?.phase === phase) return entry.promise
  const promise = new Promise(resolve => { queue.push({ id, resolve }); pump() }).then(detail => {
    const current = cache.get(id)
    if (current?.promise === promise) current.detail = detail
    return detail
  })
  cache.set(id, { phase, promise, detail: entry?.detail ?? null })
  return promise
}

export default function useTaskEcho(task, enabled = true) {
  const id = Number(task?.id), valid = enabled && Number.isInteger(id) && id > 0, phase = echoPhase(task?.status)
  const [state, setState] = useState(() => (valid ? { id, detail: cache.get(id)?.detail ?? null } : null))
  useEffect(() => {
    if (!valid) { setState(null); return }
    let live = true
    setState(previous => (previous?.id === id ? previous : { id, detail: cache.get(id)?.detail ?? null }))
    load(id, phase).then(detail => { if (live && detail) setState({ id, detail }) })
    return () => { live = false }
  }, [valid, id, phase])
  return valid && state?.id === id ? state.detail : null
}
