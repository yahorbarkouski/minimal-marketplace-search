import type { CSSProperties } from "react"
import type { Metadata } from "next"
import { Inter } from "next/font/google"

import { TooltipProvider } from "@/components/ui/tooltip"

import "./globals.css"

/**
 * The site's typeface, for all text and the heat-map wordmark. `block` keeps the text hidden for the moment it takes,
 * so the page never flashes a fallback face and then swaps it. The catalogue's names need the extra subsets.
 */
const inter = Inter({ subsets: ["latin", "latin-ext", "vietnamese"], variable: "--font-inter", display: "block" })

/** Set by `scripts/build_site.py` when a build is given a licensed font. Glyphs it lacks still come from Inter. */
const licensedFont = Boolean(process.env.CURATED_LICENSED_FONT)
const LICENSED_FONT_FILE = "/fonts/licensed.woff2"
const LICENSED_FONT_FACE = `@font-face {
  font-family: "Licensed";
  src: url(${LICENSED_FONT_FILE}) format("woff2");
  font-weight: 400;
  font-display: block;
}`
const siteFont = {
  "--font-site": licensedFont ? '"Licensed", var(--font-inter)' : "var(--font-inter)",
} as CSSProperties

export const metadata: Metadata = {
  title: "Curated Supply search",
  description: "Search 1,301 well-designed products by what you mean.",
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} antialiased`} style={siteFont}>
      {licensedFont ? (
        <head>
          <link rel="preload" href={LICENSED_FONT_FILE} as="font" type="font/woff2" crossOrigin="" />
          <style>{LICENSED_FONT_FACE}</style>
        </head>
      ) : null}
      <body className="min-h-dvh">
        <TooltipProvider delayDuration={150}>{children}</TooltipProvider>
      </body>
    </html>
  )
}
