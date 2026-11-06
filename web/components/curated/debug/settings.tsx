"use client"

import type { ReactNode } from "react"

import type { SearchDebug } from "@/lib/api"

import { num } from "./format"
import { Label } from "./ui"

function Dotted({ entries }: { entries: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-8 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map(([key, value]) => (
        <div key={key} className="flex min-w-0 items-baseline gap-2 text-[12.5px]">
          <dt className="font-mono text-[11.5px] text-ink-3">{key}</dt>
          <span aria-hidden className="mb-[3px] min-w-3 flex-1 border-b border-dotted border-ink-6/50" />
          <dd className="truncate font-mono text-ink tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** The models and sizes the server ran this search with (`curated.settings`). */
export function SettingsView({ settings }: { settings: SearchDebug["settings"] }) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Label>Models</Label>
        <Dotted entries={Object.entries(settings.models)} />
      </div>
      <div>
        <Label>Sizes and thresholds</Label>
        <Dotted entries={Object.entries(settings.sizes).map(([key, value]) => [key, num(value)])} />
      </div>
    </div>
  )
}
