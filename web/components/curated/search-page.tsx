"use client"

import { type CSSProperties, type FormEvent, type ReactNode, useEffect, useRef, useState } from "react"
import { flushSync } from "react-dom"
import { ArrowUpIcon, BugIcon, DicesIcon, SearchIcon } from "lucide-react"
import { cn } from "cn"
import { Arc } from "loading-dev"

import { type Batch, type Product, type SearchResult, fetchMore, streamSearch } from "@/lib/api"

import { setDebug, toggleDebug, useDebug } from "./debug"
import type { FurtherBatch } from "./debug/funnel"
import { DebugDialog } from "./debug-dialog"
import { EXAMPLES } from "./examples"
import { ProductDialog } from "./product-dialog"
import { ProductGrid } from "./product-card"
import { Wordmark } from "./wordmark"

/**
 * Where the page is. `intro` says whether the start page plays its entrance; `stale` is what the previous search
 * showed, kept on screen, dimmed, until the new search's first products replace it.
 */
type SearchState =
  | { kind: "idle"; intro: boolean }
  | { kind: "searching"; query: string; found: Product[]; stale: Shown | null }
  | { kind: "done"; query: string; result: SearchResult; further: Further }
  | { kind: "failed"; query: string; message: string }

/**
 * The products the search found past the ones it showed first, judged a batch at a time: `more` says whether another
 * batch may still hold matches, `looking` that one is being judged now, and `batches` what each batch judged.
 */
type Further = { products: Product[]; more: boolean; looking: boolean; batches: FurtherBatch[] }

/**
 * Adds products to a list, each product once. The grid keys its cards by product, and React cannot reconcile two cards
 * with one key: a product listed twice can leave a card on screen that outlives its search.
 */
function addNew(products: Product[], incoming: Product[]): Product[] {
  const seen = new Set(products.map((product) => product.id))
  const fresh = incoming.filter((product) => {
    if (seen.has(product.id)) return false
    seen.add(product.id)
    return true
  })
  return [...products, ...fresh]
}

function withBatch(state: SearchState, query: string, batch: Batch): SearchState {
  if (state.kind !== "done" || state.query !== query) return state
  const { further } = state
  return {
    ...state,
    further: {
      products: [...further.products, ...batch.products],
      more: batch.more,
      looking: false,
      batches: [...further.batches, { judged: batch.judged, kept: batch.products.length }],
    },
  }
}

/** What the results area shows: the products, and the full result once it has arrived. */
type Shown = { products: Product[]; result: SearchResult | null }

function shownOf(state: SearchState): Shown | null {
  switch (state.kind) {
    case "done":
      return { products: addNew(state.result.products, state.further.products), result: state.result }
    case "searching":
      return state.found.length ? { products: state.found, result: null } : state.stale
    case "idle":
    case "failed":
      return null
  }
}

/**
 * Runs a change between the start page and the results as a view transition: the search box glides between the
 * middle of the page and the bar while the rest cross-fades. Without support, or with reduced motion, it just
 * happens.
 */
function transition(change: () => void): void {
  if (!("startViewTransition" in document) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    change()
    return
  }
  document.startViewTransition(() => flushSync(change))
}

/** One search the page asked for; a new one, even for the same text, gets a new id and a new stream. */
type Request = { id: number; query: string }

export function SearchPage({ initialQuery }: { initialQuery: string | null }) {
  const [text, setText] = useState(initialQuery ?? "")
  const [request, setRequest] = useState<Request | null>(initialQuery ? { id: 0, query: initialQuery } : null)
  const [state, setState] = useState<SearchState>(
    initialQuery
      ? { kind: "searching", query: initialQuery, found: [], stale: null }
      : { kind: "idle", intro: true },
  )
  const [open, setOpen] = useState<Product | null>(null)
  const lastExample = useRef<number | null>(null)
  const debug = useDebug()

  useEffect(() => {
    if (!request) return
    const { query } = request
    return streamSearch({
      query,
      onFirst: (first) =>
        setState((previous) =>
          previous.kind === "searching" && previous.query === query
            ? { ...previous, found: addNew(previous.found, first.products) }
            : previous,
        ),
      onResult: (result) =>
        setState({ kind: "done", query, result, further: { products: [], more: result.more, looking: false, batches: [] } }),
      onError: (message) => setState({ kind: "failed", query, message }),
    })
  }, [request])

  /** Asks the search for its next batch, when the buyer reaches the end of what is shown. */
  const lookFurther = () => {
    if (state.kind !== "done" || !state.further.more || state.further.looking) return
    const { query, result } = state
    if (!result.search_id) return
    setState({ ...state, further: { ...state.further, looking: true } })
    fetchMore(result.search_id).then(
      (batch) => setState((previous) => withBatch(previous, query, batch)),
      () =>
        setState((previous) =>
          previous.kind === "done" && previous.query === query
            ? { ...previous, further: { ...previous.further, more: false, looking: false } }
            : previous,
        ),
    )
  }

  const run = (query: string, { fromHistory = false } = {}) => {
    const trimmed = query.trim()
    if (!trimmed) return
    // The first search leaves the start page behind as a history entry, so Back returns to it; later ones replace it.
    if (!fromHistory) {
      const url = `?q=${encodeURIComponent(trimmed)}`
      if (state.kind === "idle") window.history.pushState(null, "", url)
      else window.history.replaceState(null, "", url)
    }
    const start = () => {
      setText(trimmed)
      setState((previous) => ({ kind: "searching", query: trimmed, found: [], stale: shownOf(previous) }))
      setRequest((previous) => ({ id: (previous?.id ?? 0) + 1, query: trimmed }))
    }
    if (state.kind === "idle") transition(start)
    else start()
  }

  const runRandom = () => {
    let index = Math.floor(Math.random() * EXAMPLES.length)
    if (index === lastExample.current) index = (index + 1) % EXAMPLES.length
    lastExample.current = index
    run(EXAMPLES[index])
  }

  const showStart = () => {
    setDebug(false)
    transition(() => {
      setRequest(null)
      setState({ kind: "idle", intro: false })
      setText("")
    })
  }

  // Subscribed afresh on every render, so the handlers always see the current page.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLElement && event.target.closest("input, textarea, [contenteditable]")
      if (event.key === "d" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey && state.kind !== "idle") {
        toggleDebug()
      }
    }
    // Back from the results returns to the start page; Forward runs the search again.
    const onHistory = () => {
      const query = new URLSearchParams(window.location.search).get("q")
      if (query) run(query, { fromHistory: true })
      else showStart()
    }
    window.addEventListener("keydown", onKey)
    window.addEventListener("popstate", onHistory)
    return () => {
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("popstate", onHistory)
    }
  })

  // The page shows it is working only until the first products are on screen; the rest of the search adds to them quietly.
  const waiting = state.kind === "searching" && state.found.length === 0
  // The start page's entrance plays on arrival only; coming back from results, the view transition carries it.
  const rise = state.kind === "idle" && state.intro ? "rise" : undefined
  const search = { text, onText: setText, onSubmit: () => run(text), busy: waiting }

  return (
    <div className="relative flex min-h-dvh flex-col">
      {state.kind === "idle" ? (
        <main className="flex flex-1 flex-col items-center justify-center px-4 pb-[18vh]">
          <h1 className="sr-only">Curated Supply: search well-designed products by what you mean</h1>
          <div className={cn("mb-8", rise)}>
            <Wordmark />
          </div>
          <SearchForm {...search} size="hero" autoFocus className={cn(rise, "w-full max-w-[560px]")} style={beat(1)} />
          <button type="button" onClick={runRandom} className={cn("pill dice mt-5", rise)} style={beat(2)}>
            <DicesIcon aria-hidden className="size-4" strokeWidth={1.9} />
            Try a random search
          </button>
        </main>
      ) : (
        <>
          {/* The bar shares the grid's width and gutters; the search box sits in its middle, as wide as on the start
              page, and the breakdown button at the grid's right edge. */}
          <Bar>
            <div className="mx-auto grid h-[76px] max-w-[1240px] grid-cols-[minmax(0,1fr)] items-center gap-3 px-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,560px)_minmax(0,1fr)] sm:px-8">
              <SearchForm {...search} onRandom={runRandom} className="sm:col-start-2" />
              <button
                type="button"
                onClick={toggleDebug}
                title="How this search was decided (d)"
                aria-label="How this search was decided"
                className="round hidden justify-self-end sm:grid"
              >
                <BugIcon className="size-[18px]" strokeWidth={1.9} />
              </button>
            </div>
          </Bar>
          <main className="mx-auto w-full max-w-[1240px] flex-1 px-4 pt-[100px] pb-24 sm:px-8">
            <Results state={state} waiting={waiting} onOpen={setOpen} />
            {state.kind === "done" ? <LookFurther further={state.further} onLook={lookFurther} /> : null}
          </main>
          <DebugDialog
            query={state.query}
            result={state.kind === "done" ? state.result : null}
            further={state.kind === "done" ? state.further.batches : []}
            open={debug}
            onOpenChange={setDebug}
            onOpenLot={setOpen}
          />
        </>
      )}
      <ProductDialog product={open} onClose={() => setOpen(null)} />
    </div>
  )
}

/**
 * The bar over the results. It is fixed, so it never moves while the page scrolls or bounces under it, and it is
 * clear; once the page has scrolled, the search box and the breakdown button frost over what passes beneath. A
 * one-pixel sentinel at the top of the page says when it has scrolled, so nothing runs on each scroll event.
 */
function Bar({ children }: { children: ReactNode }) {
  const top = useRef<HTMLDivElement>(null)
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const sentinel = top.current
    if (!sentinel) return
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) setScrolled(!entry.isIntersecting)
    })
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [])
  return (
    <>
      <div ref={top} aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px" />
      <header className="bar" data-scrolled={scrolled}>
        {children}
      </header>
    </>
  )
}

/** The hero's parts rise in one after another, a beat apart. */
function beat(index: number): CSSProperties {
  return { animationDelay: `${index * 70}ms` }
}

function SearchForm({
  text,
  onText,
  onSubmit,
  busy,
  size,
  onRandom,
  autoFocus,
  className,
  style,
}: {
  text: string
  onText: (text: string) => void
  onSubmit: () => void
  busy: boolean
  size?: "hero"
  /** Puts the random-search dice in the bar, beside the search button. */
  onRandom?: () => void
  autoFocus?: boolean
  className?: string
  style?: CSSProperties
}) {
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit()
  }
  return (
    <form onSubmit={submit} data-size={size} className={cn("find", className)} style={style}>
      <SearchIcon aria-hidden className="size-[18px] shrink-0 text-[var(--ink-4)]" strokeWidth={1.9} />
      <input
        value={text}
        onChange={(event) => onText(event.target.value)}
        placeholder="quiet luxury desk setup"
        aria-label="Search"
        maxLength={200}
        autoFocus={autoFocus}
        enterKeyHint="search"
      />
      {onRandom && (
        <button
          type="button"
          onClick={onRandom}
          title="Try a random search"
          aria-label="Try a random search"
          className="round dice"
        >
          <DicesIcon className="size-[18px]" strokeWidth={1.9} />
        </button>
      )}
      <button type="submit" data-round aria-label={busy ? "Searching" : "Search"} disabled={!busy && !text.trim()} className="cta">
        {busy ? <Arc size={18} color="currentColor" /> : <ArrowUpIcon className="size-4" strokeWidth={2.2} />}
      </button>
    </form>
  )
}

/**
 * The products for a search. While a new search has nothing to show yet, the previous one's products stay, dimmed, so the
 * page never goes blank. The grid keeps its place as the full results replace the first ones, so the products already on
 * screen stay put and only new ones rise in; everything else that arrives later appears below them.
 */
function Results({
  state,
  waiting,
  onOpen,
}: {
  state: Exclude<SearchState, { kind: "idle" }>
  waiting: boolean
  onOpen: (product: Product) => void
}) {
  if (state.kind === "failed") {
    return <p className="pt-24 text-center text-[15px] text-[var(--ink-6)]">{state.message}</p>
  }
  const shown = shownOf(state)
  if (!shown) return null
  const { products, result } = shown
  return (
    <div aria-busy={waiting} className={cn("transition-opacity duration-200", waiting && "pointer-events-none opacity-40")}>
      {result && products.length === 0 ? (
        <p className="pt-24 text-center text-[15px] text-[var(--ink-6)]">Nothing in the directory matches that.</p>
      ) : null}
      {products.length > 0 ? <ProductGrid products={products} onOpen={onOpen} /> : null}
    </div>
  )
}

/**
 * The end of the results while the search may still find more. A batch being judged shows a quiet line; otherwise
 * reaching the end asks for the next batch once the buyer has scrolled, and a short page offers a button instead,
 * so a search no one looks past costs nothing more.
 */
function LookFurther({ further, onLook }: { further: Further; onLook: () => void }) {
  const end = useRef<HTMLDivElement>(null)
  const { more, looking } = further
  useEffect(() => {
    const node = end.current
    if (!node || !more || looking) return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && window.scrollY > 0) onLook()
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [more, looking, onLook])
  if (!more && !looking) return null
  return (
    <div ref={end} className="flex justify-center pt-14">
      {looking ? (
        <span className="inline-flex items-center gap-2 text-[13px] text-[var(--ink-6)]">
          <Arc size={14} color="currentColor" />
          Looking further
        </span>
      ) : (
        <button type="button" onClick={onLook} className="pill">
          Look further
        </button>
      )}
    </div>
  )
}
