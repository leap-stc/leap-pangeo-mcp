"""Docs tests run against the bundled search index (conftest makes live fetches fail)."""

import re

from leap_pangeo_mcp.core import docs
from leap_pangeo_mcp.core.common import MAX_CHARS


def _urls(text: str) -> list[str]:
    return re.findall(r"^   (https://\S+)$", text, re.M)


def test_html_is_stripped_and_entities_decoded():
    assert docs.html_to_text("<p>Tom &amp; <code>dask-gateway</code></p><ul><li>a</li><li>b</li></ul>") == (
        "Tom & dask-gateway a b"
    )


def test_sections_have_page_urls_and_page_titles():
    sections, from_snapshot = docs.load_sections()
    assert from_snapshot is True
    by_url = {s["url"]: s for s in sections}
    assert by_url["https://leap-stc.github.io/compute/dask/#cleaning-up"]["title"] == "Dask Guide: Cleaning up"
    assert "https://leap-stc.github.io/" in by_url
    assert not any(re.search(r"</?(p|li|ul|code|pre)>", s["text"]) for s in sections)


def test_ranked_results_with_links_and_short_excerpts():
    text = docs.search_docs("How do I shut down my Dask cluster?")
    urls = _urls(text)
    assert urls[0] == "https://leap-stc.github.io/compute/dask/#cleaning-up"
    assert len(urls) == docs.TOP_N
    assert "cluster.shutdown()" in text
    assert len(text) <= MAX_CHARS
    for excerpt in re.findall(r"^   (?!https://)(.+)$", text, re.M):
        assert len(excerpt) <= docs.EXCERPT_CHARS
        assert "<p>" not in excerpt


def test_scratch_retention_question_finds_the_buckets_page():
    urls = _urls(docs.search_docs("leap-scratch 7 days"))
    assert "https://leap-stc.github.io/data/data_locations/#leap-cloud-buckets" in urls[:3]


def test_plural_and_suffix_forms_match():
    assert "https://leap-stc.github.io/compute/compute_scaling/#gpu" in _urls(docs.search_docs("GPUs"))


def test_no_match_and_empty_query():
    assert docs.search_docs("qwxzv").startswith("No LEAP docs sections match")
    assert docs.search_docs("how do I").startswith("Pass a few keywords")
