"use client"

import { type ReactNode, useEffect, useState } from "react"
import { BugIcon, CheckIcon, CopyIcon } from "lucide-react"

import { DialogDescription, DialogTitle } from "@/components/ui/dialog"
import type { Product, SearchResult } from "@/lib/api"

import { count, ms, plural } from "./format"
import { type FurtherBatch, Pipeline } from "./funnel"
import { GateView } from "./gate"
import { ReadingView } from "./reading"
import { ResultsTable } from "./results"
import { SettingsView } from "./settings"
import { DebugSection, Stat } from "./ui"
import { Waterfall } from "./waterfall"

export const SECTIONS = ["latency", "pipeline", "reading", "gate", "results", "settings"] as const
export type SectionId = (typeof SECTIONS)[number]
export const DEFAULT_OPEN: ReadonlySet<SectionId> = new Set<SectionId>(["latency", "pipeline", "results"])

const TITLES: Record<SectionId, string> = {
  latency: "Latency",
  pipeline: "Pipeline",
  reading: "How the search was read",
  gate: "Decision model gate",
  results: "Products judged",
  settings: "Settings",
}

function CopyJson({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1600)
    return () => window.clearTimeout(timer)
  }, [copied])
  return (
    <button
      type="button"
      className="pill"
      data-size="sm"
      onClick={() => void navigator.clipboard.writeText(JSON.stringify(value, null, 2)).then(() => setCopied(true))}
    >
      {copied ? <CheckIcon className="size-3.5" strokeWidth={2.2} /> : <CopyIcon className="size-3.5" strokeWidth={2} />}
      {copied ? "Copied" : "Copy JSON"}
    </button>
  )
}

function summaries(result: SearchResult, further: FurtherBatch[]): Record<SectionId, string> {
  const { debug } = result
  const slowest = debug.steps.reduce<(typeof debug.steps)[number] | null>(
    (best, step) => (best && best.ms >= step.ms ? best : step),
    null,
  )
  const stage = (key: string) => debug.funnel.find((entry) => entry.key === key)?.count ?? 0
  const chain = ["catalogue", "found", "gated", "shown"].map((key) => count(stage(key)))
  const reading = debug.reading
  const over = debug.gate.values.filter((p) => p >= debug.gate.line).length
  return {
    latency: `${ms(debug.moments.total ?? 0)} · ${plural(debug.steps.length, "stage")}${
      slowest ? ` · slowest ${slowest.label.toLowerCase()} ${ms(slowest.ms)}` : ""
    }`,
    pipeline: `${chain.join(" → ")}${
      further.length ? ` · ${plural(further.length, "further batch", "further batches")}` : ""
    }`,
    reading: `${reading.query_type?.replace("_", " ") ?? "unknown"} · ${
      reading.interpretation === null ? "no interpretation" : reading.interpretation_cached ? "cached" : "fresh"
    } interpretation · ${plural(reading.categories.length, "category", "categories")}`,
    gate: `${count(debug.gate.values.length)} asked · ${count(over)} at or over ${debug.gate.line}`,
    results: `${plural(debug.rows.length, "product")} · ${count(stage("shown"))} shown`,
    settings: `${plural(Object.keys(debug.settings.sizes).length, "size")} · ${plural(
      Object.keys(debug.settings.models).length,
      "model",
    )}`,
  }
}

function Header({ query, children, aside }: { query: string; children?: ReactNode; aside?: ReactNode }) {
  return (
    <header className="flex flex-none flex-col gap-4 px-6 pt-5 pb-5">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink-5">
        <BugIcon className="size-3.5" strokeWidth={2} />
        Query debug
      </div>
      <div className="flex min-w-0 items-baseline gap-3 pr-12">
        <DialogTitle className="min-w-0 truncate text-[22px] leading-tight font-medium tracking-heading text-ink" title={query}>
          {query}
        </DialogTitle>
      </div>
      <DialogDescription className="sr-only">Every stage, count and decision behind the results on screen.</DialogDescription>
      {(children || aside) && (
        <div className="flex flex-wrap items-end gap-x-7 gap-y-3">
          {children}
          <div className="ml-auto flex items-center gap-2">{aside}</div>
        </div>
      )}
    </header>
  )
}

/** The panel while the search is still running: the query, and a note that the account comes with the result. */
export function PendingPanel({ query }: { query: string }) {
  return (
    <>
      <Header query={query} />
      <p className="border-t border-hairline px-6 py-5 text-[13px] text-ink-6">The breakdown arrives with the full results.</p>
    </>
  )
}

export function DebugPanel({
  result,
  further,
  open,
  onOpenChange,
  onOpenLot,
}: {
  result: SearchResult
  further: FurtherBatch[]
  open: ReadonlySet<SectionId>
  onOpenChange: (open: ReadonlySet<SectionId>) => void
  onOpenLot: (product: Product) => void
}) {
  const { debug } = result
  const sums = summaries(result, further)
  const allOpen = SECTIONS.every((id) => open.has(id))
  const toggle = (id: SectionId) => {
    const next = new Set(open)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onOpenChange(next)
  }
  const section = (id: SectionId, body: () => ReactNode) => (
    <DebugSection key={id} title={TITLES[id]} summary={sums[id]} open={open.has(id)} onToggle={() => toggle(id)}>
      {body()}
    </DebugSection>
  )
  const stage = (key: string) => debug.funnel.find((entry) => entry.key === key)?.count ?? 0

  return (
    <>
      <Header
        query={result.query}
        aside={
          <>
            <button
              type="button"
              className="pill"
              data-size="sm"
              onClick={() => onOpenChange(allOpen ? new Set() : new Set(SECTIONS))}
            >
              {allOpen ? "Collapse all" : "Expand all"}
            </button>
            <CopyJson value={result} />
          </>
        }
      >
        <Stat label="Full page">{ms(debug.moments.total ?? 0)}</Stat>
        <Stat label="First product">{debug.moments.first_product === undefined ? "none" : ms(debug.moments.first_product)}</Stat>
        <Stat label="Understood as">{debug.reading.query_type?.replace("_", " ") ?? "unknown"}</Stat>
        <Stat label="Interpretation">
          {debug.reading.interpretation === null ? "none" : debug.reading.interpretation_cached ? "cached" : "fresh"}
        </Stat>
        <Stat label="Gated">{count(stage("gated"))}</Stat>
        <Stat label="Shown">{count(stage("shown"))}</Stat>
        <Stat label="Catalogue">{count(stage("catalogue"))}</Stat>
      </Header>
      <div className="flex-1 overflow-y-auto overscroll-contain pb-6">
        {section("latency", () => (
          <Waterfall steps={debug.steps} moments={debug.moments} />
        ))}
        {section("pipeline", () => (
          <Pipeline debug={debug} further={further} />
        ))}
        {section("reading", () => (
          <ReadingView reading={debug.reading} />
        ))}
        {section("gate", () => (
          <GateView gate={debug.gate} />
        ))}
        {section("results", () => (
          <ResultsTable rows={debug.rows} line={debug.gate.line} onOpenLot={onOpenLot} />
        ))}
        {section("settings", () => (
          <SettingsView settings={debug.settings} />
        ))}
      </div>
    </>
  )
}
