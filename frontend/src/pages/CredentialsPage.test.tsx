import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { type Auth, AuthContext } from '../auth/context'
import { CredentialsPage } from './CredentialsPage'

function renderPage(auth: Partial<Auth>, mode: 'login' | 'signup' = 'login') {
  const value: Auth = {
    status: 'anonymous',
    user: null,
    signUp: vi.fn(),
    logIn: vi.fn(),
    logOut: vi.fn(),
    ...auth,
  }
  render(
    <AuthContext value={value}>
      <MemoryRouter initialEntries={[`/${mode}`]}>
        <Routes>
          <Route path="/" element={<p>Home page</p>} />
          <Route path={`/${mode}`} element={<CredentialsPage mode={mode} />} />
        </Routes>
      </MemoryRouter>
    </AuthContext>,
  )
  return value
}

function fillIn(username: string, password: string) {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
}

describe('CredentialsPage', () => {
  it('logs in and goes to the home page', async () => {
    const auth = renderPage({ logIn: vi.fn().mockResolvedValue(undefined) })

    fillIn('owen', 'secret-password')

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(auth.logIn).toHaveBeenCalledWith('owen', 'secret-password')
  })

  it('shows the error messages from the API', async () => {
    const error = new ApiError(400, { detail: 'Incorrect username or password.' })
    renderPage({ logIn: vi.fn().mockRejectedValue(error) })

    fillIn('owen', 'wrong')

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect username or password.')
  })

  it('sends a logged-in user straight to the home page', () => {
    renderPage({ status: 'authenticated', user: { id: 1, username: 'owen' } })

    expect(screen.getByText('Home page')).toBeInTheDocument()
  })

  it('uses new-password autocomplete when signing up', () => {
    renderPage({}, 'signup')

    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password')
  })
})
