"use client"

import { useSyncExternalStore } from "react"
import { ArrowUpIcon, LockIcon } from "lucide-react"

import { Wordmark } from "@/components/curated/wordmark"

const neverChanges = () => () => undefined
const currentAddress = () => window.location.pathname + window.location.search
const addressWhenBuilt = () => "/"

/**
 * The page the password gate answers with at any address, so `next` is where the visitor was going and signing in
 * returns them there. The form posts to the gate itself.
 */
export default function LoginPage() {
  const address = useSyncExternalStore(neverChanges, currentAddress, addressWhenBuilt)
  const url = new URL(address, "https://site.invalid")
  const wrong = url.searchParams.has("wrong")
  url.searchParams.delete("wrong")

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 pb-[18vh]">
      <div className="mb-8">
        <Wordmark />
      </div>
      <form method="post" action="/api/login" data-size="hero" className="find w-full max-w-[420px]">
        <LockIcon aria-hidden className="size-[18px] shrink-0 text-[var(--ink-4)]" strokeWidth={1.9} />
        <input type="password" name="password" placeholder="Password" aria-label="Password" required autoFocus />
        <input type="hidden" name="next" value={url.pathname + url.search} />
        <button type="submit" data-round aria-label="Enter" className="cta">
          <ArrowUpIcon className="size-4" strokeWidth={2.2} />
        </button>
      </form>
      <p aria-live="polite" className="mt-4 h-5 text-[13px] text-[var(--ink-6)]">
        {wrong ? "That password is not right." : null}
      </p>
    </main>
  )
}
