import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'

import { api, ApiError } from '../api/client'
import { type Auth, AuthContext, type User } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api<User>('/api/auth/me')
      .then((me) => !cancelled && setUser(me))
      .catch((error: unknown) => {
        if (!(error instanceof ApiError && error.status === 403)) {
          console.error('Could not load the current user', error)
        }
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const signUp = useCallback(async (username: string, password: string) => {
    setUser(await api<User>('/api/auth/signup', { method: 'POST', body: { username, password } }))
  }, [])

  const logIn = useCallback(async (username: string, password: string) => {
    setUser(await api<User>('/api/auth/login', { method: 'POST', body: { username, password } }))
  }, [])

  const logOut = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(null)
  }, [])

  const auth = useMemo<Auth>(
    () => ({
      status: loading ? 'loading' : user ? 'authenticated' : 'anonymous',
      user,
      signUp,
      logIn,
      logOut,
    }),
    [loading, user, signUp, logIn, logOut],
  )

  return <AuthContext value={auth}>{children}</AuthContext>
}
