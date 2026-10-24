import type { Balance, Order } from '../trading/types'

/** An order as the API returns it; override what the test cares about. */
export function order(overrides: Partial<Order> = {}): Order {
  return {
    id: 1, symbol: 'BTC/USD', side: 'buy', type: 'limit', quantity: '0.50000000',
    limit_price: '80000.00000000', status: 'pending', filled_quantity: '0E-8',
    average_price: null, quote_amount: null, fee: null, reject_reason: '',
    reserved_asset: 'USD', reserved_amount: '40100.00000000', cancel_requested: false,
    created_at: '2026-10-24T12:00:00Z', settled_at: null,
    ...overrides,
  }
}

export const balances: Balance[] = [
  { asset: 'BTC', available: '0.50000000', reserved: '0.00000000', total: '0.50000000' },
  { asset: 'USD', available: '59899.94', reserved: '40100.06', total: '100000.00' },
]
