import { describe, expect, it } from 'vitest'

import { initialMarketState, MAX_TRADES, marketReducer } from './state'
import type { BookEvent, Frame, TradeEvent } from './types'

function bookFrame(symbol: string, bidPrice: string): Frame {
  const data: BookEvent = {
    v: 1, venue: 'kraken', symbol, bids: [[bidPrice, '1']], asks: [],
    exchange_ts: '2026-10-20T10:00:00Z', ingested_at_ns: 0,
  }
  return { type: 'book', data }
}

function tradeFrame(tradeId: number, symbol = 'BTC/USD'): Frame {
  const data: TradeEvent = {
    v: 1, venue: 'kraken', symbol, side: 'buy', price: '1', qty: '1', trade_id: tradeId,
    exchange_ts: '2026-10-20T10:00:00Z', ingested_at_ns: 0,
  }
  return { type: 'trade', data }
}

const apply = (frames: Frame[]) => frames.reduce(marketReducer, initialMarketState)

describe('marketReducer', () => {
  it('replaces the book for a symbol and leaves other symbols alone', () => {
    const state = apply([bookFrame('BTC/USD', '1'), bookFrame('ETH/USD', '2'), bookFrame('BTC/USD', '3')])

    expect(state.books['BTC/USD'].bids[0][0]).toBe('3')
    expect(state.books['ETH/USD'].bids[0][0]).toBe('2')
  })

  it('keeps trades newest first, without duplicates, capped', () => {
    const ids = [...Array(60).keys()]
    const state = apply([...ids.map((id) => tradeFrame(id)), tradeFrame(59), tradeFrame(30)])

    const kept = state.trades['BTC/USD'].map((t) => t.trade_id)
    expect(kept).toHaveLength(MAX_TRADES)
    expect(kept[0]).toBe(59)
    expect(new Set(kept).size).toBe(MAX_TRADES)
  })

  it('places a late, older trade in order', () => {
    const state = apply([tradeFrame(10), tradeFrame(12), tradeFrame(11)])

    expect(state.trades['BTC/USD'].map((t) => t.trade_id)).toEqual([12, 11, 10])
  })

  it('does not change state for a duplicate trade', () => {
    const once = apply([tradeFrame(1)])

    expect(marketReducer(once, tradeFrame(1))).toBe(once)
  })
})
