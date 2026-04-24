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
    
    links = await _search_duckduckgo(query, max_results)
    if not links:
        logger.warning("DuckDuckGo mengembalikan 0 hasil (kemungkinan diblokir). Fallback ke Google Scholar...")
        links = await _search_google_scholar(query, max_results)
        
    return links


async def _search_duckduckgo(query: str, max_results: int) -> list[str]:
    """Search DuckDuckGo using the ddgs library (bypasses bot protection)."""
    links: list[str] = []
    try:
        from ddgs import DDGS
        import asyncio
        
        def run_ddg():
            with DDGS() as ddgs:
                return [r["href"] for r in ddgs.text(query, max_results=max_results)]
                
        links = await asyncio.to_thread(run_ddg)
    except Exception as e:
        logger.error("DDGS error: %s", e)
        
    logger.info("DuckDuckGo: %d results for %r", len(links), query)
    return links


async def _search_google_scholar(query: str, max_results: int) -> list[str]:
    """Scrape Google Scholar results (public, no API key)."""
    links: list[str] = []
    start = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, verify=False) as client:
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