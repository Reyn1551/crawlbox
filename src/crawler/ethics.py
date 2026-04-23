"""robots.txt checker — non-blocking, caches per domain."""
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx


class RobotsChecker:
    """Check robots.txt before crawling.  Uses httpx (async) to fetch
    the robots.txt content and feeds it into the stdlib parser."""

    def __init__(self):
        self._cache: dict[str, RobotFileParser | None] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10, follow_redirects=True)
        return self._client

    async def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc
        if not domain:
            return True

        if domain in self._cache:
            rp = self._cache[domain]
            return rp.can_fetch(user_agent, url) if rp else True

        rp = None
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        try:
            client = await self._get_client()
            resp = await client.get(robots_url)
            if resp.status_code == 200:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                # Parse the content directly instead of calling rp.read()
                # which does a blocking HTTP fetch internally
                rp.parse(resp.text.splitlines())
        except Exception:
            rp = None

        self._cache[domain] = rp
        return rp.can_fetch(user_agent, url) if rp else True

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()