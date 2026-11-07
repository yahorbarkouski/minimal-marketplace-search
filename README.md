# Minimal marketplace search

Natural-language search for a product catalogue, in about 5,000 lines of Python and a small Next.js site. A buyer types what they want in their own words, and the search returns the matching products, best first. On the example catalogue a search takes 1.7 seconds and costs about half a cent.

Minimal here means the whole system is one Python process and a set of files. The files, about 35 MB for 1,301 products, hold the catalogue and its index, and the process loads them into memory at startup. The process calls two model APIs and, on one machine, needs no other service to answer a search. It can also deploy as a single serverless function, where a small Blob store keeps the spend total its instances share.

The repository comes with an example catalogue: the 1,301 products of [curated.supply](https://www.curated.supply/browse), a directory of design products, downloaded with its owner's permission. Each of these searches on it tests something different, a price limit, an exclusion, a scene and a person's taste:

| Search | First three products |
| --- | --- |
| `espresso machine under $1000` | Terra Kaffe Demi ($795), Breville Barista Express ($700), Wacaco Minipresso GR2 ($60) |
| `slim wallet that is not leather` | Ekster Aluminum Cardholder Wallet, Ridge Gunmetal Aluminum Wallet, The James Brand The Lowe |
| `a Bond villain's desk` | Transparent Brutalist Speaker, Herman Miller Coyl Gaming Desk, Geistmaschine Bauwerk |
| `something Dieter Rams would own` | Vitsoe 606 Universal Shelving System, Braun BNE001 Calculator, Braun BC17 Wall Clock |

The models' answers vary a little, so another run can order these differently. To search a catalogue of your own, see [Use your own catalogue](#use-your-own-catalogue).

## Run it

You need [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh), and two API keys: `TYPESAFE_API_KEY` for Jev, TypeSafe's decision model, which judges each product a search finds, from [TypeSafe](https://typesafe.ai), and `OPENROUTER_API_KEY` for the Gemini and GPT-6 Luna models, from [OpenRouter](https://openrouter.ai). Copy the template and fill in both:

```bash
cp .env.example .env
```

```bash
uv sync
```

Download the example catalogue with its index already built, about 23 MB, from this repository's `data-v1` release. It needs no API key, and unpacked it takes about 35 MB. The command checks the file against `data-release.sha256` before it unpacks anything. The file holds the example catalogue's text and photos, which the MIT licence does not cover:

```bash
uv run curated download
```

Start the search server, on port 8790, and the site in two terminals:

```bash
uv run curated serve
```

```bash
cd web && bun install && bun run dev
```

To try the site with no keys, see [Development](#development). Open http://localhost:3210, or http://localhost:3210/?q=calm+bedroom to run a search from the address. On a results page, the bug button or the `d` key opens the query debug panel: each stage's timing, the count of products at each stage, how Jev read the search, and every product it judged.

Each search makes several paid model calls, $0.0049 on average on the [benchmark](#how-well-it-works) and nearly all of it Jev. Reaching the end of a long page judges one more batch, which adds about $0.0025. The spend ledger, `data/ledger.jsonl`, records every paid call, and `uv run curated spend` prints the total by purpose. Once the total reaches `CURATED_BUDGET_USD`, $10 unless you set it in `.env`, the search refuses new model calls and the page says so.

## Use your own catalogue

A catalogue is one JSON line and one photo per product. You write those, change the few sentences that describe the catalogue to the models, and build the index. Skip `curated download`, which fills `data/` with the example catalogue and refuses to replace files already there unless you pass `--force`.

**1. Write `data/products.jsonl`,** one product per line:

```json
{"product_id": "walnut-desk-lamp", "url": "https://shop.example/walnut-desk-lamp", "name": "Walnut Desk Lamp", "brand": "Acme", "brand_slug": "acme", "category": "Lighting", "category_slug": "lighting", "lists": ["Small spaces"], "articles": [], "price": 120.0, "staff_pick": false, "rank": 0, "added": "2026-01-01", "about": "A small lamp with a walnut base and a brass arm.", "designed_in": "Denmark", "specs": [{"name": "Height", "value": "40 cm"}], "alternatives": [], "photo_url": "https://shop.example/img/walnut-desk-lamp.jpg"}
```

Every field must be present: `lists`, `articles` and `alternatives` are lists of strings, `rank` is an integer, `added` is a date, and `designed_in` may be `null`. The models read `name`, `brand`, `category`, `lists` (themed collections that hold the product), `articles` (titles of articles about it), `price`, `about` (its description), `designed_in` and `specs`. `price` is in US dollars, or `null` when unknown, and a product with no price passes every price limit. The site shows the photo at `photo_url` and links to `url`; the build reads the local copy from step 2. `category_slug` only groups products when you read a sample, and the search never reads `brand_slug`, `staff_pick`, `rank`, `added` or `alternatives`, so any value of the right type works for those.

**2. Save each product's photo** as `data/photos/<product_id>.webp`, with the product id percent-encoded as Python's `urllib.parse.quote(product_id, safe='')` writes it. Any format Pillow opens works under that name, because the build converts every photo to JPEG.

**3. Describe your catalogue to the models.** Five prompts describe the example catalogue, and each needs your catalogue in its place:

| File | What to change |
| --- | --- |
| `src/curated/indexing/reading.py` | The first paragraph of `INSTRUCTIONS`, which names the catalogue and its kinds of product |
| `src/curated/indexing/taxonomy_writer.py` | The first sentence of `PROMPT` |
| `src/curated/search/interpretation.py` | The first sentence of `PROMPT`, which lists the catalogue's kinds of product |
| `src/curated/search/understanding.py` | The first sentence of `FILTER_PROMPT` |
| `src/curated/search/gate.py` | `GATE_FALSE`, the text that tells Jev when to answer no, which calls a fit generic when the product "could suit almost any tasteful home, desk or person" |

Prices are in US dollars throughout: the cards Jev reads write them with `$`, and the Gemini Flash call that reads a search's price limit expects USD. For another currency, convert prices to dollars in `products.jsonl`, or change `price_line` in `src/curated/indexing/card.py` and `FILTER_PROMPT`.

**4. Build the index.** The costs are from building the example catalogue in November 2026, about $1 per 1,000 products:

| Step | Command | What it does | Cost for 1,301 products |
| --- | --- | --- | --- |
| Sample the read | `uv run curated read --per-category 3` | GPT-6 Luna reads three products from each category. Check `data/readings.jsonl` before reading the rest: every field should describe its product truthfully. | $0.02 |
| Read | `uv run curated read` | GPT-6 Luna reads every product's text and photo and writes what it is made of, its colors and look, five searches a buyer might type, and the aesthetics, moods and settings it suits. | $0.69 |
| Taxonomy | `uv run curated taxonomy` | GPT-6 Luna writes `taxonomy/taxonomy.yaml`, the categories and facets Jev uses, from what the readings found, replacing the example's file. Run it after the full read. | $0.01 |
| Index | `uv run curated index` | Gemini embeds each product's text, style and photo, Jev tags every product with the taxonomy, and each photo is saved as the small JPEG Jev reads. | $0.61 |

Jev reports no price, so its share is computed from input tokens at $0.042 per million. `read` and `index` save each result as it arrives and stop after five failures in a row, or once the job has spent `--max-cost` ($3 by default), counting its earlier runs. Running a job again retries its failures and continues where it stopped. `index` refuses to start until every product has a reading. Restart `curated serve` to load the new index.

**5. Rename the site.** Five places in `web/` belong to the example catalogue: the page title in `web/app/layout.tsx`, the heading in `web/components/curated/search-page.tsx`, the word drawn on the start page in `web/components/curated/wordmark.tsx`, the "View on Curated Supply" link in `web/components/curated/product-dialog.tsx`, and the searches behind the dice button, which runs a random example search, in `web/components/curated/examples.ts`.

To share what you built, `uv run curated package` writes the catalogue and index as one file in `dist/` and records its checksum in `data-release.sha256`. `uv run curated download --source <url or path>` unpacks such a file elsewhere.

### Rebuild the example catalogue

`uv run curated scrape` downloads the 1,859 pages in curated.supply's sitemap and all 1,301 product photos, and a rerun fetches only what is missing. `uv run curated catalog` parses them into `data/products.jsonl`. Both are free. Then build the index as in step 4, with the prompts as they are.

## How a search works

A decision model answers yes-or-no questions with a probability, and this repository uses Jev, the decision model from [TypeSafe](https://typesafe.ai). Gemini models, reached through [OpenRouter](https://openrouter.ai), write a short interpretation of each search, read any price limit, and turn text and photos into vectors. Building the index also uses GPT-6 Luna, through OpenRouter too, which reads each product once. Every model name, count and threshold is in `src/curated/settings.py`.

That reading gives every product two texts besides its own record: a catalogue record, such as its materials and colors, and a style description, the aesthetics, moods and settings it suits. A product's card is the text Jev and the text embedding read: its record, description, specifications and the catalogue record. The taxonomy is a set of categories and facets, attributes such as a material or a color, that a model wrote for the catalogue, and Jev tags every product with it.

```text
search text
 ├─ Jev: categories, facets, kind of search, and whether it states a price limit
 ├─ Gemini embedding of the search
 ├─ Gemini Flash-Lite: the interpretation, then its Gemini embedding
 └─ Gemini Flash: the price limit, used only when Jev says one is stated
      │
      ▼
eight rankings of the products inside the price limit
  on the buyer's words:    keyword, text, photo, facets, style
  on the interpretation:   text, photo, style
      │  reciprocal rank fusion keeps the best 80; tag expansion adds up to 20
      ▼
Jev reads each of those products' text and photo: the probability p that it is a convincing answer
 ├─ p ≥ 0.35  shown, highest p first
 └─ p < 0.35  dropped
```

The four calls at the top start together. The keyword ranking is BM25 over each product's text. The text, photo and style rankings compare the search's vector with each product's vectors, and the facets ranking uses the tags Jev gave every product when the index was built. Reciprocal rank fusion merges the eight rankings by each product's positions in them, so their scores never have to be comparable. The last step is the gate. Jev answers one question about each product, written in `src/curated/search/gate.py`, and its probability decides what the page shows and in what order, after any early results. The kind of search that Jev reads at the top appears only in the debug panel.

- **The interpretation** is at most 45 words of world knowledge about the search. For `a Bond villain's desk`, it can name sleek dark objects that the words alone never reach.
- **Tag expansion** adds products outside the fused 80 whose tags match the categories and facets Jev is confident the search asks for. It covers broad searches with more matches than the rankings return.
- **Early results.** While the interpretation is on its way, Jev reads the 24 best products found by the buyer's words alone, and those at p ≥ 0.6 appear at once. They stay at the top of the page, in that order, whatever the final reading says of them.
- **More results.** When the buyer reaches the end of the page, the search ranks again with each ranking searched deeper, Jev judges the next 60 products it has not judged yet, and the search keeps adding batches while at least 2 of the last 20 judged reached the page.

## What it stores

The build reads each product's record and photo, and `curated read`, `curated taxonomy` and `curated index` write the rest. The server loads the catalogue, the taxonomy and the index into memory at startup and only reads them after that.

| Stored | Where | Holds | Size for 1,301 products |
| --- | --- | --- | --- |
| Source | `data/photos/`, and `data/raw/` for the example catalogue | Each product's photo, which the build reads, and the example catalogue's downloaded pages | 253 MB, 79 MB |
| Catalogue | `data/products.jsonl`, `data/readings.jsonl` | One record per product, and what a model read from its text and photo | 4 MB |
| Taxonomy | `taxonomy/taxonomy.yaml` | The categories and facets a model wrote for the catalogue | 32 KB |
| Search index | `data/index/` | Cards and keyword fields (JSON), text, style and photo vectors and Jev's tags (NumPy), and the small photo Jev reads for each product (JPEG) | 31 MB |
| Paid answers | `data/runs/`, `data/cache/` | Each reading and tag as it arrived, and each embedding by a hash of its input, so a rebuild pays only for what changed | 85 MB |
| Spend | `data/ledger.jsonl`, or a Vercel Blob store when deployed | Every paid call | under 1 MB |

Everything the build writes lands in `data/`, which git ignores, except `taxonomy/taxonomy.yaml`.

The server also keeps three things in memory: the BM25 keyword indexes, which it builds from the keyword fields at startup; recent interpretations, so a repeated search skips that call; and the searches a page may still ask more results of. Losing any of them costs a little time or money and no data. Vector search multiplies a matrix by the search's vector in NumPy, which takes milliseconds at this size.

The index takes about 24 KB per product, so Vercel's 500 MB function limit fits roughly 20,000 products. A larger catalogue needs a long-running server, or a vector store and an object store.

## How well it works

`benchmark/searches.jsonl` holds 40 searches on the example catalogue, written after the search's question and thresholds were fixed, and none of them was used to tune either. `benchmark/grades.jsonl` holds what two blind judges said of 644 pairs of search and product: each page's first ten, up to five more from the page, and the five products just under the 0.35 line. The judges read each product's text with no score, rank or sign of whether it was shown, and graded each pair from 0 (wrong) to 3 (exactly right). A product counts as good when its mean grade is at least 2.

| Kind of search | Searches | Good in the first 10 | Order (nDCG@10) | Good products found | Median products shown |
| --- | --- | --- | --- | --- | --- |
| All | 40 | 78% | 0.88 | 90% | 15.5 |
| Brand or name | 6 | 100% | 0.96 | 99% | 7.5 |
| Stated limit | 6 | 94% | 0.91 | 86% | 11 |
| Attributes | 7 | 88% | 0.96 | 98% | 5 |
| Appearance | 5 | 80% | 0.94 | 89% | 33 |
| Across categories | 6 | 67% | 0.80 | 81% | 37 |
| Mood | 5 | 66% | 0.80 | 85% | 42 |
| Person, film or place | 5 | 40% | 0.71 | 92% | 34 |

A search cost $0.0049 on average and $0.0056 at most. Run one at a time, a full page took 1.66 s at the median and 2.93 s at most, and on the 30 searches with an early result, the first product appeared at 0.72 s.

Read these numbers with their limits in mind:

- **Judges.** Both were Claude, given differently worded instructions. They gave the same grade on 83% of pairs and agreed on good or not on 93% (kappa 0.85), which likely overstates how far people would agree.
- **Text only.** The judges read product text and saw no photos, though the search itself reads them, so searches about looks are the least certain.
- **Found means found among the graded products.** Products Jev rated far under the line, and those the rankings never reached, were never graded, so the true share found is lower than the table says.
- **Small groups.** Each kind has 5 to 7 searches, so one search moves its row by several points. `things for a new dad` shows a single product, graded weak, and `Steve Jobs's living room` has 1 good product in its first 10.

To run the benchmark, which costs about $0.20, and then score it, which is free:

```bash
uv run curated benchmark run --name my-change
```

```bash
uv run curated benchmark score --name my-change
```

`curated benchmark pool --name my-change` lists the pairs a change has brought up that have no grade yet, and the score shows how much of each first ten was graded. To grade them, add lines to `benchmark/grades.jsonl` in the same form, `{"search", "product_id", "judge", "grade"}`, from at least two judges who can't see the scores. Tuning against these 40 searches would stop them measuring anything, so write new searches for each round of tuning.

## Known limits

- **Searches that name a person, film or place are the weakest kind**, with 40% good in the first ten, because they rest on the interpretation: only 78 of the 1,301 readings named a reference. `Wes Anderson hotel lobby` returns 4 products, and the aesthetic search `cyberpunk desk` 3, all but one at low scores. Asking the interpretation to name the brands and designers tied to a person or film was tried on 22 other test searches, which are not in the repository, with two blind judges. It changed good products in the first ten by -1 point, give or take 11 on the reference searches, so it was left out.
- **Broad searches keep long tails.** On a search many products could answer, Jev drops few: `things a design student would save up for` shows 94 of the 100 products it read, and `retro objects that still work` ends on Nike sneakers. The order keeps the weak ones at the end.
- **Jev's strict question loses some good products.** `desk lamp under $150` shows 3 products, and the Govee table lamp at $135 scores 0.30. `calm bedroom` loses the sleep mask at 0.33, and `dark academia study` loses the Lamy 2000 at 0.30.
- **An early result stays even if the final reading disagrees.** This happened to 5 of the 287 early results on the 38 searches behind the site's dice button. Four were in `round speaker that looks like sculpture`, where the interpretation made Jev's final reading more literal, so the Beosound A9 sits near the top with a score of 0.16.
- **A narrow limit returns what exists.** `espresso machine under $500` returns one espresso machine and four stovetop makers, because nearly every espresso machine in the example catalogue costs more.
- **The interpretation can time out.** Its limit is 2.5 s. It missed it on 1 of 20 searches in an earlier test run, and that page was thin; it never missed it on the 40 benchmark searches.

## The site

`web/` is a Next.js site. In development, Next.js passes `/api/*` to the search server on port 8790. Clicking a product opens its photo, style description, text and specifications.

The site uses [Inter](https://rsms.me/inter/), a free font that the build downloads through Next.js, so the build needs network access. The hosted demo uses ABC Diatype by [Dinamo](https://abcdinamo.com) under a paid web licence, and that licence forbids putting the font in a public repository. To build with a font you hold a web licence for, give the build its `.woff2` file:

```bash
CURATED_FONT_FILE=/path/to/font.woff2 uv run python scripts/build_site.py
```

The file reaches only the build's output in `public/`, which git ignores. A single Regular file serves every weight, and the browser thickens bold text.

## Deploy

The site runs as one Vercel project. FastAPI runs as a single function, `index.py`, which serves the search, an optional password page and the HTML pages. The catalogue, readings, taxonomy and index ship inside the function. Vercel's CDN serves the built JavaScript and fonts from `public/`, and product photos load from the URLs in the catalogue. To deploy, build the site, then deploy it:

```bash
uv run python scripts/build_site.py
```

```bash
vercel deploy --prod --yes
```

`.vercelignore` keeps `.env`, the downloaded pages and photos, the benchmark and `dist/` out of the upload. The project needs these environment variables:

| Variable | Holds |
| --- | --- |
| `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | The model keys |
| `SITE_PASSWORD` | The password the site asks for; without it the site is open |
| `CURATED_BUDGET_USD` | The spend cap across every instance |
| `CURATED_SPENT_BEFORE_USD` | What was spent before deploying, which counts against the cap |
| `CURATED_DAILY_BUDGET_USD` | When set, the cap is this much per UTC day, in place of the two above |
| `CURATED_SEARCHES_PER_HOUR` | When set, how many searches and further batches one visitor may ask for in an hour |
| `CURATED_LEDGER` | A writable path for each instance's ledger, such as `/tmp/ledger.jsonl` |
| `BLOB_READ_WRITE_TOKEN` | Access to the project's Vercel Blob store, which Vercel sets when you connect one |

Serverless instances share no memory or disk, so each records what it spent as a small blob in that store, and every search starts by summing them (`src/curated/shared_spend.py`). To change a cap, set the variable and redeploy:

```bash
vercel env add CURATED_BUDGET_USD production --value 10 --yes --force
```

To run the deployed app locally, password and all, build the site, then run `SITE_PASSWORD=<password> uv run curated serve --site` and open http://localhost:8790.

### In public

A public deployment spends your money on every search, so set both limits, for example `CURATED_DAILY_BUDGET_USD=5`, about 1,000 searches a day, and `CURATED_SEARCHES_PER_HOUR=30`. Leave `SITE_PASSWORD` unset so visitors need no password. Connect a Blob store: without one, each instance counts only its own spend, so several instances can each spend the whole budget.

- **The daily budget bounds the bill.** Every search checks the total across all instances first, so past the cap searches stop however many visitors or addresses there are. Searches already running when the cap is reached still finish, so the total can pass the cap by a few searches.
- **The per-visitor limit stops casual abuse.** It counts in each instance's memory, so several instances allow several times the limit, and someone with many addresses gets around it. On Vercel it reads `x-vercel-forwarded-for`, which Vercel sets itself. Elsewhere it reads the connection's address, so behind your own proxy every visitor counts as one.

Past either limit the page shows a short message. Other failures show a generic message, and the details go to the server's log.

## Design choices

- Indexing calls GPT-6 Luna once per product, and that one answer holds both the catalogue record and the style description.
- A model writes the taxonomy from the catalogue's readings, so a new catalogue needs no hand-made categories.
- Price is the only hard limit. Jev weighs everything else the buyer asks for, exclusions such as "not leather" included.
- Jev alone decides what reaches the page. An earlier version also had Gemini Flash-Lite grade the products Jev was unsure about, and dropping it cut the average search from $0.0081 to $0.0049, and the median page from 2.8 s to 1.8 s on test runs of 3 searches at a time. Jev's question became stricter to make up for it. In one blind judge's grades on 10 searches, 78% of the graded products on the new pages were good against 67% before, though the new pages found fewer good products in all, 118 against 145. Those 10 searches shaped the question, so the comparison flatters it.
- Jev reads each product's photo at 280 pixels on its short side, sent with TypeSafe's experimental `TypeSafe-Danger-Zone-Images` header. A Jev call that fails counts its products as not matching, so one failure costs only those products.

## Development

```bash
uv run pytest
```

The tests run the query path, the server, the limits and the data download on stand-ins for Jev and OpenRouter, so they spend nothing and need no keys or data. `.github/workflows/ci.yml` runs them on every push to `main` and every pull request, with the same checks you can run by hand: `uv run ruff format --check`, `uv run ruff check` and `uv run pyright`, and in `web/`, `bun x next typegen`, then `bun x tsc --noEmit` and `bun run lint`.

To try the site with no keys, run `curated scrape` and `curated catalog`, then the command below in place of `curated serve`, and start `web/` as usual. It builds an index over the example catalogue in the folder that `CURATED_STUB_ROOT` names, with a small placeholder taxonomy, and serves it on port 8790. The stand-ins rank by word overlap, so this run shows that the site works and says nothing about search quality.

```bash
CURATED_STUB_ROOT=/tmp/curated-stub uv run python -m tests.stubbed_index
```

| Path | Holds |
| --- | --- |
| `src/curated/scrape.py`, `catalog.py` | The example catalogue's download and the parser of its pages |
| `src/curated/indexing/` | The product reading, taxonomy writer, cards, embeddings, Jev's tags and the index build |
| `src/curated/search/` | The query path: `searcher.py` runs it, and understanding, interpretation, the rankings (`arms.py`), fusion, expansion and the gate each have a module |
| `src/curated/server.py`, `debug_view.py`, `limits.py` | The HTTP API, the debug panel's account of a search, and the per-visitor limit |
| `src/curated/ledger.py`, `shared_spend.py` | The spend ledger and its budgets, and the total that Vercel instances share |
| `src/curated/benchmark.py`, `benchmark/` | The benchmark's commands, searches and grades |
| `src/curated/data_release.py` | `curated package` and `curated download` |
| `src/curated/settings.py` | Every model name, count and threshold |
| `index.py`, `src/curated/deployment.py`, `src/curated/gate.py` | What Vercel runs: the app and the password page, which is unrelated to the search's gate in `src/curated/search/gate.py` |
| `web/components/curated/` | The search page, cards, product dialog and debug panel |
| `tests/` | The tests, the stand-ins and the stubbed index |

## Licence

The code is under the [MIT licence](LICENSE). The licence does not cover the products, text and photos of the example catalogue, which belong to their owners, or any font you add at build time. `web/components/heat/heat-map.tsx` is adapted from Bencho's Heat map, under the MIT licence beside it.
