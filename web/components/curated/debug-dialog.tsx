"use client"

import { useState } from "react"

import { Dialog } from "@/components/ui/dialog"
import type { Product, SearchResult } from "@/lib/api"

import type { FurtherBatch } from "./debug/funnel"
import { DEFAULT_OPEN, DebugPanel, PendingPanel, type SectionId } from "./debug/panel"
import { SheetContent } from "./sheet"

/**
 * The query debug panel of one search, opened from the bug button or the `d` key: each stage on one time axis, the
 * counts from the catalogue to the page, how the decision model and the interpretation read the search, the gate's
 * answers, and every product the search judged. The normal page shows none of it. Which sections are open survives
 * closing and reopening.
 */
export function DebugDialog({
  query,
  result,
  further,
  open,
  onOpenChange,
  onOpenLot,
}: {
  query: string
  /** The full result of the search in the bar, or null while it is still running. */
  result: SearchResult | null
  /** The batches the search judged past its first, as they arrived. */
  further: FurtherBatch[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpenLot: (product: Product) => void
}) {
  const [sections, setSections] = useState<ReadonlySet<SectionId>>(DEFAULT_OPEN)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex h-[88dvh] flex-col overflow-hidden p-0 sm:max-w-[1180px] sm:p-0">
        {result ? (
          <DebugPanel result={result} further={further} open={sections} onOpenChange={setSections} onOpenLot={onOpenLot} />
        ) : (
          <PendingPanel query={query} />
        )}
      </SheetContent>
    </Dialog>
  )
}

/** How the search decided a product: the gate's probability. */
export function Decision({ product }: { product: Product }) {
  if (product.gate === null) return null
  return (
    <span className="font-mono text-[11px] whitespace-nowrap text-[var(--ink-5)] tabular-nums">
      gate {product.gate.toFixed(2)}
    </span>
  )
}
