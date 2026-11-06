"use client"

import type { GateSummary } from "@/lib/api"

import { BAR, count, num } from "./format"
import { Stat } from "./ui"

/** The gate's answers in twenty bins over 0..1, with the line marked. */
function Spread({ values, line }: { values: number[]; line: number }) {
  const bins = Array.from({ length: 20 }, () => 0)
  for (const value of values) bins[Math.min(19, Math.max(0, Math.floor(value * 20)))] += 1
  const max = Math.max(1, ...bins)
  return (
    <div className="flex flex-col gap-1">
      <div className="relative h-20">
        <div className="absolute inset-0 flex items-end gap-[2px]">
          {bins.map((value, index) => (
            <div
              key={index}
              title={`${(index / 20).toFixed(2)}–${((index + 1) / 20).toFixed(2)}: ${value}`}
              className="flex-1 rounded-t-[3px]"
              style={{ height: value ? `${(value / max) * 100}%` : 1, background: value ? BAR : "var(--hairline)" }}
            />
          ))}
        </div>
        <div className="absolute inset-y-0 w-px bg-ink-3" style={{ left: `${line * 100}%` }}>
          <span className="absolute -top-4 left-1 font-mono text-[10.5px] whitespace-nowrap text-ink-4">shown ≥ {num(line)}</span>
        </div>
      </div>
      <div className="flex justify-between font-mono text-[10.5px] text-ink-6 tabular-nums">
        <span>0</span>
        <span>0.5</span>
        <span>1</span>
      </div>
    </div>
  )
}

export function GateView({ gate }: { gate: GateSummary }) {
  const over = gate.values.filter((p) => p >= gate.line).length
  return (
    <div className="flex max-w-[560px] flex-col gap-4">
      <p className="text-[12.5px] leading-snug text-ink-3">
        The decision model reads each product&apos;s catalogue card, style description and photo beside the search and its
        interpretation, and gives the probability that the product is a convincing answer to the search. Its answer alone
        decides what reaches the page and in what order.
      </p>
      <div className="flex gap-8">
        <Stat label="Asked" large>
          {count(gate.values.length)}
        </Stat>
        <Stat label="At or over the line" large>
          {count(over)}
        </Stat>
        <Stat label="Under the line" large>
          {count(gate.values.length - over)}
        </Stat>
      </div>
      {gate.values.length > 0 && (
        <div className="pt-4">
          <Spread values={gate.values} line={gate.line} />
        </div>
      )}
      {gate.early > 0 && (
        <p className="text-[11.5px] text-ink-5">
          {count(gate.early)} products were shown early, from a gate on the buyer&apos;s words alone at {num(gate.first_line)} or
          more, before the interpretation arrived. They stay at the top of the page.
        </p>
      )}
    </div>
  )
}
