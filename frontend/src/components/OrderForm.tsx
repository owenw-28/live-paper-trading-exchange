import { type FormEvent, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import type { BookEvent } from '../market/types'
import { estimate } from '../trading/estimate'
import { money } from '../trading/format'
import type { Order, OrderRequest, OrderType, Side } from '../trading/types'

interface Props {
  symbol: string
  book: BookEvent | undefined
  onSubmit: (request: OrderRequest, idempotencyKey: string) => Promise<Order>
}

const UNKNOWN_OUTCOME =
  "We couldn't reach the exchange, so the order may or may not have been placed. " +
  'Submitting the same order again is safe: it will only be placed once.'

export function OrderForm({ symbol, book, onSubmit }: Props) {
  const [side, setSide] = useState<Side>('buy')
  const [type, setType] = useState<OrderType>('market')
  const [quantity, setQuantity] = useState('')
  const [limitPrice, setLimitPrice] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  // An attempt whose result we never heard (the network failed). Retrying exactly that order
  // reuses its key, so the server returns the original instead of placing a second one.
  const unanswered = useRef<{ body: string; key: string } | null>(null)

  const base = symbol.split('/')[0]
  const guess = estimate({
    side,
    type,
    quantity,
    limitPrice,
    bids: book?.bids ?? [],
    asks: book?.asks ?? [],
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    const request: OrderRequest = { symbol, side, type, quantity: quantity.trim() }
    if (type === 'limit') {
      request.limit_price = limitPrice.trim()
    }
    const body = JSON.stringify(request)
    const key = unanswered.current?.body === body ? unanswered.current.key : crypto.randomUUID()
    unanswered.current = { body, key }
    setSubmitting(true)
    setErrors([])
    try {
      await onSubmit(request, key)
      unanswered.current = null
      setQuantity('')
    } catch (error) {
      if (error instanceof ApiError) {
        unanswered.current = null // the server answered: this attempt is settled either way
        setErrors(error.messages())
      } else {
        setErrors([UNKNOWN_OUTCOME])
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 p-3 text-sm">
      <div className="grid grid-cols-2 gap-1" role="group" aria-label="Side">
        {(['buy', 'sell'] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={side === option}
            onClick={() => setSide(option)}
            className={`rounded py-1.5 capitalize ${
              side === option
                ? option === 'buy'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-rose-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:text-white'
            }`}
          >
            {option}
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1">
        Order type
        <select
          value={type}
          onChange={(event) => setType(event.target.value as OrderType)}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
        >
          <option value="market">Market</option>
          <option value="limit">Limit</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        Quantity ({base})
        <input
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-2 font-mono"
          placeholder="0.001"
          required
        />
      </label>
      {type === 'limit' && (
        <label className="flex flex-col gap-1">
          Limit price (USD)
          <input
            inputMode="decimal"
            value={limitPrice}
            onChange={(event) => setLimitPrice(event.target.value)}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2 font-mono"
            required
          />
        </label>
      )}
      <p className="text-slate-400" data-testid="estimate">
        {guess === null
          ? 'Enter a quantity to see an estimate.'
          : `${side === 'buy' ? 'You pay' : 'You receive'} ${guess.bound} $${money(guess.total)} ` +
            `(fee $${money(guess.fee)})`}
      </p>
      {errors.length > 0 && (
        <ul role="alert" className="text-rose-400">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <button
        type="submit"
        disabled={submitting}
        className={`rounded py-2 font-medium capitalize disabled:opacity-50 ${
          side === 'buy' ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-rose-600 hover:bg-rose-500'
        }`}
      >
        {side} {base}
      </button>
    </form>
  )
}
