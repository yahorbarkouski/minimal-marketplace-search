"""Builds the site as static files for Vercel: its JavaScript, styles and fonts into `public/`, which the CDN serves,
and its pages into `site/`, which the app serves behind the password gate.

The site uses a free font. To build it with a font you hold a web licence for, set `CURATED_FONT_FILE` to its `.woff2`.
The file reaches the build's output only, so it never lands in the repository.
"""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = WEB / "out"
PAGES = ("index.html", "login.html")
PUBLIC_FILES = ("favicon.ico",)
BUILT_ASSETS = "_next"
LICENSED_FONT = "fonts/licensed.woff2"
ROBOTS = "User-agent: *\nDisallow: /\n"


def main() -> None:
    env = {**os.environ, "CURATED_EXPORT": "1"}
    font_file = os.environ.get("CURATED_FONT_FILE")
    if font_file:
        env["CURATED_LICENSED_FONT"] = "1"
    subprocess.run(["bun", "run", "build"], cwd=WEB, env=env, check=True)
    for folder in (ROOT / "public", ROOT / "site"):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
    for page in PAGES:
        shutil.copy(OUT / page, ROOT / "site" / page)
    for name in PUBLIC_FILES:
        shutil.copy(OUT / name, ROOT / "public" / name)
    shutil.copytree(OUT / BUILT_ASSETS, ROOT / "public" / BUILT_ASSETS)
    if font_file:
        (ROOT / "public" / LICENSED_FONT).parent.mkdir()
        shutil.copy(font_file, ROOT / "public" / LICENSED_FONT)
    (ROOT / "public" / "robots.txt").write_text(ROBOTS)


if __name__ == "__main__":
    main()
