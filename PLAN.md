# PLAN: leap-pangeo-mcp Phase 1

Authoritative with SPEC.md. Re-read both at each checkpoint.

## Steps

| # | Step | Done when | Status |
| --- | --- | --- | --- |
| 1 | Collect 15-20 real researcher questions from `#leap-pangeo`, `#technical_questions` and `data-management` issues | Questions saved in `evals/questions.md`; runs alongside steps 2-5, must finish before step 6 | Not started |
| 2 | Scaffold the package: `core/`, `server.py`, `snapshots/`, `pyproject.toml` with the `leap-pangeo-mcp` console script | `pip install -e .` works and the server starts with zero tools | Done (2026-10-29) |
| 3 | Build the eight Phase 1 tools with the mcp-builder skill (Python/FastMCP) | Each tool has a docstring and a unit test in `core/` | Done (2026-10-29) |
| 4 | Test outside Jupyter: MCP Inspector, then `claude mcp add leap -- leap-pangeo-mcp` | Acceptance criteria 1-2 met | Done (2026-10-30) |
| 5 | Test on own hub server: `pip install -e`, add to `~/.jupyter/mcp_settings.json`, try Claude, Codex, Gemini | Acceptance criterion 3 met | In progress |
| 6 | Run evals with step 1 questions; fix docstrings first | Acceptance criterion 4 met | Not started |
| 7 | Add to `pangeo-jupyter-ai` image: pinned install, `jupyter_server_config.d` JSON, CLI system configs, `/etc/claude-code/CLAUDE.md`; extend smoke test | Acceptance criterion 5 met | Not started |
| 8 | Pilot with 2-3 researchers for two weeks, then file the 2i2c Image Change Request | Acceptance criterion 6 met | Not started |

Phase 2 starts only after step 8. It is not part of this plan.

## Open questions

- Codex managed config file name under `/etc/codex/` for the version the build resolves.
- Whether each ACP agent actually connects to stdio servers passed in `session/new` (check in step 5).

## Parking lot

Issues found that are outside the current step. Record here; do not fix unless blocking.

- `mcp` 2.x renames `FastMCP` to `MCPServer`. The package pins `mcp<2` to match Jupyter AI 3.2's dependency chain; revisit when Jupyter AI moves to `mcp` 2.
- Catalog data (leap-stc/data-management): the 42 "CorrDiff NYC Downscaling Datasets" stores are `.nc` files but their `xarray_open_kwargs` say `engine: zarr`, so their `get_dataset` snippets fail as written. They are also marked `public: false`, yet anonymous reads from OSN worked on 2026-10-29.
- `https://ncsa.osn.xsede.org` timed out from a laptop on 2026-10-29 (curl too), while `nyu1.osn.mghpcc.org` answered in 0.2 s. 12 catalog stores use NCSA; re-check from the hub in step 5.
- Catalog data (leap-stc/data-management): the catalog publishes OSN `https://` store URLs, and over plain HTTPS a Zarr v3 store without consolidated metadata opens as an empty dataset with no error (HTTPS cannot list folders). This affects researchers outside the MCP too: anyone opening the catalog URL with `xr.open_dataset(url, engine="zarr")`. On 2026-10-30, 2 of the 9 public nyu1 Zarr stores opened empty this way, OSTIA Reprocessed and Caravan (both Zarr v3); both open fully as `s3://` with the OSN endpoint. Since the step 4 fix, `get_dataset` snippets rewrite every OSN URL (nyu1 and NCSA) to `s3://` with anonymous `storage_options`; the 12 NCSA stores are untested with this (see the NCSA item). The catalog itself, and catalog.leap.columbia.edu, still show the HTTPS URLs.
- Catalog data (leap-stc/data-management): the CASM store URL `https://nyu1.osn.mghpcc.org/leap-pangeo-pipeline/CASM/casm.zarr` does not exist, so its `get_dataset` snippet fails with `GroupNotFoundError`. The data is at `.../leap-pangeo-pipeline/CASM/obstore/casm.zarr` (Zarr v2, consolidated, 4 variables; checked with `describe_store` on 2026-10-30).
- OSTIA and Caravan have no consolidated metadata, so their `get_dataset` snippets open with xarray's "Failed to open Zarr store with consolidated metadata" `RuntimeWarning`. Harmless; the snippet does not add `consolidated=False` because it only adds the OSN access options to the catalog's own kwargs.
- `search_datasets("sea surface temperature")` misses "AWS NOAA Optimum Interpolated SST", whose entry only says "SST"; and `tag="sst"` misses HadISST and Geo-Polar SST, which lack the tag. Found on 2026-10-30 answering "What SST datasets does LEAP have?"; input for step 6 (docstrings, or synonyms in search).
- `tests/test_server.py` finds the server through `leap-pangeo-mcp` on `PATH`, so `.venv/bin/python -m pytest` without an activated venv errors on its 4 tests. Run `source .venv/bin/activate` first, or put `.venv/bin` on `PATH`.

## Deviations

Material changes from SPEC.md or this plan, with reason, impact and alternatives.

- 2026-10-29, step 1 order: step 1 runs in parallel with steps 2-5 instead of first. Reason: the Phase 1 tool list is already fixed in SPEC.md, so building does not depend on the questions. Impact: tool choices are not re-checked against real questions before building; step 6 (evals) is blocked until step 1 is done. Alternative: keep step 1 first and delay the build.
- 2026-10-30, step 3, `get_dataset` cursor: `get_dataset(title, cursor="")` takes an optional cursor, beyond the `get_dataset(title)` in the step 3 brief. Reason: SPEC.md requires every tool to page with a `cursor`, and the 42 stores of "CorrDiff NYC Downscaling Datasets" (one open snippet each) come to about 10,000 characters, over the 8,000-character cap. Impact: one optional argument; datasets that fit on one page behave as briefed. Alternative: drop stores past a cap, or cut the output without a way to reach the rest.
- 2026-10-30, step 3, dask and h5py as runtime dependencies: `pyproject.toml` declares `dask` and `h5py` beyond the seven runtime dependencies in the step 3 brief. Reason: `describe_store` opens stores with `chunks={}`, which needs dask, and h5netcdf 1.8 no longer installs h5py; both are needed for local testing in step 4 and already ship in the Pangeo image. Impact: `pip install` outside the image also installs dask and h5py; the image already has them. Alternative: keep them test-only and let `describe_store` fail outside the image.
- 2026-10-30, step 3, `core/common.py`: a helper module beside the five core modules in the step 3 brief. Reason: catalog, docs and storage share the cached fetch with snapshot fallback, cursors, the page budget and the error type; one module avoids three copies. Impact: none on the tools; it has no MCP imports and its own tests (`tests/test_common.py`). Alternative: repeat the helpers in each module.
- 2026-10-30, step 3, `list_storage` refuses `s3://`: it accepts only `gs://` and OSN `https://` folders, while `describe_store` also accepts `s3://` URLs. Reason: the step 3 brief lists only GCS and OSN for `list_storage`. Impact: folders in other S3 buckets cannot be listed, though single stores there can still be described. Alternative: accept `s3://` (anonymous) in `list_storage` too.
