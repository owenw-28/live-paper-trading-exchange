import { describe, expect, it } from 'vitest'

import type { Level } from '../market/types'
import { estimate } from './estimate'

const asks: Level[] = [['100.0', '1'], ['100.5', '2']]
const bids: Level[] = [['99.9', '1'], ['99.5', '2']]
const base = { limitPrice: '', bids, asks }

describe('estimate', () => {
  it('walks the asks for a market buy, rounding against the buyer like the server', () => {
    // Same numbers as the engine test: 150.25 for the coins, 0.375625 fee rounded up.
    expect(estimate({ ...base, side: 'buy', type: 'market', quantity: '1.5' })).toEqual({
      total: '150.63',
      fee: '0.38',
      bound: 'about',
    })
  })

  it('rounds a fraction of a cent up for the buyer', () => {
    // 0.00123 * 100.0 = 0.123 -> 0.13, fee 0.0003075 -> 0.01
    expect(estimate({ ...base, side: 'buy', type: 'market', quantity: '0.00123' })?.total).toBe('0.14')
  })

  it('walks the bids for a market sell: proceeds rounded down, fee rounded up', () => {
    // 99.900000995 -> 99.90, fee 0.2497... -> 0.25
    expect(estimate({ ...base, side: 'sell', type: 'market', quantity: '1.00000001' })).toEqual({
      total: '99.65',
      fee: '0.25',
      bound: 'about',
    })
  })

  it('bounds limit orders by their price', () => {
    const order = { ...base, type: 'limit' as const, quantity: '2', limitPrice: '50.0' }

    expect(estimate({ ...order, side: 'buy' })?.bound).toBe('at most')
    expect(estimate({ ...order, side: 'buy' })?.total).toBe('100.25')
    expect(estimate({ ...order, side: 'sell' })?.bound).toBe('at least')
  })

  it('has no estimate for bad input or orders bigger than the visible book', () => {
    expect(estimate({ ...base, side: 'buy', type: 'market', quantity: '' })).toBeNull()
    expect(estimate({ ...base, side: 'buy', type: 'market', quantity: 'abc' })).toBeNull()
    expect(estimate({ ...base, side: 'buy', type: 'market', quantity: '0' })).toBeNull()
    expect(estimate({ ...base, side: 'buy', type: 'market', quantity: '3.1' })).toBeNull()
    expect(estimate({ ...base, side: 'buy', type: 'limit', quantity: '1' })).toBeNull()
  })
})
