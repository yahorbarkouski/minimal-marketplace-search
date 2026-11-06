"use client"

import { Fragment } from "react"
import { cn } from "cn"

import type { SearchDebug, Stage } from "@/lib/api"

import { ARM_DESCRIPTIONS, ARM_LABELS } from "../arms"
import { BAR, count } from "./format"
import { Label } from "./ui"

/** A batch the search judged past its first, as the page received it. */
export type FurtherBatch = { judged: number; kept: number }

type Column = { kind: "node"; stage: Stage } | { kind: "stack"; stages: Stage[] }

const NODE_H = 52
const STACK_GAP = 8
const FAN_W = 28

/** The stages that split the gated products, drawn side by side. */
const SPLITS = [["shown", "dropped"]]

/** Each stage's count compares with the stage it came from; a split stage with the stage before the split. */
const FROM: Record<string, string> = {
  limits: "catalogue",
  shown: "gated",
  dropped: "gated",
}

function flowColumns(funnel: Stage[]): Column[] {
  const columns: Column[] = []
  const byKey = new Map(funnel.map((stage) => [stage.key, stage]))
  const placed = new Set<string>()
  for (const stage of funnel) {
    if (placed.has(stage.key)) continue
    const split = SPLITS.find((keys) => keys.includes(stage.key))
    if (split) {
      const stages = split.flatMap((key) => byKey.get(key) ?? [])
      stages.forEach((member) => placed.add(member.key))
      columns.push({ kind: "stack", stages })
    } else {
      placed.add(stage.key)
      columns.push({ kind: "node", stage })
    }
  }
  return columns
}

const stackHeight = (size: number) => size * NODE_H + (size - 1) * STACK_GAP

function Node({ stage, className }: { stage: Stage; className?: string }) {
  const off = stage.count === 0
  return (
    <div
      title={stage.detail ? `${stage.label}: ${stage.detail}` : stage.label}
      className={cn(
        "flex min-w-[84px] flex-none flex-col justify-center rounded-[14px] px-3",
        className,
        off ? "text-ink-6 outline-1 -outline-offset-1 outline-[rgb(var(--ink-rgb)/0.2)] outline-dashed" : "bg-wash",
      )}
      style={{ height: NODE_H }}
    >
      <span className={cn("truncate text-[11px] leading-tight", off ? "text-ink-6" : "text-ink-5")}>{stage.label}</span>
      <span className={cn("font-mono text-[15px] leading-tight font-medium tabular-nums", off ? "text-ink-6" : "text-ink")}>
        {count(stage.count)}
      </span>
    </div>
  )
}

/** Curves from one point to each node of a stack (out), or back (in). */
function Fan({ size, direction }: { size: number; direction: "out" | "in" }) {
  const height = stackHeight(size)
  const mid = height / 2
  const ends = Array.from({ length: size }, (_, i) => i * (NODE_H + STACK_GAP) + NODE_H / 2)
  return (
    <svg aria-hidden width={FAN_W} height={height} viewBox={`0 0 ${FAN_W} ${height}`} className="flex-none overflow-visible">
      {ends.map((y) => {
        const [from, to] = direction === "out" ? [mid, y] : [y, mid]
        return (
          <path
            key={y}
            d={`M0 ${from} C${FAN_W / 2} ${from}, ${FAN_W / 2} ${to}, ${FAN_W} ${to}`}
            fill="none"
            stroke="rgb(var(--ink-rgb) / 0.22)"
            strokeWidth={1.5}
          />
        )
      })}
    </svg>
  )
}

function Link() {
  return (
    <svg aria-hidden width={FAN_W} height={10} viewBox={`0 0 ${FAN_W} 10`} className="flex-none">
      <path d={`M0 5 H${FAN_W - 2}`} stroke="rgb(var(--ink-rgb) / 0.22)" strokeWidth={1.5} />
      <path d={`M${FAN_W - 6} 1.5 L${FAN_W - 1.5} 5 L${FAN_W - 6} 8.5`} fill="none" stroke="rgb(var(--ink-rgb) / 0.3)" strokeWidth={1.5} />
    </svg>
  )
}

/** The stages as a left-to-right flow, with what the gate keeps and drops drawn as parallel nodes. */
function Flow({ columns }: { columns: Column[] }) {
  return (
    <div className="overflow-x-auto pb-1">
      <div className="flex items-center">
        {columns.map((column, index) => {
          const previous = columns[index - 1]
          const connector =
            index === 0 ? null : column.kind === "stack" ? (
              <Fan size={column.stages.length} direction="out" />
            ) : previous?.kind === "stack" ? (
              <Fan size={previous.stages.length} direction="in" />
            ) : (
              <Link />
            )
          return (
            <Fragment key={column.kind === "node" ? column.stage.key : column.stages.map((stage) => stage.key).join("+")}>
              {connector}
              {column.kind === "node" ? (
                <Node stage={column.stage} className="flex-1" />
              ) : (
                <div className="flex min-w-[92px] flex-1 flex-col" style={{ gap: STACK_GAP }}>
                  {column.stages.map((stage) => (
                    <Node key={stage.key} stage={stage} />
                  ))}
                </div>
              )}
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}

/** Stage counts as centred bars on a log scale, the stage each came from ghosted behind it. */
function Bars({ funnel }: { funnel: Stage[] }) {
  const byKey = new Map(funnel.map((stage) => [stage.key, stage]))
  const max = Math.max(1, ...funnel.map((stage) => stage.count))
  const width = (value: number) => (value <= 0 ? 0 : (Math.log10(1 + value) / Math.log10(1 + max)) * 100)

  return (
    <div className="flex flex-col gap-1.5">
      <ol className="flex flex-col">
        {funnel.map((stage, index) => {
          const parent = byKey.get(FROM[stage.key] ?? "") ?? (index > 0 ? funnel[index - 1] : undefined)
          return (
            <li
              key={stage.key}
              className="grid h-8 items-center gap-x-4"
              style={{ gridTemplateColumns: "120px minmax(0, 1fr) 56px 72px minmax(0, 300px)" }}
            >
              <span className="truncate text-[12.5px] text-ink-2">{stage.label}</span>
              <span className="relative h-3.5">
                {parent && (
                  <span
                    aria-hidden
                    className="absolute inset-y-0 left-1/2 -translate-x-1/2 rounded-[4px] bg-wash"
                    style={{ width: `${width(parent.count)}%` }}
                  />
                )}
                <span
                  aria-hidden
                  className="absolute inset-y-0 left-1/2 min-w-[2px] -translate-x-1/2 rounded-[4px]"
                  style={{ width: `${width(stage.count)}%`, background: BAR }}
                />
              </span>
              <span className="text-right font-mono text-[12.5px] text-ink tabular-nums">{count(stage.count)}</span>
              <span className="truncate text-right font-mono text-[11px] text-ink-6 tabular-nums">
                {parent ? `of ${count(parent.count)}` : ""}
              </span>
              <span className="truncate text-[12px] text-ink-5" title={stage.detail ?? undefined}>
                {stage.detail}
              </span>
            </li>
          )
        })}
      </ol>
      <p className="text-[11px] text-ink-6">
        Bar widths on a log scale. The pale bar behind each is the stage it came from: the gate&apos;s answers split the gated
        products into those shown and those not.
      </p>
    </div>
  )
}

export function Pipeline({ debug, further }: { debug: SearchDebug; further: FurtherBatch[] }) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Label>Flow</Label>
        <Flow columns={flowColumns(debug.funnel)} />
      </div>
      <div>
        <Label>Rankings</Label>
        <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {debug.arms.map((arm) => (
            <li
              key={arm.name}
              className={cn(
                "flex flex-col gap-0.5 rounded-[14px] px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--hairline)]",
                arm.count === 0 && "text-ink-6",
              )}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="text-[12.5px] font-medium text-ink-2">{ARM_LABELS[arm.name] ?? arm.name}</span>
                <span className="font-mono text-[12.5px] text-ink tabular-nums">{arm.count ? count(arm.count) : "off"}</span>
              </span>
              <span className="text-[11.5px] leading-snug text-ink-5">{ARM_DESCRIPTIONS[arm.name]}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <Label>Funnel</Label>
        <Bars funnel={debug.funnel} />
      </div>
      <div>
        <Label>Further batches</Label>
        {further.length ? (
          <ol className="flex flex-col gap-1">
            {further.map((batch, index) => (
              <li key={index} className="flex items-baseline gap-4 font-mono text-[12.5px] text-ink-3 tabular-nums">
                <span className="w-16 font-sans text-ink-5">Batch {index + 1}</span>
                <span>judged {count(batch.judged)}</span>
                <span>{count(batch.kept)} shown</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[12.5px] text-ink-6">
            None yet. The decision model judges a further batch when the buyer reaches the end of the page and the last products
            judged still held matches.
          </p>
        )}
      </div>
    </div>
  )
}
