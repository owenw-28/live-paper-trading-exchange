import { Link } from 'react-router'

import { useAuth } from '../auth/context'

export function UserMenu() {
  const auth = useAuth()
  if (auth.status === 'loading') {
    return null
  }
  if (auth.user === null) {
    return (
      <nav className="flex gap-4 text-sm">
        <Link to="/login" className="text-slate-300 hover:text-white">
          Log in
        </Link>
        <Link to="/signup" className="text-slate-300 hover:text-white">
          Sign up
        </Link>
      </nav>
    )
  }
  return (
    <div className="flex items-center gap-4 text-sm">
      <span className="text-slate-300">{auth.user.username}</span>
      <button onClick={() => void auth.logOut()} className="text-slate-400 hover:text-white">
        Log out
      </button>
    </div>
  )
}
