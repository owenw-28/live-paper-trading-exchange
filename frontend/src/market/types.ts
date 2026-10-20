// Mirrors apps/marketdata/events.py. Prices and quantities stay strings so they stay exact.

export type Level = [price: string, qty: string]

export interface BookEvent {
  v: number
  venue: string
  symbol: string
  bids: Level[]
  asks: Level[]
  exchange_ts: string
  ingested_at_ns: number
}

export interface TradeEvent {
  v: number
  venue: string
  symbol: string
  side: 'buy' | 'sell'
  price: string
  qty: string
  trade_id: number
  exchange_ts: string
  ingested_at_ns: number
}

export type Frame = { type: 'book'; data: BookEvent } | { type: 'trade'; data: TradeEvent }

/** Parse one WebSocket message. Returns null for anything that isn't a frame we understand. */
export function parseFrame(text: string): Frame | null {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return null
  }
  if (!isRecord(value) || !isRecord(value.data) || typeof value.data.symbol !== 'string') {
    return null
  }
  if (typeof value.data.ingested_at_ns !== 'number') {
    return null
  }
  const data = value.data
  if (value.type === 'book' && isLevels(data.bids) && isLevels(data.asks)) {
    return { type: 'book', data: data as unknown as BookEvent }
  }
  if (
    value.type === 'trade' &&
    (data.side === 'buy' || data.side === 'sell') &&
    typeof data.price === 'string' &&
    typeof data.qty === 'string' &&
    typeof data.trade_id === 'number'
  ) {
    return { type: 'trade', data: data as unknown as TradeEvent }
  }
  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isLevels(value: unknown): value is Level[] {
  return (
    Array.isArray(value) &&
    value.every(
      (level) =>
        Array.isArray(level) &&
        level.length === 2 &&
        typeof level[0] === 'string' &&
        typeof level[1] === 'string',
    )
  )
}
