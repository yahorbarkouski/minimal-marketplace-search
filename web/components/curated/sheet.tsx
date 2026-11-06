"use client"

import type { ReactNode } from "react"
import { XIcon } from "lucide-react"
import { cn } from "cn"

import { DialogClose, DialogContent } from "@/components/ui/dialog"

/**
 * The body of the site's dialogs: a white sheet with a round close button. On wider screens its top edge stays
 * put, so it grows downward as its content arrives instead of re-centring.
 */
export function SheetContent({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <DialogContent
      showCloseButton={false}
      className={cn(
        "max-h-[90dvh] gap-0 overflow-y-auto rounded-[28px] p-5 shadow-[0_24px_80px_rgb(23_24_26/0.16)] ring-0 sm:top-[6vh] sm:max-h-[88dvh] sm:translate-y-0 sm:p-6",
        className,
      )}
    >
      {children}
      <DialogClose className="round absolute top-4 right-4 bg-white/70 backdrop-blur-sm">
        <XIcon className="size-[18px]" strokeWidth={1.9} />
        <span className="sr-only">Close</span>
      </DialogClose>
    </DialogContent>
  )
}
