from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from stockpredict import daily_news as news
from stockpredict.main import app

NOW = datetime(2026, 11, 15, 8, tzinfo=timezone.utc)


def payload():
    def both(value):
        return {"zh-TW": value, "en": value}

    return {
        "version": 1,
        "status": "ready",
        "brief_date": "2026-11-15",
        "generated_at": "2026-11-15T07:55:00+00:00",
        "articles": [
            {
                "id": f"story-{i}",
                "category": "ai" if i else "economy",
                "published_date": "2026-11-15",
                "published_at": None,
                "title": both(f"Test headline {i}"),
                "summary": both("Test summary"),
                "impact": both("Test inference"),
                "sources": [
                    {
                        "publisher": "Test source",
                        "url": (
                            f"https://{'www.cna.com.tw' if i else 'nvidianews.nvidia.com'}"
                            f"/news/test-{i}"
                        ),
                    }
                ],
            }
            for i in range(5)
        ],
        "watchlist": [
            {
                "symbol": s,
                "name": both("Test company"),
                "sector": both("Test sector"),
                "reason": both("Test relevance, not an order announcement"),
                "risk": both("Test risk"),
                "article_ids": [f"story-{i}"],
                "relationship": "industry_inference",
            }
            for i, s in enumerate(["2330.TW", "2382.TW", "2308.TW", "2408.TW", "3711.TW"])
        ],
    }


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(news, "_CACHE", None)
    monkeypatch.setattr(news, "_ERROR_UNTIL", 0)


def test_five_sources_and_five_watch_stocks_keep_only_safe_fields():
    data = payload()
    data["private"] = "must not be served"
    data["watchlist"][0]["internal"] = "not public"
    result = news.validate_brief(data, NOW)
    assert len(result["articles"]) == len(result["watchlist"]) == 5
    assert result["forecast_input"] is False
    assert result["watchlist"][0]["relationship"] == "industry_inference"
    assert "private" not in result and "internal" not in result["watchlist"][0]
    assert result["articles"][0]["published_at"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_story",
        "duplicate_source",
        "duplicate_stock",
        "unknown_reference",
        "unsafe_url",
        "future_generated",
        "future_published",
        "old_article",
        "ready_partial",
        "untranslated",
        "false_precision",
        "missing_relationship",
        "same_source_aliases",
    ],
)
def test_invalid_or_misleading_editorial_data_fails_closed(fault):
    data = payload()
    if fault == "duplicate_story":
        data["articles"][1]["id"] = data["articles"][0]["id"]
    elif fault == "duplicate_source":
        data["articles"][1]["sources"] = deepcopy(data["articles"][0]["sources"])
    elif fault == "duplicate_stock":
        data["watchlist"][1]["symbol"] = data["watchlist"][0]["symbol"]
    elif fault == "unknown_reference":
        data["watchlist"][0]["article_ids"] = ["not-a-story"]
    elif fault == "unsafe_url":
        data["articles"][0]["sources"][0]["url"] = "javascript:alert(1)"
    elif fault == "future_generated":
        data["generated_at"] = (NOW + timedelta(hours=1)).isoformat()
    elif fault == "future_published":
        data["articles"][0]["published_at"] = (NOW + timedelta(hours=1)).isoformat()
    elif fault == "old_article":
        data["articles"][0]["published_date"] = "2026-11-10"
    elif fault == "ready_partial":
        data["watchlist"].pop()
    elif fault == "untranslated":
        data["articles"][0]["summary"].pop("en")
    elif fault == "false_precision":
        data["articles"][0]["published_at"] = "2026-11-15T07:00:00"
    elif fault == "missing_relationship":
        data["watchlist"][0].pop("relationship")
    elif fault == "same_source_aliases":
        for i, item in enumerate(data["articles"]):
            item["sources"][0] = {
                "publisher": f"Different label {i}",
                "url": f"https://www.cna.com.tw/news/{i}",
            }
    with pytest.raises(ValueError):
        news.validate_brief(data, NOW)


@pytest.mark.parametrize(
    "url",
    [
        "https://cna.com.tw.evil.test/news",
        "http://www.cna.com.tw/news",
        "https://user:password@www.cna.com.tw/news",
        "https://127.0.0.1/news",
        "https://www.cna.com.tw:8000/news",
    ],
)
def test_source_links_cannot_escape_trusted_https_hosts(url):
    with pytest.raises(ValueError):
        news.source_url(url)


def test_partial_brief_does_not_pretend_to_have_five():
    data = payload()
    data["status"] = "partial"
    data["articles"] = data["articles"][:1]
    data["watchlist"] = []
    result = news.validate_brief(data, NOW)
    assert result["status"] == "partial"
    assert len(result["articles"]) == 1


def test_cache_is_copied_and_prior_day_is_never_presented_as_today(monkeypatch):
    calls = []
    monkeypatch.setattr(news, "download", lambda: (calls.append(1), payload())[1])
    first = news.read_brief(NOW)
    first["articles"].clear()
    assert len(news.read_brief(NOW)["articles"]) == 5
    assert len(calls) == 1
    result = news.read_brief(NOW + timedelta(days=1))
    assert result["status"] == "waiting"
    assert result["articles"] == [] and result["watchlist"] == []
    assert len(calls) == 2


def test_expired_cache_source_failure_never_falls_back_to_old_headlines(monkeypatch):
    monkeypatch.setattr(news, "download", payload)
    news.read_brief(NOW)
    monkeypatch.setattr(news, "_CACHE", (NOW.astimezone(news.TAIPEI).date(), 0, payload()))

    def unavailable():
        raise RuntimeError("private internal details")

    monkeypatch.setattr(news, "download", unavailable)
    with TestClient(app) as client:
        response = client.get("/api/news/daily")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "articles": [], "watchlist": []}
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


def test_reader_does_not_follow_redirect_to_a_different_source():
    with pytest.raises(ValueError):
        news._FixedRedirect().redirect_request(
            None, None, 302, "", {}, "https://example.com/data.json"
        )
