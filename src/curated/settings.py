"""Run-wide settings: where data lives, which models to call, and the sizes the search uses."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    return Path(os.environ.get("CURATED_ROOT", Path(__file__).resolve().parents[2]))


@dataclass(frozen=True)
class Models:
    reading: str = "openai/gpt-6-luna"
    """The indexing model: reads each product's page and photo once."""
    taxonomy: str = "openai/gpt-6-luna"
    """Writes the category and facet taxonomy from what the readings found."""
    query_parse: str = "google/gemini-3.8-flash"
    query_parse_provider: str = "google-ai-studio"
    interpretation: str = "google/gemini-3.5-flash-lite"
    """Says what a search refers to."""
    interpretation_provider: str | None = None
    embedding: str = "google/gemini-embedding-2"
    embedding_dimensions: int = 768
    jev: str | None = None  # TypeSafe's default, jev-latest
    jev_usd_per_million_input_tokens: float = 0.042
    fallback_decider: str = "pplx-decider-latest"
    """Perplexity's decision model, which the gate asks when TypeSafe's fails and PERPLEXITY_API_KEY is set."""
    fallback_decider_usd_per_million_input_tokens: float = 0.02


@dataclass(frozen=True)
class SearchSizes:
    """How many products each stage keeps, and the probability lines the query path routes on. The counts keep a search
    well under a cent; the gate's lines were read off 240 pairs one blind judge graded on 10 searches."""

    arm_k: int = 50
    fused_k: int = 80
    early_gate_k: int = 24
    """The best-fused products the gate reads on the buyer's words, while the interpretation is on its way."""
    rrf_k: int = 60
    gate_products_per_call: int = 6
    gate_line: float = 0.35
    """A product the gate rates at or above this reaches the page. Graded products above it were 76% relevant."""
    first_line: float = 0.6
    """A product the gate on the buyer's words rates at or above this appears before the search finishes."""
    interpretation_timeout_s: float = 2.5
    """A search whose interpretation has not answered by then goes on with the buyer's words alone."""
    interpretation_cache_size: int = 10_000
    """Interpretations kept in memory by normalized search text; 0 turns the cache off."""
    limit_route_threshold: float = 0.2
    """The search waits for the price parse only when Jev's probability of a stated limit reaches this."""
    further_batch: int = 60
    """Products in each batch a search judges past its first."""
    further_tail: int = 20
    further_share: float = 0.1
    """A search judges another batch only while at least this share of the last `further_tail` products it
    judged were admitted, so it stops where the fused list runs out of matches."""
    further_max: int = 9
    """Further batches one search may judge in all."""
    expansion_cap: int = 20
    expansion_category_floor: float = 0.5
    expansion_facet_floor: float = 0.7
    expansion_product_floor: float = 0.5


@dataclass(frozen=True)
class Settings:
    """Everything the catalogue, the index and the spend ledger hold lives under `data/`."""

    root: Path = field(default_factory=_project_root)
    daily_budget_usd: float = 5.0
    """The most all paid calls together may spend in one UTC day: indexing, searches and the benchmark."""
    searches_per_hour: int = 60
    """How many searches and further batches one visitor may ask for in an hour."""
    models: Models = field(default_factory=Models)
    sizes: SearchSizes = field(default_factory=SearchSizes)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def raw_dir(self) -> Path:
        """Every page of the site as it was downloaded, gzipped, one folder per kind of page."""
        return self.data_dir / "raw"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def runs_dir(self) -> Path:
        """Each long job's saved results and progress, one folder per job."""
        return self.data_dir / "runs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def ledger_path(self) -> Path:
        """On Vercel, the one place a function may write."""
        return Path("/tmp/ledger.jsonl") if os.environ.get("VERCEL") else self.data_dir / "ledger.jsonl"

    @property
    def pages_dir(self) -> Path:
        """The built HTML pages the app serves on Vercel, from `scripts/build_site.py`."""
        return self.root / "site"

    @property
    def products_path(self) -> Path:
        return self.data_dir / "products.jsonl"

    @property
    def readings_path(self) -> Path:
        return self.data_dir / "readings.jsonl"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def gate_photos_dir(self) -> Path:
        """Each product's photo as Jev reads it in the gate."""
        return self.index_dir / "gate-photos"

    @property
    def taxonomy_path(self) -> Path:
        return self.root / "taxonomy" / "taxonomy.yaml"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set; add it to .env (see .env.example).")
    return value
