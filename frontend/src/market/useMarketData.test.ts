import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type SocketLike, useMarketData } from './useMarketData'

class FakeSocket implements SocketLike {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  closed = false

  close() {
    this.closed = true
    this.onclose?.(new CloseEvent('close')) // a real browser fires close after close()
  }

  open() {
    this.onopen?.(new Event('open'))
  }

  receive(frame: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(frame) }))
  }

  drop() {
    this.onclose?.(new CloseEvent('close'))
  }
}

const book = (bid: string) => ({
  type: 'book',
  data: {
    v: 1, venue: 'kraken', symbol: 'BTC/USD', bids: [[bid, '1']], asks: [],
    exchange_ts: '', ingested_at_ns: Date.now() * 1e6,
  },
})

let sockets: FakeSocket[] = []
const createSocket = () => {
  const socket = new FakeSocket()
  sockets.push(socket)
  return socket
}

beforeEach(() => {
  sockets = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useMarketData', () => {
  it('goes live on the first frame and keeps one socket across re-renders', () => {
    const { result } = renderHook(() => useMarketData('ws://test', { createSocket }))
    expect(result.current.status).toBe('connecting')

    act(() => {
      sockets[0].open()
      sockets[0].receive(book('1'))
      sockets[0].receive(book('2'))
    })

    expect(result.current.status).toBe('live')
    expect(result.current.market.books['BTC/USD'].bids[0][0]).toBe('2')
    expect(sockets).toHaveLength(1)
  })

  it('marks the feed stale when frames stop arriving', () => {
    const { result } = renderHook(() =>
      useMarketData('ws://test', { createSocket, staleAfterMs: 5_000 }),
    )
    act(() => sockets[0].receive(book('1')))

    act(() => vi.advanceTimersByTime(5_001))

    expect(result.current.status).toBe('stale')
  })

  it('reconnects with backoff after the socket drops, keeping the last book', () => {
    vi.spyOn(Math, 'random').mockReturnValue(1)
    const { result } = renderHook(() => useMarketData('ws://test', { createSocket }))
    act(() => sockets[0].receive(book('1')))

    act(() => sockets[0].drop())
    expect(result.current.status).toBe('reconnecting')
    act(() => vi.advanceTimersByTime(499))
    expect(sockets).toHaveLength(1)
    act(() => vi.advanceTimersByTime(1))
    expect(sockets).toHaveLength(2)
    expect(result.current.market.books['BTC/USD'].bids[0][0]).toBe('1')

    act(() => sockets[1].drop())
    act(() => vi.advanceTimersByTime(999))
    expect(sockets).toHaveLength(2)
    act(() => vi.advanceTimersByTime(1))
    expect(sockets).toHaveLength(3)
  })

  it('closes the socket and does not reconnect after unmount', () => {
    const { unmount } = renderHook(() => useMarketData('ws://test', { createSocket }))

    unmount()
    act(() => vi.advanceTimersByTime(60_000))

    expect(sockets[0].closed).toBe(true)
    expect(sockets).toHaveLength(1)
  })

  it('keeps one browser WebSocket across re-renders when using the default socket', () => {
    vi.stubGlobal(
      'WebSocket',
      class {
        constructor() {
          return createSocket()
        }
      },
    )
    renderHook(() => useMarketData('ws://test'))

    act(() => {
      sockets[0].receive(book('1'))
      sockets[0].receive(book('2'))
    })

    expect(sockets).toHaveLength(1)
    expect(sockets[0].closed).toBe(false)
  })
})
