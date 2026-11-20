import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { User, LockKeyhole, LoaderCircle } from 'lucide-react'
import BrandMark from './ui/BrandMark'
import inkAmbientUrl from '../assets/ink-ambient-login.webp'

export function LoginPage({ onLogin }) {
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    setError('')
    try {
      const res = await axios.post('/api/login', {
        username: e.target.username.value,
        password: e.target.password.value
      })
      if (res.data.success) {
        onLogin()
        return
      }
      setError(res.data?.error || '登录失败')
    } catch (err) {
      setError(err.response?.data?.error || '登录失败')
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }
  return (
    <div className="login-stage relative flex min-h-screen items-center justify-center overflow-hidden bg-[var(--bg)] p-5">
      <div className="login-ambient-dots" aria-hidden="true" />
      <div
        className="login-ambient-ink"
        style={{ backgroundImage: `url(${inkAmbientUrl})` }}
        aria-hidden="true"
      />
      <div className="login-ambient-glow" aria-hidden="true" />
      <form onSubmit={handleSubmit} className="liquid-login relative z-10 w-full max-w-[380px] p-6">
        <div className="mb-6 flex items-center gap-3.5">
          <div className="brand-mark brand-mark-hero flex size-11 shrink-0 items-center justify-center">
            <BrandMark size={28} variant="hero" />
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-[-0.01em] text-nexus-text-light">Ink Traces</h1>
            <p className="mt-0.5 text-xs text-nexus-muted">本地视觉创作工作台</p>
          </div>
        </div>
        <label className="mb-1.5 block text-xs font-medium text-nexus-text" htmlFor="login-username">用户名</label>
        <div className="relative mb-4">
          <User size={15} className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-nexus-muted" />
          <input id="login-username" name="username" autoComplete="username" required autoFocus disabled={submitting}
            className="glass-input h-10 w-full pl-9 pr-3 text-sm text-nexus-text-light outline-none" />
        </div>
        <label className="mb-1.5 block text-xs font-medium text-nexus-text" htmlFor="login-password">密码</label>
        <div className="relative mb-4">
          <LockKeyhole size={15} className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-nexus-muted" />
          <input id="login-password" name="password" type="password" autoComplete="current-password" required disabled={submitting}
            className="glass-input h-10 w-full pl-9 pr-3 text-sm text-nexus-text-light outline-none" />
        </div>
        {error && <div role="alert" className="mb-3 rounded border border-nexus-red/25 bg-nexus-red/10 px-3 py-2 text-xs text-nexus-red">{error}</div>}
        <button type="submit" disabled={submitting} aria-busy={submitting} className="btn btn-primary btn-block h-10 min-h-10 text-sm">
          {submitting ? <><LoaderCircle size={15} className="animate-spin" /> 登录中…</> : '登录'}
        </button>
      </form>
    </div>
  )
}

export function AuthGate({ component: Workspace }) {
  const [authed, setAuthed] = useState(null)
  useEffect(() => {
    axios.get('/api/auth/check').then(() => setAuthed(true)).catch(() => setAuthed(false))
  }, [])
  if (authed === null) return <div className="min-h-screen bg-nexus-bg flex items-center justify-center"><div className="w-5 h-5 border-2 border-nexus-green border-t-transparent rounded-full animate-spin"></div></div>
  if (!authed) return <LoginPage onLogin={() => setAuthed(true)} />
  return <Workspace onLogout={() => setAuthed(false)} />
}
