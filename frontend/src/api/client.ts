/** JSON requests to the Django API, with the session cookie and CSRF token handled. */

export class ApiError extends Error {
  readonly status: number
  readonly body: Record<string, unknown>

  constructor(status: number, body: Record<string, unknown>) {
    super(`API request failed with status ${status}`)
    this.status = status
    this.body = body
  }

  messages(): string[] {
    return Object.entries(this.body)
      .filter(([key]) => key !== 'code') // a machine-readable reason, not for people
      .flatMap(([, value]) => (Array.isArray(value) ? value.map(String) : [String(value)]))
  }

  get code(): string | undefined {
    return typeof this.body.code === 'string' ? this.body.code : undefined
  }
}

export function csrfToken(): string | undefined {
  return document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith('csrftoken='))
    ?.split('=')[1]
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
}

export async function api<T>(
  path: string,
  { method = 'GET', body, headers: extraHeaders = {} }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...extraHeaders }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (method !== 'GET') {
    if (csrfToken() === undefined) {
      await fetch('/api/auth/csrf', { credentials: 'same-origin' })
    }
    headers['X-CSRFToken'] = csrfToken() ?? ''
  }
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  if (response.status === 204) {
    return undefined as T
  }
  const data: unknown = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(response.status, (data ?? {}) as Record<string, unknown>)
  }
  return data as T
}
