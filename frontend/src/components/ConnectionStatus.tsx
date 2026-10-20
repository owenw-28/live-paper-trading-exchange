import type { Status } from '../market/useMarketData'

const styles: Record<Status, { dot: string; label: string }> = {
  connecting: { dot: 'bg-slate-400', label: 'Connecting' },
  live: { dot: 'bg-emerald-400', label: 'Live' },
  stale: { dot: 'bg-amber-400', label: 'Stale' },
  reconnecting: { dot: 'bg-rose-400', label: 'Reconnecting' },
}

export function ConnectionStatus({ status, latencyMs }: { status: Status; latencyMs: number | null }) {
  const { dot, label } = styles[status]
  return (
    <div className="flex items-center gap-2 text-sm text-slate-300" role="status">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span>{label}</span>
      {status === 'live' && latencyMs !== null && (
        <span className="font-mono text-slate-500">{Math.round(latencyMs)} ms</span>
      )}
    </div>
  )
}
