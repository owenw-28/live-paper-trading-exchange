// Mirrors apps/trading/serializers.py and apps/ledger/views.py. Amounts stay strings: exact.

export type Side = 'buy' | 'sell'
export type OrderType = 'market' | 'limit'
export type OrderStatus = 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected'

export interface Order {
  id: number
  symbol: string
  side: Side
  type: OrderType
  quantity: string
  limit_price: string | null
  status: OrderStatus
  filled_quantity: string
  average_price: string | null
  quote_amount: string | null
  fee: string | null
  reject_reason: string
  reserved_asset: string
  reserved_amount: string
  cancel_requested: boolean
  created_at: string
  settled_at: string | null
}

export interface Balance {
  asset: string
  available: string
  reserved: string
  total: string
}

export interface OrderRequest {
  symbol: string
  side: Side
  type: OrderType
  quantity: string
  limit_price?: string
}
