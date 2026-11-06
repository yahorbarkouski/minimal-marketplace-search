"""The site as Vercel runs it: the search API, the built pages and the password gate, in one app. Vercel's CDN serves
`public/`, so `/` is the only page that reaches this app, and the gate decides what it gets."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse

from curated.gate import PasswordGate
from curated.server import DemoFactory, create_app
from curated.settings import Settings


def create_site(settings: Settings, open_demo: DemoFactory) -> FastAPI:
    app = create_app(open_demo)

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(settings.pages_dir / "index.html", headers={"Cache-Control": "no-cache"})

    password = os.environ.get("SITE_PASSWORD")
    if password:
        app.add_middleware(PasswordGate, password=password, login_page=settings.pages_dir / "login.html")
    return app
