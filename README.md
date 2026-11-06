# Curated Supply search

Natural-language search over the 1,301 products of [curated.supply](https://www.curated.supply/browse). A buyer types what they want in their own words, such as `quiet luxury desk setup`, `espresso machine under $500` or `a Bond villain's desk`, and the site returns the matching products in one list, the strongest first. Each one links to its page on curated.supply.

Jev, the decision model from TypeSafe, answers the yes-or-no questions, reading each candidate's text and photo. Gemini writes each search's interpretation, reads any price limit, and provides the embeddings. The owner of curated.supply has allowed the full download.

**State on 2026-11-06:** all 1,301 products are indexed and the search runs on the real models, deployed at https://curated-supply-search.vercel.app behind a password. See [Benchmark](#benchmark) for how well it works.

## Run it

You need [uv](https://docs.astral.sh/uv/) and [bun](https://bun.sh). The project needs two keys: `TYPESAFE_API_KEY` for Jev, and `OPENROUTER_API_KEY` for everything else (GPT-6 Luna and all of Gemini go through OpenRouter). Copy the template and fill in both:

```bash
cp .env.example .env
```

```bash
uv sync
```

The quickest way to run the search is to download the built catalogue and index, about 23 MB, which needs no scrape and no paid build. The file is checked against `data-release.sha256` before anything is unpacked:

```bash
uv run curated download
```

Then skip to the two commands that start the search. The file holds text and photos from curated.supply, which the MIT licence does not cover. Searches still need both keys.

To build everything yourself, for example for a catalogue of your own, build the data in this order. Everything lands in `data/`, which is not meant for version control, except the taxonomy, which lands in `taxonomy/`.

| Step | Command | What it does | Cost |
| --- | --- | --- | --- |
| Download | `uv run curated scrape` | Fetches the 1,859 pages in the sitemap and all 1,301 product photos. A rerun fetches only what is missing. | Free |
| Parse | `uv run curated catalog` | Writes `data/products.jsonl`, one record per product. | Free |
| Sample the read | `uv run curated read --per-category 3` | GPT-6 Luna reads three products from each of the site's 12 categories. Look through `data/readings.jsonl`: every field should describe the product truthfully. | $0.02 |
| Read | `uv run curated read` | GPT-6 Luna reads the remaining products' text and photos and writes what each is made of, its colors and look, five searches a buyer might type, and its style: the aesthetics, moods and settings it suits. | $0.69 |
| Taxonomy | `uv run curated taxonomy` | GPT-6 Luna writes `taxonomy/taxonomy.yaml`, the categories and facets Jev uses, from what the readings found. | $0.01 |
| Index | `uv run curated index` | Gemini embeds each product's text, style and photo, Jev tags every product with the taxonomy from its text, and each photo is saved as the JPEG the search shows Jev. | $0.61 |

`curated package` writes what you have built as one file to publish, and records its checksum. These are the measured costs of the build on 2026-11-04; Jev reports no price, so its share is computed from input tokens at $0.042 per million. Run the taxonomy after the full read, because it is written from whichever readings exist.

`read` and `index` save each result as it arrives and stop after five failures in a row. They also stop once the job has spent `--max-cost` (default $3), counting its earlier runs, so pass a higher value if a job stops there. Running a job again retries its failures and continues, so run `read` again if its last line counts fewer than 1,301 readings; `index` refuses to start until every product has one. The spend ledger, `data/ledger.jsonl`, counts every paid call, and `uv run curated spend` prints its total. It refuses new model calls once the total reaches `CURATED_BUDGET_USD` (default $10, which you can set in `.env`); from then on a search shows that error on the page.

`curated serve` loads the catalogue, the readings, the taxonomy and the index at startup and fails without them. To use the search, run these two commands in separate terminals:

```bash
uv run curated serve
```

```bash
cd web && bun install && bun run dev
```

Open http://localhost:3210, or http://localhost:3210/?q=calm+bedroom to run a search from the address. Every search makes several paid model calls: $0.0049 on average over the 38 dice searches, nearly all of it Jev's gate. A page that gates all 100 products comes to about $0.006. Reaching the end of a long page judges one more batch, which adds about $0.0025. Run 3 at a time, a page took 1.8 s at the median and 3.2 s at most, the slowest being searches with a price limit. On the 28 searches with an early product, it appeared at 0.8 s at the median.

To judge quality, see [Benchmark](#benchmark).

## How a search works

```text
search text
 ├─ Jev: categories, facets, query type, and whether it states a price limit
 ├─ Gemini embedding of the search
 ├─ Gemini Flash-Lite: the interpretation, then its Gemini embedding
 └─ Gemini Flash: the price limit, used only when Jev says one is stated
      │
      ▼
eight rankings inside the price limit
  on the buyer's words:    keyword, text, photo, facets, style
  on the interpretation:   text, photo, style
      │  reciprocal rank fusion keeps the top 80; tag expansion adds up to 20
      ▼
Jev gate, reading each product's card and photo: the probability p that it is a convincing answer
 ├─ p ≥ 0.35  shown, the highest first
 └─ p < 0.35  dropped
```

- **The interpretation** is at most 45 words of world knowledge. For `a Bond villain's desk`, it can name sleek dark objects that the words alone never reach.
- **Query type** is Jev's label for the kind of search, such as a brand name or a mood. Only the debug panel reads it.
- **Tag expansion** adds products outside the top 100 whose Jev tags match the search's confident categories and facets, which covers broad searches with many matches.
- **Early results:** while the interpretation is on its way, the gate reads the 24 best-fused products on the buyer's words alone, and those at p ≥ 0.6 appear at once. They stay at the top of the page, in that order, whatever the final gate says of them.
- **Further batches:** when the buyer reaches the end of the page, the search judges the next 60 products with the same question and line, for as long as at least 2 of the last 20 it judged were shown. Each batch adds its products after the page, the highest first.

Jev alone decides the page. An earlier version sent the products Jev was unsure about to Gemini Flash-Lite for a grade, and removing it cut the average search from $0.0081 to $0.0049 and the median page from 2.8 s to 1.8 s. The question in `src/curated/search/gate.py` is stricter to make up for it. Against one blind judge's grades on 10 searches, 78% of the graded products on the new pages were good, where the review's pages scored 67%, and they found fewer good products in all: 118 against 145. The question was written after seeing those 10 searches, so these numbers flatter it. The counts in `src/curated/settings.py` are set to keep a search under a cent.

## Benchmark

`benchmark/searches.jsonl` holds 40 searches, written after the search's question and thresholds were fixed, and used to tune neither. `benchmark/grades.jsonl` holds what two blind judges said of 644 pairs of search and product: each page's first ten, up to five more from the page, and the five products just under its line. The judges read the product's text with no score, rank or sign of whether it was shown, and graded each pair from 0 (wrong) to 3 (exactly right). A product counts as good when its mean grade is at least 2.

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

A search cost $0.0049 on average and $0.0056 at most. Run one at a time, a full page took 1.66 s at the median and 2.93 s at most, and on the 30 searches with an early product, the first appeared at 0.72 s.

Read these numbers with their limits in mind:

- **Judges:** both were the same language model given differently worded instructions, not people. They gave the same grade on 83% of pairs and agreed on good or not on 93% (kappa 0.85), which likely overstates how far people would agree.
- **Text only:** the judges read product text and saw no photos, though the search itself reads them. Searches about looks are the least certain.
- **Found means found among the graded products.** Products the gate rated far under the line, and those the rankings never reached, were not graded, so the true share found is lower than the table says.
- **Small groups:** each kind has 5 to 7 searches, so one search moves its row by several points. `things for a new dad` shows a single product and it was graded weak; `Steve Jobs's living room` has 1 good product in its first 10.

To run it, which costs about $0.20, and then score it, which is free:

```bash
uv run curated benchmark run --name my-change
```

```bash
uv run curated benchmark score --name my-change
```

`curated benchmark pool --name my-change` lists the pairs a change has brought up that have no grade yet, and the score shows how much of each first ten was graded. Compare runs with care: tuning against these searches would make them stop measuring anything, so add new searches for each round of tuning.

## Known limits


- **Broad searches keep long tails.** On a search many products could answer, the gate cuts little: `things a design student would save up for` shows 94 of the 100 products it read, and `retro objects that still work` ends on Nike sneakers. The sort keeps the weak ones at the end.
- **The strict question loses some good products.** `desk lamp under $150` shows 3 products, and the Govee table lamp at $135 scores 0.30. `calm bedroom` loses the sleep mask at 0.33, and `dark academia study` loses the Lamy 2000 at 0.30.
- **An early product stays even if the final gate disagrees.** This happened to 5 of the 287 early products on the 38 dice searches. Four were in `round speaker that looks like sculpture`, where the interpretation made the final gate more literal, so the Beosound A9 sits near the top with a score of 0.16.
- **Searches that name a person, film or aesthetic are the weakest kind**, with 40% good in the first ten on the benchmark, because they rest on the interpretation alone: only 78 of the 1,301 readings named a reference. `cyberpunk desk` returns 3 products and `Wes Anderson hotel lobby` 4, all but one at low scores.
- **A narrow limit returns what exists.** `espresso machine under $500` returns one espresso machine and four stovetop makers, because nearly every espresso machine here costs more.
- **The interpretation can lapse.** It has a 2.5 s timeout. It missed it on 1 of 20 searches in an earlier run, and that page was thin. It did not miss it on the 38 dice searches.

## Where things are stored

There is no database. Everything a search reads is a file built once by `curated read`, `taxonomy` and `index`, loaded into memory when the server starts, and read-only after that.

| Stored | Where | Holds | Size |
| --- | --- | --- | --- |
| Source | `data/raw/`, `data/photos/` | Every page of the site, gzipped, and each product's photo | 79 MB, 253 MB |
| Catalogue | `data/products.jsonl`, `data/readings.jsonl` | One record per product from the site, and one from the model reading | 4 MB |
| Paid answers | `data/runs/`, `data/cache/` | Each reading and tag as it arrived, and each embedding by a hash of its input, so a rebuild pays only for what changed | 85 MB |
| Taxonomy | `taxonomy/taxonomy.yaml` | The categories and facets a model wrote | 32 KB |
| Search index | `data/index/` | Cards and keyword fields (JSON), text, style and photo vectors and Jev's tags (NumPy), and each product's gate photo (JPEG) | 31 MB |
| Spend | `data/ledger.jsonl`, or Blob on Vercel | Every paid call locally; one small blob per search on Vercel, because instances share no disk | under 1 MB |

The server keeps three things in memory only: the BM25 keyword indexes, which it builds from the keyword fields at startup, recent interpretations, and the searches a page may still ask more of. Losing them costs a little time or money and no data. Only `data/index/`, the catalogue and the taxonomy reach Vercel, where they ship inside the function; product photos on the site load from curated.supply's CDN. Vector search multiplies a matrix by the query, which takes milliseconds at this size.

The index takes about 24 KB per product, so Vercel's 500 MB function limit allows roughly 20,000 products. A larger catalogue needs a long-running server, or a vector store and an object store.

## Design choices

- One model reading per product writes both the catalogue record and the style description.
- A model writes the taxonomy from this catalogue's readings. Rerun `curated taxonomy` for a new catalogue.
- The only hard limit is price.
- Jev alone decides what reaches the page.
- Jev's gate also reads each product's photo, at 280 pixels on its short side, sent with TypeSafe's experimental `TypeSafe-Danger-Zone-Images` header. A gate call that fails counts its products as not matching, so one failure costs only those products.
- A product's card, the text that Jev and the text embedding read, carries the editor's text, the specifications and the names of the editor's themed lists. Each product has one photo.

## The site

`web/` is a Next.js site. Next.js rewrites `/api/*` to the search server on port 8790. Clicking a product opens its photo, style description, editorial text and specifications. The bug button or the `d` key opens the query debug panel: each stage's timing, the funnel from the catalogue to the page, how Jev read the search, and every product it judged.

The site uses [Inter](https://rsms.me/inter/), a free font that the build downloads through Next.js, so the build needs network access. The hosted demo uses ABC Diatype by [Dinamo](https://abcdinamo.com), under a paid web licence. Diatype's licence forbids putting it in a public repository, so its file is not here. To build with a font you hold a web licence for, give the build its `.woff2` file:

```bash
CURATED_FONT_FILE=/path/to/font.woff2 uv run python scripts/build_site.py
```

The file reaches only the build's output in `public/`, which git ignores. One Regular file serves every weight: the browser thickens bold text, and medium text stays Regular.

## Deploy

The site runs as one Vercel project. FastAPI runs as a single function (`index.py`) that serves the search, the password gate and the HTML pages; Vercel's CDN serves the built JavaScript and fonts from `public/`, and product photos load from curated.supply's own CDN. To deploy a change, build the site, then deploy:

```bash
CURATED_FONT_FILE=/path/to/ABCDiatype-Regular.woff2 uv run python scripts/build_site.py
```

```bash
vercel deploy --prod --yes
```

`.vercelignore` keeps `.env`, the raw pages and the downloaded photos out of the upload. The project holds these environment variables:

| Variable | Holds |
| --- | --- |
| `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | The model keys |
| `SITE_PASSWORD` | The password the gate asks for; without it the site is open |
| `CURATED_BUDGET_USD` | The spend cap across every instance |
| `CURATED_SPENT_BEFORE_USD` | What had been spent before deploying, which counts against the cap |
| `CURATED_DAILY_BUDGET_USD` | When set, the cap is this much per UTC day, in place of the two above |
| `CURATED_SEARCHES_PER_HOUR` | When set, how many searches and further batches one visitor may ask for in an hour |
| `CURATED_LEDGER` | A writable path for the instance's ledger, `/tmp/ledger.jsonl` |
| `BLOB_READ_WRITE_TOKEN` | Access to the Blob store `curated-supply-spend`, set by Vercel |

Serverless instances share no memory or disk, so each one records what it spent as a small blob in that store, and every search starts by summing them (`src/curated/shared_spend.py`). Past the cap, a search shows the budget error on the page. To raise the cap, change the variable and redeploy:

```bash
vercel env add CURATED_BUDGET_USD production --value 10 --yes --force
```

To run the deployed app locally, gate and all, run `uv run python scripts/build_site.py`, then `SITE_PASSWORD=<password> uv run curated serve --site`, and open http://localhost:8790.

## Tests

```bash
uv run pytest
```

The tests run the query path and the server on stand-ins for Jev and OpenRouter, so they spend nothing and need no keys or data.

To try the site with no keys, run `curated scrape` and `curated catalog`, then the command below in place of `curated serve`, and start `web/` as usual. It builds an index over the real catalogue in the folder that `CURATED_STUB_ROOT` names, with a small placeholder taxonomy, and serves it on port 8790. The stand-ins rank by word overlap, so this run shows that the site works and says nothing about search quality.

```bash
CURATED_STUB_ROOT=/tmp/curated-stub uv run python -m tests.stubbed_index
```

Before committing, run `uv run ruff check`, `uv run ruff format --check` and `uv run pyright`; for the site, run `bun x tsc --noEmit` and `bun x eslint` in `web/`.

## Code map

| Path | Holds |
| --- | --- |
| `src/curated/scrape.py`, `catalog.py` | The download and the parser of its pages |
| `src/curated/indexing/` | The product reading, taxonomy writer, cards, embeddings, Jev tags and index build |
| `src/curated/search/` | The query path: `searcher.py` runs it; understanding, interpretation, the rankings (`arms.py`), fusion, expansion and the gate each have a module |
| `src/curated/server.py`, `debug_view.py` | The HTTP API and the debug panel's account of a search |
| `src/curated/deployment.py`, `gate.py`, `shared_spend.py`, `index.py` | What Vercel runs: the app, the password gate and the shared spend total |
| `src/curated/settings.py` | Every model name, size and threshold |
| `web/components/curated/` | The search page, cards, product dialog and debug panel |
| `tests/` | The tests, the stand-ins and the stubbed index |

## Running it in public

A public deployment spends your money on every search, so set both limits and leave `SITE_PASSWORD` out:

- **The daily budget is what bounds the bill.** Every search checks the total across all instances first, so past the cap the search stops however many visitors or addresses there are. Searches already running when the cap is reached still finish, so it can run over by a few searches.
- **The per-visitor limit stops casual abuse only.** It counts in each instance's memory, so several instances allow several times the limit, and someone with many addresses goes around it. On Vercel it reads `x-vercel-forwarded-for`, which Vercel sets itself; elsewhere it reads the connection's address, so behind your own proxy every visitor counts as one.

Past either limit the page shows a short message. Other failures show a generic message, and the details go to the server's log.

## Licence

The code is under the [MIT licence](LICENSE). It does not cover the products, text and photos on curated.supply, which belong to their owners, or any font you add at build time. `web/components/heat/heat-map.tsx` is adapted from Bencho's Heat map, under the MIT licence beside it.
