"""The site password: a visitor enters it once, and the cookie then holds a hash of it, never the password itself, so
changing the password signs everyone out. Every page and API route sits behind it except the health check and the
static files the login page itself needs."""

from __future__ import annotations

import hashlib
from hmac import compare_digest
from pathlib import Path
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "curated_access"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30
LOGIN_PATH = "/api/login"
OPEN_PATHS = frozenset({"/api/health", "/favicon.ico", "/robots.txt"})
OPEN_PREFIXES = ("/_next/", "/fonts/")
"""Vercel's CDN serves these before a request reaches the gate; a local `curated serve --site` needs them open too."""


def access_token(password: str) -> str:
    return hashlib.sha256(f"curated:{password}".encode()).hexdigest()


def safe_next(value: str) -> str:
    """Only a same-site path is a valid place to return to after signing in."""
    return value if value.startswith("/") and not value.startswith("//") else "/"


class PasswordGate:
    def __init__(self, app: ASGIApp, *, password: str, login_page: Path) -> None:
        self._app = app
        self._password = password.encode()
        self._token = access_token(password).encode()
        self._login_page = login_page

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request = Request(scope, receive)
        path = request.url.path
        response: Response
        if path == LOGIN_PATH and request.method == "POST":
            response = await self._log_in(request)
        elif (
            path in OPEN_PATHS
            or path.startswith(OPEN_PREFIXES)
            or compare_digest(request.cookies.get(COOKIE, "").encode(), self._token)
        ):
            await self._app(scope, receive, send)
            return
        elif path.startswith("/api/"):
            response = JSONResponse({"detail": "password required"}, status_code=401)
        else:
            response = FileResponse(self._login_page, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)

    async def _log_in(self, request: Request) -> Response:
        form = parse_qs((await request.body()).decode())
        back = safe_next(form.get("next", ["/"])[0])
        if not compare_digest(form.get("password", [""])[0].encode(), self._password):
            return RedirectResponse(f"{back}{'&' if '?' in back else '?'}wrong=1", status_code=303)
        response = RedirectResponse(back, status_code=303)
        response.set_cookie(
            COOKIE,
            self._token.decode(),
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        )
        return response
