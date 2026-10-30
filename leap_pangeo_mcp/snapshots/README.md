Bundled copies of the LEAP catalog JSON and docs search index. The server fetches
both live (cached for one hour under /tmp/leap-pangeo-mcp/) and uses these copies
only when the live fetch fails. The tests run against them.

| File | Source | Downloaded |
| --- | --- | --- |
| `consolidated-web-catalog.json` | https://raw.githubusercontent.com/leap-stc/data-management/main/catalog/output/consolidated-web-catalog.json | 2026-10-29 18:43 UTC (32 datasets) |
| `search_index.json` | https://leap-stc.github.io/search/search_index.json | 2026-10-29 18:43 UTC (164 sections; site last modified 2026-08-04 19:24 UTC) |

To refresh, download each file again with `curl -fsSL <source> -o <file>`, update
the dates above, and rerun `python -m pytest -q` (some tests name catalog entries).
