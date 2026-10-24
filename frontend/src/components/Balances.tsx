import { money } from '../trading/format'
import type { Balance } from '../trading/types'

const places = (asset: string) => (asset === 'USD' ? 2 : 8)

export function Balances({ balances }: { balances: Balance[] }) {
  if (balances.length === 0) {
    return <p className="p-3 text-sm text-slate-500">Loading balances…</p>
  }
  return (
    <table className="w-full text-sm tabular-nums">
      <thead className="text-xs text-slate-500">
        <tr>
          <th className="py-1 pl-3 text-left font-normal">Asset</th>
          <th className="text-right font-normal">Available</th>
          <th className="pr-3 text-right font-normal">In orders</th>
        </tr>
      </thead>
      <tbody className="font-mono">
        {balances.map((balance) => (
          <tr key={balance.asset}>
            <td className="py-1 pl-3">{balance.asset}</td>
            <td className="text-right">{money(balance.available, places(balance.asset))}</td>
            <td className="pr-3 text-right text-slate-400">
              {money(balance.reserved, places(balance.asset))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
