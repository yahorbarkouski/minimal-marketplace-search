"""Downloads curated.supply in full: every page its sitemap lists and every product's photo.

The site owner has allowed the full download. It reads only what robots.txt allows, so it never touches `/api/`
or the affiliate redirects under `/go/`. Pages are kept gzipped under `data/raw/<kind>/`, and a rerun downloads
only what is missing, so `catalog.py` can parse them again with no new requests.
"""

from __future__ import annotations

import asyncio
import gzip
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import httpx

from curated.catalog import product_cards
from curated.jobs import gather_stopping
from curated.runlog import Run
from curated.settings import Settings

SITE = "https://www.curated.supply"
SITEMAP = f"{SITE}/sitemap.xml"
USER_AGENT = "curated-search-indexer/0.1"
"""Generic on purpose: it says what the requests are for and names nobody."""
PAGE_CONCURRENCY = 12
PHOTO_CONCURRENCY = 3
"""The asset CDN answers 429 at about 100 requests a second; three at a time stays well under it."""
ATTEMPTS = 3
FIRST_BACKOFF_SECONDS = 1.0
_LOC = re.compile(r"<loc>([^<]+)</loc>")
TOP_LEVEL = "site"
"""The folder of pages that sit directly under the site's root, such as `/products` itself."""


@dataclass(frozen=True)
class Download:
    id: str
    url: str
    path: Path
    gzipped: bool


def page_path(raw_dir: Path, url: str) -> Path:
    """Where a page is kept: `/products/sofort-2` is `products/sofort-2.html.gz`. Names stay percent-encoded, so a
    slug such as `plissé-blender` keeps one spelling on a filesystem that normalizes Unicode."""
    parts = [unquote(part) for part in urlsplit(url).path.split("/") if part]
    if len(parts) < 2:
        return raw_dir / TOP_LEVEL / f"{parts[0] if parts else 'home'}.html.gz"
    return raw_dir / parts[0] / f"{quote(parts[1], safe='')}.html.gz"


def photo_path(photos_dir: Path, slug: str) -> Path:
    return photos_dir / f"{quote(slug, safe='')}.webp"


def sitemap_urls(sitemap: str) -> list[str]:
    return list(dict.fromkeys(_LOC.findall(sitemap)))


async def scrape(settings: Settings, *, limit: int | None = None) -> None:
    """Downloads the pages, then the photos of the products the `/products` page lists."""
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as http:
        response = await http.get(SITEMAP)
        response.raise_for_status()
        urls = sitemap_urls(response.text)
        pages = [Download(url, url, page_path(settings.raw_dir, url), gzipped=True) for url in urls[:limit]]
        await _download_all("pages", pages, http, settings=settings, concurrency=PAGE_CONCURRENCY)
        listing = page_path(settings.raw_dir, f"{SITE}/products")
        if not listing.exists():
            raise RuntimeError(f"{SITE}/products was not downloaded; run again without --limit")
        cards = product_cards(gzip.decompress(listing.read_bytes()).decode("utf-8"))
        photos = [
            Download(
                card["slug"],
                card["imageUrl"].replace(" ", "%20"),
                photo_path(settings.photos_dir, card["slug"]),
                gzipped=False,
            )
            for card in cards[:limit]
        ]
        await _download_all("photos", photos, http, settings=settings, concurrency=PHOTO_CONCURRENCY)


async def _download_all(
    name: str,
    downloads: Sequence[Download],
    http: httpx.AsyncClient,
    *,
    settings: Settings,
    concurrency: int,
) -> None:
    missing = [download for download in downloads if not download.path.exists()]
    run_dir = settings.runs_dir / f"scrape-{name}"
    with Run(str(run_dir), config={"site": SITE, "job": name}) as run:
        slots = asyncio.Semaphore(concurrency)

        async def fetch(download: Download) -> None:
            async with slots:
                try:
                    size = await _fetch_to_disk(download, http)
                except Exception as error:
                    run.fail(download.id, error)
                    return
                run.save(download.id, {"url": download.url, "bytes": size})

        await gather_stopping([fetch(download) for download in run.todo(missing, id_of=lambda download: download.id)])


async def _fetch_to_disk(download: Download, http: httpx.AsyncClient) -> int:
    body = await _get_with_retries(download.url, http)
    download.path.parent.mkdir(parents=True, exist_ok=True)
    temporary = download.path.with_name(download.path.name + ".tmp")
    temporary.write_bytes(gzip.compress(body) if download.gzipped else body)
    temporary.replace(download.path)
    return len(body)


async def _get_with_retries(url: str, http: httpx.AsyncClient) -> bytes:
    """Fetches one URL, resending after a timeout, a 5xx answer or a 429, whose `Retry-After` it waits out. Any other
    refusal raises at once, so a site that starts refusing stops the job through its failure count."""
    for attempt in range(1, ATTEMPTS + 1):
        wait = FIRST_BACKOFF_SECONDS * 2 ** (attempt - 1)
        try:
            response = await http.get(url)
        except httpx.TransportError:
            if attempt == ATTEMPTS:
                raise
        else:
            limited = response.status_code == httpx.codes.TOO_MANY_REQUESTS
            if limited:
                wait = float(response.headers.get("Retry-After", wait))
            retryable = limited or response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
            if not retryable or attempt == ATTEMPTS:
                response.raise_for_status()
                return response.content
        await asyncio.sleep(wait)
    raise AssertionError("unreachable: the last attempt returns or raises")
