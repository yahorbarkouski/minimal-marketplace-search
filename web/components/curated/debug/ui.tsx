"use client"

import { type ReactNode, useId } from "react"
import { ChevronRightIcon } from "lucide-react"
import { cn } from "cn"

import { clamp01 } from "./format"

/** A collapsible block of the panel: a chevron, a title, and a quiet one-line summary on the right. */
export function DebugSection({
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  title: string
  summary?: ReactNode
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  const body = useId()
  return (
    <section className="border-t border-hairline">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={body}
          onClick={onToggle}
          className="flex w-full cursor-pointer items-center gap-2 px-6 py-3.5 text-left transition-colors hover:bg-wash/50"
        >
          <ChevronRightIcon
            className={cn("size-4 flex-none text-ink-6 transition-transform duration-200", open && "rotate-90")}
            strokeWidth={2}
          />
          <span className="text-[14px] font-medium text-ink">{title}</span>
          {summary !== undefined && (
            <span className="ml-auto min-w-0 truncate pl-4 font-mono text-[11.5px] text-ink-5 tabular-nums">{summary}</span>
          )}
        </button>
      </h3>
      {open && (
        <div id={body} className="px-6 pt-1 pb-7">
          {children}
        </div>
      )}
    </section>
  )
}

/** A small heading inside a section. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <h4 className={cn("mb-2 text-[12px] font-medium text-ink-6", className)}>{children}</h4>
}

/** A value in 0..1 as a short track with the number beside it; a tick marks the threshold the code applies. */
export function Meter({
  value,
  threshold = null,
  width = 44,
  className,
}: {
  value: number | null
  threshold?: number | null
  width?: number
  className?: string
}) {
  if (value === null) return <span className="font-mono text-[11.5px] text-ink-6">–</span>
  const below = threshold !== null && value < threshold
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span aria-hidden className="relative h-1 flex-none rounded-full bg-wash-strong" style={{ width }}>
        <span
          className={cn("absolute inset-y-0 left-0 rounded-full", below ? "bg-ink-6" : "bg-ink-3")}
          style={{ width: `${clamp01(value) * 100}%` }}
        />
        {threshold !== null && (
          <span className="absolute -top-[3px] h-2.5 w-px bg-ink-4" style={{ left: `${clamp01(threshold) * 100}%` }} />
        )}
      </span>
      <span className={cn("font-mono text-[11.5px] tabular-nums", below ? "text-ink-5" : "text-ink-3")}>
        {value.toFixed(2)}
      </span>
    </span>
  )
}

/** A monospaced token: a key, a term, an id. */
export function Tag({ children, title, className }: { children: ReactNode; title?: string; className?: string }) {
  return (
    <span
      title={title}
      className={cn("inline-flex items-center rounded-md bg-wash px-1.5 py-px font-mono text-[11.5px] text-ink-2", className)}
    >
      {children}
    </span>
  )
}

/** A yes or no as a dot and a word, so it never rests on colour alone. */
export function YesNo({ value, yes = "yes", no = "no" }: { value: boolean; yes?: string; no?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[12.5px]", value ? "text-ink-2" : "text-ink-5")}>
      <span className="dot" data-tone={value ? "on" : undefined} aria-hidden />
      {value ? yes : no}
    </span>
  )
}

/** Key and value rows in two columns. */
export function Pairs({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(0,150px)_minmax(0,1fr)] gap-x-4 gap-y-2 text-[12.5px]", className)}>
      {rows.map(([key, value], index) => (
        <div key={index} className="contents">
          <dt className="text-ink-5">{key}</dt>
          <dd className="min-w-0 text-ink-2">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Nothing({ children }: { children: ReactNode }) {
  return <span className="text-[12.5px] text-ink-6">{children}</span>
}

/** A number with its label above, for the header and the section stats. */
export function Stat({ label, children, large = false }: { label: string; children: ReactNode; large?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11.5px] text-ink-6">{label}</span>
      <span
        className={cn(
          "font-mono leading-tight whitespace-nowrap text-ink tabular-nums",
          large ? "text-[16px]" : "text-[14px]",
        )}
      >
        {children}
      </span>
    </div>
  )
}
