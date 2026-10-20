import { useEffect, useReducer, useState } from 'react'

import { initialMarketState, marketReducer } from './state'
import { parseFrame } from './types'

export type Status = 'connecting' | 'live' | 'stale' | 'reconnecting'

/** The parts of the browser's WebSocket this hook uses, so tests can pass a fake. */
export interface SocketLike {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  close(): void
}

export interface Options {
  createSocket?: (url: string) => SocketLike
  staleAfterMs?: number
}

/** Exponential backoff with full jitter, like the ingestor's: up to 0.5 s, 1 s, 2 s ... 30 s. */
export function backoffDelayMs(attempt: number): number {
  return Math.random() * Math.min(30_000, 500 * 2 ** (attempt - 1))
}

// Defined once at module level: a new function on every render would change the effect's
// dependencies and reconnect the socket after every message.
const browserSocket = (url: string): SocketLike => new WebSocket(url)

export function marketSocketUrl(location: Location = window.location): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/ws/market/`
}

export function useMarketData(url: string, options: Options = {}) {
  const { createSocket = browserSocket, staleAfterMs = 5_000 } = options
  const [market, dispatch] = useReducer(marketReducer, initialMarketState)
  const [status, setStatus] = useState<Status>('connecting')
  const [latencyMs, setLatencyMs] = useState<number | null>(null)

  useEffect(() => {
    let socket: SocketLike | null = null
    let attempt = 0
    let stopped = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let staleTimer: ReturnType<typeof setTimeout> | undefined

    const markStaleLater = () => {
      clearTimeout(staleTimer)
      staleTimer = setTimeout(() => setStatus('stale'), staleAfterMs)
    }

    const connect = () => {
      socket = createSocket(url)
      socket.onopen = () => markStaleLater()
      socket.onmessage = (event) => {
        const frame = parseFrame(event.data)
        if (frame === null) {
          return
        }
        attempt = 0
        setStatus('live')
        markStaleLater()
        dispatch(frame)
        if (frame.type === 'book') {
          setLatencyMs(Date.now() - frame.data.ingested_at_ns / 1e6)
        }
      }
      socket.onclose = () => {
        clearTimeout(staleTimer)
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
      clearTimeout(staleTimer)
      socket?.close()
    }
  }, [url, createSocket, staleAfterMs])

  return { market, status, latencyMs }
}
