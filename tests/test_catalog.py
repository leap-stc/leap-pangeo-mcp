"""Catalog tests run against the bundled snapshot (conftest makes live fetches fail)."""

import re

import pytest

from leap_pangeo_mcp.core import catalog
from leap_pangeo_mcp.core.common import MAX_CHARS, OSN_ENDPOINTS

CURSOR = re.compile(r'cursor="([^"]+)"')


def _titles(text: str) -> list[str]:
    return re.findall(r"^### (.+)$", text, re.M)


def test_search_is_case_insensitive_over_title_description_and_tags():
    assert "ARCO ERA5" in _titles(catalog.search_datasets("era5"))
    assert "ARCO ERA5" in _titles(catalog.search_datasets("ERA5"))
    # "downscaling" appears in the CorrDiff tags and description, not its title.
    assert "CorrDiff NYC Downscaling Datasets" in _titles(catalog.search_datasets("downscaling"))
    assert "AWS NOAA Optimum Interpolated SST" in _titles(catalog.search_datasets("oisst"))  # tag only


def test_every_query_word_must_match():
    titles = _titles(catalog.search_datasets("sea surface"))
    assert titles
    assert "ClimSim" not in titles


def test_result_shows_tags_description_and_store_ids():
    text = catalog.search_datasets("ARCO ERA5")
    assert "Tags: " in text
    assert "0_25_deg_pressure_surface_levels" in text
    assert "get_dataset" in text
    assert "snapshot" in text  # the offline fallback is reported


def test_long_store_lists_are_capped_in_search():
    text = catalog.search_datasets("corrdiff")
    assert "(+34 more)" in text


def test_tag_filter_is_exact():
    titles = _titles(catalog.search_datasets(tag="SST"))
    assert "AWS NOAA Optimum Interpolated SST" in titles
    assert _titles(catalog.search_datasets(tag="ss")) == []


def test_listing_everything_pages_ten_at_a_time():
    entries, _ = catalog.load_catalog()
    seen, cursor = [], ""
    for _ in range(10):
        text = catalog.search_datasets(cursor=cursor)
        assert len(text) <= MAX_CHARS
        page = _titles(text)
        assert 1 <= len(page) <= catalog.SEARCH_PAGE_SIZE
        seen += page
        match = CURSOR.search(text)
        if not match:
            break
        cursor = match.group(1)
    assert seen == [e["title"] for e in entries]


def test_no_match_suggests_tags():
    text = catalog.search_datasets("zzzz-no-such-thing")
    assert text.startswith("No datasets matching")
    assert "Common tags:" in text


def test_get_dataset_returns_entry_stores_and_runnable_snippets():
    text = catalog.get_dataset("arco era5")
    assert text.startswith("# ARCO ERA5")
    for piece in ["License: Apache Version 2.0", "Provenance:", "Maintainers:", "(@jbusecke)",
                  "0_25_deg_model_levels", "gs://gcp-public-data-arco-era5/ar/model-level-1h-0p25deg.zarr-v1",
                  "Public: yes"]:
        assert piece in text, piece
    snippets = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(snippets) == 2
    assert "xr.open_dataset('gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3', engine='zarr')" in snippets[0]
    for code in snippets:
        compile(code, "snippet", "exec")


def test_snippet_uses_the_stores_own_kwargs():
    store = {"url": "gs://b/x.zarr", "xarray_open_kwargs": {"engine": "zarr", "chunks": {}, "consolidated": False}}
    assert catalog.open_snippet(store).endswith(
        "xr.open_dataset('gs://b/x.zarr', engine='zarr', chunks={}, consolidated=False)"
    )
    assert catalog.open_snippet({"url": "gs://b/x.zarr"}).endswith("xr.open_dataset('gs://b/x.zarr')")


@pytest.mark.parametrize("endpoint", OSN_ENDPOINTS)
def test_snippet_reads_osn_https_stores_as_anonymous_s3(endpoint):
    # Over plain HTTPS, a Zarr v3 store without consolidated metadata (e.g. OSTIA) opens empty.
    store = {"url": f"{endpoint}/leap-pangeo-pipeline/OSTIA/OSTIA.zarr", "xarray_open_kwargs": {"engine": "zarr"}}
    assert catalog.open_snippet(store).endswith(
        "xr.open_dataset('s3://leap-pangeo-pipeline/OSTIA/OSTIA.zarr', engine='zarr', "
        f"storage_options={{'anon': True, 'client_kwargs': {{'endpoint_url': '{endpoint}'}}}})"
    )


@pytest.mark.parametrize(
    "url",
    ["gs://leap-persistent-ro/data-library-manual/CESM.zarr", "s3://carbonplan-data-viewer/demo/a.zarr",
     "https://example.org/x.zarr", "https://nyu1.osn.mghpcc.org.evil.org/b/x.zarr"],
)
def test_snippet_leaves_other_urls_unchanged(url):
    store = {"url": url, "xarray_open_kwargs": {"engine": "zarr"}}
    assert catalog.open_snippet(store).endswith(f"xr.open_dataset({url!r}, engine='zarr')")


def test_get_dataset_shows_catalog_url_and_s3_snippet_for_osn():
    text = catalog.get_dataset("OSTIA Reprocessed")
    assert "- URL: https://nyu1.osn.mghpcc.org/leap-pangeo-pipeline/OSTIA/OSTIA.zarr" in text
    assert "xr.open_dataset('s3://leap-pangeo-pipeline/OSTIA/OSTIA.zarr', engine='zarr', storage_options=" in text


def test_unknown_title_returns_closest_titles():
    text = catalog.get_dataset("ERA5")
    assert text.startswith("No dataset titled 'ERA5'")
    assert "- ARCO ERA5" in text


def test_many_stores_are_paged_and_all_reachable():
    title = "CorrDiff NYC Downscaling Datasets"
    entry = next(e for e in catalog.load_catalog()[0] if e["title"] == title)
    seen, cursor = [], ""
    for _ in range(10):
        text = catalog.get_dataset(title, cursor=cursor)
        assert len(text) <= MAX_CHARS
        seen += _titles(text)
        match = CURSOR.search(text)
        if not match:
            break
        cursor = match.group(1)
    assert seen == [s["id"] for s in entry["stores"]]


def test_entry_without_stores():
    assert "This entry lists no stores." in catalog.get_dataset("CMIP6")
