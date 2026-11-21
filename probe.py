"""Minimal public-page smoke test for Avito and Cian, not a production scraper."""
import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

TARGETS = {
    "avito": "https://www.avito.ru/voronezh/kvartiry/sdam/na_dlitelnyy_srok",
    "cian": "https://voronezh.cian.ru/snyat-kvartiru/",
}

async def probe_one(source: str, url: str) -> dict:
    result = {"source": source, "url": url, "checked_at": datetime.now(timezone.utc).isoformat(), "status": "unknown", "listing_links": 0}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; RealtyMonitorSmokeTest/0.1)"}) as client:
            response = await client.get(url)
        result["http_status"] = response.status_code
        result["final_host"] = urlparse(str(response.url)).hostname
        if response.status_code != 200:
            result["status"] = "http_error_or_blocked"
            return result
        soup = BeautifulSoup(response.text, "html.parser")
        links = {a.get("href", "").split("?")[0] for a in soup.find_all("a", href=True)}
        if source == "avito":
            matches = [u for u in links if re.search(r"/kvartiry/[^/]+_\\d+$", u)]
        else:
            matches = [u for u in links if re.search(r"/rent/flat/\\d+", u)]
        result["listing_links"] = len(matches)
        result["status"] = "listing_links_found" if matches else "html_received_no_listing_links"
        result["html_bytes"] = len(response.content)
    except Exception as exc:
        result["status"] = "request_failed"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:180]
    return result

async def run_probe():
    return await asyncio.gather(*(probe_one(k, v) for k, v in TARGETS.items()))
