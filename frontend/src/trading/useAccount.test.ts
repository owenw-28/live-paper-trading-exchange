import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SocketLike } from '../market/useMarketData'
import { balances, order } from '../test/fixtures'
import type { Balance, Order } from './types'
import { type AccountApi, useAccount } from './useAccount'

class FakeSocket implements SocketLike {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  closed = false

  close() {
    this.closed = true
    this.onclose?.(new CloseEvent('close'))
  }

  open() {
    this.onopen?.(new Event('open'))
  }

  push(pushed: Order) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ type: 'order', order: pushed }) }))
  }

  drop() {
    this.onclose?.(new CloseEvent('close'))
  }
}

let sockets: FakeSocket[] = []
const createSocket = () => {
  const socket = new FakeSocket()
  sockets.push(socket)
  return socket
}

function fakeApi(serverOrders: Order[] = [], serverBalances: Balance[] = balances) {
  return {
    fetchOrders: vi.fn(async () => serverOrders),
    fetchBalances: vi.fn(async () => serverBalances),
    placeOrder: vi.fn(async () => order({ id: 9 })),
    cancelOrder: vi.fn(async () => order({ status: 'open', cancel_requested: true })),
  } satisfies AccountApi
}

const flush = () => act(async () => {}) // let resolved promises update state

beforeEach(() => {
  sockets = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useAccount', () => {
  it('does nothing while logged out', () => {
    const accountApi = fakeApi()
    const { result } = renderHook(() => useAccount(null, { createSocket, accountApi }))

    expect(sockets).toHaveLength(0)
    expect(result.current.status).toBe('offline')
  })

  it('loads orders and balances once subscribed, then applies pushed updates', async () => {
    const accountApi = fakeApi([order({ id: 1, status: 'open' })])
    const { result } = renderHook(() => useAccount('ws://test', { createSocket, accountApi }))

    act(() => sockets[0].open())
    await flush()
    expect(result.current.status).toBe('live')
    expect(result.current.orders.map((o) => o.status)).toEqual(['open'])
    expect(result.current.balances).toEqual(balances)

    act(() => sockets[0].push(order({ id: 1, status: 'filled' })))
    await flush()

    expect(result.current.orders.map((o) => o.status)).toEqual(['filled'])
    expect(accountApi.fetchBalances).toHaveBeenCalledTimes(2) // a fill moves money
  })

  it('catches up on anything it missed after reconnecting', async () => {
    const accountApi = fakeApi()
    const { result } = renderHook(() => useAccount('ws://test', { createSocket, accountApi }))
    act(() => sockets[0].open())
    await flush()

    act(() => sockets[0].drop())
    expect(result.current.status).toBe('reconnecting')
    accountApi.fetchOrders.mockResolvedValue([order({ id: 3, status: 'filled' })])
    await act(async () => vi.runOnlyPendingTimers())
    act(() => sockets[1].open())
    await flush()

    expect(result.current.orders.map((o) => o.id)).toEqual([3])
  })

  it('ignores a slow balance response that a newer one overtook', async () => {
    const accountApi = fakeApi()
    let answerSlowly: (value: Balance[]) => void = () => {}
    const old = [{ asset: 'USD', available: '1.00', reserved: '0.00', total: '1.00' }]
    accountApi.fetchBalances.mockReturnValueOnce(new Promise((resolve) => (answerSlowly = resolve)))
    const { result } = renderHook(() => useAccount('ws://test', { createSocket, accountApi }))

    act(() => sockets[0].open()) // first request: slow
    act(() => sockets[0].push(order())) // second request: answered at once
    await flush()
    await act(async () => answerSlowly(old))

    expect(result.current.balances).toEqual(balances)
  })

  it('places and cancels orders, showing the result straight away', async () => {
    const accountApi = fakeApi()
    const { result } = renderHook(() => useAccount('ws://test', { createSocket, accountApi }))
    act(() => sockets[0].open())
    await flush()

    await act(() => result.current.place({ symbol: 'BTC/USD', side: 'buy', type: 'market', quantity: '1' }, 'key-1'))
    await act(() => result.current.cancel(1))

    expect(accountApi.placeOrder).toHaveBeenCalledWith(expect.objectContaining({ quantity: '1' }), 'key-1')
    expect(result.current.orders.map((o) => [o.id, o.cancel_requested])).toEqual([[9, false], [1, true]])
  })

  it('closes the socket and forgets the account on log out', async () => {
    const accountApi = fakeApi([order()]) // created once: a new object each render would reconnect
    const { result, rerender } = renderHook(
      ({ url }: { url: string | null }) => useAccount(url, { createSocket, accountApi }),
      { initialProps: { url: 'ws://test' as string | null } },
    )
    act(() => sockets[0].open())
    await flush()

    rerender({ url: null })

    expect(sockets[0].closed).toBe(true)
    expect(result.current.orders).toEqual([])
    expect(result.current.status).toBe('offline')
  })
})
