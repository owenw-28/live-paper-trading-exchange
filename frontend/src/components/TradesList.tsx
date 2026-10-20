import type { TradeEvent } from '../market/types'

const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

export function TradesList({ trades }: { trades: TradeEvent[] }) {
  if (trades.length === 0) {
    return <p className="p-4 text-slate-400">No trades yet.</p>
  }
  return (
    <table className="w-full font-mono text-sm tabular-nums">
      <thead className="text-xs text-slate-500">
        <tr>
          <th className="py-1 pl-3 text-left font-normal">Time</th>
          <th className="py-1 text-right font-normal">Price</th>
          <th className="py-1 pr-3 text-right font-normal">Qty</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((trade) => (
          <tr key={trade.trade_id} data-testid="trade-row">
            <td className="py-0.5 pl-3 text-slate-400">
              {timeFormat.format(new Date(trade.exchange_ts))}
            </td>
            <td
              className={`py-0.5 text-right ${trade.side === 'buy' ? 'text-emerald-400' : 'text-rose-400'}`}
            >
              {trade.price}
            </td>
            <td className="py-0.5 pr-3 text-right">{trade.qty}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
