import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

const DATABASE_NAME = 'ink-traces-workspace'
const DATABASE_VERSION = 1
const STORE_NAME = 'state'

let databasePromise

function openLegacyDatabase() {
  if (!('indexedDB' in window)) return Promise.reject(new Error('IndexedDB unavailable'))
  if (databasePromise) return databasePromise
  databasePromise = new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains(STORE_NAME)) database.createObjectStore(STORE_NAME)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  return databasePromise
}

async function readLegacyIndexedValue(key) {
  const database = await openLegacyDatabase()
  return new Promise((resolve, reject) => {
    const request = database.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(key)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function deleteLegacyValue(key) {
  try { window.localStorage.removeItem(key) } catch {}
  try {
    const database = await openLegacyDatabase()
    await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, 'readwrite')
      transaction.objectStore(STORE_NAME).delete(key)
      transaction.oncomplete = resolve
      transaction.onerror = () => reject(transaction.error)
    })
  } catch {}
}

function readLegacyLocalValue(key, fallback) {
  try {
    const saved = window.localStorage.getItem(key)
    return saved === null ? fallback : JSON.parse(saved)
  } catch {
    return fallback
  }
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

async function serializeWorkspaceValue(value) {
  if (Array.isArray(value)) return Promise.all(value.map(serializeWorkspaceValue))
  if (!value || typeof value !== 'object') return value
  if (value instanceof Blob) {
    return {
      name: value instanceof File ? value.name : 'asset',
      mimeType: value.type || 'application/octet-stream',
      preview: await blobToDataUrl(value),
    }
  }

  const output = {}
  for (const [key, child] of Object.entries(value)) {
    if (child instanceof Blob) {
      output[key] = null
      if (!output.name && child instanceof File) output.name = child.name
      if (!output.mimeType) output.mimeType = child.type || 'application/octet-stream'
      if (!value.preview) output.preview = await blobToDataUrl(child)
    } else {
      output[key] = await serializeWorkspaceValue(child)
    }
  }
  return output
}

export function useWorkspaceState(key, defaultValue, options = {}) {
  const initialValueRef = useRef(readLegacyLocalValue(key, defaultValue))
  const optionsRef = useRef(options)
  optionsRef.current = options
  const [value, setValue] = useState(initialValueRef.current)
  const [ready, setReady] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const lastSavedRef = useRef(null)
  const saveSequenceRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    setReady(false)

    axios.get(`/api/workspace/state/${key}`)
      .then(async response => {
        if (cancelled) return
        const serverState = response.data.state
        if (serverState) {
          lastSavedRef.current = JSON.stringify(serverState.value)
          const hydrate = optionsRef.current.hydrate || ((serverValue) => serverValue)
          setValue(current => hydrate(serverState.value, current))
          await deleteLegacyValue(key)
          return
        }
        const indexedValue = await readLegacyIndexedValue(key).catch(() => undefined)
        if (!cancelled && indexedValue !== undefined) setValue(indexedValue)
      })
      .catch(requestError => {
        if (!cancelled) setError(requestError)
      })
      .finally(() => {
        if (!cancelled) setReady(true)
      })

    return () => { cancelled = true }
  }, [key])

  useEffect(() => {
    if (!ready) return undefined
    const selectPersisted = optionsRef.current.selectPersisted || ((currentValue) => currentValue)
    const persistedValue = selectPersisted(value)
    if (JSON.stringify(persistedValue) === lastSavedRef.current) return undefined
    const sequence = ++saveSequenceRef.current
    const controller = new AbortController()
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        setSaving(true)
        const serialized = await serializeWorkspaceValue(persistedValue)
        if (cancelled || sequence !== saveSequenceRef.current) return
        const serializedJson = JSON.stringify(serialized)
        if (serializedJson === lastSavedRef.current) return
        const response = await axios.put(
          `/api/workspace/state/${key}`,
          { value: serialized },
          { signal: controller.signal },
        )
        if (cancelled || sequence !== saveSequenceRef.current) return
        const normalized = response.data.state.value
        const normalizedJson = JSON.stringify(normalized)
        lastSavedRef.current = normalizedJson
        await deleteLegacyValue(key)
        if (sequence === saveSequenceRef.current && normalizedJson !== JSON.stringify(persistedValue)) {
          const mergeNormalized = optionsRef.current.mergeNormalized || ((_current, serverValue) => serverValue)
          setValue(current => mergeNormalized(current, normalized))
        }
        setError(null)
      } catch (requestError) {
        if (!cancelled && !axios.isCancel(requestError)) setError(requestError)
      } finally {
        if (!cancelled && sequence === saveSequenceRef.current) setSaving(false)
      }
    }, 450)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [key, ready, value])

  return [value, setValue, { ready, saving, error }]
}
