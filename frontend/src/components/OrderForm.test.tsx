import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import type { BookEvent } from '../market/types'
import { order } from '../test/fixtures'
import { OrderForm } from './OrderForm'

const book: BookEvent = {
  v: 1, venue: 'kraken', symbol: 'BTC/USD',
  bids: [['99.9', '1']], asks: [['100.0', '1'], ['100.5', '2']],
  exchange_ts: '', ingested_at_ns: 0,
}

function setup(onSubmit = vi.fn(async () => order())) {
  render(<OrderForm symbol="BTC/USD" book={book} onSubmit={onSubmit} />)
  const type = (text: string) =>
    fireEvent.change(screen.getByLabelText('Quantity (BTC)'), { target: { value: text } })
  const submit = () => fireEvent.click(screen.getByRole('button', { name: /buy btc|sell btc/i }))
  return { onSubmit, type, submit }
}

describe('OrderForm', () => {
  it('shows a live estimate from the book', () => {
    const { type } = setup()

    type('1.5')

    expect(screen.getByTestId('estimate')).toHaveTextContent('You pay about $150.63 (fee $0.38)')
  })

  it('sends a limit order with its price and an idempotency key', async () => {
    const { onSubmit, type, submit } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'sell' }))
    fireEvent.change(screen.getByLabelText('Order type'), { target: { value: 'limit' } })
    type('0.5')
    fireEvent.change(screen.getByLabelText('Limit price (USD)'), { target: { value: '120.0' } })

    submit()

    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalled())
    const [request, key] = onSubmit.mock.calls[0] as unknown as [object, string]
    expect(request).toEqual({
      symbol: 'BTC/USD', side: 'sell', type: 'limit', quantity: '0.5', limit_price: '120.0',
    })
    expect(key).toMatch(/^[A-Za-z0-9_-]{8,64}$/) // what the API accepts
  })

  it('shows why the exchange refused, and uses a new key next time', async () => {
    const onSubmit = vi.fn(async () => {
      throw new ApiError(400, { detail: 'Not enough USD available.', code: 'insufficient_funds' })
    })
    const { type, submit } = setup(onSubmit)
    type('1')

    submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Not enough USD available.')
    submit()
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))

    const keys = onSubmit.mock.calls.map((call) => (call as unknown as [object, string])[1])
    expect(keys[0]).not.toBe(keys[1])
  })

  it('retries an order whose outcome is unknown with the same key, so it is placed once', async () => {
    const onSubmit = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    const { type, submit } = setup(onSubmit)
    type('1')

    submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('may or may not have been placed')
    submit()
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))
    type('2') // a different order is a new attempt
    submit()
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(3))

    const keys = onSubmit.mock.calls.map((call) => (call as unknown as [object, string])[1])
    expect(keys[1]).toBe(keys[0])
    expect(keys[2]).not.toBe(keys[0])
  })
})
