"""Async web crawler with depth-first link following."""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.config import settings
from src.crawler.ethics import RobotsChecker
from src.crawler.extractor import extract_main_content

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


@dataclass
class CrawlResult:
    url: str
    title: str
    text: str
    status_code: int
    links: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class AsyncCrawler:
    """Crawl a list of seed URLs, optionally following links up to *max_depth*."""

    def __init__(self, max_depth: int | None = None, on_result=None, on_progress=None):
        self.max_depth = max_depth or settings.crawler_max_depth
        self.sem = asyncio.Semaphore(settings.crawler_max_concurrency)
        self.visited: set[str] = set()
        self.robots = RobotsChecker() if settings.crawler_respect_robots else None
        self.on_result = on_result
        self.on_progress = on_progress

    @staticmethod
    def _headers() -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.5",
        }

    @staticmethod
    def _normalise(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")

    @staticmethod
    def _same_domain(a: str, b: str) -> bool:
        return urlparse(a).netloc == urlparse(b).netloc

    # ------------------------------------------------------------------
    async def crawl(self, urls: list[str]) -> list[CrawlResult]:
        """Crawl *urls* and return all results."""
        results: list[CrawlResult] = []
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        for u in urls:
            await queue.put((u, 0))

        num_workers = min(settings.crawler_max_concurrency, max(len(urls), 4))
        workers = [asyncio.create_task(self._worker(queue, results)) for _ in range(num_workers)]
        await queue.join()
        for w in workers:
            w.cancel()

        if self.robots:
            await self.robots.close()
        return results

    async def _worker(self, queue: asyncio.Queue, results: list[CrawlResult]):
        """Process items from *queue* until cancelled."""
        while True:
            try:
                url, depth = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            except asyncio.CancelledError:
                return

            norm = self._normalise(url)
            if norm in self.visited or depth > self.max_depth:
                queue.task_done()
                continue

            if self.robots and not await self.robots.is_allowed(norm):
                logger.debug("Blocked by robots.txt: %s", norm)
                queue.task_done()
                continue

            self.visited.add(norm)
            async with self.sem:
                result = await self._fetch(norm)
                if result:
                    results.append(result)
                    if self.on_result:
                        if asyncio.iscoroutinefunction(self.on_result):
                            await self.on_result(result)
                        else:
                            self.on_result(result)
                    if self.on_progress:
                        if asyncio.iscoroutinefunction(self.on_progress):
                            await self.on_progress(len(results))
                        else:
                            self.on_progress(len(results))
                    if depth < self.max_depth:
                        for link in result.links[:20]:
                            child = self._normalise(link)
                            if self._same_domain(norm, child) and child not in self.visited:
                                await queue.put((child, depth + 1))
                await asyncio.sleep(settings.crawler_delay_seconds + random.uniform(0, 0.3))
            queue.task_done()

    async def _fetch(self, url: str) -> CrawlResult | None:
        """Fetch a single page with retries."""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    proxy=settings.proxy_url,
                    timeout=settings.crawler_request_timeout,
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(url, headers=self._headers())
                    resp.raise_for_status()
                    content_type = resp.headers.get("Content-Type", "").lower()
                    
                    if "application/pdf" in content_type:
                        try:
                            import io
                            import pypdf
                            pdf = pypdf.PdfReader(io.BytesIO(resp.content))
                            text_pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
                            text = "\n".join(text_pages)
                            title = url.split("/")[-1]
                            if pdf.metadata and pdf.metadata.title:
                                title = pdf.metadata.title
                            return CrawlResult(
                                url=url,
                                title=title,
                                text=text,
                                status_code=resp.status_code,
                                metadata={"is_pdf": True}
                            )
                        except Exception as e:
                            logger.error("Failed to parse PDF %s: %s", url, e)
                            return None
                    elif "text/html" in content_type or "application/xhtml+xml" in content_type or not content_type:
                        soup = BeautifulSoup(resp.text, "lxml")
                        text = extract_main_content(soup)
                        links = [urljoin(url, a.get("href", "")) for a in soup.find_all("a", href=True)]
                        title = soup.title.string.strip() if soup.title and soup.title.string else ""
                        og_title = soup.find("meta", property="og:title")
                        og_desc = soup.find("meta", property="og:description")
                        return CrawlResult(
                            url=url,
                            title=title,
                            text=text,
                            status_code=resp.status_code,
                            links=links,
                            metadata={
                                "og_title": og_title.get("content", "") if og_title else "",
                                "og_description": og_desc.get("content", "") if og_desc else "",
                            },
                        )
                    else:
                        return None
            except Exception as exc:
                if attempt < 2:
                    logger.debug("Retry %d for %s: %s", attempt + 1, url, exc)
                    await asyncio.sleep(2**attempt)
                    continue
                logger.debug("Failed to fetch %s after 3 attempts: %s", url, exc)
                return None
        return None