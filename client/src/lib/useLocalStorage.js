import { useState, useEffect } from 'react'

const LARGE_DATA_URL_LIMIT = 256 * 1024

function stripNonSerializable(value) {
  return JSON.parse(JSON.stringify(value, (k, v) => {
    if (v instanceof File || v instanceof Blob) return undefined
    if (typeof v === 'string' && v.startsWith('data:') && v.length > LARGE_DATA_URL_LIMIT) return undefined
    if (v && typeof v === 'object' && v.file instanceof File) {
      const safe = { ...v }
      delete safe.file
      if (typeof safe.preview === 'string' && safe.preview.startsWith('data:') && safe.preview.length > LARGE_DATA_URL_LIMIT) {
        delete safe.preview
      }
      return Object.keys(safe).length ? safe : undefined
    }
    return v
  }))
}

export function useLocalStorage(key, defaultValue) {
  const [value, setValue] = useState(() => {
    try {
      const saved = localStorage.getItem(key)
      return saved !== null ? JSON.parse(saved) : defaultValue
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(stripNonSerializable(value)))
    } catch { /* quota exceeded, ignore */ }
  }, [key, value])

  return [value, setValue]
}
