"""Product photos as models read them."""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from curated.domain import ProductId

MODEL_PHOTO_WIDTH = 512
"""The width the reading and the photo embedding read a photo at."""
GATE_PHOTO_SHORT_SIDE = 280
"""The smallest side Jev accepts."""


def model_photo(path: Path) -> bytes:
    """The stored WebP as a JPEG at the width models read, its transparent parts on white, as the site shows them."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    flattened = Image.new("RGB", rgba.size, "white")
    flattened.paste(rgba, mask=rgba.getchannel("A"))
    if flattened.width > MODEL_PHOTO_WIDTH:
        height = round(flattened.height * MODEL_PHOTO_WIDTH / flattened.width)
        flattened = flattened.resize((MODEL_PHOTO_WIDTH, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    flattened.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def gate_photo(path: Path) -> bytes:
    """The photo as Jev reads it in the gate: the stored WebP on white, with its short side at the smallest size Jev
    accepts. On 12 products it used 70% of the tokens of the 512-pixel photo, and no answer moved by more than 0.06."""
    with Image.open(io.BytesIO(model_photo(path))) as image:
        scale = GATE_PHOTO_SHORT_SIDE / min(image.size)
        small = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    small.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def gate_photo_path(directory: Path, product_id: ProductId) -> Path:
    return directory / f"{quote(product_id, safe='')}.jpg"


def write_gate_photos(sources: Mapping[ProductId, Path], directory: Path) -> None:
    """Keeps each product's gate photo on disk, so a search reads a file instead of decoding a WebP."""
    directory.mkdir(parents=True, exist_ok=True)
    for product_id, source in sources.items():
        target = gate_photo_path(directory, product_id)
        if not target.exists():
            target.write_bytes(gate_photo(source))
