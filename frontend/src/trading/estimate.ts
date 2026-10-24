import Big from 'big.js'

import type { Level } from '../market/types'
import type { OrderType, Side } from './types'

// Same rate and rounding as apps/trading/pricing.py; the server is still what charges you.
export const FEE_RATE = new Big('0.0025')

export interface Estimate {
  /** What you pay (buy) or receive (sell), fee included. */
  total: string
  fee: string
  /** Market orders walk the live book; limit orders are bounded by their price. */
  bound: 'about' | 'at most' | 'at least'
}

interface Input {
  side: Side
  type: OrderType
  quantity: string
  limitPrice: string
  bids: Level[]
  asks: Level[]
}

export function estimate({ side, type, quantity, limitPrice, bids, asks }: Input): Estimate | null {
  const qty = parse(quantity)
  if (qty === null || qty.lte(0)) {
    return null
  }
  let gross: Big | null
  if (type === 'limit') {
    const price = parse(limitPrice)
    gross = price === null || price.lte(0) ? null : qty.times(price)
  } else {
    gross = walk(side === 'buy' ? asks : bids, qty)
  }
  if (gross === null) {
    return null
  }
  const fee = gross.times(FEE_RATE).round(2, Big.roundUp)
  const total =
    side === 'buy' ? gross.round(2, Big.roundUp).plus(fee) : gross.round(2, Big.roundDown).minus(fee)
  const bound = type === 'market' ? 'about' : side === 'buy' ? 'at most' : 'at least'
  return { total: total.toFixed(2), fee: fee.toFixed(2), bound }
}

/** Cost of `qty` taken from `levels`, best first. Null if the visible book runs out. */
function walk(levels: Level[], qty: Big): Big | null {
  let remaining = qty
  let gross = new Big(0)
  for (const [price, available] of levels) {
    const size = remaining.lt(available) ? remaining : new Big(available)
    gross = gross.plus(size.times(price))
    remaining = remaining.minus(size)
    if (remaining.eq(0)) {
      return gross
    }
  }
  return null
}

function parse(text: string): Big | null {
  try {
    return new Big(text.trim())
  } catch {
    return null
  }
}
