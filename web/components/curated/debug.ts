"use client"

import { useSyncExternalStore } from "react"

/**
 * Whether the breakdown of the current search is open: what it was understood as, the decision funnel, every product's
 * gate answer, the eight rankings and the timings. While it is open, a product opened from it also shows how the
 * search decided it. It starts closed on every visit, so the normal page never shows any of it.
 */
let open = false
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function setDebug(next: boolean): void {
  if (next === open) return
  open = next
  listeners.forEach((listener) => listener())
}

export function toggleDebug(): void {
  setDebug(!open)
}

export function useDebug(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => open,
    () => false,
  )
}
