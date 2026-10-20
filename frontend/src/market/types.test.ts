import { describe, expect, it } from 'vitest'

import { parseFrame } from './types'

const book = {
  v: 1, venue: 'kraken', symbol: 'BTC/USD',
  bids: [['80940.3', '0.00010000']], asks: [['80940.4', '2.52172147']],
  exchange_ts: '2026-10-20T10:00:00Z', ingested_at_ns: 1,
}

describe('parseFrame', () => {
  it('keeps prices and quantities as exact strings', () => {
    const frame = parseFrame(JSON.stringify({ type: 'book', data: book }))

    expect(frame?.type).toBe('book')
    expect(frame?.type === 'book' && frame.data.bids[0]).toEqual(['80940.3', '0.00010000'])
  })

  it.each([
    ['not JSON', 'nope{'],
    ['unknown type', JSON.stringify({ type: 'ticker', data: book })],
    ['missing data', JSON.stringify({ type: 'book' })],
    ['numeric prices', JSON.stringify({ type: 'book', data: { ...book, bids: [[1, 2]] } })],
    ['bad trade side', JSON.stringify({ type: 'trade', data: { ...book, side: 'up' } })],
  ])('rejects %s', (_, text) => {
    expect(parseFrame(text)).toBeNull()
  })
})
