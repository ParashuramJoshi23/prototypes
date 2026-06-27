"""Find recipe URLs on the target site.

Preferred path is the sitemap (sitemap.xml, recursively following sitemap
indexes). If there's no sitemap, fall back to crawling links from a listing
page. Either way, results are filtered by a URL pattern so we only keep things
that look like individual recipes.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .http_client import Client

# A recipe detail URL on food.upliance.ai is assumed to live under /recipe(s)/.
# Adjust once you see the real URL shape (run `discover` and eyeball output).
DEFAULT_RECIPE_PATTERN = re.compile(r"/recipes?/[^/]+/?$", re.IGNORECASE)


def discover(
    client: Client,
    base_url: str,
    pattern: re.Pattern = DEFAULT_RECIPE_PATTERN,
    limit: int | None = None,
) -> list[str]:
    urls = _from_sitemaps(client, base_url, pattern)
    if not urls:
        urls = _from_crawl(client, base_url, pattern)
    deduped = list(dict.fromkeys(urls))  # stable de-dup
    return deduped[:limit] if limit else deduped


# --------------------------------------------------------------------------
# Sitemap discovery
# --------------------------------------------------------------------------

def _from_sitemaps(client: Client, base_url: str, pattern: re.Pattern) -> list[str]:
    root = _root(base_url)
    found: list[str] = []
    seen_maps: set[str] = set()
    queue = [f"{root}/sitemap.xml"]
    while queue:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        xml = _safe_get(client, sm)
        if not xml:
            continue
        child_maps, page_urls = _parse_sitemap(xml)
        queue.extend(child_maps)
        found.extend(u for u in page_urls if pattern.search(u))
    return found


def _parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """Return (nested sitemap urls, page urls) from a sitemap or sitemap index."""
    try:
        root = ElementTree.fromstring(xml.encode("utf-8"))
    except ElementTree.ParseError:
        return [], []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    sitemaps = [e.text.strip() for e in root.findall(".//sm:sitemap/sm:loc", ns) if e.text]
    pages = [e.text.strip() for e in root.findall(".//sm:url/sm:loc", ns) if e.text]
    if not sitemaps and not pages:  # namespace mismatch: fall back to any <loc>
        locs = [e.text.strip() for e in root.iter() if e.tag.endswith("loc") and e.text]
        pages = [u for u in locs if not u.endswith(".xml")]
        sitemaps = [u for u in locs if u.endswith(".xml")]
    return sitemaps, pages


# --------------------------------------------------------------------------
# Crawl fallback
# --------------------------------------------------------------------------

def _from_crawl(client: Client, base_url: str, pattern: re.Pattern) -> list[str]:
    html = _safe_get(client, base_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    host = urlparse(base_url).netloc
    out = []
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        if urlparse(full).netloc == host and pattern.search(full):
            out.append(full.split("#")[0])
    return out


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _safe_get(client: Client, url: str) -> str | None:
    try:
        return client.get(url)
    except Exception:
        return None
