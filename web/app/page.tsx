"use client"

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"

import { SearchPage } from "@/components/curated/search-page"

function Home() {
  const q = useSearchParams().get("q")?.trim()
  return <SearchPage initialQuery={q || null} />
}

/** The page is built as a static file, so the address is only known in the browser. */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <Home />
    </Suspense>
  )
}
