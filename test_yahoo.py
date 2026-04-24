import httpx, asyncio
from bs4 import BeautifulSoup
async def main():
    async with httpx.AsyncClient(verify=False, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}) as c:
        r = await c.get("https://search.yahoo.com/search?p=Stunting")
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            if "yahoo.com" not in a["href"] and a["href"].startswith("http"):
                links.append(a["href"])
        print(links[:10])
asyncio.run(main())
