"""Vercel's entrypoint: the deployed site."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from curated.deployment import create_site
from curated.server import connect_demo
from curated.settings import Settings

settings = Settings()
app = create_site(settings, connect_demo(settings))
