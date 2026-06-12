"""
Lexical retrieval over the indexed sanas.ai content (server/web_index.json,
built by scripts/index_site.py). Sani uses it to ground chat answers and return
real page links to cite. Degrades to empty results if the index is absent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "web_index.json"
_STOP = set("the a an and or of to for in on with is are be it as at by from this that "
            "how what why your you our we us they i do does can will sanas com www".split())
_pages: list[dict] = []
_loaded = False


def _load() -> list[dict]:
    global _pages, _loaded
    if _loaded:
        return _pages
    _loaded = True
    try:
        data = json.loads(_PATH.read_text())
        for p in data.get("pages", []):
            p["_t"] = p["title"].lower()
            p["_x"] = p["text"].lower()
            _pages.append(p)
    except Exception:
        _pages = []
    return _pages


def available() -> bool:
    return bool(_load())


def count() -> int:
    return len(_load())


def _terms(q: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) > 2 and t not in _STOP]


def _snippet(page: dict, terms: list[str]) -> str:
    x = page["text"]
    pos = min((page["_x"].find(t) for t in terms if page["_x"].find(t) != -1), default=-1)
    if pos < 0:
        return x[:180].strip()
    start = max(0, pos - 60)
    return ("…" if start else "") + x[start:start + 200].strip() + "…"


def search(query: str, k: int = 3, prefer: str | None = None) -> list[dict]:
    """Lexical top-k over the index. `prefer` (a URL substring, e.g. "/science")
    boosts matching pages so a given section surfaces for the right persona —
    used to ground the Data Scientist in the Sanas science articles."""
    pages, terms = _load(), _terms(query or "")
    if not pages or not terms:
        return []
    scored = []
    for p in pages:
        s = sum(3 * p["_t"].count(t) + p["_x"].count(t) for t in terms)
        if s and prefer and prefer in p["url"]:
            s = s * 3 + 2          # float the preferred section to the top
        if s:
            scored.append((s, p))
    scored.sort(key=lambda sp: -sp[0])
    return [{"title": p["title"], "url": p["url"], "snippet": _snippet(p, terms)}
            for _, p in scored[:k]]
