import { useEffect, useState } from 'react'

const LARGE_DATA_URL_LIMIT = 256 * 1024
const DATABASE_NAME = 'ink-traces-workspace'
const DATABASE_VERSION = 1
const STORE_NAME = 'state'

let databasePromise

function openDatabase() {
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

async function readIndexedValue(key) {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, 'readonly')
    const request = transaction.objectStore(STORE_NAME).get(key)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function writeIndexedValue(key, value) {
  const database = await openDatabase()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, 'readwrite')
    transaction.objectStore(STORE_NAME).put(value, key)
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error)
  })
}

function stripNonSerializable(value) {
  return JSON.parse(JSON.stringify(value, (key, item) => {
    if (item instanceof File || item instanceof Blob) return undefined
    if (typeof item === 'string' && item.startsWith('data:') && item.length > LARGE_DATA_URL_LIMIT) return undefined
    if (item && typeof item === 'object' && item.file instanceof File) {
      const safe = { ...item }
      delete safe.file
      if (typeof safe.preview === 'string' && safe.preview.startsWith('data:') && safe.preview.length > LARGE_DATA_URL_LIMIT) {
        delete safe.preview
      }
      return Object.keys(safe).length ? safe : undefined
    }
    return item
  }))
}

function localFallback(key, defaultValue) {
  try {
    const saved = window.localStorage.getItem(key)
    return saved !== null ? JSON.parse(saved) : defaultValue
  } catch {
    return defaultValue
  }
}

export function useLocalStorage(key, defaultValue) {
  const [value, setValue] = useState(() => localFallback(key, defaultValue))
  const [storageReady, setStorageReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    setStorageReady(false)

    readIndexedValue(key)
      .then(saved => {
        if (!cancelled && saved !== undefined) setValue(saved)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setStorageReady(true)
      })

    return () => { cancelled = true }
  }, [key])

  useEffect(() => {
    if (!storageReady) return undefined

    const timer = window.setTimeout(() => {
      try {
        window.localStorage.setItem(key, JSON.stringify(stripNonSerializable(value)))
      } catch {
        // IndexedDB remains the primary store when localStorage is full.
      }
      writeIndexedValue(key, value).catch(() => {})
    }, 200)

    return () => window.clearTimeout(timer)
  }, [key, storageReady, value])

  return [value, setValue]
}
