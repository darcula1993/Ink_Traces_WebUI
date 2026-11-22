import { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import { User, LockKeyhole, LoaderCircle } from 'lucide-react'
import BrandMark from './ui/BrandMark'
import LaunchSplash from './ui/LaunchSplash'
import inkAmbientUrl from '../assets/ink-ambient-login.webp'

const LAUNCH_RITUAL_SESSION_KEY = 'ink-traces-launch-ritual-v1'
const BOOT_MIN_DURATION_MS = 780
const LOGIN_BOOT_DURATION_MS = 820
const BOOT_EXIT_DURATION_MS = 300
const QUICK_EXIT_DURATION_MS = 220

function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function hasSeenLaunchRitual() {
  try {
    return Boolean(window.sessionStorage.getItem(LAUNCH_RITUAL_SESSION_KEY))
  } catch {
    return false
  }
}

function markLaunchRitualSeen() {
  try {
    window.sessionStorage.setItem(LAUNCH_RITUAL_SESSION_KEY, '1')
  } catch {
    // Ignore storage restrictions in private contexts.
  }
}

function clearLaunchRitualSeen() {
  try {
    window.sessionStorage.removeItem(LAUNCH_RITUAL_SESSION_KEY)
  } catch {
    // Ignore storage restrictions in private contexts.
  }
}

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
  const seenBeforeRef = useRef(null)
  if (seenBeforeRef.current === null) {
    seenBeforeRef.current = hasSeenLaunchRitual()
  }
  const bootStartedAtRef = useRef(null)
  if (bootStartedAtRef.current === null) {
    bootStartedAtRef.current = Date.now()
  }

  const [authed, setAuthed] = useState(null)
  const [splashPhase, setSplashPhase] = useState(() => (
    seenBeforeRef.current || prefersReducedMotion() ? 'quick' : 'boot'
  ))
  const [exitDuration, setExitDuration] = useState(BOOT_EXIT_DURATION_MS)
  const [splashKey, setSplashKey] = useState(0)

  const holdTimerRef = useRef(null)
  const exitTimerRef = useRef(null)
  const splashPhaseRef = useRef(splashPhase)
  splashPhaseRef.current = splashPhase

  const clearSplashTimers = useCallback(() => {
    if (holdTimerRef.current !== null) {
      window.clearTimeout(holdTimerRef.current)
      holdTimerRef.current = null
    }
    if (exitTimerRef.current !== null) {
      window.clearTimeout(exitTimerRef.current)
      exitTimerRef.current = null
    }
  }, [])

  const startSplashExit = useCallback((durationMs) => {
    clearSplashTimers()
    setExitDuration(durationMs)
    setSplashPhase('exiting')
    exitTimerRef.current = window.setTimeout(() => {
      exitTimerRef.current = null
      setSplashPhase(null)
    }, durationMs)
  }, [clearSplashTimers])

  useEffect(() => {
    let cancelled = false
    axios.get('/api/auth/check')
      .then(() => {
        if (cancelled) return
        setAuthed(true)
        if (prefersReducedMotion()) {
          clearSplashTimers()
          setSplashPhase(null)
          return
        }
        if (!seenBeforeRef.current) {
          markLaunchRitualSeen()
          const elapsed = Date.now() - bootStartedAtRef.current
          const remaining = Math.max(0, BOOT_MIN_DURATION_MS - elapsed)
          clearSplashTimers()
          holdTimerRef.current = window.setTimeout(() => {
            holdTimerRef.current = null
            startSplashExit(BOOT_EXIT_DURATION_MS)
          }, remaining)
        } else {
          startSplashExit(QUICK_EXIT_DURATION_MS)
        }
      })
      .catch(() => {
        if (cancelled) return
        clearSplashTimers()
        setSplashPhase(null)
        setAuthed(false)
      })
    return () => {
      cancelled = true
      clearSplashTimers()
    }
  }, [clearSplashTimers, startSplashExit])

  const handleLoginSuccess = useCallback(() => {
    markLaunchRitualSeen()
    seenBeforeRef.current = true
    clearSplashTimers()
    setAuthed(true)
    if (prefersReducedMotion()) {
      setSplashPhase(null)
      return
    }
    setSplashKey(k => k + 1)
    setExitDuration(BOOT_EXIT_DURATION_MS)
    setSplashPhase('boot')
    holdTimerRef.current = window.setTimeout(() => {
      holdTimerRef.current = null
      startSplashExit(BOOT_EXIT_DURATION_MS)
    }, LOGIN_BOOT_DURATION_MS)
  }, [clearSplashTimers, startSplashExit])

  const handleLogout = useCallback(() => {
    clearSplashTimers()
    clearLaunchRitualSeen()
    seenBeforeRef.current = false
    setSplashPhase(null)
    setAuthed(false)
  }, [clearSplashTimers])

  const handleSkipSplash = useCallback(() => {
    if (splashPhaseRef.current !== 'boot') return
    startSplashExit(QUICK_EXIT_DURATION_MS)
  }, [startSplashExit])

  return (
    <>
      {authed === false && <LoginPage onLogin={handleLoginSuccess} />}
      {authed === true && <Workspace onLogout={handleLogout} />}
      {splashPhase && (
        <LaunchSplash
          key={splashKey}
          phase={splashPhase}
          pending={authed === null}
          exitDuration={exitDuration}
          onSkip={authed === true && splashPhase === 'boot' ? handleSkipSplash : undefined}
        />
      )}
    </>
  )
}
