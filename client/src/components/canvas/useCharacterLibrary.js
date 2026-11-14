// CHARACTER-LIBRARY-20261114 C: the global character library for the @ menu and the node notices.
// Reloaded whenever a generation panel opens (so a changed character is noticed "next time the node is
// opened") and when the window regains focus; a failed load keeps the last list and is reported as unknown.
import {useEffect,useState} from 'react'
import {listCharacters} from '../../lib/canvasApi'

let cache = null
const listeners = new Set()
let pending = null
function refresh() {
  if (pending) return pending
  pending = listCharacters().then(characters => { cache = { characters, error: '' } }, error => { cache = { characters: cache?.characters || null, error: error?.response?.data?.error || '无法读取角色库' } })
    .finally(() => { pending = null; listeners.forEach(listener => listener(cache)) })
  return pending
}

export default function useCharacterLibrary(enabled = true) {
  const [state, setState] = useState(cache)
  useEffect(() => {
    if (!enabled) return undefined
    listeners.add(setState)
    refresh()
    const focus = () => refresh()
    window.addEventListener('focus', focus)
    return () => { listeners.delete(setState); window.removeEventListener('focus', focus) }
  }, [enabled])
  return { characters: state?.characters || null, error: state?.error || '', reload: refresh }
}
