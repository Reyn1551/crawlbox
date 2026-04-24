"""Social media scrapers — no API keys required.

Twitter/X (via Nitter), Reddit (public JSON), YouTube comments.
"""
from __future__ import annotations
import asyncio, json, logging, re
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse, parse_qs
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36", "Accept": "text/html,application/json,*/*;q=0.8", "Accept-Language": "id-ID,id;q=0.9,en;q=0.5"}
NITTER = ["https://nitter.privacydev.net", "https://nitter.poast.org", "https://nitter.1d4.us"]

@dataclass
class SocialPost:
    platform: str; post_id: str; author: str; text: str; url: str
    timestamp: str = ""; likes: int = 0; replies: int = 0; reposts: int = 0
    metadata: dict = field(default_factory=dict)

class TwitterScraper:
    async def search(self, keyword: str, max_results: int = 50) -> list[SocialPost]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            for inst in NITTER:
                try:
                    r = await c.get(f"{inst}/search", params={"f": "tweets", "q": quote(keyword)}, headers=_H)
                    if r.status_code == 200: 
                        posts = self._parse(r.text)
                        if posts: return posts[:max_results]
                except: continue
        
        # Fallback to DDG if Nitter fails
        logger.warning(f"Nitter instances failed for Twitter search '{keyword}'. Falling back to DuckDuckGo.")
        try:
            from ddgs import DDGS
            import asyncio
            def run_ddg():
                with DDGS() as ddgs:
                    return list(ddgs.text(f"site:twitter.com {keyword}", max_results=max_results))
            res = await asyncio.to_thread(run_ddg)
            posts = []
            for r in res:
                # r has 'href', 'title', 'body'
                text = r.get("body", "")
                if not text: continue
                # clean up typical twitter preview text
                text = re.sub(r"^.*?on X: \"", "", text)
                text = re.sub(r"\" / X$", "", text)
                url = r.get("href", "")
                author = r.get("title", "").split(" on X:")[0] if " on X:" in r.get("title", "") else "twitter_user"
                posts.append(SocialPost(
                    platform="twitter",
                    post_id=url.split("/")[-1] if "/" in url else "",
                    author=author,
                    text=text,
                    url=url
                ))
            return posts
        except Exception as e:
            logger.error(f"DDG fallback for Twitter failed: {e}")
            
        return []

    async def scrape_user(self, username: str, max_results: int = 50) -> list[SocialPost]:
        u = username.lstrip("@")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            for inst in NITTER:
                try:
                    r = await c.get(f"{inst}/{u}", headers=_H)
                    if r.status_code == 200: 
                        posts = self._parse(r.text)
                        if posts: return posts[:max_results]
                except: continue
                
        # Fallback to DDG if Nitter fails
        logger.warning(f"Nitter instances failed for user '{u}'. Falling back to DuckDuckGo.")
        try:
            from ddgs import DDGS
            import asyncio
            def run_ddg():
                with DDGS() as ddgs:
                    return list(ddgs.text(f"site:twitter.com/{u}", max_results=max_results))
            res = await asyncio.to_thread(run_ddg)
            posts = []
            for r in res:
                text = r.get("body", "")
                if not text: continue
                text = re.sub(r"^.*?on X: \"", "", text)
                text = re.sub(r"\" / X$", "", text)
                url = r.get("href", "")
                posts.append(SocialPost(
                    platform="twitter",
                    post_id=url.split("/")[-1] if "/" in url else "",
                    author=username,
                    text=text,
                    url=url
                ))
            return posts
        except Exception as e:
            logger.error(f"DDG fallback for Twitter user failed: {e}")

        return []

    async def scrape_hashtag(self, hashtag: str, max_results: int = 50) -> list[SocialPost]:
        return await self.search(f"#{hashtag.lstrip('#')}", max_results)

    def _parse(self, html: str) -> list[SocialPost]:
        soup = BeautifulSoup(html, "html.parser"); posts = []
        for item in soup.select(".timeline-item"):
            try:
                ue = item.select_one(".username"); ce = item.select_one(".tweet-content"); le = item.select_one(".tweet-link")
                if not ce: continue
                tp = le.get("href", "") if le else ""
                posts.append(SocialPost(platform="twitter", post_id=tp.split("/")[-1] if tp else "", author=ue.get_text(strip=True) if ue else "?", text=ce.get_text(strip=True), url=f"https://twitter.com{tp}" if tp else "", timestamp=(item.select_one(".tweet-date a") or {}).get("title", "")))
            except: continue
        return posts

    async def get_comments(self, post_url: str, max_comments: int = 50) -> list[SocialPost]:
        """Scrape comments from a tweet via Nitter thread page."""
        path = urlparse(post_url).path
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            for inst in NITTER:
                try:
                    r = await c.get(f"{inst}{path}", headers=_H)
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        comments = []
                        # Comments are usually in .replies div
                        for item in soup.select(".replies .timeline-item"):
                            try:
                                ue = item.select_one(".username"); ce = item.select_one(".tweet-content"); le = item.select_one(".tweet-link")
                                if not ce: continue
                                tp = le.get("href", "") if le else ""
                                comments.append(SocialPost(platform="twitter", post_id=tp.split("/")[-1] if tp else "", author=ue.get_text(strip=True) if ue else "?", text=ce.get_text(strip=True), url=f"https://twitter.com{tp}" if tp else "", timestamp=(item.select_one(".tweet-date a") or {}).get("title", "")))
                                if len(comments) >= max_comments: break
                            except: continue
                        return comments
                except: continue
        return []

class RedditScraper:
    async def search(self, keyword: str, subreddit: str | None = None, max_results: int = 50, sort: str = "relevance", time_filter: str = "all") -> list[SocialPost]:
        posts = []
        url = f"https://www.reddit.com/r/{subreddit}/search.json" if subreddit else "https://www.reddit.com/search.json"
        params = {"q": keyword, "sort": sort, "t": time_filter, "limit": min(max_results, 100)}
        if subreddit: params["restrict_sr"] = "on"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            try:
                r = await c.get(url, params=params, headers={**_H, "Accept": "application/json"})
                if r.status_code == 200:
                    for ch in r.json().get("data", {}).get("children", []):
                        d = ch.get("data", {})
                        posts.append(SocialPost(platform="reddit", post_id=d.get("id", ""), author=d.get("author", "[deleted]"), text=f"{d.get('title', '')} {d.get('selftext', '')}".strip(), url=f"https://reddit.com{d.get('permalink', '')}", timestamp=str(d.get("created_utc", "")), likes=d.get("ups", 0), replies=d.get("num_comments", 0), metadata={"subreddit": d.get("subreddit", ""), "score": d.get("score", 0)}))
            except Exception as e: logger.error("Reddit: %s", e)
        return posts[:max_results]

    async def get_comments(self, post_url: str, max_comments: int = 100) -> list[SocialPost]:
        comments = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            try:
                r = await c.get(post_url.rstrip("/") + ".json", headers={**_H, "Accept": "application/json"})
                if r.status_code == 200 and len(r.json()) > 1:
                    self._walk(r.json()[1].get("data", {}).get("children", []), comments, max_comments)
            except Exception as e: logger.error("Reddit comments: %s", e)
        return comments

    def _walk(self, children, out, limit, depth=0):
        for ch in children:
            if len(out) >= limit or ch.get("kind") != "t1": continue
            d = ch.get("data", {}); body = d.get("body", "")
            if not body or body == "[deleted]": continue
            out.append(SocialPost(platform="reddit", post_id=d.get("id", ""), author=d.get("author", "[deleted]"), text=body, url=f"https://reddit.com{d.get('permalink', '')}", timestamp=str(d.get("created_utc", "")), likes=d.get("ups", 0), metadata={"depth": depth}))
            reps = d.get("replies")
            if isinstance(reps, dict): self._walk(reps.get("data", {}).get("children", []), out, limit, depth + 1)

class YouTubeScraper:
    async def get_comments(self, video_url: str, max_comments: int = 100) -> list[SocialPost]:
        comments = []; vid = self._vid(video_url)
        if not vid: return comments
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            try:
                r = await c.get(f"https://www.youtube.com/watch?v={vid}", headers=_H)
                if r.status_code != 200: return comments
                m = re.search(r"var ytInitialData = ({.*?});</script>", r.text)
                if not m: return comments
                tokens = [t.group(1) for t in re.finditer(r'"continuation":"([^"]{50,})"', m.group(1))][:3]
                for tok in tokens:
                    try:
                        cr = await c.post("https://www.youtube.com/youtubei/v1/next", json={"context": {"client": {"hl": "id", "gl": "ID", "clientName": "WEB", "clientVersion": "2.20240101.00.00"}}, "continuation": tok}, headers=_H)
                        if cr.status_code == 200: self._parse_yt(cr.json(), comments, vid, max_comments)
                    except: continue
                    if len(comments) >= max_comments: break
            except Exception as e: logger.error("YouTube: %s", e)
        return comments[:max_comments]

    @staticmethod
    def _vid(url):
        m = re.search(r"(?:v=|/v/|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})", url)
        return m.group(1) if m else None

    def _parse_yt(self, data, out, vid, limit):
        try:
            actions = data.get("onResponseReceivedEndpoints", []) + data.get("onResponseReceivedActions", [])
            for a in actions:
                for sk in ("appendContinuationItemsAction", "reloadContinuationItemsCommand"):
                    for item in a.get(sk, {}).get("continuationItems", []):
                        if len(out) >= limit: return
                        cr = item.get("commentThreadRenderer", {}).get("comment", {}).get("commentRenderer", {})
                        if not cr: continue
                        txt = " ".join(r.get("text", "") for r in cr.get("contentText", {}).get("runs", [])).strip()
                        if not txt: continue
                        out.append(SocialPost(platform="youtube", post_id=cr.get("commentId", ""), author=cr.get("authorText", {}).get("simpleText", "?"), text=txt, url=f"https://youtube.com/watch?v={vid}&lc={cr.get('commentId', '')}", timestamp=(cr.get("publishedTimeText", {}).get("runs", [{}])[0].get("text", "")), likes=int(re.sub(r"[^\d]", "", str(cr.get("voteCount", {}).get("simpleText", "0"))) or "0"), metadata={"video_id": vid}))
        except Exception as e: logger.debug("YT parse: %s", e)

class ThreadsScraper:
    async def search(self, keyword: str, max_results: int = 50) -> list[SocialPost]:
        """Search Threads via DuckDuckGo (since Threads is heavily protected)."""
        from src.crawler.search import keyword_to_urls
        urls = await keyword_to_urls(keyword, max_results=max_results, site_filter="threads.net")
        posts = []
        async with httpx.AsyncClient(timeout=15, headers=_H) as c:
            for url in urls:
                try:
                    # We can't easily parse Threads SPA content without JS, 
                    # so we'll use the search snippet or try to get meta description
                    r = await c.get(url)
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        desc = soup.find("meta", property="og:description")
                        author = soup.find("meta", property="og:title")
                        text = desc["content"] if desc else ""
                        if not text: continue
                        # Clean up text if it contains "on Threads"
                        text = re.sub(r"Threads menyertakan.*?$", "", text).strip()
                        posts.append(SocialPost(
                            platform="threads", 
                            post_id=url.split("/")[-1], 
                            author=author["content"] if author else "threads_user",
                            text=text,
                            url=url
                        ))
                except: continue
        return posts

class GenericSearchScraper:
    async def search(self, platform: str, keyword: str, max_results: int = 50) -> list[SocialPost]:
        """Search generic platforms via DuckDuckGo."""
        domains = {
            "tiktok": "tiktok.com",
            "instagram": "instagram.com",
            "facebook": "facebook.com",
            "linkedin": "linkedin.com/posts"
        }
        domain = domains.get(platform)
        if not domain: return []
        
        posts = []
        try:
            from ddgs import DDGS
            import asyncio
            def run_ddg():
                with DDGS() as ddgs:
                    return list(ddgs.text(f"site:{domain} {keyword}", max_results=max_results))
            res = await asyncio.to_thread(run_ddg)
            
            for r in res:
                text = r.get("body", "")
                if not text: continue
                # clean up text
                text = re.sub(f".*? on {platform.title()}: \"", "", text, flags=re.IGNORECASE)
                text = re.sub(r"\"$", "", text)
                url = r.get("href", "")
                author = r.get("title", "").split(" on ")[0] if " on " in r.get("title", "") else f"{platform}_user"
                posts.append(SocialPost(
                    platform=platform,
                    post_id=url.split("/")[-1] if "/" in url else "",
                    author=author,
                    text=text,
                    url=url
                ))
        except Exception as e:
            logger.error(f"DDG generic search failed for {platform}: {e}")
            
        return posts

async def scrape_social(platform: str, query: str, max_results: int = 50, **kw) -> list[SocialPost]:
    queries = [q.strip() for q in query.split(",") if q.strip()]
    all_posts = []
    
    for q in queries:
        posts = []
        if platform == "twitter":
            s = TwitterScraper()
            if q.startswith("@"): posts = await s.scrape_user(q, max_results)
            elif q.startswith("#"): posts = await s.scrape_hashtag(q, max_results)
            else: posts = await s.search(q, max_results)
        elif platform == "reddit":
            posts = await RedditScraper().search(q, subreddit=kw.get("subreddit"), max_results=max_results)
        elif platform == "youtube":
            posts = await YouTubeScraper().get_comments(q, max_results)
        elif platform == "threads":
            posts = await ThreadsScraper().search(q, max_results)
        elif platform in ["tiktok", "instagram", "facebook", "linkedin"]:
            posts = await GenericSearchScraper().search(platform, q, max_results)
        
        all_posts.extend(posts)
        if len(all_posts) >= max_results * len(queries): break

    return all_posts[:max_results * len(queries)]

