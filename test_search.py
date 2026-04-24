import httpx, asyncio
from bs4 import BeautifulSoup
import re

async def main():
    async with httpx.AsyncClient(verify=False, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}) as c:
        r = await c.get("https://www.bing.com/search?q=Stunting")
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            print(a["href"])
asyncio.run(main())
