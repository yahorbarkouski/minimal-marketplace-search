"""The command line: download the site, parse it, build the index, serve the search."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
import uvicorn
from fastapi.staticfiles import StaticFiles

from curated.benchmark import load_grades, load_run, pool, report, run_benchmark, run_directory, score_run
from curated.cache import JsonCache
from curated.catalog import build_catalog, load_products
from curated.deployment import create_site
from curated.indexing.build import build_index
from curated.indexing.reading import load_readings, read_products, sample_per_category, write_readings
from curated.indexing.taxonomy_writer import write_taxonomy
from curated.ledger import SpendLedger, spend_by_purpose
from curated.providers.jev import JevClient
from curated.providers.openrouter import OpenRouterClient
from curated.scrape import scrape as scrape_site
from curated.server import connect_demo, create_app
from curated.settings import Settings

DEFAULT_JOB_CAP = 3.0
"""Dollars one paid indexing job may spend before it stops itself."""

app = typer.Typer(no_args_is_help=True, add_completion=False)
benchmark = typer.Typer(no_args_is_help=True, help="Measure the search on fixed searches and blind grades.")
app.add_typer(benchmark, name="benchmark")


def _settings() -> Settings:
    """The settings, with the model keys of the project's `.env`, which override the environment's."""
    path: Path = Settings().root / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.strip().partition("=")
            if separator and value and not name.startswith("#"):
                os.environ[name.strip()] = value.strip().strip("'\"")
    # Built after the file is read, because the settings read the environment.
    return Settings()


@app.command()
def scrape(limit: int | None = typer.Option(None, help="Download only this many pages and photos.")) -> None:
    """Download every page of curated.supply and every product's photo; a rerun fetches only what is missing."""
    asyncio.run(scrape_site(Settings(), limit=limit))


@app.command()
def catalog() -> None:
    """Parse the downloaded pages into data/products.jsonl."""
    typer.echo(f"wrote {len(build_catalog(Settings()))} products")


@app.command()
def read(
    per_category: int | None = typer.Option(None, help="Read only this many products of each site category."),
    max_cost: float = typer.Option(DEFAULT_JOB_CAP, help="Stop once the reading run has spent this many dollars."),
) -> None:
    """Have the indexing model read each product's page and photo; a rerun reads only what is missing."""
    settings = _settings()
    products = list(load_products(settings).values())
    if per_category is not None:
        products = sample_per_category(products, per_category)

    async def run() -> None:
        ledger = SpendLedger.open(settings.ledger_path, settings.budget_usd)
        async with OpenRouterClient.connect(ledger) as client:
            await read_products(products, settings=settings, client=client, max_cost=max_cost)

    asyncio.run(run())
    typer.echo(f"{write_readings(settings)} readings saved")


@app.command()
def taxonomy() -> None:
    """Have a model write taxonomy/taxonomy.yaml from what the readings found."""
    settings = _settings()

    async def run() -> None:
        ledger = SpendLedger.open(settings.ledger_path, settings.budget_usd)
        async with OpenRouterClient.connect(ledger) as client:
            written = await write_taxonomy(
                load_products(settings), load_readings(settings), settings=settings, client=client
            )
        typer.echo(f"{len(written.categories)} categories and {len(written.facets)} facet values")

    asyncio.run(run())


@app.command()
def index(
    max_cost: float = typer.Option(DEFAULT_JOB_CAP, help="Stop once the tagging run has spent this many dollars."),
) -> None:
    """Build the cards, the embeddings and Jev's tags; a rerun pays only for what changed."""
    settings = _settings()

    async def run() -> None:
        ledger = SpendLedger.open(settings.ledger_path, settings.budget_usd)
        async with (
            OpenRouterClient.connect(ledger) as openrouter,
            JevClient.connect(ledger, settings.models) as jev,
        ):
            await build_index(
                settings, openrouter=openrouter, jev=jev, cache=JsonCache(settings.cache_dir), max_cost=max_cost
            )

    asyncio.run(run())


@app.command()
def spend() -> None:
    """Print what the ledger holds, by purpose."""
    settings = _settings()
    totals = spend_by_purpose(settings.ledger_path)
    for purpose, total in sorted(totals.items(), key=lambda item: -item[1]):
        typer.echo(f"{purpose}: ${total:.4f}")
    typer.echo(f"total: ${sum(totals.values()):.4f} of ${settings.budget_usd:.2f}")


@app.command()
def serve(
    port: int = typer.Option(8790),
    host: str = typer.Option("127.0.0.1"),
    site: bool = typer.Option(False, help="Serve the built site and its password gate too, as Vercel does."),
) -> None:
    """Serve the search API for the site in web/."""
    settings = _settings()
    if not site:
        uvicorn.run(create_app(connect_demo(settings)), host=host, port=port)
        return
    built = create_site(settings, connect_demo(settings))
    built.mount("/", StaticFiles(directory=settings.root / "public"))
    uvicorn.run(built, host=host, port=port)


@benchmark.command("run")
def benchmark_run(
    name: str = typer.Option("latest", help="The saved run to write; a rerun continues it."),
    limit: int | None = typer.Option(None, help="Run only this many searches, to try it cheaply."),
) -> None:
    """Run the benchmark's searches for real, one at a time. It costs about $0.005 a search."""
    settings = _settings()
    results = asyncio.run(
        run_benchmark(settings, searches=settings.root / "benchmark" / "searches.jsonl", name=name, limit=limit)
    )
    typer.echo(f"saved to {results}")


@benchmark.command("pool")
def benchmark_pool(name: str = typer.Option("latest", help="The saved run to read.")) -> None:
    """Print the pairs of search and product that still need a grade, one JSON object per line. It costs nothing."""
    settings = _settings()
    runs = load_run(run_directory(settings, name) / "results.jsonl")
    for search, product_id in pool(runs, load_grades(settings.root / "benchmark" / "grades.jsonl")):
        typer.echo(json.dumps({"search": search, "product_id": product_id}, ensure_ascii=False))


@benchmark.command("score")
def benchmark_score(
    name: str = typer.Option("latest", help="The saved run to score."),
    details: bool = typer.Option(False, help="Print each search's numbers as JSON too."),
) -> None:
    """Score a saved run against the blind grades. It costs nothing."""
    settings = _settings()
    runs = load_run(run_directory(settings, name) / "results.jsonl")
    scores = score_run(runs, load_grades(settings.root / "benchmark" / "grades.jsonl"))
    typer.echo(report(scores))
    if details:
        for row in scores["searches"]:
            typer.echo(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    app()
