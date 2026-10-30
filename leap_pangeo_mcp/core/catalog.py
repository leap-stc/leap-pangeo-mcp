"""Search and read the LEAP data catalog (https://catalog.leap.columbia.edu)."""

import difflib
import keyword
from collections import Counter
from typing import Any

from .common import (
    PAGE_BUDGET,
    decode_cursor,
    encode_cursor,
    fetch_json,
    fit_page,
    one_line,
    parse_osn_url,
    snapshot_note,
)

CATALOG_URL = (
    "https://raw.githubusercontent.com/leap-stc/data-management/main/"
    "catalog/output/consolidated-web-catalog.json"
)
SNAPSHOT = "consolidated-web-catalog.json"
SEARCH_PAGE_SIZE = 10
STORE_PAGE_SIZE = 20
MAX_STORE_IDS = 8


def load_catalog() -> tuple[list[dict[str, Any]], bool]:
    """Return (entries, from_snapshot)."""
    data, from_snapshot = fetch_json(CATALOG_URL, SNAPSHOT)
    return [e for e in data if isinstance(e, dict) and e.get("title")], from_snapshot


def _tags(entry: dict) -> list[str]:
    return [str(t) for t in entry.get("tags") or []]


def _stores(entry: dict) -> list[dict]:
    return [s for s in entry.get("stores") or [] if isinstance(s, dict)]


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def search_datasets(query: str = "", tag: str = "", cursor: str = "") -> str:
    entries, from_snapshot = load_catalog()
    start = decode_cursor(cursor)
    terms = query.lower().split()
    tag_key = _norm(tag)

    hits = []
    for entry in entries:
        tags = _tags(entry)
        if tag_key and tag_key not in {_norm(t) for t in tags}:
            continue
        haystack = " ".join([entry["title"], str(entry.get("description") or ""), *tags]).lower()
        if all(term in haystack for term in terms):
            hits.append(entry)
    # Datasets whose title contains every term come first; otherwise keep catalog order.
    hits.sort(key=lambda e: not all(term in e["title"].lower() for term in terms))

    parts = []
    if terms:
        parts.append(f"matching {query.strip()!r}")
    if tag_key:
        parts.append(f"tagged {tag.strip()!r}")
    criteria = " and ".join(parts) or "in the catalog"
    found = f"{len(hits)} dataset{'' if len(hits) == 1 else 's'} {criteria}"
    note = [snapshot_note("catalog")] if from_snapshot else []

    if not hits:
        common_tags = ", ".join(t for t, _ in Counter(t for e in entries for t in _tags(e)).most_common(30))
        return "\n".join(
            [
                f"No datasets {criteria}. Try one broader word, or call search_datasets() "
                "with no arguments to list every dataset.",
                f"Common tags: {common_tags}",
                *note,
            ]
        )

    blocks = [_summary(entry) for entry in hits]
    if start >= len(blocks):
        return f"No more results: {found}. Leave cursor empty to start again."
    end = fit_page(blocks, start, SEARCH_PAGE_SIZE)
    lines = [f"{found}. Showing {start + 1}-{end}.", "", "\n\n".join(blocks[start:end]), ""]
    if end < len(hits):
        lines.append(
            f'More results: call search_datasets again with the same query and tag and cursor="{encode_cursor(end)}".'
        )
    lines.append("Next: get_dataset(title) gives store URLs and a snippet to open the data.")
    return "\n".join(lines + note)


def _summary(entry: dict) -> str:
    stores = _stores(entry)
    ids = [str(s.get("id")) for s in stores[:MAX_STORE_IDS]]
    if len(stores) > MAX_STORE_IDS:
        ids.append(f"(+{len(stores) - MAX_STORE_IDS} more)")
    return "\n".join(
        [
            f"### {entry['title']}",
            f"Tags: {', '.join(_tags(entry)) or 'none'}",
            one_line(entry.get("description") or "No description.", 200),
            f"Stores: {', '.join(ids) if ids else 'none listed'}",
        ]
    )


def get_dataset(title: str, cursor: str = "") -> str:
    entries, from_snapshot = load_catalog()
    note = [snapshot_note("catalog")] if from_snapshot else []
    wanted = _norm(title)
    if not wanted:
        return "Pass a dataset title. Use search_datasets to find one."

    entry = next((e for e in entries if _norm(e["title"]) == wanted), None)
    if entry is None:
        return "\n".join([_closest_titles(title, entries), *note])

    start = decode_cursor(cursor)
    stores = _stores(entry)
    if start == 0:
        header = _entry_header(entry)
    else:
        header = f"# {entry['title']} (stores continued)"
    if not stores:
        return "\n".join([header, "", "This entry lists no stores.", *note])
    if start >= len(stores):
        return f"No more stores: {entry['title']!r} has {len(stores)}. Leave cursor empty to start again."

    blocks = [_store_block(store) for store in stores]
    end = fit_page(blocks, start, STORE_PAGE_SIZE, budget=PAGE_BUDGET - len(header))
    shown = f"showing {start + 1}-{end}" if (start, end) != (0, len(stores)) else "all shown"
    lines = [header, "", f"## Stores ({len(stores)}, {shown})", "", "\n\n".join(blocks[start:end]), ""]
    if end < len(stores):
        lines.append(f'More stores: call get_dataset again with the same title and cursor="{encode_cursor(end)}".')
    lines.append("Next: describe_store(url) lists a store's variables, chunks and size without loading data.")
    return "\n".join(lines + note)


def _closest_titles(title: str, entries: list[dict]) -> str:
    titles = [e["title"] for e in entries]
    wanted = _norm(title)
    contains = [t for t in titles if wanted in _norm(t) or _norm(t) in wanted]
    lowered = {_norm(t): t for t in titles}
    similar = [lowered[t] for t in difflib.get_close_matches(wanted, list(lowered), n=5, cutoff=0.3)]
    closest = list(dict.fromkeys(contains + similar))[:5]
    if not closest:
        return f"No dataset titled {title!r}, and no similar titles. Use search_datasets to find one."
    listed = "\n".join(f"- {t}" for t in closest)
    return f"No dataset titled {title!r}. Closest titles:\n{listed}\nCall get_dataset with one of these exact titles."


def _entry_header(entry: dict) -> str:
    provenance = entry.get("provenance") or {}
    license_text = provenance.get("license") or "not stated"
    if provenance.get("license_link"):
        license_text += f" ({provenance['license_link']})"
    providers = []
    for p in provenance.get("providers") or []:
        roles = ", ".join(p.get("roles") or [])
        text = p.get("name") or "unnamed provider"
        text += f" ({roles})" if roles else ""
        text += f" {p['url']}" if p.get("url") else ""
        providers.append(text)
    maintainers = [
        f"{m.get('name') or m.get('github')}" + (f" (@{m['github']})" if m.get("github") else "")
        for m in entry.get("maintainers") or []
    ]
    return "\n".join(
        [
            f"# {entry['title']}",
            "",
            one_line(entry.get("description") or "No description.", 1500),
            "",
            f"- License: {license_text}",
            f"- Provenance: {'; '.join(providers) or 'not stated'}",
            f"- Maintainers: {', '.join(maintainers) or 'not stated'}",
            f"- Tags: {', '.join(_tags(entry)) or 'none'}",
        ]
    )


def _store_block(store: dict) -> str:
    public = {True: "yes", False: "no"}.get(store.get("public"), "unknown")
    return "\n".join(
        [
            f"### {store.get('id')}",
            f"- Name: {one_line(store.get('name') or '-', 200)}",
            f"- URL: {store.get('url')}",
            f"- Public: {public}",
            "```python",
            open_snippet(store),
            "```",
        ]
    )


def open_snippet(store: dict) -> str:
    """Build `xr.open_dataset(url, **xarray_open_kwargs)` from the store's own kwargs.

    OSN https URLs become anonymous s3:// reads (see OsnPath), with the OSN access
    options merged into the store's own storage_options.
    """
    url = store.get("url")
    kwargs = dict(store.get("xarray_open_kwargs") or {})
    osn = parse_osn_url(url) if isinstance(url, str) else None
    if osn and osn.key:
        url = osn.s3_url
        kwargs["storage_options"] = {**(kwargs.get("storage_options") or {}), **osn.storage_options}
    args = [repr(url)]
    if all(isinstance(k, str) and k.isidentifier() and not keyword.iskeyword(k) for k in kwargs):
        args += [f"{k}={v!r}" for k, v in kwargs.items()]
    else:
        args.append(f"**{kwargs!r}")
    return f"import xarray as xr\nds = xr.open_dataset({', '.join(args)})"
