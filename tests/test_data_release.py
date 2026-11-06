"""What the data download does with a good file, and that it refuses a bad one and leaves `data/` alone."""

import hashlib
import io
import tarfile
from pathlib import Path

import httpx
import pytest

from curated.data_release import ARCHIVE_NAME, DataReleaseError, download_data, expected_checksum, package_data
from curated.search.searcher import SearchIndex
from curated.settings import Settings

SECRET_NAMES = ("ledger.jsonl", "raw/page.html.gz", "photos/a.webp", "runs/job/results.jsonl")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tarball(*members: tuple[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def empty_root(tmp_path: Path, name: str = "clone") -> Settings:
    root = Settings(root=tmp_path / name)
    root.root.mkdir(parents=True)
    return root


@pytest.fixture
def packaged(settings: Settings, tmp_path: Path) -> tuple[Settings, Path, str]:
    return settings, *package_data(settings, tmp_path / "dist")


def test_a_packaged_release_runs_the_search_from_an_empty_checkout(
    packaged: tuple[Settings, Path, str], tmp_path: Path
) -> None:
    built, archive, checksum = packaged
    clone = empty_root(tmp_path)
    clone.taxonomy_path.parent.mkdir()
    clone.taxonomy_path.write_bytes(built.taxonomy_path.read_bytes())
    assert download_data(clone, source=str(archive), checksum=checksum) > 2
    index = SearchIndex.load(clone)
    assert set(index.products) == set(SearchIndex.load(built).products)


def test_the_release_holds_only_what_a_search_reads(settings: Settings, tmp_path: Path) -> None:
    for name in SECRET_NAMES:
        path = settings.data_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private")
    (settings.root / ".env").write_text("TYPESAFE_API_KEY=secret")
    archive, _ = package_data(settings, tmp_path / "dist")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert not [
        name for name in names if not (name in {"products.jsonl", "readings.jsonl"} or name.startswith("index/"))
    ]
    assert not [name for name in names if "env" in name or "ledger" in name]


def test_packaging_twice_gives_the_same_bytes_and_records_the_checksum(settings: Settings, tmp_path: Path) -> None:
    first, checksum = package_data(settings, tmp_path / "one")
    second, again = package_data(settings, tmp_path / "two")
    assert checksum == again
    assert first.read_bytes() == second.read_bytes()
    assert expected_checksum(settings) == checksum


def test_a_wrong_checksum_changes_nothing(packaged: tuple[Settings, Path, str], tmp_path: Path) -> None:
    _, archive, _ = packaged
    clone = empty_root(tmp_path)
    with pytest.raises(DataReleaseError, match="checksum"):
        download_data(clone, source=str(archive), checksum="0" * 64)
    assert list(clone.data_dir.iterdir()) == []


def test_existing_data_stays_unless_forced(packaged: tuple[Settings, Path, str], tmp_path: Path) -> None:
    _, archive, checksum = packaged
    clone = empty_root(tmp_path)
    clone.data_dir.mkdir()
    clone.products_path.write_text("mine")
    with pytest.raises(DataReleaseError, match="--force"):
        download_data(clone, source=str(archive), checksum=checksum)
    assert clone.products_path.read_text() == "mine"
    download_data(clone, source=str(archive), checksum=checksum, force=True)
    assert clone.products_path.read_text() != "mine"
    assert not [path.name for path in clone.data_dir.iterdir() if path.name.startswith(".download")]


@pytest.mark.parametrize("name", ["../../evil.txt", ".env", "index/../../evil.txt", "/tmp/evil.txt"])
def test_a_file_outside_the_release_refuses_the_whole_download(tmp_path: Path, name: str) -> None:
    bad = tarball(("products.jsonl", b"{}"), (name, b"evil"))
    source = tmp_path / ARCHIVE_NAME
    source.write_bytes(bad)
    clone = empty_root(tmp_path)
    with pytest.raises(DataReleaseError, match="should not"):
        download_data(clone, source=str(source), checksum=sha(bad))
    assert not (tmp_path / "evil.txt").exists()
    assert list(clone.data_dir.iterdir()) == []


def test_a_link_in_the_archive_refuses_the_whole_download(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("index/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    source = tmp_path / ARCHIVE_NAME
    source.write_bytes(buffer.getvalue())
    with pytest.raises(DataReleaseError, match="should not"):
        download_data(empty_root(tmp_path), source=str(source), checksum=sha(buffer.getvalue()))


def test_a_release_missing_a_needed_file_is_refused(tmp_path: Path) -> None:
    thin = tarball(("products.jsonl", b"{}"), ("readings.jsonl", b"{}"), ("index/cards.json", b"{}"))
    source = tmp_path / ARCHIVE_NAME
    source.write_bytes(thin)
    clone = empty_root(tmp_path)
    with pytest.raises(DataReleaseError, match="lacks"):
        download_data(clone, source=str(source), checksum=sha(thin))
    assert not clone.products_path.exists()


def test_a_url_is_fetched_through_redirects_with_no_key_and_a_failure_is_an_error(
    packaged: tuple[Settings, Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, archive, checksum = packaged
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/release":
            return httpx.Response(302, headers={"location": "https://cdn.test/file"})
        return httpx.Response(200, content=archive.read_bytes())

    clone = empty_root(tmp_path)
    download_data(clone, source="https://host.test/release", checksum=checksum, transport=httpx.MockTransport(respond))
    assert clone.products_path.exists()
    assert len(seen) == 2
    assert all("authorization" not in request.headers for request in seen)
    missing = httpx.MockTransport(lambda _: httpx.Response(404))
    with pytest.raises(DataReleaseError, match="404"):
        download_data(empty_root(tmp_path, "other"), source="https://host.test/x", checksum=checksum, transport=missing)
