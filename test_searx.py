import httpx, asyncio
async def main():
    instances = [
        "https://searx.tiekoetter.com",
        "https://searx.be",
        "https://searx.ru",
        "https://search.mdosch.de",
    ]
    async with httpx.AsyncClient(verify=False, timeout=10) as c:
        for inst in instances:
            try:
                r = await c.get(f"{inst}/search?q=Stunting&format=json")
                if r.status_code == 200:
                    data = r.json()
                    print("SearXNG works:", inst, len(data.get("results", [])))
                    return
            except Exception as e:
                print(inst, e)
asyncio.run(main())
