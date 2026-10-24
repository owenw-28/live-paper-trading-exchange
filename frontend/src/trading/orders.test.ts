import { describe, expect, it } from 'vitest'

import { order } from '../test/fixtures'
import { isActive, mergeOrder, mergeOrders, newestFirst } from './orders'

describe('mergeOrder', () => {
  it('adds new orders and applies newer states', () => {
    const placed = mergeOrder({}, order())
    const filled = mergeOrder(placed, order({ status: 'filled', quote_amount: '40000.00' }))

    expect(filled[1].status).toBe('filled')
    expect(filled[1].quote_amount).toBe('40000.00')
  })

  it('never lets a late, older view undo a newer one', () => {
    // The socket pushed the fill before the POST response (still "pending") came back.
    const filled = mergeOrder({}, order({ status: 'filled' }))

    expect(mergeOrder(filled, order({ status: 'pending' }))[1].status).toBe('filled')
    expect(mergeOrder(filled, order({ status: 'open' }))[1].status).toBe('filled')
  })

  it('accepts updates at the same stage, such as a cancel being requested', () => {
    const open = mergeOrder({}, order({ status: 'open' }))

    expect(mergeOrder(open, order({ status: 'open', cancel_requested: true }))[1].cancel_requested).toBe(
      true,
    )
  })
})

describe('helpers', () => {
  it('lists newest first and knows which orders are still active', () => {
    const orders = mergeOrders({}, [order({ id: 1, status: 'filled' }), order({ id: 2, status: 'open' })])

    expect(newestFirst(orders).map((o) => o.id)).toEqual([2, 1])
    expect(newestFirst(orders).map(isActive)).toEqual([true, false])
  })
})
