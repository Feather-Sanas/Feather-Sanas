#!/usr/bin/env python3
"""
Index https://www.sanas.ai (product/industry/science pages + the blog & news posts)
into server/web_index.json. The backend uses it to ground Sani's chat answers and
cite real page links.

Run (needs network):
    python3 scripts/index_site.py
Re-run anytime to refresh; safe to commit the JSON (public marketing content).
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = ssl.create_default_context()

BASE = "https://www.sanas.ai"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36 Chrome/124 Safari/537.36"
OUT = Path(__file__).resolve().parent.parent / "server" / "web_index.json"

SEED_PATHS = [
    "/", "/accent-translation", "/noise-cancellation", "/speech-enhancement",
    "/language-translation", "/speech-intelligence", "/science", "/developer-platform",
    "/customer-stories", "/healthcare", "/financial-services", "/retail", "/travel",
    "/partners", "/blog", "/news",
]
MAX_PAGES = 60
SKIP_SLUG = re.compile(r"/(blog|news)/(layout|loading|page)-")


def fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20, context=_CTX) as r:
            ct = r.headers.get("Content-Type", "")
            if "text/html" not in ct and "application/xhtml" not in ct:
                return None
            return r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  ! {url}: {type(e).__name__}", file=sys.stderr)
        return None


class _Extract(HTMLParser):
    """Pull visible text + <title>/og:title, skipping script/style/nav noise."""
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.title = None
        self.og = None
        self._skip = 0
        self._intitle = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag == "title":
            self._intitle = True
        if tag == "meta":
            a = dict(attrs)
            if a.get("property") == "og:title" and a.get("content"):
                self.og = a["content"].strip()

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._intitle = False

    def handle_data(self, data):
        if self._intitle and not self.title:
            t = data.strip()
            if t:
                self.title = t
        if self._skip == 0:
            t = data.strip()
            if len(t) > 1:
                self.parts.append(t)


def parse(html: str) -> tuple[str, str, list[str]]:
    ex = _Extract()
    try:
        ex.feed(html)
    except Exception:
        pass
    title = (ex.og or ex.title or "").replace(" | Sanas", "").strip()
    text = re.sub(r"\s+", " ", " ".join(ex.parts)).strip()
    # internal links (for discovering blog/news posts)
    links = re.findall(r'href="(/(?:blog|news)/[a-z0-9][a-z0-9-]+)"', html)
    return title, text, links


def main() -> int:
    seen: set[str] = set()
    queue = [BASE + p for p in SEED_PATHS]
    pages = []
    print(f"Indexing {BASE} …")
    while queue and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        html = fetch(url)
        if not html:
            continue
        title, text, links = parse(html)
        # enqueue discovered blog/news posts
        for ln in links:
            full = BASE + ln
            if full not in seen and not SKIP_SLUG.search(ln) and full not in queue:
                queue.append(full)
        # index pages with real content (skip thin listing shells)
        if text and len(text) > 200 and not url.rstrip("/").endswith(("/blog", "/news")):
            pages.append({"url": url, "title": title or url, "text": text[:4500]})
            print(f"  + {title[:60] or url}")
        time.sleep(0.15)
    OUT.write_text(json.dumps({"base": BASE, "pages": pages}, ensure_ascii=False, indent=0))
    print(f"\nWrote {len(pages)} pages → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
