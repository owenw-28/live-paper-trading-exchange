import { describe, expect, it } from 'vitest'

import { spread } from './decimal'
import type { BookEvent } from './types'

const book = (bid: string, ask: string): BookEvent => ({
  v: 1, venue: 'kraken', symbol: 'BTC/USD', bids: [[bid, '1']], asks: [[ask, '1']],
  exchange_ts: '', ingested_at_ns: 0,
})

describe('spread', () => {
  it('is exact where floating point is not', () => {
    expect(0.3 - 0.1).not.toBe(0.2)
    expect(spread(book('0.1', '0.3'))).toBe('0.2')
  })

  it('handles real BTC prices', () => {
    expect(spread(book('80940.3', '80940.4'))).toBe('0.1')
  })

  it('is null when a side is empty', () => {
    expect(spread({ ...book('1', '2'), asks: [] })).toBeNull()
  })
})
