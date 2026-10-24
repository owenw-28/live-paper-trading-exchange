import { useState } from 'react'
import { Link } from 'react-router'

import { useAuth } from '../auth/context'
import { Balances } from '../components/Balances'
import { ConnectionStatus } from '../components/ConnectionStatus'
import { OrderBook } from '../components/OrderBook'
import { OrderForm } from '../components/OrderForm'
import { OrdersTable } from '../components/OrdersTable'
import { SymbolTabs } from '../components/SymbolTabs'
import { TradesList } from '../components/TradesList'
import { marketSocketUrl, useMarketData } from '../market/useMarketData'
import type { BookEvent } from '../market/types'
import { isActive } from '../trading/orders'
import { useAccount, userSocketUrl } from '../trading/useAccount'

const SYMBOLS = ['BTC/USD', 'ETH/USD']
const SOCKET_URL = marketSocketUrl()
const USER_SOCKET_URL = userSocketUrl()

const panel = 'rounded-lg border border-slate-800'
const heading = 'border-b border-slate-800 px-3 py-2 text-sm text-slate-400'

export function MarketPage() {
  const [symbol, setSymbol] = useState(SYMBOLS[0])
  const { market, status, latencyMs } = useMarketData(SOCKET_URL)
  const auth = useAuth()

  return (
    <>
      <div className="flex items-center justify-between px-6 pt-4">
        <SymbolTabs symbols={SYMBOLS} selected={symbol} onSelect={setSymbol} />
        <ConnectionStatus status={status} latencyMs={latencyMs} />
      </div>
      <main className="grid gap-6 p-6 lg:grid-cols-3">
        <section className={panel}>
          <h2 className={heading}>Order book</h2>
          <OrderBook book={market.books[symbol]} />
        </section>
        <section className={panel}>
          <h2 className={heading}>Recent trades</h2>
          <TradesList trades={market.trades[symbol] ?? []} />
        </section>
        {auth.status === 'authenticated' ? (
          // Keyed by user, so logging in as someone else starts from a clean slate.
          <Trading key={auth.user?.id} symbol={symbol} book={market.books[symbol]} />
        ) : (
          <section className={`${panel} p-4 text-sm text-slate-300`}>
            <p className="mb-3">Trade against the live market with $100,000 of paper money.</p>
            <Link to="/signup" className="text-emerald-400 hover:text-emerald-300">
              Create an account
            </Link>
            {' or '}
            <Link to="/login" className="text-emerald-400 hover:text-emerald-300">
              log in
            </Link>
          </section>
        )}
      </main>
    </>
  )
}

function Trading({ symbol, book }: { symbol: string; book: BookEvent | undefined }) {
  const account = useAccount(USER_SOCKET_URL)
  const cancel = (id: number) => {
    // A 409 means it finished first; the pushed update will show how.
    account.cancel(id).catch((error: unknown) => console.warn('Cancel failed', error))
  }

  return (
    <>
      <div className="flex flex-col gap-6">
        <section className={panel}>
          <h2 className={heading}>Place order</h2>
          <OrderForm symbol={symbol} book={book} onSubmit={account.place} />
        </section>
        <section className={panel}>
          <h2 className={heading}>Balances</h2>
          <Balances balances={account.balances} />
        </section>
      </div>
      <section className={`${panel} lg:col-span-3`}>
        <h2 className={heading}>Open orders</h2>
        <OrdersTable
          orders={account.orders.filter(isActive)}
          empty="No open orders."
          onCancel={cancel}
        />
      </section>
      <section className={`${panel} lg:col-span-3`}>
        <h2 className={heading}>Order history</h2>
        <OrdersTable
          orders={account.orders.filter((order) => !isActive(order))}
          empty="No finished orders yet."
        />
      </section>
    </>
  )
}
