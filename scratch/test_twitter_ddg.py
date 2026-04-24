import asyncio
import httpx
from bs4 import BeautifulSoup
from src.crawler.search import keyword_to_urls, _search_duckduckgo

async def test_ddg_twitter():
    keyword = "stunting"
    
    # We can use ddgs directly to get the snippet, not just URLs.
    # The current `keyword_to_urls` only returns URLs, but `DDGS.text` returns dicts with 'title', 'href', 'body'.
    from ddgs import DDGS
    def run_ddg():
        with DDGS() as ddgs:
            return list(ddgs.text(f"site:twitter.com {keyword}", max_results=5))
            
    res = await asyncio.to_thread(run_ddg)
    for r in res:
        print(f"URL: {r['href']}\nSnippet: {r['body']}\n")

if __name__ == "__main__":
    asyncio.run(test_ddg_twitter())
