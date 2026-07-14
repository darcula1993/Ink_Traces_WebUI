import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

const DATABASE_NAME = 'ink-traces-workspace'
const DATABASE_VERSION = 1
const STORE_NAME = 'state'

let databasePromise
const workspaceBlobUploads = new WeakMap()

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

export function persistWorkspaceBlob(key, blob, preferredName = '') {
  let uploadsByKey = workspaceBlobUploads.get(blob)
  if (!uploadsByKey) {
    uploadsByKey = new Map()
    workspaceBlobUploads.set(blob, uploadsByKey)
  }
  if (uploadsByKey.has(key)) return uploadsByKey.get(key)

  const formData = new FormData()
  const name = preferredName || (blob instanceof File ? blob.name : 'asset')
  formData.append('file', blob, name)
  const upload = axios.post(`/api/workspace/assets/${key}`, formData)
    .then(response => response.data.asset)
    .catch(error => {
      uploadsByKey.delete(key)
      throw error
    })
  uploadsByKey.set(key, upload)
  return upload
}

function containsBlob(value) {
  if (typeof Blob !== 'undefined' && value instanceof Blob) return true
  if (Array.isArray(value)) return value.some(containsBlob)
  if (!value || typeof value !== 'object') return false
  return Object.values(value).some(containsBlob)
}

async function serializeWorkspaceValue(value, workspaceKey) {
  if (Array.isArray(value)) return Promise.all(value.map(child => serializeWorkspaceValue(child, workspaceKey)))
  if (!value || typeof value !== 'object') return value
  if (value instanceof Blob) {
    const asset = await persistWorkspaceBlob(workspaceKey, value)
    return {
      name: value instanceof File ? value.name : 'asset',
      mimeType: value.type || 'application/octet-stream',
      preview: asset.url,
    }
  }

  const output = {}
  let uploadedAsset = null
  for (const [key, child] of Object.entries(value)) {
    if (child instanceof Blob) {
      uploadedAsset = uploadedAsset || await persistWorkspaceBlob(workspaceKey, child, value.name)
      output[key] = null
      if (!output.name && child instanceof File) output.name = child.name
      if (!output.mimeType) output.mimeType = child.type || 'application/octet-stream'
    } else {
      output[key] = await serializeWorkspaceValue(child, workspaceKey)
    }
  }
  if (uploadedAsset) output.preview = uploadedAsset.url
  return output
}

function stableStringify(value) {
  return JSON.stringify(value, (_key, child) => {
    if (typeof Blob !== 'undefined' && child instanceof Blob) {
      return {
        __workspaceBlob: true,
        name: child instanceof File ? child.name : '',
        type: child.type,
        size: child.size,
        lastModified: child instanceof File ? child.lastModified : 0,
      }
    }
    if (!child || typeof child !== 'object' || Array.isArray(child)) return child
    const prototype = Object.getPrototypeOf(child)
    if (prototype !== Object.prototype && prototype !== null) return child
    return Object.keys(child).sort().reduce((sorted, name) => {
      sorted[name] = child[name]
      return sorted
    }, {})
  })
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
          lastSavedRef.current = stableStringify(serverState.value)
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
    const persistedFingerprint = stableStringify(persistedValue)
    if (persistedFingerprint === lastSavedRef.current) return undefined
    const sequence = ++saveSequenceRef.current
    const controller = new AbortController()
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        setSaving(true)
        const serialized = await serializeWorkspaceValue(persistedValue, key)
        if (cancelled || sequence !== saveSequenceRef.current) return
        const serializedFingerprint = stableStringify(serialized)
        if (serializedFingerprint === lastSavedRef.current) return
        const response = await axios.put(
          `/api/workspace/state/${key}`,
          { value: serialized },
          { signal: controller.signal },
        )
        if (cancelled || sequence !== saveSequenceRef.current) return
        const normalized = response.data.state.value
        const normalizedFingerprint = stableStringify(normalized)
        lastSavedRef.current = normalizedFingerprint
        await deleteLegacyValue(key)
        if (sequence === saveSequenceRef.current && normalizedFingerprint !== persistedFingerprint) {
          const mergeNormalized = optionsRef.current.mergeNormalized || ((_current, serverValue) => serverValue)
          setValue(current => mergeNormalized(current, normalized))
        }
        setError(null)
      } catch (requestError) {
        if (!cancelled && !axios.isCancel(requestError)) setError(requestError)
      } finally {
        if (!cancelled && sequence === saveSequenceRef.current) setSaving(false)
      }
    }, containsBlob(persistedValue) ? 0 : 450)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [key, ready, value])

  return [value, setValue, { ready, saving, error }]
}
