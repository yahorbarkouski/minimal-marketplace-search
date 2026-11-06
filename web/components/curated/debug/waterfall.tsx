"use client"

import { type MouseEvent, useRef, useState } from "react"
import { cn } from "cn"

import type { Step } from "@/lib/api"

import { KIND_COLOR, KIND_LABEL, KINDS, ms } from "./format"

const LABEL_WIDTH = 220
const GAP = 16
const ROW = 26

/** Round tick values on [0, end]: steps of 1, 2 or 5 times a power of ten, about six of them. */
function ticks(end: number): number[] {
  const rough = end / 6
  const power = 10 ** Math.floor(Math.log10(Math.max(rough, 0.1)))
  const step = [1, 2, 5, 10].map((m) => m * power).find((candidate) => candidate >= rough) ?? 10 * power
  const out: number[] = []
  for (let value = 0; value <= end + 1e-9; value += step) out.push(Math.round(value * 1000) / 1000)
  return out
}

const tickLabel = (value: number) => (value >= 1000 ? ms(value) : `${value} ms`)

/**
 * Each stage a bar on one time axis, placed where it began and sized by how long it took, so the stages that run
 * at once overlap. A dashed line marks the first product on the page; the solid line, the full page.
 */
export function Waterfall({ steps, moments }: { steps: Step[]; moments: Record<string, number> }) {
  const rows = [...steps].sort((a, b) => a.start - b.start)
  const total = moments.total ?? 0
  const firstLot = moments.first_product
  const end = Math.max(total, 1, ...steps.map((step) => step.start + step.ms))
  const pct = (value: number) => (value / end) * 100
  const marks = ticks(end)
  const kinds = KINDS.filter((kind) => steps.some((step) => step.kind === kind))

  const box = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ index: number; x: number; width: number } | null>(null)
  const track = (event: MouseEvent, index: number) => {
    const rect = box.current?.getBoundingClientRect()
    if (rect) setHover({ index, x: event.clientX - rect.left, width: rect.width })
  }
  const active = hover ? rows[hover.index] : undefined

  if (steps.length === 0) return <p className="text-[12.5px] text-ink-6">No stages were recorded.</p>

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-4" aria-label="Kinds of work">
        {kinds.map((kind) => (
          <li key={kind} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="h-2 w-3 rounded-[2px]" style={{ background: KIND_COLOR[kind] }} />
            {KIND_LABEL[kind]}
          </li>
        ))}
        {firstLot !== undefined && (
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden className="h-3 border-l border-dashed border-ink-3" />
            First product {ms(firstLot)}
          </li>
        )}
        <li className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-3 w-px bg-ink-5" />
          Full page {ms(total)}
        </li>
      </ul>

      <div ref={box} className="relative" onMouseLeave={() => setHover(null)}>
        <div className="relative h-5" style={{ marginLeft: LABEL_WIDTH + GAP }}>
          {marks.map((value) => {
            const left = pct(value)
            return (
              <span
                key={value}
                className="absolute top-0 font-mono text-[10.5px] whitespace-nowrap text-ink-6 tabular-nums"
                style={{
                  left: `${left}%`,
                  transform: left === 0 ? undefined : left > 94 ? "translateX(-100%)" : "translateX(-50%)",
                }}
              >
                {tickLabel(value)}
              </span>
            )
          })}
        </div>

        <div className="relative">
          <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0" style={{ left: LABEL_WIDTH + GAP }}>
            {marks.map((value) => (
              <span key={value} className="absolute inset-y-0 w-px bg-hairline/70" style={{ left: `${pct(value)}%` }} />
            ))}
            {active && (
              <span
                className="absolute inset-y-0 bg-[rgb(var(--ink-rgb)/0.045)] shadow-[inset_1px_0_0_rgb(var(--ink-rgb)/0.18),inset_-1px_0_0_rgb(var(--ink-rgb)/0.18)]"
                style={{ left: `${pct(active.start)}%`, width: `max(${pct(active.ms)}%, 1px)` }}
              />
            )}
            {firstLot !== undefined && (
              <span className="absolute inset-y-0 border-l border-dashed border-ink-3" style={{ left: `${pct(firstLot)}%` }} />
            )}
            <span className="absolute inset-y-0 w-px bg-ink-5" style={{ left: `${pct(total)}%` }} />
          </div>

          <ol className="relative">
            {rows.map((step, index) => {
              const left = pct(step.start)
              const width = pct(step.ms)
              const labelInside = left + width > 82
              return (
                <li
                  key={step.key}
                  className={cn("grid items-center rounded-md transition-colors", hover?.index === index && "bg-wash/60")}
                  style={{ gridTemplateColumns: `${LABEL_WIDTH}px minmax(0, 1fr)`, columnGap: GAP, height: ROW }}
                  onMouseMove={(event) => track(event, index)}
                >
                  <span className="flex min-w-0 items-center gap-2 pl-1 text-[12.5px] text-ink-2">
                    <span aria-hidden className="size-1.5 flex-none rounded-full" style={{ background: KIND_COLOR[step.kind] }} />
                    <span className="truncate" title={step.label}>
                      {step.label}
                    </span>
                  </span>
                  <span className="relative h-full">
                    <span
                      className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-[3px]"
                      style={{ left: `${left}%`, width: `max(${width}%, 2px)`, background: KIND_COLOR[step.kind] }}
                    />
                    <span
                      className="absolute top-1/2 -translate-y-1/2 font-mono text-[11px] whitespace-nowrap text-ink-3 tabular-nums"
                      style={labelInside ? { right: `calc(${100 - left}% + 6px)` } : { left: `calc(${left + width}% + 6px)` }}
                    >
                      {ms(step.ms)}
                    </span>
                  </span>
                </li>
              )
            })}
          </ol>
        </div>

        {active && hover && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 w-[300px] rounded-[14px] bg-white p-3 text-[12px] shadow-[0_0_0_1px_rgb(var(--ink-rgb)/0.08),0_10px_30px_rgb(var(--ink-rgb)/0.12)]"
            style={{ left: Math.max(0, Math.min(hover.x + 14, hover.width - 300)), top: 20 + (hover.index + 1) * ROW + 6 }}
          >
            <div className="flex items-center gap-2">
              <span aria-hidden className="h-2 w-3 rounded-[2px]" style={{ background: KIND_COLOR[active.kind] }} />
              <span className="font-medium text-ink">{active.label}</span>
            </div>
            <dl className="mt-2 grid grid-cols-[72px_minmax(0,1fr)] gap-y-1 text-ink-3">
              <dt className="text-ink-6">Kind</dt>
              <dd>{KIND_LABEL[active.kind]}</dd>
              <dt className="text-ink-6">Time</dt>
              <dd className="font-mono tabular-nums">
                {ms(active.ms)} · {ms(active.start)} → {ms(active.start + active.ms)}
              </dd>
              <dt className="text-ink-6">Stage</dt>
              <dd className="font-mono">{active.key}</dd>
              {active.detail && (
                <>
                  <dt className="text-ink-6">Detail</dt>
                  <dd className="text-ink-2">{active.detail}</dd>
                </>
              )}
            </dl>
          </div>
        )}
      </div>
      <p className="text-[11px] text-ink-6">
        Times from the moment the search arrived. Products the early gate is confident about appear at the first product; the rest at the full page.
      </p>
    </div>
  )
}
