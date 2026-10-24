import { describe, expect, it } from 'vitest'

import { money, quantity } from './format'

describe('format', () => {
  it('trims quantities without switching to exponent notation', () => {
    expect(quantity('0.00100000')).toBe('0.001')
    expect(quantity('0.00000001')).toBe('0.00000001')
    expect(quantity('0E-8')).toBe('0')
  })

  it('shows money with thousands separators and fixed decimals', () => {
    expect(money('40100.06000000')).toBe('40,100.06')
    expect(money('-1234567.5')).toBe('-1,234,567.50')
    expect(money('0.00000001', 8)).toBe('0.00000001')
  })
})
