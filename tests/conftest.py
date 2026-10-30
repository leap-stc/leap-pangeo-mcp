import httpx
import pytest

from leap_pangeo_mcp.core import common


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Keep every test offline: live fetches fail and the cache lives in tmp_path.

    Core modules therefore read the bundled snapshots unless a test patches httpx.get.
    """

    def no_network(url, **kwargs):
        raise httpx.ConnectError("network disabled in tests")

    monkeypatch.setattr(common.httpx, "get", no_network)
    monkeypatch.setattr(common, "CACHE_DIR", tmp_path / "cache")
