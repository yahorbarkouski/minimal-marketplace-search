import { z } from "zod"

/** The search server (`uv run curated serve`), reached through the rewrite in next.config.ts. */
export const API_URL = ""

const ProductSchema = z.object({
  id: z.string(),
  name: z.string(),
  price: z.string(),
  brand: z.string(),
  category: z.string(),
  url: z.string(),
  photo: z.string().nullable(),
  aesthetics: z.array(z.string()),
  gate: z.number().nullable(),
})
export type Product = z.infer<typeof ProductSchema>

/** One timed stage of a search, placed on the search's time axis: it began `start` ms in and took `ms`. */
const StepSchema = z.object({
  key: z.string(),
  label: z.string(),
  kind: z.enum(["decision", "llm", "embedding", "code"]),
  start: z.number(),
  ms: z.number(),
  detail: z.string().nullable(),
})
export type Step = z.infer<typeof StepSchema>

const ProbabilitySchema = z.object({ id: z.string(), name: z.string(), p: z.number() })

/** How the decision model and the interpretation read the search. */
const ReadingSchema = z.object({
  query_type: z.string().nullable(),
  query_type_confidence: z.number().nullable(),
  states_limit: z.number().nullable(),
  limit_threshold: z.number(),
  filters: z.record(z.string(), z.unknown()).nullable(),
  interpretation: z.string().nullable(),
  interpretation_cached: z.boolean(),
  categories: z.array(ProbabilitySchema),
  facets: z.array(ProbabilitySchema),
  category_floor: z.number(),
  facet_floor: z.number(),
})
export type Reading = z.infer<typeof ReadingSchema>

const StageSchema = z.object({ key: z.string(), label: z.string(), count: z.number().int(), detail: z.string().nullable() })
export type Stage = z.infer<typeof StageSchema>

const GateSchema = z.object({
  values: z.array(z.number()),
  line: z.number(),
  first_line: z.number(),
  early: z.number().int(),
})
export type GateSummary = z.infer<typeof GateSchema>

/** A product the search judged: where each ranking put it, its fused rank and score, and the gate's answer. */
const RowSchema = z.object({
  id: z.string(),
  name: z.string(),
  price: z.string(),
  brand: z.string(),
  category: z.string(),
  url: z.string(),
  photo: z.string().nullable(),
  shown: z.number().int().nullable(),
  fused: z.number().int().nullable(),
  rrf: z.number().nullable(),
  arms: z.record(z.string(), z.number().int()),
  expansion: z.boolean(),
  early: z.boolean(),
  gate: z.number(),
})
export type Row = z.infer<typeof RowSchema>

/** The account of one search the query debug panel draws (`curated.debug_view` on the server). */
const DebugSchema = z.object({
  steps: z.array(StepSchema),
  moments: z.record(z.string(), z.number()),
  reading: ReadingSchema,
  arms: z.array(z.object({ name: z.string(), count: z.number().int() })),
  funnel: z.array(StageSchema),
  gate: GateSchema,
  rows: z.array(RowSchema),
  settings: z.object({
    sizes: z.record(z.string(), z.number()),
    models: z.record(z.string(), z.string()),
  }),
})
export type SearchDebug = z.infer<typeof DebugSchema>

const ResultSchema = z.object({
  query: z.string(),
  interpretation: z.string().nullable(),
  query_type: z.string().nullable(),
  filters: z.record(z.string(), z.unknown()).nullable(),
  products: z.array(ProductSchema),
  first_results: z.array(z.string()),
  debug: DebugSchema,
  /** Asks for the search's further batches; `more` says whether one may still hold matches. */
  search_id: z.string().optional(),
  more: z.boolean().default(false),
})
export type SearchResult = z.infer<typeof ResultSchema>

/** A batch the search judged past the products it showed: the products it adds, and whether another may hold matches. */
const BatchSchema = z.object({
  batch: z.number().int().optional(),
  judged: z.number().int(),
  products: z.array(ProductSchema),
  more: z.boolean(),
})
export type Batch = z.infer<typeof BatchSchema>

const FirstSchema = z.object({ elapsed_ms: z.number(), products: z.array(ProductSchema) })
export type FirstResults = z.infer<typeof FirstSchema>

const ErrorSchema = z.object({ message: z.string() })

const ProductDetailSchema = ProductSchema.extend({
  card: z.string(),
  about: z.string(),
  specs: z.array(z.object({ name: z.string(), value: z.string() })),
  designed_in: z.string().nullable(),
  lists: z.array(z.string()),
  style: z.object({
    vibe: z.string(),
    aesthetics: z.array(z.string()),
    moods: z.array(z.string()),
    settings: z.array(z.string()),
    appeals_to: z.array(z.string()),
    references: z.array(z.string()),
  }),
})
export type ProductDetail = z.infer<typeof ProductDetailSchema>

export function assetUrl(path: string): string {
  return `${API_URL}${path}`
}

/** Opens one search's event stream, which ends with its result; returns a function that closes it. */
export function streamSearch({
  query,
  onFirst,
  onResult,
  onError,
}: {
  query: string
  onFirst: (first: FirstResults) => void
  onResult: (result: SearchResult) => void
  onError: (message: string) => void
}): () => void {
  const source = new EventSource(`${API_URL}/api/search?q=${encodeURIComponent(query)}`)
  let finished = false
  const finish = () => {
    finished = true
    source.close()
  }
  source.addEventListener("first", (event) => {
    const parsed = FirstSchema.safeParse(JSON.parse(event.data))
    if (parsed.success) onFirst(parsed.data)
  })
  source.addEventListener("result", (event) => {
    finish()
    const parsed = ResultSchema.safeParse(JSON.parse(event.data))
    if (parsed.success) onResult(parsed.data)
    else onError(`The server sent a result this page cannot read: ${parsed.error.message}`)
  })
  source.addEventListener("error", (event) => {
    // A server-sent "error" event carries data; a dropped connection does not.
    const data = event instanceof MessageEvent ? ErrorSchema.safeParse(JSON.parse(event.data)) : null
    if (finished) return
    finish()
    onError(data?.success ? data.data.message : "Cannot reach the search server. Is `uv run curated serve` running?")
  })
  return finish
}

/** Judges the search's next batch; a search the server no longer keeps answers with nothing more. */
export async function fetchMore(searchId: string): Promise<Batch> {
  const response = await fetch(`${API_URL}/api/search/${encodeURIComponent(searchId)}/more`)
  if (response.status === 404) return { judged: 0, products: [], more: false }
  if (!response.ok) throw new Error(`more: ${response.status}`)
  return BatchSchema.parse(await response.json())
}

async function fetchLot(id: string): Promise<ProductDetail> {
  const response = await fetch(`${API_URL}/api/products/${encodeURIComponent(id)}`)
  if (!response.ok) throw new Error(`product ${id}: ${response.status}`)
  return ProductDetailSchema.parse(await response.json())
}

/** Product details are fetched once per page: pointing at a card starts the fetch, and opening the card reuses it. */
const productRequests = new Map<string, Promise<ProductDetail>>()
const productDetails = new Map<string, ProductDetail>()

export function loadLot(id: string): Promise<ProductDetail> {
  const known = productRequests.get(id)
  if (known) return known
  const request = fetchLot(id)
  productRequests.set(id, request)
  request.then(
    (detail) => productDetails.set(id, detail),
    () => productRequests.delete(id),
  )
  return request
}

/** Starts fetching a product's details ahead of a click; a failure is left for the dialog's own fetch to report. */
export function prefetchLot(id: string): void {
  loadLot(id).catch(() => undefined)
}

/** A product's details if they have already arrived, so the dialog can open with them in its first frame. */
export function loadedLot(id: string): ProductDetail | undefined {
  return productDetails.get(id)
}
