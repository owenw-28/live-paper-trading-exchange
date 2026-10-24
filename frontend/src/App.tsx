import { Link, Route, Routes } from 'react-router'

import { UserMenu } from './components/UserMenu'
import { CredentialsPage } from './pages/CredentialsPage'
import { MarketPage } from './pages/MarketPage'

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
        <Link to="/" className="font-semibold">
          Paper Exchange
        </Link>
        <UserMenu />
      </header>
      <Routes>
        <Route path="/" element={<MarketPage />} />
        <Route path="/login" element={<CredentialsPage mode="login" />} />
        <Route path="/signup" element={<CredentialsPage mode="signup" />} />
      </Routes>
    </div>
  )
}
