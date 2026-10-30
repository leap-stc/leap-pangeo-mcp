import re
import sys
import types

import numpy as np
import pytest
import xarray as xr
from fsspec.implementations.memory import MemoryFileSystem
from fsspec.registry import _registry

from leap_pangeo_mcp.core import knowledge


class FakeObjectStore(MemoryFileSystem):
    """In-memory stand-in for gcsfs and s3fs that accepts gs:// and s3:// URLs."""

    protocol = ("gs", "gcs", "s3")

    @classmethod
    def _strip_protocol(cls, path):
        for prefix in ("gs://", "gcs://", "s3://"):
            if path.startswith(prefix):
                path = path[len(prefix):]
        return super()._strip_protocol(path)


@pytest.fixture
def fake_buckets(monkeypatch):
    monkeypatch.setattr(FakeObjectStore, "store", {})
    monkeypatch.setattr(FakeObjectStore, "pseudo_dirs", [""])
    for protocol in FakeObjectStore.protocol:
        monkeypatch.setitem(_registry, protocol, FakeObjectStore)
    return FakeObjectStore


def _code(text: str) -> str:
    return re.search(r"```python\n(.*?)```", text, re.S).group(1)


def test_primer_covers_the_essentials():
    primer = knowledge.overview()
    assert 20 <= len(primer.splitlines()) <= 40
    for fact in [
        "gs://leap-scratch/", "7 days", "gs://leap-persistent/", "gs://leap-persistent-ro/",
        "read-only", "OSN", "egress", "<bucket>/<github-username>/", "home directory",
        "credentials", "lazily", "T4", "shut clusters down", "leap-stc/LEAP-batch-jobs",
        "@data-and-compute", "https://leap-stc.github.io", "https://catalog.leap.columbia.edu",
    ]:
        assert fact in primer, fact


def test_unknown_task_lists_valid_tasks():
    text = knowledge.how_to("make_coffee")
    assert "Unknown task" in text
    for name in knowledge.TASKS:
        assert name in text


def test_username_is_filled_in_when_set(monkeypatch):
    monkeypatch.setenv("JUPYTERHUB_USER", "jdoe")
    text = knowledge.how_to("write_to_my_folder")
    assert 'user = "jdoe"' in text
    assert knowledge.USER_PLACEHOLDER not in text


def test_placeholder_and_hint_when_user_unset(monkeypatch):
    monkeypatch.delenv("JUPYTERHUB_USER", raising=False)
    text = knowledge.how_to(" Copy_To_OSN ")
    assert 'user = "<github-username>"' in text
    assert "not set (not on the LEAP hub?)" in text


@pytest.mark.parametrize("task", list(knowledge.TASKS))
def test_snippets_compile_and_hold_no_credentials(task):
    code = _code(knowledge.how_to(task))
    compile(code, task, "exec")
    assert not re.search(r"(key|secret|token)\s*=\s*['\"]", code, re.I)


def test_write_then_copy_to_osn_run_end_to_end(monkeypatch, fake_buckets):
    monkeypatch.setenv("JUPYTERHUB_USER", "jdoe")
    monkeypatch.setenv("OSN_ACCESS_KEY_INBOX", "test-key")
    monkeypatch.setenv("OSN_SECRET_KEY_INBOX", "test-secret")
    ds = xr.Dataset({"t": (("time",), np.arange(4.0))}, coords={"time": np.arange(4)})

    exec(_code(knowledge.how_to("write_to_my_folder")), {"ds": ds})
    fs = fake_buckets()
    assert fs.exists("leap-persistent/jdoe/my_result.zarr/zarr.json")
    assert fs.cat("leap-scratch/jdoe/notes.txt") == b"written from the LEAP hub"

    exec(_code(knowledge.how_to("copy_to_osn")), {})
    copied = xr.open_dataset("s3://leap-pangeo-inbox/jdoe/my_result.zarr", engine="zarr")
    np.testing.assert_array_equal(copied.t.values, ds.t.values)


def test_dask_snippet_starts_and_shuts_down_the_cluster(monkeypatch):
    calls = []

    class Client:
        dashboard_link = "https://hub/dask/status"

        def close(self):
            calls.append("client.close")

    class Cluster:
        def adapt(self, minimum, maximum):
            calls.append("adapt")

        def get_client(self):
            return Client()

        def shutdown(self):
            calls.append("shutdown")

    class Gateway:
        def cluster_options(self):
            return types.SimpleNamespace()

        def new_cluster(self, options):
            calls.append("new_cluster")
            return Cluster()

    monkeypatch.setitem(sys.modules, "dask_gateway", types.SimpleNamespace(Gateway=Gateway))
    exec(_code(knowledge.how_to("start_dask_cluster")), {})
    assert calls == ["new_cluster", "adapt", "client.close", "shutdown"]
