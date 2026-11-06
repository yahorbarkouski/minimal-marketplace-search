"use client"

import { useState } from "react"
import { ImageOffIcon } from "lucide-react"
import { cn } from "cn"

import { assetUrl, type Product, prefetchLot } from "@/lib/api"

/** A product's photo, whole and centred on a wash tile; it fades in once it has loaded instead of popping in. */
export function ProductPhoto({ path, alt, className }: { path: string | null; alt: string; className?: string }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <div className={cn("tile", className)}>
      {path ? (
        // The photos come from the search server, so the Next image optimizer has nothing to add.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={assetUrl(path)}
          alt={alt}
          loading="lazy"
          data-loaded={loaded}
          onLoad={() => setLoaded(true)}
          className="size-full object-contain p-[9%]"
        />
      ) : (
        <div className="flex size-full items-center justify-center text-[var(--ink-6)]">
          <ImageOffIcon className="size-5" />
        </div>
      )}
    </div>
  )
}

function ProductCard({
  product,
  index,
  onOpen,
}: {
  product: Product
  index: number
  onOpen: (product: Product) => void
}) {
  // The entrance delay is fixed when the card first appears: if a card moved in the grid and its delay changed
  // while it was still rising, the browser would rewind its entrance and the card would blink.
  const [delay] = useState(() => Math.min(index, 14) * 28)
  return (
    <button
      type="button"
      onClick={() => onOpen(product)}
      onPointerEnter={() => prefetchLot(product.id)}
      onFocus={() => prefetchLot(product.id)}
      style={{ animationDelay: `${delay}ms` }}
      className="product flex cursor-pointer flex-col gap-3 text-left"
    >
      <ProductPhoto path={product.photo} alt={product.name} className="aspect-square w-full" />
      <div className="flex flex-col gap-1 px-1">
        <span className="line-clamp-2 text-[13.5px] leading-[1.35] font-medium text-[var(--ink-2)]">{product.name}</span>
        <span className="truncate text-[13px] text-[var(--ink-6)]">{[product.brand, product.price].filter(Boolean).join(" · ")}</span>
      </div>
    </button>
  )
}

export function ProductGrid({ products, onOpen }: { products: Product[]; onOpen: (product: Product) => void }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-9 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {products.map((product, index) => (
        <ProductCard key={product.id} product={product} index={index} onOpen={onOpen} />
      ))}
    </div>
  )
}
