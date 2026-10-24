import { type FormEvent, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import { useAuth } from '../auth/context'

interface Props {
  mode: 'login' | 'signup'
}

const copy = {
  login: { title: 'Log in', button: 'Log in', other: '/signup', otherText: 'Create an account' },
  signup: { title: 'Create an account', button: 'Sign up', other: '/login', otherText: 'Log in instead' },
}

export function CredentialsPage({ mode }: Props) {
  const auth = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  if (auth.status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setErrors([])
    try {
      await (mode === 'login' ? auth.logIn : auth.signUp)(username, password)
      navigate('/')
    } catch (error) {
      setErrors(error instanceof ApiError ? error.messages() : ['Something went wrong. Try again.'])
    } finally {
      setSubmitting(false)
    }
  }

  const text = copy[mode]
  return (
    <main className="mx-auto mt-16 max-w-sm px-6">
      <h1 className="mb-6 text-xl font-semibold">{text.title}</h1>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          Username
          <input
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {errors.length > 0 && (
          <ul role="alert" className="text-sm text-rose-400">
            {errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-emerald-600 px-3 py-2 font-medium hover:bg-emerald-500 disabled:opacity-50"
        >
          {text.button}
        </button>
      </form>
      <Link to={text.other} className="mt-4 inline-block text-sm text-slate-400 hover:text-white">
        {text.otherText}
      </Link>
    </main>
  )
}
