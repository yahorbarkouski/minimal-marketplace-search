"use client"

/* From Bencho's "Heat map" (MIT, Copyright (c) 2026 Lorenzo Cabra; see LICENSE here), adapted: the word and the canvas size are props, and the
   face is the site's own. */

import { useEffect, useRef, useState } from "react"

/* ══ Heat word ════════════════════════════════════════════
   A big word in flat, dull grey — until the hand comes. Around
   the cursor the word turns into a heat map of its own shape:
   deep navy in the middle of every stroke, through blue, cyan,
   yellow, orange and red, to a pink rim. Right under the pointer
   the heat opens up and the strokes thin, like something melting;
   leave and it fades back to grey. Press it and the next shape
   melts in.

   ── A FIELD, THEN A PALETTE ─────────────────────────────
   The word is drawn once, blurred, into a grey field: bright in
   the thick of a stroke, fading at its edge. The cursor adds a
   soft round of heat to that field. Every pixel's brightness is
   then looked up in a 256-entry table of colours. Two strokes
   close together overlap in the field, so they fuse where the
   heat pools — that is the liquid, and nothing animates it but
   the field.

   ── THE BLUR IS A SHADOW ────────────────────────────────
   ctx.filter is not in every Safari, shadowBlur is. The word is
   drawn far off the canvas with its shadow thrown back on, so
   only the blurred shadow lands. */

const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))

/* the word is the site's own face at its bold, so it
   is already on the page and never fetched. next/font names the
   family, so it is read from the variable the layout sets */
const FACE = { variable: "--font-site", weight: 700 }

function faceFamily(): string {
  const declared = getComputedStyle(document.documentElement).getPropertyValue(FACE.variable).trim()
  return declared || "system-ui, sans-serif"
}

/* ── or a shape, instead of a word ─────────────────────────
   The heat reads any shape, and the ones that look most liquid
   are where strokes meet or nearly touch: bars crossing at a
   centre, dots close enough to run together. Each takes a seed,
   so a press deals a new arrangement of the same kind. */
export const SHAPES = ["Dots", "Asterisk", "Word"] as const
export type Shape = (typeof SHAPES)[number]

function rng(seed: number) {
  let t = seed * 9301 + 49297
  return () => {
    t = (t * 9301 + 49297) % 233280
    return t / 233280
  }
}

/* a thick line through a list of points */
function line(g: CanvasRenderingContext2D, pts: [number, number][]) {
  g.beginPath()
  pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)))
  g.stroke()
}

/* where the hand is, in the field's pixels, and how present it is */
type Hand = { x: number; y: number; on: number; area: number }

function drawShape(
  g: CanvasRenderingContext2D,
  shape: Shape,
  w: number,
  h: number,
  r: number,
  seed: number,
  hand?: Hand,
) {
  const rand = rng(seed)
  const cx = w / 2,
    cy = h / 2
  g.lineCap = "round"
  g.lineJoin = "round"
  if (shape === "Dots") {
    /* a loose grid, near enough that neighbours run together. The
       dots under the hand swell, on a gaussian, so the ones nearest
       grow into each other and fuse while the far ones keep their
       size — and the rand() calls stay in the same order, so the
       arrangement never shifts while they do */
    const cols = 7,
      rows = 3
    const reach = 62 * r * (hand?.area ?? 1)
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const x = cx + (i - (cols - 1) / 2) * 38 * r + (rand() - 0.5) * 8 * r
        const y = cy + (j - (rows - 1) / 2) * 38 * r + (rand() - 0.5) * 8 * r
        let rad = (9 + rand() * 7) * r
        if (hand && hand.on > 0.002) {
          const d2 = ((x - hand.x) ** 2 + (y - hand.y) ** 2) / (reach * reach)
          rad *= 1 + 0.75 * hand.on * Math.exp(-d2)
        }
        g.beginPath()
        g.arc(x, y, rad, 0, Math.PI * 2)
        g.fill()
      }
    }
  } else if (shape === "Asterisk") {
    /* fat bars crossing, every one of them through the centre */
    g.lineWidth = 16 * r
    const n = 3 + Math.floor(rand() * 2),
      turn = rand() * Math.PI
    for (let i = 0; i < n; i++) {
      const a = turn + (i / n) * Math.PI
      const c = Math.cos(a) * 66 * r,
        sn = Math.sin(a) * 66 * r
      line(g, [
        [cx - c, cy - sn],
        [cx + c, cy + sn],
      ])
    }
  }
}

/* the face is on the page already, but may not have arrived by
   the first frame — waited for, or the first word is the fallback */
async function ensure() {
  try {
    await document.fonts?.load(`${FACE.weight} 100px ${faceFamily()}`)
  } catch {
    /* drawn in the fallback, which is still a word */
  }
}

/* the palettes, rim (0) to core (1); below the floor it is the card.
   Neon is the heat camera: a pink rim through red, yellow and
   cyan to a navy core. The others keep its shape — a light rim, a
   dark core, a bright band between — in other colours. */
type Stops = [number, [number, number, number]][]
export const PALETTES: Record<string, Stops> = {
  Neon: [
    [0.0, [255, 150, 225]],
    [0.1, [255, 90, 190]],
    [0.2, [255, 50, 60]],
    [0.32, [255, 150, 40]],
    [0.42, [255, 228, 100]],
    [0.54, [120, 215, 255]],
    [0.68, [40, 120, 245]],
    [0.84, [12, 44, 150]],
    [1.0, [6, 18, 80]],
  ],
  Fire: [
    [0.0, [255, 238, 180]],
    [0.16, [255, 200, 80]],
    [0.34, [255, 130, 30]],
    [0.52, [228, 58, 28]],
    [0.72, [150, 18, 44]],
    [0.88, [74, 6, 42]],
    [1.0, [30, 2, 24]],
  ],
  Sea: [
    [0.0, [210, 255, 225]],
    [0.16, [110, 245, 175]],
    [0.34, [40, 215, 200]],
    [0.52, [40, 150, 235]],
    [0.72, [80, 70, 205]],
    [0.88, [60, 20, 130]],
    [1.0, [24, 8, 60]],
  ],
  Pop: [
    [0.0, [255, 225, 240]],
    [0.16, [255, 160, 210]],
    [0.34, [245, 110, 190]],
    [0.52, [180, 110, 255]],
    [0.72, [100, 150, 255]],
    [0.88, [40, 70, 190]],
    [1.0, [20, 24, 100]],
  ],
}
const FLOOR = 34

function table(STOPS: Stops) {
  const t = new Uint8ClampedArray(256 * 4)
  for (let i = 0; i < 256; i++) {
    if (i < FLOOR) {
      /* under the floor: nothing, so the card shows through */
      t[i * 4 + 3] = 0
      continue
    }
    const u = (i - FLOOR) / (255 - FLOOR)
    let k = 0
    while (k < STOPS.length - 2 && u > STOPS[k + 1][0]) k++
    const [u0, c0] = STOPS[k]
    const [u1, c1] = STOPS[k + 1]
    const f = clamp((u - u0) / (u1 - u0), 0, 1)
    for (let c = 0; c < 3; c++) t[i * 4 + c] = c0[c] + (c1[c] - c0[c]) * f
    /* the rim fades in over the first stretch, so the pink is a
       glow at the edge rather than a hard line */
    t[i * 4 + 3] = 255 * clamp((i - FLOOR) / 26, 0, 1)
  }
  return t
}
/* one table per palette, made the first time it is asked for */
const LUTS = new Map<string, Uint8ClampedArray>()
function lut(name: string) {
  let t = LUTS.get(name)
  if (!t) {
    t = table(PALETTES[name] ?? PALETTES.Neon)
    LUTS.set(name, t)
  }
  return t
}

/* ── and at rest, just grey ────────────────────────────────
   The word sits on the card as a flat, dull grey — solid where
   the heat would be, soft at the edge — and the heat map is only
   ever shown where the hand is. GREY_A is the grey's alpha per
   brightness: the letter's body at full, a short soft edge. */
const GREY = [150, 150, 154]
const GREY_A = new Uint8ClampedArray(256)
for (let i = 0; i < 256; i++) GREY_A[i] = 255 * clamp((i - 70) / 45, 0, 1)

export function HeatMap({
  /* the word drawn when the shape is "Word" */
  word = "BEND",
  /* the canvas, in CSS pixels; the shapes are laid out for 360 by 170 and scale with it */
  width = 360,
  height = 170,
  /* how much heat the cursor brings, 0..100 */
  heat = 60,
  /* how soft the letters are, 0..100 */
  soft = 50,
  /* how big the patch under the hand is, 0..100 */
  area = 50,
  /* which heat map the hand reveals */
  colors = "Neon",
  /* the shape it starts on; a press steps to the next of `cycle` */
  shape: start = "Dots",
  /* the shapes a press steps through; one shape means a press deals it afresh */
  cycle = SHAPES,
  /* what a press does instead, when the map is a link or a button of the page's */
  onPress,
  /* keeps the heat moving on its own while no hand is over it, as a
     loader would; off for anyone who asks for reduced motion */
  idle = false,
  label,
}: {
  word?: string
  width?: number
  height?: number
  heat?: number
  soft?: number
  area?: number
  colors?: string
  shape?: Shape
  cycle?: readonly Shape[]
  onPress?: () => void
  idle?: boolean
  label?: string
} = {}) {
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1000))
  const [shape, setShape] = useState<Shape>(start)
  /* the knob moving is a new start, whatever the presses did */
  const [lastStart, setLastStart] = useState(start)
  if (lastStart !== start) {
    setLastStart(start)
    setShape(start)
  }
  const shown = useRef<HTMLCanvasElement>(null)
  const st = useRef({
    base: null as HTMLCanvasElement | null,
    work: null as HTMLCanvasElement | null,
    px: 0.5,
    py: 0.5,
    tx: 0.5,
    ty: 0.5,
    power: 0,
    want: 0,
    grow: 0,
    raf: 0,
    ratio: 1,
    /* a hand is over it, so the idle path stands aside */
    hand: false,
    /* the dots were last drawn swollen, and owe one redraw at rest */
    swollen: false,
  })
  const knobs = useRef({ heat, soft, area, colors, idle })
  useEffect(() => {
    knobs.current = { heat, soft, area, colors, idle }
  })
  /* Area as a multiplier on every radius the hand has: half at 0,
     as it was at 50, half again at 100 */
  const spread = () => 0.5 + clamp(knobs.current.area, 0, 100) / 100
  /* the blur and the heat were tuned on a 360 by 170 canvas; a
     smaller one shrinks them with it, or a header-sized word would
     blur into a bar and the heat would cover all of it at once */
  const zoom = Math.min(1, width / 360, height / 170)

  /* the field itself, into the base at its current size — once per
     build for a word, and every frame the hand moves for the dots,
     which change size under it */
  const field = () => {
    const s = st.current
    const base = s.base!
    const r = s.ratio
    const w = base.width,
      h = base.height
    const g = base.getContext("2d")!
    g.setTransform(1, 0, 0, 1, 0, 0)
    g.shadowColor = "transparent"
    g.fillStyle = "#000"
    g.fillRect(0, 0, w, h)
    const blur = (6 + (clamp(knobs.current.soft, 0, 100) / 100) * 16) * r * zoom
    const off = w * 3
    g.shadowColor = "#fff"
    g.shadowBlur = blur
    g.shadowOffsetX = off
    g.fillStyle = "#fff"
    g.strokeStyle = "#fff"
    if (shape !== "Word") {
      /* drawn off the canvas so only the blurred shadow lands */
      g.save()
      g.translate(-off, 0)
      const hand = { x: s.px * w, y: s.py * h, on: s.power, area: spread() }
      drawShape(g, shape, w, h, r, seed, hand)
      drawShape(g, shape, w, h, r, seed, hand)
      g.restore()
      return
    }
    /* as large as fits */
    let size = 150 * r * (h / Math.round(170 * r) || 1)
    const f = faceFamily()
    g.font = `${FACE.weight} ${size}px ${f}`
    const fit = (w * 0.88) / g.measureText(word).width
    size = Math.min(size, size * fit)
    g.font = `${FACE.weight} ${size}px ${f}`
    g.textAlign = "center"
    g.textBaseline = "middle"
    /* twice over, so the thick of a stroke saturates */
    g.fillText(word, w / 2 - off, h / 2 + size * 0.04)
    g.fillText(word, w / 2 - off, h / 2 + size * 0.04)
  }

  /* the word, blurred, into the base field — redrawn when the
     word or the softness changes */
  const build = () => {
    const s = st.current
    const r = Math.min(2, window.devicePixelRatio || 1)
    s.ratio = r
    const w = Math.round(width * r),
      h = Math.round(height * r)
    const base = s.base ?? document.createElement("canvas")
    base.width = w
    base.height = h
    s.base = base
    if (!s.work) s.work = document.createElement("canvas")
    s.work.width = w
    s.work.height = h
    const c = shown.current!
    c.width = w
    c.height = h
    field()
  }

  /* one frame: base, plus heat at the cursor, through the palette */
  const paint = () => {
    const s = st.current
    const c = shown.current
    if (!c || !s.base || !s.work) return
    const w = c.width,
      h = c.height
    /* the dots follow the hand, so their field is redrawn with it */
    if (shape === "Dots" && (s.power > 0.002 || s.swollen)) {
      field()
      s.swollen = s.power > 0.002
    }
    const g = s.work.getContext("2d", { willReadFrequently: true })!
    g.globalCompositeOperation = "source-over"
    g.globalAlpha = 1
    g.fillStyle = "#000"
    g.fillRect(0, 0, w, h)
    /* the shape grows in from nothing when it changes */
    g.globalAlpha = s.grow
    g.drawImage(s.base, 0, 0)
    g.globalAlpha = 1
    if (s.power > 0.002) {
      const cx = s.px * w,
        cy = s.py * h
      const rad = (60 + (knobs.current.heat / 100) * 50) * s.ratio * spread() * zoom
      const amt = s.power * (0.35 + (knobs.current.heat / 100) * 0.55)
      /* the cursor COOLS the field: a multiply that dims it toward
         the middle of the pointer, so the navy cores open up into
         rings of blue, cyan, yellow and red and the strokes thin
         there — the letters melting under the hand */
      g.globalCompositeOperation = "multiply"
      const cool = g.createRadialGradient(cx, cy, 0, cx, cy, rad)
      const v = (k: number) => Math.round(255 * (1 - amt * k))
      cool.addColorStop(0, `rgb(${v(1)},${v(1)},${v(1)})`)
      cool.addColorStop(0.45, `rgb(${v(0.6)},${v(0.6)},${v(0.6)})`)
      cool.addColorStop(1, "rgb(255,255,255)")
      g.fillStyle = cool
      g.fillRect(0, 0, w, h)
    }
    const src = g.getImageData(0, 0, w, h).data
    const LUT = lut(knobs.current.colors)
    const out = c.getContext("2d")!.createImageData(w, h)
    const d = out.data
    /* the reveal: how much heat map each pixel shows, a soft disc
       around the cursor scaled by how present the hand is. Outside
       it the word is grey. */
    const cx = s.px * w,
      cy = s.py * h
    const R = (95 + (knobs.current.heat / 100) * 55) * s.ratio * spread() * zoom
    const R2 = R * R
    const on = s.power
    for (let y = 0, i = 0; y < h; y++) {
      const dy2 = (y - cy) * (y - cy)
      for (let x = 0; x < w; x++, i += 4) {
        const f = src[i]
        const v = f * 4
        let m = 0
        if (on > 0.002) {
          const q = ((x - cx) * (x - cx) + dy2) / R2
          if (q < 1) {
            const t = 1 - q
            m = on * t * t * (3 - 2 * t)
          }
        }
        const ga = GREY_A[f]
        if (m <= 0) {
          d[i] = GREY[0]
          d[i + 1] = GREY[1]
          d[i + 2] = GREY[2]
          d[i + 3] = ga
          continue
        }
        const k = 1 - m
        d[i] = GREY[0] * k + LUT[v] * m
        d[i + 1] = GREY[1] * k + LUT[v + 1] * m
        d[i + 2] = GREY[2] * k + LUT[v + 2] * m
        d[i + 3] = ga * k + LUT[v + 3] * m
      }
    }
    c.getContext("2d")!.putImageData(out, 0, 0)
  }

  /* idle, the heat wanders by itself on a slow figure. The
     hand, when it comes, takes over; when it leaves, the heat
     eases back onto the path */
  const wandering = () =>
    knobs.current.idle && !st.current.hand && !matchMedia("(prefers-reduced-motion: reduce)").matches
  const wander = (t: number) => {
    const s = st.current
    if (shape === "Word") {
      s.tx = 0.5 + 0.4 * Math.sin(t * 1.6)
      s.ty = 0.5 + 0.12 * Math.sin(t * 2.9)
    } else {
      s.tx = 0.5 + 0.3 * Math.sin(t * 1.1)
      s.ty = 0.5 + 0.22 * Math.sin(t * 1.7)
    }
    s.want = 1
  }

  /* the loop runs only while something is moving — or forever, idle */
  const run = () => {
    const s = st.current
    if (s.raf) return
    let prev = performance.now()
    const step = (t: number) => {
      const dt = Math.min(0.05, (t - prev) / 1000)
      prev = t
      const idling = wandering()
      if (idling) wander(t / 1000)
      else if (!s.hand) s.want = 0
      const k = 1 - Math.pow(0.002, dt)
      s.px += (s.tx - s.px) * k
      s.py += (s.ty - s.py) * k
      s.power += (s.want - s.power) * (1 - Math.pow(0.01, dt))
      s.grow = Math.min(1, s.grow + dt / 0.9)
      paint()
      const still =
        !idling &&
        s.grow >= 1 &&
        Math.abs(s.want - s.power) < 0.004 &&
        Math.abs(s.tx - s.px) < 0.001 &&
        Math.abs(s.ty - s.py) < 0.001
      if (still && s.want === 0) s.power = 0
      s.raf = still ? 0 : requestAnimationFrame(step)
      if (still) paint()
    }
    s.raf = requestAnimationFrame(step)
  }

  useEffect(() => {
    const s = st.current
    const go = () => {
      build()
      s.grow = 0
      run()
    }
    /* the face first, or the first word is drawn in the fallback */
    let live = true
    ensure().then(() => {
      if (live) go()
    })
    return () => {
      live = false
      cancelAnimationFrame(s.raf)
      s.raf = 0
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, seed, word, width, height])

  /* idle switching on starts the loop; switching off, the loop
     sees it and lets the heat fade */
  useEffect(() => {
    if (idle && st.current.base) run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idle])

  /* softness redraws the field without replaying the melt-in */
  useEffect(() => {
    if (!st.current.base) return
    build()
    paint()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soft])

  const aim = (e: React.PointerEvent) => {
    const r = e.currentTarget.getBoundingClientRect()
    const s = st.current
    s.tx = (e.clientX - r.left) / r.width
    s.ty = (e.clientY - r.top) / r.height
  }

  const name = label ?? (shape === "Word" ? word : shape)
  return (
    <div
      className="heat"
      style={{ width, aspectRatio: `${width} / ${height}` }}
      onPointerEnter={(e) => {
        const s = st.current
        /* idle, the heat is already somewhere: it slides to the hand */
        const jump = s.power < 0.05
        s.hand = true
        aim(e)
        if (jump) {
          s.px = s.tx
          s.py = s.ty
        }
        s.want = 1
        run()
      }}
      onPointerMove={(e) => {
        st.current.hand = true
        aim(e)
        st.current.want = 1
        run()
      }}
      onPointerLeave={() => {
        st.current.hand = false
        run()
      }}
      onClick={() => {
        if (onPress) return onPress()
        /* the next shape round, the dots and the asterisk
           dealt a fresh arrangement as they come back */
        const i = cycle.indexOf(shape)
        setSeed((n) => n + 1)
        setShape(cycle[(i + 1) % cycle.length])
      }}
      onKeyDown={(e) => {
        /* a button, so Enter and Space press it too */
        if (e.key !== "Enter" && e.key !== " ") return
        e.preventDefault()
        e.currentTarget.click()
      }}
      role="button"
      tabIndex={0}
      aria-label={onPress ? name : `${name}. Press for the next shape`}
    >
      <canvas ref={shown} className="heat-canvas" aria-hidden="true" />
    </div>
  )
}
