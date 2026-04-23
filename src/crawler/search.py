"""Keyword → URL discovery via search engines (no API key needed)."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote, unquote, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.5",
}


async def keyword_to_urls(
    keyword: str,
    max_results: int = 10,
    engine: str = "duckduckgo",
    site_filter: str | None = None,
) -> list[str]:
    """Search for *keyword* and return a list of result URLs.

    Supported engines: ``duckduckgo`` (default), ``google_scholar``.
    Optionally restrict results to a domain via *site_filter*
    (e.g. ``"twitter.com"``).
    """
    query = keyword.strip()
    if site_filter:
        query = f"site:{site_filter} {query}"

    if engine == "google_scholar":
        return await _search_google_scholar(query, max_results)
    return await _search_duckduckgo(query, max_results)


async def _search_duckduckgo(query: str, max_results: int) -> list[str]:
    """Scrape DuckDuckGo Lite HTML results."""
    links: list[str] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(
            f"https://lite.duckduckgo.com/lite/?q={quote(query)}",
            headers=_HEADERS,
        )
        soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if not href.startswith("http"):
            continue
        if "duckduckgo" in href:
            # Extract the actual destination from redirect URLs
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                href = unquote(qs["uddg"][0])
            else:
                continue

        href = href.split("#")[0].rstrip("/")
        if href and href not in links:
            links.append(href)
        if len(links) >= max_results:
            break

    logger.info("DuckDuckGo: %d results for %r", len(links), query)
    return links


async def _search_google_scholar(query: str, max_results: int) -> list[str]:
    """Scrape Google Scholar results (public, no API key)."""
    links: list[str] = []
    start = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        while len(links) < max_results:
            resp = await client.get(
                "https://scholar.google.com/scholar",
                params={"q": query, "start": start, "hl": "id"},
                headers=_HEADERS,
            )
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            found = False
            for h3 in soup.select("h3.gs_rt a"):
                href = h3.get("href", "")
                if href.startswith("http") and href not in links:
                    links.append(href)
                    found = True
                if len(links) >= max_results:
                    break
            if not found:
                break
            start += 10

    logger.info("Google Scholar: %d results for %r", len(links), query)
    return links