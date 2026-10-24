import { money, quantity } from '../trading/format'
import { isActive } from '../trading/orders'
import type { Order } from '../trading/types'

interface Props {
  orders: Order[]
  empty: string
  onCancel?: (id: number) => void
}

const statusStyle: Record<Order['status'], string> = {
  pending: 'text-slate-400',
  open: 'text-sky-400',
  filled: 'text-emerald-400',
  cancelled: 'text-slate-500',
  rejected: 'text-rose-400',
}

function price(order: Order): string {
  if (order.average_price !== null) {
    return money(order.average_price) // what it actually filled at
  }
  return order.limit_price === null ? 'Market' : money(order.limit_price)
}

export function OrdersTable({ orders, empty, onCancel }: Props) {
  if (orders.length === 0) {
    return <p className="p-3 text-sm text-slate-500">{empty}</p>
  }
  return (
    <table className="w-full text-sm tabular-nums">
      <thead className="text-xs text-slate-500">
        <tr>
          <th className="py-1 pl-3 text-left font-normal">Time</th>
          <th className="text-left font-normal">Symbol</th>
          <th className="text-left font-normal">Side</th>
          <th className="text-right font-normal">Qty</th>
          <th className="text-right font-normal">Price</th>
          <th className="text-right font-normal">Total</th>
          <th className="pl-4 text-left font-normal">Status</th>
          {onCancel && <th className="pr-3" />}
        </tr>
      </thead>
      <tbody className="font-mono">
        {orders.map((order) => (
          <tr key={order.id} data-testid="order-row" className="border-t border-slate-900">
            <td className="py-1 pl-3 text-slate-400">
              {new Date(order.created_at).toLocaleTimeString()}
            </td>
            <td>{order.symbol}</td>
            <td className={order.side === 'buy' ? 'text-emerald-400' : 'text-rose-400'}>
              {order.side} {order.type}
            </td>
            <td className="text-right">{quantity(order.quantity)}</td>
            <td className="text-right">{price(order)}</td>
            <td className="text-right text-slate-400">
              {order.quote_amount === null ? '—' : money(order.quote_amount)}
            </td>
            <td className={`pl-4 ${statusStyle[order.status]}`}>
              {order.status}
              {order.reject_reason && (
                <span className="text-slate-500"> ({order.reject_reason.replace(/_/g, ' ')})</span>
              )}
            </td>
            {onCancel && (
              <td className="pr-3 text-right">
                {isActive(order) &&
                  (order.cancel_requested ? (
                    <span className="text-slate-500">Cancelling…</span>
                  ) : (
                    <button
                      onClick={() => onCancel(order.id)}
                      className="text-slate-400 hover:text-white"
                    >
                      Cancel
                    </button>
                  ))}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
