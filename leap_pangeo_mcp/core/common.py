"""Helpers shared by the core modules: user-facing errors, cached fetches, paging and OSN URLs."""

import base64
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

MAX_CHARS = 8000
# Room left for headers and paging footers when a module fills a page.
PAGE_BUDGET = 7000

CACHE_DIR = Path("/tmp/leap-pangeo-mcp")
CACHE_TTL_SECONDS = 3600
# Below the server's 20 s tool timeout, so a failed fetch still falls back to the snapshot.
FETCH_TIMEOUT_SECONDS = 10
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "snapshots"
OSN_ENDPOINTS = ("https://nyu1.osn.mghpcc.org", "https://ncsa.osn.xsede.org")


class LeapError(Exception):
    """An expected failure. The message is one line written for the researcher."""


@dataclass(frozen=True)
class OsnPath:
    """A path on OSN, read anonymously through OSN's S3 API.

    Use the S3 API, not plain HTTPS: HTTPS cannot list folders, so a Zarr v3 store
    without consolidated metadata opens over HTTPS as an empty dataset.
    """

    endpoint: str  # one of OSN_ENDPOINTS
    key: str  # "bucket/path" without outer slashes; "" if the URL names no bucket

    @property
    def s3_url(self) -> str:
        return f"s3://{self.key}"

    @property
    def storage_options(self) -> dict[str, Any]:
        return {"anon": True, "client_kwargs": {"endpoint_url": self.endpoint}}


def parse_osn_url(url: str) -> OsnPath | None:
    """Return the OsnPath for an https URL on an OSN endpoint, or None for any other URL."""
    parts = urlsplit(url.strip())
    endpoint = f"https://{parts.netloc.lower()}"
    if parts.scheme.lower() != "https" or endpoint not in OSN_ENDPOINTS:
        return None
    return OsnPath(endpoint, parts.path.strip("/"))


def fetch_json(url: str, filename: str) -> tuple[Any, bool]:
    """Return (data, from_snapshot) for url.

    Order: a cache file under CACHE_DIR younger than one hour, then a live fetch
    (which refreshes the cache), then the bundled snapshot with the same filename.
    """
    cache = CACHE_DIR / filename
    try:
        if time.time() - cache.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(cache.read_bytes()), False
    except (OSError, ValueError):
        pass
    try:
        response = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return json.loads((SNAPSHOT_DIR / filename).read_bytes()), True
    _write_cache(cache, response.content)
    return data, False


def _write_cache(cache: Path, content: bytes) -> None:
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as tmp:
            tmp.write(content)
        os.replace(tmp.name, cache)
    except OSError:
        pass  # A read-only /tmp only costs a refetch next time.


def snapshot_note(source: str) -> str:
    return (
        f"Note: could not reach the live {source}; these results come from the snapshot "
        "bundled with this server and may be out of date."
    )


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def decode_cursor(cursor: str) -> int:
    """Return the offset in cursor ("" means 0). Raises LeapError if it was not made by encode_cursor."""
    if not cursor:
        return 0
    try:
        # binascii.Error and UnicodeDecodeError are both ValueErrors.
        kind, value = base64.urlsafe_b64decode(cursor.encode()).decode().split(":")
        if kind != "o" or int(value) < 0:
            raise ValueError(cursor)
        return int(value)
    except ValueError:
        raise LeapError(
            "Invalid cursor. Pass the cursor value from the previous result unchanged, "
            "or leave it empty to start from the first page."
        ) from None


def fit_page(blocks: list[str], start: int, max_items: int, budget: int = PAGE_BUDGET) -> int:
    """Return the end index of the page of blocks that starts at start.

    The page holds at most max_items blocks and stays within budget characters,
    but always holds at least one block so paging makes progress.
    """
    end, used = start, 0
    while end < len(blocks) and end - start < max_items:
        used += len(blocks[end]) + 1
        if used > budget and end > start:
            break
        end += 1
    return end


def human_bytes(n: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.0f} B" if i == 0 else f"{n:.1f} {units[i]}"


def one_line(text: str, limit: int) -> str:
    """Collapse whitespace and shorten text to at most limit characters."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
