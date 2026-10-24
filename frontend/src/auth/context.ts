import { createContext, useContext } from 'react'

export interface User {
  id: number
  username: string
}

export type AuthStatus = 'loading' | 'anonymous' | 'authenticated'

export interface Auth {
  status: AuthStatus
  user: User | null
  signUp: (username: string, password: string) => Promise<void>
  logIn: (username: string, password: string) => Promise<void>
  logOut: () => Promise<void>
}

export const AuthContext = createContext<Auth | null>(null)

export function useAuth(): Auth {
  const auth = useContext(AuthContext)
  if (auth === null) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return auth
}
