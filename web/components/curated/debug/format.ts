/** Formatting and colours shared by the query debug panel. Pure. */
import type { Step } from "@/lib/api"

/** One hue per kind of work, in the validated categorical order (blue, aqua, yellow, violet). */
export const KIND_COLOR: Record<Step["kind"], string> = {
  code: "#2a78d6",
  decision: "#1baf7a",
  embedding: "#eda100",
  llm: "#8a63d2",
}

export const KIND_LABEL: Record<Step["kind"], string> = {
  code: "Code",
  decision: "Decision model",
  embedding: "Embedding",
  llm: "Language model",
}

export const KINDS = ["decision", "llm", "embedding", "code"] as const satisfies readonly Step["kind"][]

/** The bar colour of the panel's single-series charts. */
export const BAR = "#2a78d6"

export function ms(value: number): string {
  if (value < 1) return "<1 ms"
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 1 : 2)} s`
  return `${Math.round(value)} ms`
}

/** A number at the precision its size deserves: 0.004 keeps three places, 0.35 two, a count of 30 none. */
export function num(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString()
  const abs = Math.abs(value)
  if (abs < 0.01) return value.toFixed(3)
  if (abs < 10) return value.toFixed(2)
  if (abs < 100) return value.toFixed(1)
  return Math.round(value).toLocaleString()
}

export function count(value: number): string {
  return value.toLocaleString()
}

export const plural = (n: number, one: string, many = `${one}s`) => `${count(n)} ${n === 1 ? one : many}`

export const clamp01 = (value: number) => Math.max(0, Math.min(1, value))
