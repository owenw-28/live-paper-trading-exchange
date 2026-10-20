import { spread } from '../market/decimal'
import type { BookEvent, Level } from '../market/types'

interface Row {
  price: string
  qty: string
  total: number
}

function withRunningTotals(levels: Level[]): Row[] {
  let total = 0
  return levels.map(([price, qty]) => {
    total += Number(qty) // display only: bar widths don't need exact arithmetic
    return { price, qty, total }
  })
}

function BookRow({ row, maxTotal, side }: { row: Row; maxTotal: number; side: 'bid' | 'ask' }) {
  const width = `${(row.total / maxTotal) * 100}%`
  const bar = side === 'bid' ? 'bg-emerald-500/15' : 'bg-rose-500/15'
  const text = side === 'bid' ? 'text-emerald-400' : 'text-rose-400'
  return (
    <tr className="relative" data-testid={`${side}-row`}>
      <td className={`py-0.5 pl-3 ${text}`}>
        <span className={`absolute inset-y-0 right-0 ${bar}`} style={{ width }} aria-hidden />
        <span className="relative">{row.price}</span>
      </td>
      <td className="relative py-0.5 text-right">{row.qty}</td>
      <td className="relative py-0.5 pr-3 text-right text-slate-400">{row.total.toFixed(4)}</td>
    </tr>
  )
}

export function OrderBook({ book }: { book: BookEvent | undefined }) {
  if (book === undefined) {
    return <p className="p-4 text-slate-400">Waiting for the order book…</p>
  }
  const asks = withRunningTotals(book.asks)
  const bids = withRunningTotals(book.bids)
  const maxTotal = Math.max(asks.at(-1)?.total ?? 0, bids.at(-1)?.total ?? 0) || 1
  return (
    <table className="w-full font-mono text-sm tabular-nums">
      <thead className="text-xs text-slate-500">
        <tr>
          <th className="py-1 pl-3 text-left font-normal">Price</th>
          <th className="py-1 text-right font-normal">Qty</th>
          <th className="py-1 pr-3 text-right font-normal">Total</th>
        </tr>
      </thead>
      <tbody>
        {[...asks].reverse().map((row) => (
          <BookRow key={row.price} row={row} maxTotal={maxTotal} side="ask" />
        ))}
        <tr>
          <td colSpan={3} className="border-y border-slate-800 py-1 text-center text-xs text-slate-400">
            Spread {spread(book) ?? '—'}
          </td>
        </tr>
        {bids.map((row) => (
          <BookRow key={row.price} row={row} maxTotal={maxTotal} side="bid" />
        ))}
      </tbody>
    </table>
  )
}
