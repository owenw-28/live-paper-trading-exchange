import type { Order, OrderStatus } from './types'

// How far along an order is. Updates arrive from two places (REST responses and the user
// socket) in no guaranteed order, so an older view must never replace a newer one.
const progress: Record<OrderStatus, number> = {
  pending: 0,
  open: 1,
  filled: 2,
  cancelled: 2,
  rejected: 2,
}

export type Orders = Record<number, Order>

export function isActive(order: Order): boolean {
  return progress[order.status] < 2
}

/** Add or update an order, unless what we already have is further along. */
export function mergeOrder(orders: Orders, incoming: Order): Orders {
  const current = orders[incoming.id]
  if (current !== undefined && progress[current.status] > progress[incoming.status]) {
    return orders
  }
  return { ...orders, [incoming.id]: incoming }
}

export function mergeOrders(orders: Orders, incoming: Order[]): Orders {
  return incoming.reduce(mergeOrder, orders)
}

/** Newest first. */
export function newestFirst(orders: Orders): Order[] {
  return Object.values(orders).sort((a, b) => b.id - a.id)
}
