import asyncio
import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
}

async def main():
    query = "Stunting"
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=_HEADERS)
        print(f"Status: {resp.status_code}")
        print(resp.text[:500])
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", class_="result__url", href=True)
        print(f"Total links: {len(links)}")
        for a in links[:10]:
            print(a['href'])

asyncio.run(main())
