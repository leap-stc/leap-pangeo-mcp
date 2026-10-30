"""Keyword search over the LEAP docs (https://leap-stc.github.io)."""

import math
import re
from html.parser import HTMLParser

from .common import fetch_json, one_line, snapshot_note

DOCS_INDEX_URL = "https://leap-stc.github.io/search/search_index.json"
SITE_URL = "https://leap-stc.github.io/"
SNAPSHOT = "search_index.json"
TOP_N = 5
TITLE_WEIGHT = 3.0
EXCERPT_CHARS = 400
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from get how i in is it me my of on or "
    "should the to use using what when where which why with you your".split()
)
_BLOCK_TAGS = frozenset("br div h1 h2 h3 h4 h5 h6 li ol p pre table td th tr ul".split())
_TOKEN = re.compile(r"[a-z0-9_]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _stems(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower())]


def _hits(term: str, stems: list[str]) -> int:
    # Longer terms also match words they start, e.g. "gateway" in "gateways".
    if len(term) >= 4:
        return sum(1 for s in stems if s.startswith(term))
    return stems.count(term)


def load_sections() -> tuple[list[dict[str, str]], bool]:
    """Return (sections, from_snapshot); each section has title, url and plain text."""
    data, from_snapshot = fetch_json(DOCS_INDEX_URL, SNAPSHOT)
    docs = [d for d in (data.get("docs") or [] if isinstance(data, dict) else []) if isinstance(d, dict)]
    page_titles = {
        d.get("location", ""): html_to_text(d.get("title") or "") for d in docs if "#" not in d.get("location", "")
    }
    sections = []
    for d in docs:
        location = d.get("location", "")
        title = html_to_text(d.get("title") or "")
        page_title = page_titles.get(location.split("#")[0], "")
        if page_title and page_title != title:
            title = f"{page_title}: {title}"
        sections.append({"title": title, "url": SITE_URL + location, "text": html_to_text(d.get("text") or "")})
    return sections, from_snapshot


def search_docs(query: str) -> str:
    terms = list(dict.fromkeys(_stem(t) for t in _TOKEN.findall(query.lower()) if t not in STOPWORDS))
    if not terms:
        return "Pass a few keywords, for example search_docs('dask gateway shutdown')."

    sections, from_snapshot = load_sections()
    sections = [s for s in sections if s["text"]]
    indexed = [(s, _stems(s["title"]), _stems(s["text"])) for s in sections]
    df = {t: sum(1 for _, title, text in indexed if _hits(t, title) or _hits(t, text)) for t in terms}

    ranked = []
    for section, title, text in indexed:
        matched, score = 0, 0.0
        for term in terms:
            in_title, in_text = _hits(term, title), _hits(term, text)
            if in_title or in_text:
                matched += 1
                idf = math.log(1 + len(indexed) / df[term])
                score += idf * (TITLE_WEIGHT * min(in_title, 1) + math.log1p(in_text))
        if matched:
            # Sections that match more of the query's words rank first.
            ranked.append((matched, score, section))
    ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)

    note = [snapshot_note("docs index")] if from_snapshot else []
    if not ranked:
        return "\n".join(
            [f"No LEAP docs sections match {query!r}. Try other keywords, or browse {SITE_URL}", *note]
        )
    lines = [f"Top {min(TOP_N, len(ranked))} LEAP docs results for {query!r}:", ""]
    for n, (_, _, section) in enumerate(ranked[:TOP_N], start=1):
        lines += [f"{n}. **{section['title']}**", f"   {section['url']}", f"   {_excerpt(section['text'], terms)}", ""]
    return "\n".join(lines + note)


def _excerpt(text: str, terms: list[str]) -> str:
    """Up to three sentences, starting at the sentence that matches the most query words."""
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()]
    coverage = [sum(1 for t in terms if _hits(t, _stems(s))) for s in sentences]
    best = coverage.index(max(coverage))
    return one_line(" ".join(sentences[best : best + 3]), EXCERPT_CHARS)
