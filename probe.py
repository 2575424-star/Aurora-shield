"""Browser-based smoke test of publicly accessible rental search pages."""
import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from playwright.async_api import async_playwright

TARGETS = {
    "avito": "https://www.avito.ru/voronezh/kvartiry/sdam/na_dlitelnyy_srok",
    "cian": "https://voronezh.cian.ru/snyat-kvartiru/",
}

async def probe_one(browser, source, url):
    result = {"source":source,"url":url,"checked_at":datetime.now(timezone.utc).isoformat(),"status":"unknown","listing_links":0}
    context = await browser.new_context(locale="ru-RU", viewport={"width":1365,"height":900})
    try:
        page = await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(3500)
        result["http_status"] = response.status if response else None
        result["final_host"] = urlparse(page.url).hostname
        result["title"] = (await page.title())[:120]
        links = await page.locator("a[href]").evaluate_all("(nodes) => nodes.map(n => n.href)")
        if source == "avito":
            matches = [u for u in links if re.search(r"/kvartiry/[^/]+_[0-9]+(?:[?#]|$)",u)]
        else:
            matches = [u for u in links if re.search(r"/rent/flat/[0-9]+",u)]
        result["listing_links"] = len(set(matches))
        result["status"] = "listing_links_found" if matches else ("http_error_or_blocked" if result["http_status"] != 200 else "no_listing_links")
        result["html_bytes"] = len((await page.content()).encode())
    except Exception as exc:
        result["status"] = "browser_failed"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:220]
    finally:
        await context.close()
    return result

async def run_probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            return await asyncio.gather(*(probe_one(browser,k,v) for k,v in TARGETS.items()))
        finally:
            await browser.close()
