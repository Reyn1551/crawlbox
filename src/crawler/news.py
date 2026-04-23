"""Indonesian news portal scraper + RSS feed parser."""
from __future__ import annotations
import asyncio, logging, re, xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from src.crawler.extractor import extract_main_content

logger = logging.getLogger(__name__)
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0", "Accept": "text/html,application/xml,*/*;q=0.8"}

# Popular Indonesian news RSS feeds
NEWS_FEEDS = {
    "kompas": "https://rss.kompas.com/kompas-cetak",
    "detik": "https://rss.detik.com/index.php/detikcom",
    "cnnindonesia": "https://www.cnnindonesia.com/nasional/rss",
    "tribunnews": "https://www.tribunnews.com/rss",
    "tempo": "https://rss.tempo.co/nasional",
    "liputan6": "https://www.liputan6.com/rss",
    "tirto": "https://tirto.id/feed/",
    "kumparan": "https://kumparan.com/feed",
    "okezone": "https://sindikasi.okezone.com/index.php/rss/0/RSS2.0",
    "antaranews": "https://www.antaranews.com/rss/terkini.xml",
}

@dataclass
class NewsArticle:
    title: str; url: str; text: str; source: str
    author: str = ""; published: str = ""; category: str = ""
    image_url: str = ""; description: str = ""
    metadata: dict = field(default_factory=dict)

class NewsScraper:
    """Scrape news articles from Indonesian portals."""

    async def scrape_article(self, url: str) -> NewsArticle | None:
        """Fetch and parse a single news article."""
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            try:
                r = await c.get(url, headers=_H)
                if r.status_code != 200: return None
                soup = BeautifulSoup(r.text, "lxml")
                domain = urlparse(url).netloc.replace("www.", "")
                title = self._title(soup)
                text = extract_main_content(soup)
                author = self._author(soup)
                published = self._date(soup)
                category = self._category(soup)
                img = soup.find("meta", property="og:image")
                desc = soup.find("meta", property="og:description")
                return NewsArticle(title=title, url=url, text=text, source=domain, author=author, published=published, category=category, image_url=img.get("content", "") if img else "", description=desc.get("content", "") if desc else "")
            except Exception as e:
                logger.error("News scrape failed %s: %s", url, e)
                return None

    async def scrape_rss(self, feed_name: str | None = None, feed_url: str | None = None, max_articles: int = 20) -> list[NewsArticle]:
        """Parse an RSS feed and return article metadata."""
        url = feed_url or NEWS_FEEDS.get(feed_name or "", "")
        if not url:
            logger.error("Unknown feed: %s", feed_name)
            return []
        articles = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            try:
                r = await c.get(url, headers={**_H, "Accept": "application/rss+xml,application/xml,text/xml"})
                if r.status_code != 200: return []
                root = ET.fromstring(r.text)
                ns = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/", "content": "http://purl.org/rss/1.0/modules/content/"}
                items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
                for item in items[:max_articles]:
                    title = self._xml_text(item, "title", ns)
                    link = self._xml_link(item, ns)
                    desc = self._xml_text(item, "description", ns) or self._xml_text(item, "{http://www.w3.org/2005/Atom}summary", ns)
                    pub = self._xml_text(item, "pubDate", ns) or self._xml_text(item, "{http://www.w3.org/2005/Atom}published", ns)
                    author = self._xml_text(item, "dc:creator", ns) or self._xml_text(item, "{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name", ns)
                    cat = self._xml_text(item, "category", ns)
                    if link:
                        articles.append(NewsArticle(title=title or "", url=link, text=re.sub(r"<[^>]+>", " ", desc or "").strip(), source=feed_name or urlparse(url).netloc, author=author or "", published=pub or "", category=cat or "", description=desc or ""))
            except Exception as e:
                logger.error("RSS parse failed %s: %s", url, e)
        return articles

    async def scrape_rss_full(self, feed_name: str | None = None, feed_url: str | None = None, max_articles: int = 10) -> list[NewsArticle]:
        """Parse RSS + fetch full article text for each item."""
        rss_items = await self.scrape_rss(feed_name, feed_url, max_articles)
        tasks = [self.scrape_article(a.url) for a in rss_items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        full = []
        for rss_item, result in zip(rss_items, results):
            if isinstance(result, NewsArticle) and result.text:
                result.published = result.published or rss_item.published
                result.category = result.category or rss_item.category
                full.append(result)
            else:
                if rss_item.text:
                    full.append(rss_item)
        return full

    async def search_news(self, keyword: str, sources: list[str] | None = None, max_per_source: int = 5) -> list[NewsArticle]:
        """Search across multiple RSS feeds for keyword matches."""
        feed_names = sources or list(NEWS_FEEDS.keys())
        all_articles = []
        for name in feed_names:
            if name not in NEWS_FEEDS: continue
            articles = await self.scrape_rss(feed_name=name, max_articles=max_per_source * 3)
            kw_lower = keyword.lower()
            matched = [a for a in articles if kw_lower in a.title.lower() or kw_lower in a.text.lower()]
            all_articles.extend(matched[:max_per_source])
        return all_articles

    @staticmethod
    def available_feeds() -> dict[str, str]:
        return dict(NEWS_FEEDS)

    # ── helpers ──
    @staticmethod
    def _title(soup):
        for sel in ["h1.read__title", "h1.detail__title", "h1.content__title", "h1.article-title", "h1"]:
            el = soup.select_one(sel)
            if el: return el.get_text(strip=True)
        og = soup.find("meta", property="og:title")
        return og.get("content", "") if og else (soup.title.string.strip() if soup.title and soup.title.string else "")

    @staticmethod
    def _author(soup):
        for sel in [".read__credit", ".detail__author", ".author-name", "[rel='author']", ".byline", "meta[name='author']"]:
            el = soup.select_one(sel)
            if el:
                if el.name == "meta": return el.get("content", "")
                return el.get_text(strip=True)
        return ""

    @staticmethod
    def _date(soup):
        for sel in ["time[datetime]", ".read__time", ".detail__date", "meta[property='article:published_time']", "meta[name='pubdate']"]:
            el = soup.select_one(sel)
            if el:
                if el.name == "meta": return el.get("content", "")
                return el.get("datetime", "") or el.get_text(strip=True)
        return ""

    @staticmethod
    def _category(soup):
        for sel in [".read__channel", ".detail__category", "meta[property='article:section']"]:
            el = soup.select_one(sel)
            if el:
                if el.name == "meta": return el.get("content", "")
                return el.get_text(strip=True)
        return ""

    @staticmethod
    def _xml_text(el, tag, ns):
        child = el.find(tag, ns) if ":" in tag else el.find(tag)
        return child.text.strip() if child is not None and child.text else ""

    @staticmethod
    def _xml_link(el, ns):
        link_el = el.find("link")
        if link_el is not None:
            if link_el.text and link_el.text.strip(): return link_el.text.strip()
            return link_el.get("href", "")
        return ""
