import { useState } from 'react'

import { ConnectionStatus } from '../components/ConnectionStatus'
import { OrderBook } from '../components/OrderBook'
import { SymbolTabs } from '../components/SymbolTabs'
import { TradesList } from '../components/TradesList'
import { marketSocketUrl, useMarketData } from '../market/useMarketData'

const SYMBOLS = ['BTC/USD', 'ETH/USD']
const SOCKET_URL = marketSocketUrl()

export function MarketPage() {
  const [symbol, setSymbol] = useState(SYMBOLS[0])
  const { market, status, latencyMs } = useMarketData(SOCKET_URL)

  return (
    <>
      <div className="flex items-center justify-between px-6 pt-4">
        <SymbolTabs symbols={SYMBOLS} selected={symbol} onSelect={setSymbol} />
        <ConnectionStatus status={status} latencyMs={latencyMs} />
      </div>
      <main className="grid gap-6 p-6 md:grid-cols-2">
        <section className="rounded-lg border border-slate-800">
          <h2 className="border-b border-slate-800 px-3 py-2 text-sm text-slate-400">Order book</h2>
          <OrderBook book={market.books[symbol]} />
        </section>
        <section className="rounded-lg border border-slate-800">
          <h2 className="border-b border-slate-800 px-3 py-2 text-sm text-slate-400">
            Recent trades
          </h2>
          <TradesList trades={market.trades[symbol] ?? []} />
        </section>
      </main>
    </>
  )
}
