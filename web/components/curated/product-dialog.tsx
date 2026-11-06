"use client"

import { useEffect, useState } from "react"
import { ArrowUpRightIcon } from "lucide-react"

import { Dialog, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { loadedLot, loadLot, type Product, type ProductDetail } from "@/lib/api"

import { useDebug } from "./debug"
import { Decision } from "./debug-dialog"
import { ProductPhoto } from "./product-card"
import { SheetContent } from "./sheet"

type Loaded = { kind: "loading" } | { kind: "ready"; detail: ProductDetail } | { kind: "failed"; message: string }

export function ProductDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  // The dialog keeps the last product while it animates closed, so it never shrinks away empty.
  const [last, setLast] = useState(product)
  if (product !== null && product !== last) setLast(product)
  const shown = product ?? last
  const [fetched, setFetched] = useState<{ id: string; state: Loaded } | null>(null)

  useEffect(() => {
    if (!product || loadedLot(product.id)) return
    let current = true
    loadLot(product.id).then(
      (detail) => current && setFetched({ id: product.id, state: { kind: "ready", detail } }),
      (error: unknown) => current && setFetched({ id: product.id, state: { kind: "failed", message: String(error) } }),
    )
    return () => {
      current = false
    }
  }, [product])

  const cached = shown ? loadedLot(shown.id) : undefined
  const state: Loaded = cached
    ? { kind: "ready", detail: cached }
    : fetched && shown && fetched.id === shown.id
      ? fetched.state
      : { kind: "loading" }
  const debug = useDebug()

  return (
    <Dialog open={product !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="sm:max-w-4xl">
        {shown && (
          <div className="flex flex-col gap-8">
            <div className="grid gap-6 sm:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] sm:gap-8">
              <ProductPhoto key={shown.id} path={shown.photo} alt={shown.name} className="aspect-square w-full" />
              <div className="flex flex-col gap-6 sm:pt-2">
                <div className="flex flex-col gap-2 pr-10">
                  <DialogTitle className="text-[24px] leading-[1.15] font-medium tracking-heading text-balance">
                    {shown.name}
                  </DialogTitle>
                  <DialogDescription className="text-[15px] text-[var(--ink-6)]">
                    {[shown.brand, shown.category, shown.price].filter(Boolean).join(" · ")}
                  </DialogDescription>
                </div>
                <a href={shown.url} target="_blank" rel="noreferrer" className="cta w-fit">
                  View on Curated Supply <ArrowUpRightIcon className="size-3.5" strokeWidth={2.2} />
                </a>
                {debug && shown.gate !== null && (
                  <section className="flex flex-col gap-2">
                    <Label>How the search decided</Label>
                    <Decision product={shown} />
                  </section>
                )}
                <StyleSection state={state} />
              </div>
            </div>
            {state.kind === "ready" && <EditorSection detail={state.detail} />}
            {debug && state.kind === "ready" && (
              <section className="flex flex-col gap-2">
                <Label>Catalogue card, as the index holds it</Label>
                <pre className="overflow-x-auto rounded-[20px] bg-[var(--wash)] p-5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--ink-3)]">
                  {state.detail.card}
                </pre>
              </section>
            )}
            {state.kind === "failed" && <p className="text-sm text-destructive">{state.message}</p>}
          </div>
        )}
      </SheetContent>
    </Dialog>
  )
}

function Label({ children }: { children: string }) {
  return <h4 className="text-[13px] font-medium text-[var(--ink-6)]">{children}</h4>
}

function StyleSection({ state }: { state: Loaded }) {
  if (state.kind === "loading") {
    return (
      <div className="flex flex-col gap-2.5">
        <Skeleton className="h-4 w-1/3 rounded-full" />
        <Skeleton className="h-20 w-full rounded-[18px]" />
      </div>
    )
  }
  if (state.kind === "failed") return null
  const style = state.detail.style
  const rows: [string, string[]][] = [
    ["Mood", style.moods],
    ["Suits", style.settings],
    ["Appeals to", style.appeals_to],
    ["Evokes", style.references],
  ]
  return (
    <section className="flex flex-col gap-4">
      <p className="text-[15px] leading-normal text-pretty text-[var(--ink-3)]">{style.vibe}</p>
      <div className="flex flex-wrap gap-1.5">
        {style.aesthetics.map((aesthetic) => (
          <span key={aesthetic} className="pill" data-size="sm">
            {aesthetic}
          </span>
        ))}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px] leading-snug">
        {rows
          .filter(([, values]) => values.length > 0)
          .map(([label, values]) => (
            <div key={label} className="contents">
              <dt className="text-[var(--ink-6)]">{label}</dt>
              <dd className="text-[var(--ink-2)]">{values.join(", ")}</dd>
            </div>
          ))}
      </dl>
    </section>
  )
}

/** The site's own account of the product: the editor's text, and its specification table. */
function EditorSection({ detail }: { detail: ProductDetail }) {
  const rows = [...(detail.designed_in ? [{ name: "Designed in", value: detail.designed_in }] : []), ...detail.specs]
  return (
    <div className="grid gap-8 sm:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <section className="flex flex-col gap-3">
        <Label>About</Label>
        {detail.about.split("\n\n").map((paragraph) => (
          <p key={paragraph} className="text-[15px] leading-normal text-pretty text-[var(--ink-3)]">
            {paragraph}
          </p>
        ))}
      </section>
      <div className="flex flex-col gap-6">
        {rows.length > 0 && (
          <section className="flex flex-col gap-3">
            <Label>Specifications</Label>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px] leading-snug">
              {rows.map((row) => (
                <div key={row.name} className="contents">
                  <dt className="text-[var(--ink-6)]">{row.name}</dt>
                  <dd className="text-[var(--ink-2)]">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
        {detail.lists.length > 0 && (
          <section className="flex flex-col gap-3">
            <Label>On the lists</Label>
            <div className="flex flex-wrap gap-1.5">
              {detail.lists.map((list) => (
                <span key={list} className="pill" data-size="sm">
                  {list}
                </span>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
