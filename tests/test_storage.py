import dataclasses
import re

import numpy as np
import pytest
import xarray as xr
from fsspec.implementations.memory import MemoryFileSystem

from leap_pangeo_mcp.core import storage
from leap_pangeo_mcp.core.common import MAX_CHARS, OSN_ENDPOINTS, LeapError, human_bytes

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")
CURSOR = re.compile(r'cursor="([^"]+)"')


@pytest.fixture
def redirect(monkeypatch):
    """Keep the real URL checks, but read the bytes from `base` (a local dir or memory://)."""

    def apply(base: str):
        real = storage._resolve

        def fake(path, **kwargs):
            loc = real(path, **kwargs)
            return dataclasses.replace(loc, url=base + loc.url.split("://", 1)[1], options={})

        monkeypatch.setattr(storage, "_resolve", fake)

    return apply


@pytest.fixture
def memory_fs(monkeypatch):
    monkeypatch.setattr(MemoryFileSystem, "store", {})
    monkeypatch.setattr(MemoryFileSystem, "pseudo_dirs", [""])
    return MemoryFileSystem()


def _sample() -> xr.Dataset:
    tas = np.zeros((10, 4, 5), dtype="float32")
    return xr.Dataset(
        {"tas": (("time", "lat", "lon"), tas, {"units": "K", "long_name": "Near-surface air temperature"})},
        coords={"time": np.arange(10), "lat": np.linspace(-45, 45, 4), "lon": np.linspace(0, 288, 5)},
        attrs={"title": "Sample store", "history": "x" * 500},
    )


# --- resolving locations ---------------------------------------------------


def test_resolve_gcs_without_credentials_in_options():
    loc = storage._resolve("gs://leap-scratch/jdoe/", allow_s3=False)
    assert (loc.scheme, loc.url, loc.display, loc.options) == ("gs", "gs://leap-scratch/jdoe", "gs://leap-scratch/jdoe", {})


@pytest.mark.parametrize("endpoint", OSN_ENDPOINTS)
def test_resolve_osn_https_as_anonymous_s3(endpoint):
    loc = storage._resolve(f"{endpoint}/leap-pangeo-manual/x/store.zarr", allow_s3=False)
    assert loc.url == "s3://leap-pangeo-manual/x/store.zarr"
    assert loc.display == f"{endpoint}/leap-pangeo-manual/x/store.zarr"
    assert loc.options == {"anon": True, "client_kwargs": {"endpoint_url": endpoint}}


def test_resolve_s3_only_where_allowed():
    loc = storage._resolve("s3://carbonplan-data-viewer/demo/a.zarr/", allow_s3=True)
    assert (loc.url, loc.options) == ("s3://carbonplan-data-viewer/demo/a.zarr", {"anon": True})
    with pytest.raises(LeapError, match="Unsupported location"):
        storage._resolve("s3://carbonplan-data-viewer/demo", allow_s3=False)


@pytest.mark.parametrize(
    "bad",
    ["/home/jovyan/data.nc", "http://example.org/x.zarr", "https://example.org/x.zarr",
     "https://nyu1.osn.mghpcc.org.evil.org/b/x", "memory://b/x", "gs://", ""],
)
def test_resolve_refuses_other_locations(bad):
    with pytest.raises(LeapError, match="Unsupported location"):
        storage._resolve(bad, allow_s3=True)


def test_osn_url_needs_a_bucket():
    with pytest.raises(LeapError, match="Add a bucket"):
        storage._resolve("https://nyu1.osn.mghpcc.org/", allow_s3=False)


# --- describe_store --------------------------------------------------------


def test_describe_zarr_reports_structure_without_reading_values(tmp_path, redirect):
    path = tmp_path / "leap-scratch" / "jdoe" / "sample.zarr"
    ds = _sample()
    ds.to_zarr(path, encoding={"tas": {"chunks": (5, 4, 5)}})
    # Corrupt every data chunk: reading any tas value now fails.
    for chunk in (path / "tas").rglob("*"):
        if chunk.is_file() and chunk.name != "zarr.json":
            chunk.write_bytes(b"not a valid chunk")
    with pytest.raises(Exception):
        xr.open_dataset(path, engine="zarr").tas.values

    redirect(f"{tmp_path}/")
    text = storage.describe_store("gs://leap-scratch/jdoe/sample.zarr")
    assert "Format: Zarr (v3)" in text
    assert "time: 10, lat: 4, lon: 5" in text
    assert "- tas (time, lat, lon) float32, chunks (5, 4, 5) ~400 B, units K: Near-surface air temperature" in text
    assert f"Estimated size: {human_bytes(ds.nbytes)}" in text
    assert "- title: Sample store" in text
    assert "- history: " + "x" * 199 + "…" in text
    assert len(text) <= MAX_CHARS


def test_describe_netcdf(tmp_path, redirect):
    (tmp_path / "bucket").mkdir()
    _sample().to_netcdf(tmp_path / "bucket" / "sample.nc", engine="h5netcdf",
                        encoding={"tas": {"chunksizes": (5, 4, 5)}})
    redirect(f"{tmp_path}/")
    text = storage.describe_store("https://nyu1.osn.mghpcc.org/bucket/sample.nc")
    assert text.startswith("# https://nyu1.osn.mghpcc.org/bucket/sample.nc")
    assert "Format: NetCDF" in text
    assert "tas (time, lat, lon) float32, chunks (5, 4, 5)" in text


def test_describe_caps_long_variable_lists(tmp_path, redirect):
    many = xr.Dataset({f"v{i:03d}": (("x",), np.zeros(3), {"units": "1"}) for i in range(150)})
    many.to_zarr(tmp_path / "b" / "wide.zarr")
    redirect(f"{tmp_path}/")
    text = storage.describe_store("gs://b/wide.zarr")
    assert len(text) <= MAX_CHARS
    assert "## Data variables (150)" in text
    assert re.search(r"\(\+\d+ more: v\d{3}, ", text)


def test_describe_refuses_folders_and_other_files(tmp_path, redirect):
    folder = tmp_path / "b" / "folder"
    folder.mkdir(parents=True)
    (folder / "table.csv").write_text("a,b\n1,2\n")
    redirect(f"{tmp_path}/")
    for url in ["gs://b/folder", "gs://b/folder/table.csv"]:
        with pytest.raises(LeapError, match="not a Zarr store or a single NetCDF"):
            storage.describe_store(url)
    with pytest.raises(LeapError, match="not a pattern"):
        storage.describe_store("gs://b/folder/*.nc")


def test_describe_missing_file_is_a_clear_error(tmp_path, redirect):
    redirect(f"{tmp_path}/")
    with pytest.raises(LeapError, match=r"^Nothing found at gs://b/missing.nc\."):
        storage.describe_store("gs://b/missing.nc")


# --- list_storage ----------------------------------------------------------


def test_list_pages_folders_and_sizes(memory_fs, redirect):
    for i in range(150):
        memory_fs.pipe(f"/leap-scratch/jdoe/f{i:03d}.nc", b"x" * 2048)
    memory_fs.pipe("/leap-scratch/jdoe/run.zarr/zarr.json", b"{}")
    redirect("memory://")

    first = storage.list_storage("gs://leap-scratch/jdoe/")
    assert first.startswith("gs://leap-scratch/jdoe/: 151 entries (1 folders, 150 files), showing 1-100.")
    assert "- f000.nc  2.0 KiB" in first
    assert "describe_store" in first
    assert len(first) <= MAX_CHARS

    second = storage.list_storage("gs://leap-scratch/jdoe", cursor=CURSOR.search(first).group(1))
    assert "showing 101-151" in second
    assert "- run.zarr/" in second
    assert not CURSOR.search(second)


def test_list_a_file_and_an_empty_location(memory_fs, redirect):
    memory_fs.pipe("/b/one.nc", b"x")
    redirect("memory://")
    assert "is a file (1 B), not a folder" in storage.list_storage("gs://b/one.nc")
    with pytest.raises(LeapError, match="Nothing found"):
        storage.list_storage("gs://b/nothing-here")


def test_list_refuses_s3_and_bad_cursor(memory_fs, redirect):
    with pytest.raises(LeapError, match="Unsupported location"):
        storage.list_storage("s3://carbonplan-data-viewer/")
    memory_fs.pipe("/b/one.nc", b"x")
    redirect("memory://")
    with pytest.raises(LeapError, match="Invalid cursor"):
        storage.list_storage("gs://b", cursor="nope")


# --- error messages --------------------------------------------------------


class _DeniedFS:
    def __init__(self, method, exc):
        self.credentials = type("Credentials", (), {"method": method})()
        self.exc = exc

    def ls(self, path, detail=True):
        raise self.exc


@pytest.mark.parametrize(
    ("url", "method", "exc", "message"),
    [
        ("gs://leap-persistent/jdoe", "anon", OSError("Forbidden: leap-persistent"),
         "No GCS credentials found; this tool works on the LEAP hub."),
        ("gs://leap-persistent/jdoe", "google_default", OSError("Forbidden: leap-persistent"),
         "Access denied to gs://leap-persistent/jdoe. Your account cannot read this path."),
        ("https://nyu1.osn.mghpcc.org/private/x", None, PermissionError("AccessDenied"),
         "Access denied to https://nyu1.osn.mghpcc.org/private/x. This bucket does not allow anonymous reads"),
    ],
)
def test_access_errors_become_one_line_messages(monkeypatch, url, method, exc, message):
    monkeypatch.setattr(storage, "_filesystem", lambda loc: (_DeniedFS(method, exc), "path"))
    with pytest.raises(LeapError) as info:
        storage.list_storage(url)
    assert str(info.value).startswith(message)
    assert "\n" not in str(info.value)
