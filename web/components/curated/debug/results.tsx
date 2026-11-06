"use client"

import { type ReactNode, useState } from "react"
import { ArrowDownIcon, ArrowUpIcon } from "lucide-react"
import { cn } from "cn"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { Product, Row } from "@/lib/api"

import { ARM_COLUMNS, ARM_DESCRIPTIONS, ARM_LABELS } from "../arms"
import { ProductPhoto } from "../product-card"
import { clamp01 } from "./format"

type Value = number | string | null
type Column = {
  key: string
  label: string
  title: string
  value: (row: Row) => Value
  cell: (row: Row) => ReactNode
  width: number
  align?: "right"
  /** Pinned to the left edge while the table scrolls sideways, at this offset. */
  left?: number
  /** The direction a first click sorts in. */
  first: 1 | -1
}

const dash = <span className="text-ink-6">–</span>

function Mini({ value, threshold }: { value: number | null; threshold?: number }) {
  if (value === null) return dash
  const below = threshold !== undefined && value < threshold
  return (
    <span className="inline-flex items-center justify-end gap-1.5">
      <span aria-hidden className="relative h-1 w-6 flex-none rounded-full bg-wash-strong">
        <span
          className={cn("absolute inset-y-0 left-0 rounded-full", below ? "bg-ink-6" : "bg-ink-3")}
          style={{ width: `${clamp01(value) * 100}%` }}
        />
      </span>
      <span className="w-8 text-right">{value.toFixed(2)}</span>
    </span>
  )
}

const plain = (value: number | null) => (value === null ? dash : value)

function columns(line: number): Column[] {
  return [
    {
      key: "shown",
      label: "#",
      title: "Place on the page; a dash when the search did not show the product",
      value: (row) => row.shown,
      cell: (row) => plain(row.shown),
      width: 40,
      align: "right",
      left: 0,
      first: 1,
    },
    {
      key: "product",
      label: "Product",
      title: "Name, price and brand",
      value: (row) => row.name.toLowerCase(),
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2.5">
          <ProductPhoto path={row.photo} alt="" className="size-8 flex-none rounded-[8px]" />
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-sans font-medium text-ink" title={row.name}>
              {row.name}
            </span>
            <span className="truncate font-sans text-[11.5px] text-ink-5">
              {[row.price, row.brand].filter(Boolean).join(" · ")}
            </span>
          </span>
        </span>
      ),
      width: 300,
      left: 40,
      first: 1,
    },
    ...ARM_COLUMNS.map(
      ({ name, column }): Column => ({
        key: `arm.${name}`,
        label: column,
        title: `${ARM_LABELS[name]}: rank in this ranking's top 50. ${ARM_DESCRIPTIONS[name]}`,
        value: (row) => row.arms[name] ?? null,
        cell: (row) => plain(row.arms[name] ?? null),
        width: 38,
        align: "right",
        first: 1,
      }),
    ),
    {
      key: "fused",
      label: "fused",
      title: "Rank after reciprocal rank fusion of the eight rankings; a dash for a product only the tag expansion added",
      value: (row) => row.fused,
      cell: (row) => (row.fused === null ? <span className="font-sans text-ink-5">{row.expansion ? "exp" : "–"}</span> : row.fused),
      width: 56,
      align: "right",
      first: 1,
    },
    {
      key: "rrf",
      label: "RRF",
      title: "Reciprocal rank fusion score: the sum of 1 / (60 + rank) over the rankings that found the product",
      value: (row) => row.rrf,
      cell: (row) => (row.rrf === null ? dash : row.rrf.toFixed(4)),
      width: 64,
      align: "right",
      first: -1,
    },
    {
      key: "gate",
      label: "gate",
      title: "Decision model gate: the probability that the product is a convincing answer to the search",
      value: (row) => row.gate,
      cell: (row) => <Mini value={row.gate} threshold={line} />,
      width: 84,
      align: "right",
      first: -1,
    },
    {
      key: "early",
      label: "early",
      title: "Shown before the interpretation arrived, from a gate on the buyer's words alone",
      value: (row) => (row.early ? 1 : 0),
      cell: (row) => (row.early ? <span className="font-sans text-ink-3">early</span> : dash),
      width: 58,
      first: -1,
    },
  ]
}

function ColumnHeader({
  col,
  sorted,
  direction,
  onSort,
}: {
  col: Column
  sorted: boolean
  direction: 1 | -1
  onSort: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onSort}
          className={cn(
            "flex h-8 w-full cursor-pointer items-center gap-1 px-2 transition-colors hover:text-ink",
            col.align === "right" && "justify-end",
            sorted && "text-ink",
          )}
        >
          <span className={cn(col.key.startsWith("arm.") && "font-mono")}>{col.label}</span>
          {sorted &&
            (direction === 1 ? (
              <ArrowUpIcon className="size-3 flex-none" strokeWidth={2.2} />
            ) : (
              <ArrowDownIcon className="size-3 flex-none" strokeWidth={2.2} />
            ))}
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" sideOffset={6} className="max-w-64 text-left font-sans leading-snug">
        {col.title}
      </TooltipContent>
    </Tooltip>
  )
}

/** Nulls always sink to the bottom, whichever way the column sorts. */
function compare(a: Value, b: Value, direction: 1 | -1): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1
  if (typeof a === "number" && typeof b === "number") return (a - b) * direction
  return String(a).localeCompare(String(b)) * direction
}

const asLot = (row: Row): Product => ({ ...row, aesthetics: [] })

/** Every product the search judged, sortable by any column; a click opens the product. */
export function ResultsTable({ rows, line, onOpenLot }: { rows: Row[]; line: number; onOpenLot: (product: Product) => void }) {
  const [sort, setSort] = useState<{ key: string; direction: 1 | -1 }>({ key: "shown", direction: 1 })
  const cols = columns(line)
  const active = cols.find((col) => col.key === sort.key) ?? cols[0]
  const fallback = (row: Row) => row.fused ?? Number.MAX_SAFE_INTEGER
  const sorted = [...rows].sort((a, b) => compare(active.value(a), active.value(b), sort.direction) || fallback(a) - fallback(b))
  const width = cols.reduce((sum, col) => sum + col.width, 0)

  if (rows.length === 0) return <p className="text-[12.5px] text-ink-6">The search judged no products.</p>

  const shown = rows.filter((row) => row.shown !== null).length
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12px] text-ink-5">
        The {rows.length} products the gate read, {shown} of them shown; those not shown are dimmed. Click a header to sort, a row
        to open the product.
      </p>
      <div className="max-h-[min(620px,64dvh)] overflow-auto rounded-[14px] border border-hairline">
        <table
          className="min-w-full table-fixed border-separate border-spacing-0 font-mono text-[12px] text-ink-2 tabular-nums"
          style={{ width }}
        >
          <colgroup>
            {cols.map((col) => (
              <col key={col.key} style={{ width: col.width }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {cols.map((col) => {
                const isSorted = col.key === active.key
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={isSorted ? (sort.direction === 1 ? "ascending" : "descending") : undefined}
                    className={cn(
                      "sticky top-0 z-10 border-b border-hairline bg-white p-0 font-sans text-[11.5px] font-medium text-ink-5",
                      col.left !== undefined && "z-20",
                    )}
                    style={col.left !== undefined ? { left: col.left } : undefined}
                  >
                    <ColumnHeader
                      col={col}
                      sorted={isSorted}
                      direction={sort.direction}
                      onSort={() =>
                        setSort({ key: col.key, direction: isSorted ? (sort.direction === 1 ? -1 : 1) : col.first })
                      }
                    />
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.id} className="group cursor-pointer" onClick={() => onOpenLot(asLot(row))}>
                {cols.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "h-11 border-b border-hairline/60 bg-white px-2 transition-colors group-hover:bg-[rgb(246,246,245)]",
                      col.align === "right" && "text-right",
                      col.left !== undefined && "sticky z-[1]",
                      col.key === "product" && "shadow-[inset_-1px_0_0_var(--hairline)]",
                    )}
                    style={col.left !== undefined ? { left: col.left } : undefined}
                  >
                    <div className={cn("min-w-0", row.shown === null && "opacity-45")}>{col.cell(row)}</div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
