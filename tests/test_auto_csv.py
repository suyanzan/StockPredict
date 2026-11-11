"""Published snapshots must be current, immutable, bounded and internally consistent."""

import csv
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

import stockpredict.auto_csv as auto_csv
from stockpredict.data import DataSourceError

PAIR = ("UMC", "SOXX")
SESSION = "2026-10-30"


def test_latest_snapshot_is_display_only_and_does_not_relax_required_session(monkeypatch):
    server(monkeypatch)
    result = auto_csv.latest_snapshot_quotes(PAIR)
    assert result["display_only"] is True
    assert {q["symbol"] for q in result["quotes"]} == set(PAIR)
    assert all(q["session_date"] == SESSION for q in result["quotes"])
    assert "forecast" not in result
    with pytest.raises(DataSourceError) as error:
        auto_csv.auto_csv_factors(PAIR, "2026-11-02")
    assert error.value.code == "auto_csv_missing_session"


def test_latest_snapshot_rejects_corrupt_prices(monkeypatch):
    manifest, files = published_snapshot()
    files[manifest["files"]["UMC"]["path"]] = b"corrupt"
    server(monkeypatch, manifest, files)
    with pytest.raises(DataSourceError) as error:
        auto_csv.latest_snapshot_quotes(PAIR)
    assert error.value.code == "auto_csv_invalid_data"


def published_snapshot(session=SESSION, suffix="a" * 16):
    end = date.fromisoformat(session)
    days = []
    day = end
    while len(days) < 65:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    snapshot = session + "-" + suffix
    manifest = {
        "schema_version": 1,
        "session_date": session,
        "generated_at": session + "T22:00:00+00:00",
        "snapshot_id": snapshot,
        "source": {
            "provider": "Yahoo Finance",
            "currency": "USD",
            "price_type": "unadjusted_close",
            "session_timezone": "America/New_York",
        },
        "files": {},
    }
    files = {}
    for offset, symbol in enumerate(auto_csv.SYMBOLS):
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerow(["Date", "Close"])
        writer.writerows(
            (day.isoformat(), 100 + offset * 10 + index / 10) for index, day in enumerate(days)
        )
        raw = text.getvalue().encode()
        path = f"snapshots/{snapshot}/{symbol}.csv"
        files[path] = raw
        manifest["files"][symbol] = {
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": len(days),
            "first_date": days[0].isoformat(),
            "last_date": session,
        }
    return manifest, files


class Response(io.BytesIO):
    def __init__(self, raw, url):
        super().__init__(raw)
        self.url = url

    def geturl(self):
        return self.url


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    auto_csv.clear_cache()
    clock = {"mono": 1000.0, "wall": datetime(2026, 10, 31, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr(auto_csv, "_clock", lambda: clock["mono"])
    monkeypatch.setattr(auto_csv, "_now", lambda: clock["wall"])
    yield clock
    auto_csv.clear_cache()


def server(monkeypatch, manifest=None, files=None):
    if manifest is None:
        manifest, files = published_snapshot()
    state = {"manifest": manifest, "files": files, "failure": None}
    calls = []

    def open_response(request, timeout):
        url = request.full_url
        assert url.startswith(auto_csv.BASE_URL) and timeout == auto_csv.HTTP_TIMEOUT
        assert request.get_header("Authorization") is None
        calls.append(url)
        if state["failure"]:
            raise state["failure"]
        path = url.removeprefix(auto_csv.BASE_URL)
        if path == "manifest.json":
            raw = state["manifest"]
            raw = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
        else:
            raw = state["files"][path]
        return Response(raw, url)

    monkeypatch.setattr(auto_csv, "_urlopen", open_response)
    return state, calls


def test_valid_snapshot_returns_exact_session_and_provenance(monkeypatch):
    _, calls = server(monkeypatch)
    factors, metadata = auto_csv.auto_csv_factors(PAIR, SESSION)
    assert set(factors) == set(PAIR)
    assert all(points[-1]["date"] == SESSION and len(points) == 65 for points in factors.values())
    assert metadata == {
        "snapshot_session_date": SESSION,
        "generated_at": SESSION + "T22:00:00+00:00",
        "provider": "Yahoo Finance",
    }
    assert len(calls) == 3
    assert all("snapshots/2026-10-30-" in url for url in calls[1:])


def test_cache_is_detached_and_new_pair_uses_its_own_symbols(monkeypatch):
    _, calls = server(monkeypatch)
    first, _ = auto_csv.auto_csv_factors(PAIR, SESSION)
    first["UMC"][0]["close"] = -1
    second, _ = auto_csv.auto_csv_factors(PAIR, SESSION)
    assert second["UMC"][0]["close"] > 0 and len(calls) == 3
    tsm, _ = auto_csv.auto_csv_factors(("TSM", "SOXX"), SESSION)
    assert set(tsm) == {"TSM", "SOXX"} and "UMC" not in tsm
    assert len(calls) == 5


def test_weekend_query_can_use_exact_required_friday_session(monkeypatch, isolated_cache):
    isolated_cache["wall"] = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    server(monkeypatch)
    factors, _ = auto_csv.auto_csv_factors(PAIR, SESSION)
    assert factors["UMC"][-1]["date"] == SESSION


@pytest.mark.parametrize("required", ["2026-11-02", "2026-10-29"])
def test_different_manifest_session_never_substitutes_old_or_new_prices(monkeypatch, required):
    _, calls = server(monkeypatch)
    with pytest.raises(DataSourceError) as caught:
        auto_csv.auto_csv_factors(PAIR, required)
    assert caught.value.code == "auto_csv_missing_session"
    assert len(calls) == 1


def test_manifest_refresh_uses_new_immutable_paths(monkeypatch, isolated_cache):
    state, calls = server(monkeypatch)
    first, _ = auto_csv.auto_csv_factors(PAIR, SESSION)
    manifest, files = published_snapshot(suffix="b" * 16)
    raw = files[manifest["files"]["UMC"]["path"]].replace(b"100.0", b"200.0")
    files[manifest["files"]["UMC"]["path"]] = raw
    manifest["files"]["UMC"]["sha256"] = hashlib.sha256(raw).hexdigest()
    state.update(manifest=manifest, files=files)
    isolated_cache["mono"] += 300
    refreshed, _ = auto_csv.auto_csv_factors(PAIR, SESSION)
    assert refreshed["UMC"][0]["close"] != first["UMC"][0]["close"]
    assert len(calls) == 6 and "b" * 16 in calls[-1]


def test_manifest_failure_never_returns_previously_cached_pair(monkeypatch, isolated_cache):
    state, calls = server(monkeypatch)
    auto_csv.auto_csv_factors(PAIR, SESSION)
    state["failure"] = HTTPError(auto_csv.BASE_URL, 503, "PRIVATE upstream text", {}, None)
    isolated_cache["mono"] += 301
    with pytest.raises(DataSourceError) as caught:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert caught.value.code == "auto_csv_unavailable" and caught.value.http_status == 503
    assert "PRIVATE" not in str(caught.value)
    assert len(calls) == 4


def test_404_cooldown_does_not_retry_and_preserves_safe_fields(monkeypatch, isolated_cache):
    state, calls = server(monkeypatch)
    state["failure"] = HTTPError(auto_csv.BASE_URL, 404, "Secret untrusted body", {}, None)
    with pytest.raises(DataSourceError) as first:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert first.value.http_status == 404
    isolated_cache["mono"] += 59
    with pytest.raises(DataSourceError) as cached:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert cached.value.code == "auto_csv_unavailable" and cached.value.retry_after == 1
    assert cached.value.http_status == 404 and len(calls) == 1
    isolated_cache["mono"] += 1
    state["failure"] = None
    assert auto_csv.auto_csv_factors(PAIR, SESSION)[0]["UMC"][-1]["date"] == SESSION


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "bool_schema",
        "missing_symbol",
        "extra_symbol",
        "path",
        "unused_path",
        "hash",
        "bool_rows",
        "too_many_rows",
        "bad_first_date",
        "wrong_last_date",
        "bad_snapshot",
        "bad_source",
        "naive_time",
        "future_time",
        "preclose_time",
    ],
)
def test_invalid_manifest_is_rejected_before_csv_requests(monkeypatch, mutation):
    manifest, files = published_snapshot()
    if mutation == "schema":
        manifest["schema_version"] = 2
    elif mutation == "bool_schema":
        manifest["schema_version"] = True
    elif mutation == "missing_symbol":
        del manifest["files"]["TSM"]
    elif mutation == "extra_symbol":
        manifest["files"]["EVIL"] = {}
    elif mutation == "path":
        manifest["files"]["UMC"]["path"] = "../../private"
    elif mutation == "unused_path":
        manifest["files"]["TSM"]["path"] = "https://evil.test/data"
    elif mutation == "hash":
        manifest["files"]["UMC"]["sha256"] = "not a digest"
    elif mutation == "bool_rows":
        manifest["files"]["SOXX"]["rows"] = True
    elif mutation == "too_many_rows":
        manifest["files"]["SOXX"]["rows"] = 5001
    elif mutation == "bad_first_date":
        manifest["files"]["SOXX"]["first_date"] = "20261030"
    elif mutation == "wrong_last_date":
        manifest["files"]["SOXX"]["last_date"] = "2026-10-29"
    elif mutation == "bad_snapshot":
        manifest["snapshot_id"] = "../../secret"
    elif mutation == "bad_source":
        manifest["source"]["currency"] = "TWD"
    elif mutation == "naive_time":
        manifest["generated_at"] = "2026-10-30T22:00:00"
    elif mutation == "future_time":
        manifest["generated_at"] = "2026-11-01T22:00:00+00:00"
    elif mutation == "preclose_time":
        manifest["generated_at"] = "2026-10-30T18:00:00+00:00"
    _, calls = server(monkeypatch, manifest, files)
    with pytest.raises(DataSourceError) as caught:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert caught.value.code == "auto_csv_invalid_data" and len(calls) == 1


@pytest.mark.parametrize("content", [b"not-json", b"x" * (auto_csv.MANIFEST_LIMIT + 1)])
def test_bad_or_oversized_manifest_fails_closed(monkeypatch, content):
    _, calls = server(monkeypatch, content, {})
    with pytest.raises(DataSourceError) as caught:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert caught.value.code == "auto_csv_invalid_data" and len(calls) == 1


@pytest.mark.parametrize(
    "corruption", ["hash", "oversize", "utf8", "bad_price", "row_count", "first_date"]
)
def test_invalid_csv_cannot_reach_model(monkeypatch, corruption):
    manifest, files = published_snapshot()
    item = manifest["files"]["UMC"]
    path = item["path"]
    if corruption == "hash":
        files[path] += b"altered"
    elif corruption == "oversize":
        files[path] = b"x" * (auto_csv.CSV_LIMIT + 1)
    elif corruption == "utf8":
        files[path] = b"\xff"
    elif corruption == "bad_price":
        files[path] = files[path].replace(b"100.0", b"nan")
    elif corruption == "row_count":
        item["rows"] -= 1
    elif corruption == "first_date":
        item["first_date"] = "2026-01-01"
    if corruption in {"utf8", "bad_price"}:
        item["sha256"] = hashlib.sha256(files[path]).hexdigest()
    server(monkeypatch, manifest, files)
    with pytest.raises(DataSourceError) as caught:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert caught.value.code == "auto_csv_invalid_data"
    assert not auto_csv._CACHE


def test_redirect_outside_fixed_repository_is_not_followed():
    handler = auto_csv._SnapshotRedirect()
    request = Request(auto_csv.BASE_URL + "manifest.json")
    for target in (
        "https://evil.test/file",
        "https://raw.githubusercontent.com/other/repo/file",
        "http://raw.githubusercontent.com/suyanzan/StockPredict/market-data/file",
        "https://raw.githubusercontent.com/suyanzan/StockPredict/market-data/../private",
        "https://raw.githubusercontent.com/suyanzan/StockPredict/market-data/%2e%2e/private",
    ):
        with pytest.raises(URLError):
            handler.redirect_request(request, None, 302, "Found", {}, target)


def test_unexpected_final_url_is_rejected(monkeypatch):
    monkeypatch.setattr(
        auto_csv, "_urlopen", lambda *args, **kwargs: Response(b"{}", "https://evil.test/manifest")
    )
    with pytest.raises(DataSourceError) as caught:
        auto_csv.auto_csv_factors(PAIR, SESSION)
    assert caught.value.code == "auto_csv_invalid_data"


def test_concurrent_callers_share_one_manifest_and_pair(monkeypatch):
    _, calls = server(monkeypatch)
    start = Barrier(4)

    def load():
        start.wait(timeout=5)
        return auto_csv.auto_csv_factors(PAIR, SESSION)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result(timeout=10) for f in [pool.submit(load) for _ in range(4)]]
    assert all(result == results[0] for result in results)
    assert len(calls) == 3


def test_cache_and_failure_entries_are_bounded(monkeypatch):
    server(monkeypatch)
    monkeypatch.setattr(auto_csv, "MAX_CACHE_SIZE", 1)
    auto_csv.auto_csv_factors(PAIR, SESSION)
    auto_csv.auto_csv_factors(("TSM", "SOXX"), SESSION)
    assert len(auto_csv._CACHE) == 1
    for required in ("2026-10-28", "2026-10-29"):
        with pytest.raises(DataSourceError):
            auto_csv.auto_csv_factors(PAIR, required)
    assert len(auto_csv._ERRORS) == 1


@pytest.mark.parametrize(
    ("pair", "required"),
    [
        (("EVIL", "SOXX"), SESSION),
        (("UMC", "TSM"), SESSION),
        (PAIR, "20261030"),
        (PAIR, "bad"),
    ],
)
def test_invalid_arguments_do_not_start_requests(monkeypatch, pair, required):
    _, calls = server(monkeypatch)
    with pytest.raises(ValueError):
        auto_csv.auto_csv_factors(pair, required)
    assert not calls
