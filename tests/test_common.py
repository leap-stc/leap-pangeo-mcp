import json
import os
import time

import httpx
import pytest

from leap_pangeo_mcp.core import common
from leap_pangeo_mcp.core.common import LeapError

CATALOG = "consolidated-web-catalog.json"


def _serve(monkeypatch, payload, calls):
    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(common.httpx, "get", fake_get)


def test_fetch_falls_back_to_snapshot_when_offline():
    data, from_snapshot = common.fetch_json("https://example.org/catalog.json", CATALOG)
    assert from_snapshot is True
    assert any(entry["title"] == "ARCO ERA5" for entry in data)


def test_fetch_live_writes_cache_and_reuses_it(monkeypatch):
    calls = []
    _serve(monkeypatch, [{"title": "live"}], calls)
    assert common.fetch_json("https://example.org/c.json", CATALOG) == ([{"title": "live"}], False)
    assert (common.CACHE_DIR / CATALOG).exists()

    # A fresh cache is used without another request.
    assert common.fetch_json("https://example.org/c.json", CATALOG) == ([{"title": "live"}], False)
    assert len(calls) == 1


def test_stale_cache_is_refetched(monkeypatch):
    cache = common.CACHE_DIR / CATALOG
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps([{"title": "old"}]))
    hour_ago = time.time() - common.CACHE_TTL_SECONDS - 5
    os.utime(cache, (hour_ago, hour_ago))

    calls = []
    _serve(monkeypatch, [{"title": "new"}], calls)
    assert common.fetch_json("https://example.org/c.json", CATALOG) == ([{"title": "new"}], False)
    assert calls == ["https://example.org/c.json"]


def test_http_error_falls_back_to_snapshot(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(503, request=httpx.Request("GET", url))

    monkeypatch.setattr(common.httpx, "get", fake_get)
    _, from_snapshot = common.fetch_json("https://example.org/c.json", CATALOG)
    assert from_snapshot is True


def test_cursor_round_trip():
    assert common.decode_cursor("") == 0
    assert common.decode_cursor(common.encode_cursor(40)) == 40


@pytest.mark.parametrize("bad", ["garbage!", "bzotMQ==", "eDo1"])  # junk, "o:-1", "x:5"
def test_invalid_cursor_is_a_clear_error(bad):
    with pytest.raises(LeapError, match="Invalid cursor"):
        common.decode_cursor(bad)


def test_fit_page_respects_count_and_budget():
    blocks = ["x" * 10] * 30
    assert common.fit_page(blocks, 0, max_items=10) == 10
    assert common.fit_page(blocks, 25, max_items=10) == 30
    assert common.fit_page(blocks, 0, max_items=10, budget=35) == 3
    # A single oversized block still makes progress.
    assert common.fit_page(["y" * 100], 0, max_items=10, budget=5) == 1


def test_formatting_helpers():
    assert common.human_bytes(512) == "512 B"
    assert common.human_bytes(3 * 1024**3) == "3.0 GiB"
    assert common.one_line("a\n  b   c", 80) == "a b c"
    assert common.one_line("abcdefghij", 5) == "abcd…"
