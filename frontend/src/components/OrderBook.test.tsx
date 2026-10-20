import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { BookEvent } from '../market/types'
import { OrderBook } from './OrderBook'

const book: BookEvent = {
  v: 1, venue: 'kraken', symbol: 'BTC/USD',
  bids: [['80940.3', '0.5'], ['80939.9', '1.0']],
  asks: [['80940.4', '0.2'], ['80941.0', '0.3']],
  exchange_ts: '', ingested_at_ns: 0,
}

const prices = (rows: HTMLElement[]) => rows.map((row) => within(row).getAllByRole('cell')[0].textContent)

describe('OrderBook', () => {
  it('shows asks above the spread, best ask nearest the middle, then bids best first', () => {
    render(<OrderBook book={book} />)

    const rows = screen.getAllByRole('row').slice(1)
    const spreadIndex = rows.findIndex((row) => row.textContent?.startsWith('Spread'))
    expect(prices(rows.slice(0, spreadIndex))).toEqual(['80941.0', '80940.4'])
    expect(rows[spreadIndex]).toHaveTextContent('Spread 0.1')
    expect(prices(rows.slice(spreadIndex + 1))).toEqual(['80940.3', '80939.9'])
  })

  it('shows quantities exactly as received', () => {
    render(<OrderBook book={{ ...book, bids: [['80940.3', '0.00010000']] }} />)

    expect(screen.getByText('0.00010000')).toBeInTheDocument()
  })

  it('says it is waiting when there is no book yet', () => {
    render(<OrderBook book={undefined} />)

    expect(screen.getByText(/waiting for the order book/i)).toBeInTheDocument()
  })
})
