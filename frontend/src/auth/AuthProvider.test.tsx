import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from './AuthProvider'
import { useAuth } from './context'

function Probe() {
  const auth = useAuth()
  return (
    <>
      <p>{auth.status}</p>
      <p>{auth.user?.username ?? 'nobody'}</p>
      <button onClick={() => void auth.logOut()}>log out</button>
    </>
  )
}

function stubFetch(handler: (path: string) => Response) {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => handler(path)))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AuthProvider', () => {
  it('starts anonymous when the server says not logged in', async () => {
    stubFetch(() => new Response('{}', { status: 403 }))

    render(<AuthProvider><Probe /></AuthProvider>)

    expect(screen.getByText('loading')).toBeInTheDocument()
    expect(await screen.findByText('anonymous')).toBeInTheDocument()
  })

  it('restores the logged-in user, then logs out', async () => {
    document.cookie = 'csrftoken=abc'
    stubFetch((path) =>
      path === '/api/auth/me'
        ? new Response(JSON.stringify({ id: 1, username: 'owen' }), { status: 200 })
        : new Response(null, { status: 204 }),
    )
    render(<AuthProvider><Probe /></AuthProvider>)
    expect(await screen.findByText('owen')).toBeInTheDocument()

    await act(async () => screen.getByText('log out').click())

    expect(screen.getByText('anonymous')).toBeInTheDocument()
  })
})
