import { useState, useEffect } from 'react'

function stripNonSerializable(value) {
  return JSON.parse(JSON.stringify(value, (k, v) => {
    if (v instanceof File || v instanceof Blob) return undefined
    if (v && typeof v === 'object' && v.file instanceof File) {
      // Keep preview (base64 string) but drop the File object
      return v.preview ? { preview: v.preview } : undefined
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
