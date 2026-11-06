"use client"

import type { ReactNode } from "react"

import type { Reading } from "@/lib/api"

import { Label, Meter, Nothing, Pairs, Tag, YesNo } from "./ui"

function Probabilities({
  items,
  floor,
  note,
}: {
  items: Reading["categories"]
  floor: number
  note: ReactNode
}) {
  if (items.length === 0) return <Nothing>None above 0.01</Nothing>
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-1.5">
        {items.map((item) => (
          <li key={item.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
            <span className="truncate text-[12.5px] text-ink-2" title={item.id}>
              {item.name}
            </span>
            <Meter value={item.p} threshold={floor} width={56} />
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-ink-6">{note}</p>
    </div>
  )
}

const filterValue = (value: unknown) => (Array.isArray(value) ? value.join(", ") : String(value))

export function ReadingView({ reading }: { reading: Reading }) {
  const waited = reading.states_limit !== null && reading.states_limit >= reading.limit_threshold
  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Label className="mb-0">Interpretation</Label>
          <span className="pill" data-size="sm">
            {reading.interpretation === null ? "none" : reading.interpretation_cached ? "cached" : "fresh"}
          </span>
        </div>
        {reading.interpretation ? (
          <p className="max-w-3xl text-[15px] leading-normal text-pretty text-ink-2">{reading.interpretation}</p>
        ) : (
          <Nothing>No interpretation arrived in time; the search used the buyer&apos;s words alone.</Nothing>
        )}
      </div>

      <div className="grid gap-8 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <Label>The decision model&apos;s reading</Label>
          <Pairs
            className="grid-cols-[minmax(0,110px)_minmax(0,1fr)]"
            rows={[
              [
                "Query type",
                reading.query_type ? (
                  <span className="inline-flex items-center gap-2">
                    <Tag>{reading.query_type.replace("_", " ")}</Tag>
                    <Meter value={reading.query_type_confidence} width={36} />
                  </span>
                ) : (
                  <Nothing>unknown</Nothing>
                ),
              ],
              [
                "States a limit",
                <span key="limit" className="inline-flex items-center gap-2">
                  <Meter value={reading.states_limit} threshold={reading.limit_threshold} width={36} />
                </span>,
              ],
              ["Waited for parse", <YesNo key="parse" value={waited} yes="yes" no="no, cancelled" />],
              [
                "Limits",
                reading.filters ? (
                  <span className="flex flex-wrap gap-1">
                    {Object.entries(reading.filters).map(([key, value]) => (
                      <Tag key={key}>
                        {key.replace("_", " ")} {filterValue(value)}
                      </Tag>
                    ))}
                  </span>
                ) : (
                  <Nothing>none</Nothing>
                ),
              ],
            ]}
          />
          <p className="mt-2 text-[11px] text-ink-6">
            The query type is kept for diagnosis; nothing routes on it. The tick on the limit is where the search waits for the
            price parse.
          </p>
        </div>
        <div>
          <Label>Categories</Label>
          <Probabilities
            items={reading.categories}
            floor={reading.category_floor}
            note={<>The facets arm weighs every category; the tag expansion uses those at the tick and above.</>}
          />
        </div>
        <div>
          <Label>Facets</Label>
          <Probabilities
            items={reading.facets}
            floor={reading.facet_floor}
            note={<>The facets arm weighs every facet; the tag expansion uses those at the tick and above.</>}
          />
        </div>
      </div>
    </div>
  )
}
