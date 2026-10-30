"""Read-only inspection of LEAP storage.

GCS goes through gcsfs with default credentials (the pod's identity on the hub).
OSN and s3:// go through s3fs with anon=True. No credentials are read or stored here.
"""

import math
import posixpath
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import fsspec
import xarray as xr

from .common import (
    PAGE_BUDGET,
    LeapError,
    decode_cursor,
    encode_cursor,
    fit_page,
    human_bytes,
    one_line,
    parse_osn_url,
)

LIST_PAGE_SIZE = 100
NETCDF_SUFFIXES = (".nc", ".nc4")
NETCDF_BLOCK_SIZE = 256 * 1024
ZARR_MARKERS = {"zarr.json": "Zarr (v3)", ".zmetadata": "Zarr (v2, consolidated)", ".zgroup": "Zarr (v2)"}
MAX_ATTRS = 20
ATTRS_BUDGET = 1500
COORDS_BUDGET = 1500
VARIABLES_BUDGET = 3500


@dataclass(frozen=True)
class Location:
    scheme: str  # "gs", "s3" or "osn"
    url: str  # what fsspec opens, e.g. "gs://bucket/key" or "s3://bucket/key"
    display: str  # what the researcher wrote, normalized
    options: dict[str, Any] = field(default_factory=dict)


def _resolve(path: str, *, allow_s3: bool) -> Location:
    """Map a gs://, s3:// (if allowed) or OSN https URL to a Location; refuse anything else."""
    parts = urlsplit(path.strip())
    scheme, host = parts.scheme.lower(), parts.netloc.lower()
    if scheme in ("gs", "gcs") and host:
        key = f"{host}/{parts.path.strip('/')}".rstrip("/")
        return Location("gs", f"gs://{key}", f"gs://{key}")
    if scheme == "s3" and host and allow_s3:
        key = f"{host}/{parts.path.strip('/')}".rstrip("/")
        return Location("s3", f"s3://{key}", f"s3://{key}", {"anon": True})
    osn = parse_osn_url(path)
    if osn:
        if not osn.key:
            raise LeapError(f"Add a bucket to the OSN URL, for example {osn.endpoint}/leap-pangeo-manual/")
        return Location("osn", osn.s3_url, f"{osn.endpoint}/{osn.key}", osn.storage_options)

    accepted = "gs://<bucket>/<path>, " + ("s3://<bucket>/<path>, " if allow_s3 else "")
    accepted += "or an OSN URL (https://nyu1.osn.mghpcc.org/<bucket>/<path> or https://ncsa.osn.xsede.org/<bucket>/<path>)"
    raise LeapError(f"Unsupported location {path.strip()!r}. Use {accepted}.")


def _filesystem(loc: Location) -> tuple[fsspec.AbstractFileSystem, str]:
    return fsspec.core.url_to_fs(loc.url, **loc.options)


def _explain(exc: Exception, loc: Location, fs: fsspec.AbstractFileSystem) -> str | None:
    """A one-line message for common storage failures, or None to let the error through."""
    denied = (
        isinstance(exc, PermissionError)
        or getattr(exc, "code", None) in (401, 403)
        or str(exc).startswith("Forbidden")
    )
    if denied and loc.scheme == "gs":
        if getattr(getattr(fs, "credentials", None), "method", None) == "anon":
            return "No GCS credentials found; this tool works on the LEAP hub."
        return f"Access denied to {loc.display}. Your account cannot read this path."
    if denied:
        return f"Access denied to {loc.display}. This bucket does not allow anonymous reads, so this tool cannot open it."
    if isinstance(exc, FileNotFoundError):
        return f"Nothing found at {loc.display}. Check the spelling, or list the parent folder with list_storage."
    return None


@contextmanager
def _friendly_errors(loc: Location, fs: fsspec.AbstractFileSystem) -> Iterator[None]:
    try:
        yield
    except LeapError:
        raise
    except Exception as exc:
        message = _explain(exc, loc, fs)
        if message is None:
            raise
        raise LeapError(message) from exc


def list_storage(path: str, cursor: str = "") -> str:
    loc = _resolve(path, allow_s3=False)
    start = decode_cursor(cursor)
    fs, root = _filesystem(loc)
    with _friendly_errors(loc, fs):
        entries = fs.ls(root, detail=True)

    # (name, is_folder, size); some stores also list the folder itself, so drop that.
    rows = sorted(
        (posixpath.basename(e["name"].rstrip("/")), e.get("type") == "directory", e.get("size") or 0)
        for e in entries
        if not (e.get("type") == "directory" and e["name"].rstrip("/") == root)
    )
    only = entries[0] if len(entries) == 1 else {}
    if only.get("type") != "directory" and only.get("name", "").rstrip("/") == root:
        size = human_bytes(only.get("size") or 0)
        return f"{loc.display} is a file ({size}), not a folder. Use describe_store on it if it is a .nc file."
    if not rows:
        return f"{loc.display}/ is empty."
    if start >= len(rows):
        return f"No more entries: {loc.display}/ has {len(rows)}. Leave cursor empty to start again."

    lines = [f"- {name}/" if is_folder else f"- {name}  {human_bytes(size)}" for name, is_folder, size in rows]
    end = fit_page(lines, start, LIST_PAGE_SIZE)
    folders = sum(1 for _, is_folder, _ in rows if is_folder)
    out = [
        f"{loc.display}/: {len(rows)} entries ({folders} folders, {len(rows) - folders} files), "
        f"showing {start + 1}-{end}. Folders end with /.",
        "",
        *lines[start:end],
        "",
    ]
    if end < len(rows):
        out.append(f'More entries: call list_storage again with the same path and cursor="{encode_cursor(end)}".')
    if any(
        name.endswith(".zarr") if is_folder else name.lower().endswith(NETCDF_SUFFIXES)
        for name, is_folder, _ in rows[start:end]
    ):
        out.append("Next: describe_store(url) shows the variables and size of a .zarr store or .nc file.")
    return "\n".join(out)


def describe_store(url: str) -> str:
    loc = _resolve(url, allow_s3=True)
    if any(c in loc.url for c in "*?["):
        raise LeapError("describe_store takes one Zarr store or one .nc file, not a pattern. Use list_storage to pick one.")
    fs, root = _filesystem(loc)
    with _friendly_errors(loc, fs):
        if root.lower().endswith(NETCDF_SUFFIXES):
            # s3fs reads 50 MiB per block by default, so HDF5's scattered metadata
            # reads took ~2 min on a 14 GB OSN file; small cached blocks take ~1 s.
            with (
                fs.open(root, "rb", block_size=NETCDF_BLOCK_SIZE, cache_type="blockcache") as f,
                _open_lazily(f, engine="h5netcdf") as ds,
            ):
                return _summarize(ds, loc, "NetCDF")
        kind = next((label for marker, label in ZARR_MARKERS.items() if fs.exists(f"{root}/{marker}")), None)
        if kind is None:
            raise LeapError(
                f"{loc.display} is not a Zarr store or a single NetCDF (.nc) file, so describe_store "
                "will not open it. If it is a folder, use list_storage to find a .zarr store or .nc file inside."
            )
        options = {"storage_options": loc.options} if loc.options else {}
        with _open_lazily(loc.url, engine="zarr", **options) as ds:
            return _summarize(ds, loc, kind)


def _open_lazily(target: Any, **kwargs: Any) -> xr.Dataset:
    # chunks={} gives dask arrays in the store's own chunks, so no data values are read.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return xr.open_dataset(target, chunks={}, **kwargs)


def _variable_line(name: Any, var: xr.Variable) -> str:
    text = f"- {name} ({', '.join(map(str, var.dims))}) {var.dtype}"
    if var.chunks:
        shape = [c[0] for c in var.chunks]
        text += f", chunks ({', '.join(map(str, shape))}) ~{human_bytes(math.prod(shape) * var.dtype.itemsize)}"
    units = var.attrs.get("units") or var.encoding.get("units")
    text += f", units {one_line(units, 40)}" if units else ", no units"
    if var.attrs.get("long_name"):
        text += f": {one_line(var.attrs['long_name'], 60)}"
    return text


def _capped(lines: list[str], names: list[Any], budget: int, max_items: int | None = None) -> list[str]:
    """Keep the lines that fit; name the rest on one line."""
    end = fit_page(lines, 0, max_items or len(lines) or 1, budget=budget)
    if end == len(lines):
        return lines
    rest = ", ".join(map(str, names[end:]))
    return lines[:end] + [f"(+{len(lines) - end} more: {one_line(rest, 600)})"]


def _summarize(ds: xr.Dataset, loc: Location, kind: str) -> str:
    attrs = _capped([f"- {k}: {one_line(v, 200)}" for k, v in ds.attrs.items()], list(ds.attrs), ATTRS_BUDGET, MAX_ATTRS)
    coord_names, data_names = list(ds.coords), list(ds.data_vars)
    coords = _capped([_variable_line(n, ds[n].variable) for n in coord_names], coord_names, COORDS_BUDGET)
    data = _capped([_variable_line(n, ds[n].variable) for n in data_names], data_names, VARIABLES_BUDGET)

    sections = [
        f"# {loc.display}",
        f"Format: {kind}. Opened lazily; no data values were read.",
        f"Estimated size: {human_bytes(ds.nbytes)} uncompressed (from nbytes; usually smaller on disk).",
        "",
        "## Dimensions",
        ", ".join(f"{k}: {v}" for k, v in ds.sizes.items()) or "none",
        "",
        f"## Coordinates ({len(coord_names)})",
        *(coords or ["none"]),
        "",
        f"## Data variables ({len(data_names)})",
        *(data or ["none"]),
        "",
        f"## Global attributes ({len(ds.attrs)})",
        *(attrs or ["none"]),
    ]
    return "\n".join(sections)
