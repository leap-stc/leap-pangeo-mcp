# SPEC: leap-pangeo-mcp

Source of truth: "LEAP Pangeo MCP: Research and Build Plan" (approved 2026-10-29).
https://claude.ai/artifact/28y4toR7519cTJxpcPBM5Z

## Objective

Build `leap-pangeo-mcp`, a Python MCP server that gives the AI agents in LEAP's
JupyterHub (Claude, Codex, Gemini via Jupyter AI) working knowledge of LEAP
Pangeo's tools and resources, shipped in the `pangeo-jupyter-ai` image.

## Architecture (fixed)

- One Python package, three layers:
  - `core/`: plain functions, one module per source (`catalog.py`, `docs.py`,
    `storage.py`, `hub.py`; later `dask.py`, `batch.py`). No MCP imports.
  - `server.py`: FastMCP wrapper from the official `mcp` SDK. Sets server
    `instructions`, marks read-only tools `readOnlyHint`, exposes console
    script `leap-pangeo-mcp` running over stdio.
  - `snapshots/`: catalog JSON and docs search index bundled at build time,
    used when live fetches fail.
- Transport: stdio only.
- Runs inside each researcher's pod with that pod's credentials. No hosting.
- Registered system-wide in the image via
  `/srv/conda/envs/notebook/etc/jupyter/jupyter_server_config.d/leap-pangeo-mcp.json`
  setting `PersonaManager.builtin_mcp_servers`. That list must include both:
  - `{"type": "http", "name": "Jupyter MCP Server", "url": "http://localhost:3001/mcp", "headers": []}`
  - `{"name": "leap-pangeo", "command": "/srv/conda/envs/notebook/bin/leap-pangeo-mcp", "args": [], "env": []}`
- Terminal agents: `managedMcpServers` in `/etc/claude-code/managed-settings.json`
  (not `managed-mcp.json`), `mcpServers` in `/etc/gemini-cli/settings.json`,
  Codex managed config under `/etc/codex/` (file name to confirm).
- Knowledge layer: one LEAP primer, placed in the FastMCP `instructions`, a
  `leap_overview` tool, and `/etc/claude-code/CLAUDE.md`.

## Data sources

| Source | Access |
| --- | --- |
| Catalog | `https://raw.githubusercontent.com/leap-stc/data-management/main/catalog/output/consolidated-web-catalog.json` |
| Docs | `https://leap-stc.github.io/search/search_index.json` |
| GCS | `gs://leap-scratch`, `gs://leap-persistent`, `gs://leap-persistent-ro` via gcsfs, pod credentials |
| OSN | `https://nyu1.osn.mghpcc.org` (catalog also uses `https://ncsa.osn.xsede.org`) via s3fs, anonymous reads |
| Hub env | `JUPYTERHUB_USER`, `JUPYTER_IMAGE_SPEC`, CPU/memory limits, `nvidia-smi` |

## Scope: Phase 1 (this build)

Eight read-only tools:

| Tool | Does |
| --- | --- |
| `leap_overview` | Returns the LEAP primer: buckets, rules, where to get help |
| `search_datasets` | Keyword and tag search over the catalog; returns title, tags, store ids |
| `get_dataset` | Full catalog entry plus a ready-to-run `xr.open_dataset` snippet from `xarray_open_kwargs` |
| `describe_store` | Lazily opens a Zarr or single NetCDF URL; returns dims, variables, chunks, attrs, estimated size |
| `list_storage` | Lists a `gs://` or OSN prefix, capped and paged, with sizes |
| `search_docs` | Ranked passages from the LEAP docs with links |
| `get_my_environment` | Username, image tag, CPU/memory limits, GPU, personal bucket paths |
| `how_to` | Tested LEAP snippets: write to my folder, start a Dask cluster, copy to OSN |

## Out of scope for Phase 1

- Any write or action tool (Phase 2: `dask_clusters`, `draft_batch_job`,
  `validate_catalog_entry`; Phase 3: `batch_job_status`, `search_inventory`,
  `earth2_resources`).
- HTTP transport, a hosted server, or `jupyter_server_mcp.tools` entry points.
- Changes to the `pangeo-jupyter-ai` image repo before step 7 of PLAN.md.

## Runtime requirements

- No credentials in the package, image or config.
- Every tool has a timeout, caps list sizes, pages with a `cursor`, and returns
  compact text.
- Store inspection is lazy (`chunks={}`); never loads array values.
- `describe_store` refuses paths that are not Zarr or a single NetCDF file.
- Live catalog and docs fetches cache for one hour in `/tmp`, falling back to
  `snapshots/`.

## Acceptance criteria (Phase 1)

1. `leap-pangeo-mcp` starts over stdio and lists exactly the eight tools.
2. Each tool works under the MCP Inspector and in Claude Code locally
   (catalog, docs, OSN tools).
3. On the hub, via `~/.jupyter/mcp_settings.json`, Claude, Codex and Gemini each
   call the tools against real GCS paths.
4. The agent answers the eval questions (PLAN.md step 1) using the right tool.
5. Image build installs the pinned package and config; the smoke test starts the
   server and lists its tools.
6. Pilot users run the new image tag via Image > Other... before the 2i2c Image
   Change Request is filed.
