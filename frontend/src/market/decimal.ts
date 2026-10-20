import Big from 'big.js'

import type { BookEvent } from './types'

/** Best ask minus best bid, exactly, as a string. Null if either side is empty. */
export function spread(book: BookEvent): string | null {
  const bestAsk = book.asks[0]
  const bestBid = book.bids[0]
  if (bestAsk === undefined || bestBid === undefined) {
    return null
  }
  return new Big(bestAsk[0]).minus(bestBid[0]).toString()
}
