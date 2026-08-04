import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react'

import {
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  type LoginCredentials,
} from '../api/auth'
import type { UserProfileResponse } from '../api/generated'
import {
  ApiError,
  SESSION_EXPIRED_EVENT,
  type SessionExpiredEventDetail,
} from '../api/runtime'
import {
  AuthContext,
  type AuthContextValue,
  type AuthStatus,
} from './auth-context'

export function AuthProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<UserProfileResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [isPending, setIsPending] = useState(false)

  const setAnonymous = useCallback((nextError: ApiError | null = null) => {
    setStatus('anonymous')
    setUser(null)
    setError(nextError)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const profile = await getCurrentUser({
        notifySessionExpired: false,
      })
      setUser(profile)
      setStatus('authenticated')
      setError(null)
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        setAnonymous()
        return
      }
      setAnonymous(
        requestError instanceof ApiError ? requestError : null,
      )
    }
  }, [setAnonymous])

  useEffect(() => {
    const handleSessionExpired = (event: Event) => {
      const sessionEvent = event as CustomEvent<SessionExpiredEventDetail>
      setAnonymous(sessionEvent.detail.error)
    }

    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
    const refreshTimer = window.setTimeout(() => {
      void refresh()
    }, 0)

    return () => {
      window.clearTimeout(refreshTimer)
      window.removeEventListener(
        SESSION_EXPIRED_EVENT,
        handleSessionExpired,
      )
    }
  }, [refresh, setAnonymous])

  const login = useCallback(async (credentials: LoginCredentials) => {
    setIsPending(true)
    setError(null)
    try {
      const session = await loginRequest(credentials)
      setUser(session.user)
      setStatus('authenticated')
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError)
      }
      throw requestError
    } finally {
      setIsPending(false)
    }
  }, [])

  const logout = useCallback(async () => {
    setIsPending(true)
    setError(null)
    try {
      await logoutRequest()
      setAnonymous()
    } catch (requestError) {
      if (requestError instanceof ApiError) {
        setError(requestError)
      }
      throw requestError
    } finally {
      setIsPending(false)
    }
  }, [setAnonymous])

  const value = useMemo<AuthContextValue>(
    () => ({
      error,
      isPending,
      login,
      logout,
      refresh,
      status,
      user,
    }),
    [
      error,
      isPending,
      login,
      logout,
      refresh,
      status,
      user,
    ],
  )

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}
