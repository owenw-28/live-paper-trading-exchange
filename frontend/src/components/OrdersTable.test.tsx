import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { order } from '../test/fixtures'
import { OrdersTable } from './OrdersTable'

describe('OrdersTable', () => {
  it('offers Cancel only on active orders that are not already being cancelled', () => {
    const onCancel = vi.fn()
    render(
      <OrdersTable
        empty="None"
        onCancel={onCancel}
        orders={[
          order({ id: 3, status: 'open' }),
          order({ id: 2, status: 'open', cancel_requested: true }),
          order({ id: 1, status: 'filled' }),
        ]}
      />,
    )
    const rows = screen.getAllByTestId('order-row')

    fireEvent.click(within(rows[0]).getByRole('button', { name: 'Cancel' }))

    expect(onCancel).toHaveBeenCalledWith(3)
    expect(within(rows[1]).getByText('Cancelling…')).toBeInTheDocument()
    expect(within(rows[2]).queryByRole('button')).toBeNull()
  })

  it('shows fills at their average price and rejections with their reason', () => {
    render(
      <OrdersTable
        empty="None"
        orders={[
          order({ id: 2, status: 'filled', average_price: '80575.80000000', quote_amount: '80.58000000' }),
          order({ id: 1, status: 'rejected', type: 'market', limit_price: null, reject_reason: 'price_moved' }),
        ]}
      />,
    )
    const [filled, rejected] = screen.getAllByTestId('order-row')

    expect(filled).toHaveTextContent('80,575.80')
    expect(filled).toHaveTextContent('80.58')
    expect(rejected).toHaveTextContent('rejected (price moved)')
    expect(rejected).toHaveTextContent('Market')
  })

  it('says so when there is nothing to show', () => {
    render(<OrdersTable empty="No open orders" orders={[]} />)

    expect(screen.getByText('No open orders')).toBeInTheDocument()
  })
})
