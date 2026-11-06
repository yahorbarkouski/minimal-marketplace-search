"""The built catalogue and index as one file, so someone can run the search without scraping the site or paying to
build the index. `curated package` writes the file and records its checksum in the repository; `curated download`
fetches it, refuses it unless the checksum matches, and unpacks only what a search reads.

The file holds text and photos from curated.supply, which the code's licence does not cover. It holds no keys, ledger
or raw pages, because only the paths in `RELEASED_FILES` and `RELEASED_DIRECTORY` go in.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path

import httpx

from curated.settings import Settings

ARCHIVE_NAME = "curated-data.tar.gz"
CHECKSUM_FILE = "data-release.sha256"
DATA_URL = f"https://github.com/yahorbarkouski/minimal-marketplace-search/releases/download/data-v1/{ARCHIVE_NAME}"
"""A fixed tag and not `latest`, so a checkout keeps finding the file its checksum describes."""
RELEASED_FILES = ("products.jsonl", "readings.jsonl")
RELEASED_DIRECTORY = "index"
REQUIRED_IN_INDEX = ("cards.json", "gate_cards.json", "keyword_fields.json", "text.npy", "photo.npy", "style.npy")
CHUNK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_S = 300.0


class DataReleaseError(RuntimeError):
    pass


def package_data(settings: Settings, out_dir: Path) -> tuple[Path, str]:
    """Writes the archive and the repository's checksum file; the same data gives the same bytes."""
    data = settings.data_dir
    missing = [str(data / name) for name in RELEASED_FILES if not (data / name).exists()]
    _require_index(data, missing)
    if missing:
        raise DataReleaseError(f"nothing to package yet, missing {missing[:3]}; build the index first")
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / ARCHIVE_NAME
    paths = [data / name for name in RELEASED_FILES]
    paths += sorted(path for path in (data / RELEASED_DIRECTORY).rglob("*") if path.is_file())

    def clean(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        info.mode = 0o644
        return info

    with (
        archive.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", dereference=True) as tar,
    ):
        for path in paths:
            tar.add(path, arcname=path.relative_to(data).as_posix(), filter=clean)
    checksum = _sha256(archive)
    (settings.root / CHECKSUM_FILE).write_text(f"{checksum}\n", encoding="utf-8")
    return archive, checksum


def expected_checksum(settings: Settings) -> str:
    path = settings.root / CHECKSUM_FILE
    if not path.exists():
        raise DataReleaseError(f"{CHECKSUM_FILE} is missing, so a download could not be checked")
    return path.read_text(encoding="utf-8").strip()


def download_data(
    settings: Settings,
    *,
    source: str = DATA_URL,
    checksum: str,
    force: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Fetches and unpacks the release from a URL or a local path, and returns how many files it unpacked. Nothing in
    `data/` changes until the whole file has passed its checks."""
    data = settings.data_dir
    existing = [name for name in (*RELEASED_FILES, RELEASED_DIRECTORY) if (data / name).exists()]
    if existing and not force:
        raise DataReleaseError(f"data/ already holds {existing}; pass --force to replace them")
    data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data, prefix=".download-") as temporary:
        working = Path(temporary)
        archive = working / ARCHIVE_NAME
        if source.startswith(("https://", "http://")):
            _fetch(source, archive, transport)
        else:
            shutil.copyfile(source, archive)
        found = _sha256(archive)
        if found != checksum:
            raise DataReleaseError(f"the download's checksum is {found}, expected {checksum}; nothing was changed")
        unpacked = working / "unpacked"
        count = _unpack(archive, unpacked)
        missing = [name for name in RELEASED_FILES if not (unpacked / name).exists()]
        _require_index(unpacked, missing)
        if missing:
            raise DataReleaseError(f"the download lacks {missing[:3]}; nothing was changed")
        for name in existing:
            target = data / name
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        for name in (*RELEASED_FILES, RELEASED_DIRECTORY):
            (unpacked / name).replace(data / name)
    return count


def _require_index(root: Path, missing: list[str]) -> None:
    index = root / RELEASED_DIRECTORY
    missing += [f"{RELEASED_DIRECTORY}/{name}" for name in REQUIRED_IN_INDEX if not (index / name).exists()]


def _fetch(url: str, target: Path, transport: httpx.BaseTransport | None) -> None:
    # A client of its own, so a request for public data never carries a model key.
    with (
        httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_S, transport=transport) as client,
        client.stream("GET", url) as response,
        target.open("wb") as out,
    ):
        if response.status_code != httpx.codes.OK:
            raise DataReleaseError(f"{url} answered {response.status_code}")
        for chunk in response.iter_bytes(CHUNK_BYTES):
            out.write(chunk)


def _unpack(archive: Path, target: Path) -> int:
    """Unpacks only regular files and folders under the released paths; anything else refuses the whole file."""
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            allowed = member.name in RELEASED_FILES or member.name.startswith(f"{RELEASED_DIRECTORY}/")
            if not allowed or ".." in Path(member.name).parts or not (member.isfile() or member.isdir()):
                raise DataReleaseError(f"the download holds {member.name!r}, which it should not; nothing was changed")
        target.mkdir()
        tar.extractall(target, members=members, filter="data")
    return sum(member.isfile() for member in members)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as lines:
        while chunk := lines.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
