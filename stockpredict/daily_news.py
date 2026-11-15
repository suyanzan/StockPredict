"""Read a bounded, source-linked editorial brief; never feed news into forecasts."""

import json
import re
import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse

SOURCE_URL = (
    "https://raw.githubusercontent.com/suyanzan/StockPredict/main/data/daily-news/latest.json"
)
MAX_BYTES = 65_536
TAIPEI = ZoneInfo("Asia/Taipei")
LANGUAGES = ("zh-TW", "en")
HOSTS = (
    "cna.com.tw",
    "focustaiwan.tw",
    "reuters.com",
    "apnews.com",
    "ft.com",
    "wsj.com",
    "udn.com",
    "technews.tw",
    "investing.com",
    "marketscreener.com",
    "nvidia.com",
    "openai.com",
    "anthropic.com",
    "microsoft.com",
    "google.com",
    "deepmind.google",
    "federalreserve.gov",
    "bls.gov",
    "bea.gov",
    "gov.tw",
    "tsmc.com",
    "quantatw.com",
    "qct.io",
    "deltaww.com",
    "nanya.com",
    "aseglobal.com",
    "twse.com.tw",
    "bloomberg.com",
    "bbc.com",
    "cnbc.com",
    "nikkei.com",
    "yahoo.com",
    "blog.google",
    "about.fb.com",
    "amazon.com",
    "amd.com",
    "intel.com",
)
router = APIRouter()
_LOCK = Lock()
_CACHE = None
_ERROR_UNTIL = 0.0


def instant(value):
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timestamp requires timezone")
    return result


def text(value, limit):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError("Invalid text")
    return value.strip()


def bilingual(value, limit):
    if not isinstance(value, dict):
        raise ValueError("Translations required")
    return {lang: text(value.get(lang), limit) for lang in LANGUAGES}


def source_url(value):
    value = text(value, 1000)
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not any(host == allowed or host.endswith("." + allowed) for allowed in HOSTS)
    ):
        raise ValueError("Untrusted source URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def validate_brief(payload, now=None):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None or not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Invalid brief")
    day = date.fromisoformat(payload["brief_date"])
    generated = instant(payload["generated_at"])
    if generated > now or generated.astimezone(TAIPEI).date() != day:
        raise ValueError("Future or misdated brief")
    if day > now.astimezone(TAIPEI).date():
        raise ValueError("Future date")
    articles, stocks = payload["articles"], payload["watchlist"]
    if not isinstance(articles, list) or not 1 <= len(articles) <= 5:
        raise ValueError("One to five articles required")
    if not isinstance(stocks, list) or len(stocks) > 5:
        raise ValueError("At most five observation stocks")
    status = payload.get("status")
    if (
        status not in ("ready", "partial")
        or status == "ready"
        and (len(articles) != 5 or len(stocks) != 5)
    ):
        raise ValueError("Ready requires five stories and five stocks")
    ids, links, publishers, cleaned = set(), set(), set(), []
    for item in articles:
        id = text(item["id"], 40)
        if not re.fullmatch(r"[a-z0-9_-]+", id) or id in ids:
            raise ValueError("Duplicate story")
        ids.add(id)
        published = date.fromisoformat(item["published_date"])
        if not day - timedelta(days=3) <= published <= day:
            raise ValueError("Source outside the declared news window")
        at = item.get("published_at")
        if at is not None:
            stamp = instant(at)
            if stamp > generated or stamp.astimezone(TAIPEI).date() != published:
                raise ValueError("Future or misdated publication")
        if item.get("category") not in ("ai", "economy"):
            raise ValueError("Unexpected category")
        sources = item["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 3:
            raise ValueError("Traceable sources required")
        safe_sources = []
        for source in sources:
            url = source_url(source["url"])
            parsed = urlsplit(url)
            canonical = (parsed.hostname, parsed.path.rstrip("/"))
            if canonical in links:
                raise ValueError("Repeated source article")
            links.add(canonical)
            publisher = text(source["publisher"], 80)
            publishers.add(
                next(
                    allowed
                    for allowed in HOSTS
                    if parsed.hostname == allowed or parsed.hostname.endswith("." + allowed)
                )
            )
            safe_sources.append({"publisher": publisher, "url": url})
        cleaned.append(
            {
                "id": id,
                "category": item["category"],
                "published_date": str(published),
                "published_at": at,
                "title": bilingual(item["title"], 120),
                "summary": bilingual(item["summary"], 400),
                "impact": bilingual(item["impact"], 300),
                "sources": safe_sources,
            }
        )
    if status == "ready" and len(publishers) < 2:
        raise ValueError("Ready requires multiple source domains")
    symbols, observations = set(), []
    for stock in stocks:
        symbol = text(stock["symbol"], 12)
        references = stock["article_ids"]
        if not re.fullmatch(r"[0-9]{4,6}\.TW", symbol) or symbol in symbols:
            raise ValueError("Invalid or duplicate observation symbol")
        if (
            not isinstance(references, list)
            or not references
            or len(references) > 5
            or any(not isinstance(id, str) or id not in ids for id in references)
        ):
            raise ValueError("Observation stock needs article links")
        relationship = stock.get("relationship")
        if relationship not in ("direct", "industry_inference"):
            raise ValueError("Relationship must be explicit")
        symbols.add(symbol)
        observations.append(
            {
                "symbol": symbol,
                "name": bilingual(stock["name"], 80),
                "sector": bilingual(stock["sector"], 80),
                "reason": bilingual(stock["reason"], 300),
                "risk": bilingual(stock["risk"], 240),
                "article_ids": list(dict.fromkeys(references)),
                "relationship": relationship,
            }
        )
    return {
        "version": 1,
        "status": status,
        "brief_date": str(day),
        "generated_at": generated.isoformat(),
        "window_start": str(day - timedelta(days=3)),
        "window_end": str(day),
        "articles": cleaned,
        "watchlist": observations,
        "method": "source_reviewed_editorial",
        "forecast_input": False,
    }


class _FixedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl != SOURCE_URL:
            raise ValueError("Unexpected redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download():
    request = Request(
        SOURCE_URL, headers={"User-Agent": "StockPredict daily brief", "Accept": "application/json"}
    )
    with build_opener(_FixedRedirect()).open(request, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Oversized brief")
    return json.loads(raw)


def read_brief(now=None):
    global _CACHE, _ERROR_UNTIL
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(TAIPEI).date()
    if not _LOCK.acquire(timeout=1):
        raise RuntimeError("Brief busy")
    try:
        if _CACHE and _CACHE[0] == day and time.monotonic() < _CACHE[1]:
            result = deepcopy(_CACHE[2])
        else:
            if time.monotonic() < _ERROR_UNTIL:
                raise RuntimeError("Brief temporarily unavailable")
            try:
                result = validate_brief(download(), now)
                ttl = 300 if result["brief_date"] == str(day) else 30
                _CACHE = (day, time.monotonic() + ttl, deepcopy(result))
            except Exception:
                _ERROR_UNTIL = time.monotonic() + 30
                raise
        if result["brief_date"] != str(day):
            return {
                "status": "waiting",
                "last_brief_date": result["brief_date"],
                "articles": [],
                "watchlist": [],
            }
        return {**result, "checked_at": now.isoformat()}
    finally:
        _LOCK.release()


@router.get("/api/news/daily")
def daily_news():
    try:
        return read_brief()
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "articles": [], "watchlist": []}
        )


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Validate a daily editorial JSON without publishing"
    )
    parser.add_argument("path")
    args = parser.parse_args()
    try:
        body = Path(args.path).read_bytes()
        if len(body) > MAX_BYTES:
            raise ValueError("Oversized file")
        result = validate_brief(json.loads(body))
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "brief_date": result["brief_date"],
                    "articles": len(result["articles"]),
                    "watchlist": len(result["watchlist"]),
                }
            )
        )
    except Exception:
        print("Invalid daily brief; nothing published.")
        raise SystemExit(1)
