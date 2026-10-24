import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api/client'
import { backoffDelayMs, type SocketLike } from '../market/useMarketData'
import { mergeOrder, mergeOrders, newestFirst, type Orders } from './orders'
import type { Balance, Order, OrderRequest } from './types'

export type AccountStatus = 'offline' | 'connecting' | 'live' | 'reconnecting'

/** The account endpoints this hook uses, so tests can pass fakes. */
export interface AccountApi {
  fetchOrders(): Promise<Order[]>
  fetchBalances(): Promise<Balance[]>
  placeOrder(request: OrderRequest, idempotencyKey: string): Promise<Order>
  cancelOrder(id: number): Promise<Order>
}

export const httpAccountApi: AccountApi = {
  fetchOrders: () => api<Order[]>('/api/orders'),
  fetchBalances: () => api<Balance[]>('/api/balances'),
  placeOrder: (request, idempotencyKey) =>
    api<Order>('/api/orders', {
      method: 'POST',
      body: request,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
  cancelOrder: (id) => api<Order>(`/api/orders/${id}/cancel`, { method: 'POST' }),
}

// Both must keep the same identity between renders (module-level, or created once): a new
// one on every render would change the effect's dependencies and reconnect each time.
export interface Options {
  createSocket?: (url: string) => SocketLike
  accountApi?: AccountApi
}

const browserSocket = (url: string): SocketLike => new WebSocket(url)

export function userSocketUrl(location: Location = window.location): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/ws/user/`
}

export function useAccount(url: string | null, options: Options = {}) {
  const { createSocket = browserSocket, accountApi = httpAccountApi } = options
  const [orders, setOrders] = useState<Orders>({})
  const [balances, setBalances] = useState<Balance[]>([])
  const [status, setStatus] = useState<AccountStatus>('offline')
  const balanceRequest = useRef(0)

  const applyOrder = useCallback((order: Order) => setOrders((all) => mergeOrder(all, order)), [])

  const refreshBalances = useCallback(async () => {
    // Fills can trigger several refreshes at once; only the newest request may update state.
    const request = ++balanceRequest.current
    const latest = await accountApi.fetchBalances()
    if (request === balanceRequest.current) {
      setBalances(latest)
    }
  }, [accountApi])

  const refresh = useCallback(async () => {
    const [latestOrders] = await Promise.all([accountApi.fetchOrders(), refreshBalances()])
    setOrders((all) => mergeOrders(all, latestOrders))
  }, [accountApi, refreshBalances])

  useEffect(() => {
    if (url === null) {
      return
    }
    let socket: SocketLike | null = null
    let attempt = 0
    let stopped = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    const report = (error: unknown) => console.error('Could not load the account', error)

    const connect = () => {
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting')
      socket = createSocket(url)
      // Load after subscribing: anything that changes from now on is pushed, and anything
      // pushed while we were disconnected is in this snapshot.
      socket.onopen = () => {
        attempt = 0
        setStatus('live')
        refresh().catch(report)
      }
      socket.onmessage = (event) => {
        const order = parseOrderMessage(event.data)
        if (order !== null) {
          applyOrder(order)
          refreshBalances().catch(report)
        }
      }
      socket.onclose = () => {
        if (stopped) {
          return
        }
        attempt += 1
        setStatus('reconnecting')
        reconnectTimer = setTimeout(connect, backoffDelayMs(attempt))
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(reconnectTimer)
      socket?.close()
      setOrders({})
      setBalances([])
      setStatus('offline')
    }
  }, [url, createSocket, refresh, refreshBalances, applyOrder])

  const place = useCallback(
    async (request: OrderRequest, idempotencyKey: string) => {
      const order = await accountApi.placeOrder(request, idempotencyKey)
      applyOrder(order)
      refreshBalances().catch(() => undefined) // the funds are now reserved
      return order
    },
    [accountApi, applyOrder, refreshBalances],
  )

  const cancel = useCallback(
    async (id: number) => applyOrder(await accountApi.cancelOrder(id)),
    [accountApi, applyOrder],
  )

  const sorted = useMemo(() => newestFirst(orders), [orders])
  return { orders: sorted, balances, status, place, cancel }
}

function parseOrderMessage(text: string): Order | null {
  try {
    const message: unknown = JSON.parse(text)
    if (
      typeof message === 'object' &&
      message !== null &&
      'type' in message &&
      message.type === 'order' &&
      'order' in message &&
      typeof (message.order as Order)?.id === 'number'
    ) {
      return message.order as Order
    }
  } catch {
    // not JSON: ignore it, like the market socket does
  }
  return null
}
