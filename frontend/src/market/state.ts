import type { BookEvent, Frame, TradeEvent } from './types'

export const MAX_TRADES = 50

export interface MarketState {
  books: Record<string, BookEvent>
  trades: Record<string, TradeEvent[]>
}

export const initialMarketState: MarketState = { books: {}, trades: {} }

/** Pure: the next market state after one frame. Books replace; trades merge, newest first. */
export function marketReducer(state: MarketState, frame: Frame): MarketState {
  const symbol = frame.data.symbol
  if (frame.type === 'book') {
    return { ...state, books: { ...state.books, [symbol]: frame.data } }
  }
  const existing = state.trades[symbol] ?? []
  if (existing.some((trade) => trade.trade_id === frame.data.trade_id)) {
    return state
  }
  const merged = [...existing, frame.data]
    .sort((a, b) => b.trade_id - a.trade_id)
    .slice(0, MAX_TRADES)
  return { ...state, trades: { ...state.trades, [symbol]: merged } }
}
