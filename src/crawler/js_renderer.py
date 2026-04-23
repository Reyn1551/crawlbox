"""Playwright wrapper."""
async def fetch_rendered_html(url, proxy=None, timeout=30):
    try: from playwright.async_api import async_playwright
    except ImportError: raise RuntimeError("Playwright tidak terinstall.\npip install playwright\nplaywright install chromium")
    async with async_playwright() as pw:
        opts={"headless":True,"args":["--no-sandbox","--disable-setuid-sandbox","--disable-blink-features=AutomationControlled"]}
        if proxy: opts["proxy"]={"server":proxy}
        browser=await pw.chromium.launch(**opts)
        ctx=await browser.new_context(user_agent="Mozilla/5.0 Chrome/124.0.0.0",viewport={"width":1920,"height":1080},locale="id-ID")
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome={runtime:{}};")
        page=await ctx.new_page()
        try:
            await page.goto(url,wait_until="networkidle",timeout=timeout*1000); return await page.content()
        except: return None
        finally: await browser.close()