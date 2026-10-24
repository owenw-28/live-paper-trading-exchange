import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from './client'

function respond(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api', () => {
  it('sends the CSRF token from the cookie on writes', async () => {
    document.cookie = 'csrftoken=abc123'
    fetchMock.mockResolvedValue(respond(200, { id: 1 }))

    await api('/api/thing', { method: 'POST', body: { a: 1 } })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-CSRFToken']).toBe('abc123')
    expect(init.credentials).toBe('same-origin')
    expect(init.body).toBe('{"a":1}')
  })

  it('fetches a CSRF cookie first when there is none', async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/auth/csrf') {
        document.cookie = 'csrftoken=fresh'
        return respond(204)
      }
      return respond(200, {})
    })

    await api('/api/auth/login', { method: 'POST', body: {} })

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(['/api/auth/csrf', '/api/auth/login'])
    expect(fetchMock.mock.calls[1][1].headers['X-CSRFToken']).toBe('fresh')
  })

  it('does not send a CSRF token on reads', async () => {
    document.cookie = 'csrftoken=abc123'
    fetchMock.mockResolvedValue(respond(200, {}))

    await api('/api/auth/me')

    expect(fetchMock.mock.calls[0][1].headers['X-CSRFToken']).toBeUndefined()
  })

  it('throws ApiError with every field message on failure', async () => {
    fetchMock.mockResolvedValue(respond(400, { username: ['Taken.'], password: ['Too short.'] }))

    const error = await api('/api/auth/signup').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(400)
    expect((error as ApiError).messages()).toEqual(['Taken.', 'Too short.'])
  })

  it('returns undefined for 204 No Content', async () => {
    fetchMock.mockResolvedValue(respond(204))

    expect(await api('/api/auth/logout', { method: 'POST' })).toBeUndefined()
  })
})
