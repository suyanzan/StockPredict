from datetime import datetime

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

import stockpredict.scoreboard as score
from stockpredict.calendar import date_path
from stockpredict.main import app

NOW = datetime.fromisoformat("2026-10-30T08:59:59+08:00")
POINTS = [{"date": "2026-10-29", "close": 100.0}]
PATH = date_path([{"close": 101.0}] * 5, "2026-10-29", "XTAI")


@pytest.mark.parametrize("variable", ["SCOREBOARD_DATABASE_URL", "DATABASE_URL"])
def test_connection_secret_trims_pasted_whitespace_without_changing_security_options(
    monkeypatch, variable
):
    from unittest.mock import Mock

    url = "postgresql://user:pass%20word@example.test/db?sslmode=require&channel_binding=require"
    monkeypatch.delenv("SCOREBOARD_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(variable, " \r\n" + url + " \n")
    driver = Mock()
    monkeypatch.setattr(score.psycopg, "connect", driver)
    assert score.connect() is driver.return_value
    driver.assert_called_once_with(url, row_factory=dict_row, connect_timeout=5)


def save(connection, scenario="taiwan", now=NOW, path=PATH):
    return score.save_prediction(
        connection, "2303.TW", scenario, POINTS, path, now, {"source": "TWSE", "raw": "original"}
    )


def test_first_capture_wins_across_connections_and_scenarios(database):
    with database() as conn:
        assert save(conn) == "saved"
        assert save(conn, "adr") == "saved"
    with database() as conn:
        altered = [{**p, "close": 999.0} for p in PATH]
        assert save(conn, path=altered) == "already_saved"
        records = conn.execute("SELECT * FROM sp_predictions ORDER BY id").fetchall()
        assert len(records) == 2
        assert records[0]["snapshot"]["forecast"] == PATH
        assert records[0]["snapshot"]["history"] == POINTS
        assert records[0]["snapshot"]["provenance"]["raw"] == "original"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE sp_predictions SET base_close=5",
        "DELETE FROM sp_predictions",
        "UPDATE sp_actual_closes SET close=5",
        "DELETE FROM sp_actual_closes",
        "TRUNCATE sp_predictions",
        "TRUNCATE sp_actual_closes",
    ],
)
def test_database_rejects_archive_mutations(database, sql):
    with database() as conn:
        save(conn)
        score.save_actual(
            conn, "2303.TW", PATH[0], datetime.fromisoformat("2026-10-30T15:00:00+08:00")
        )
    with pytest.raises(psycopg.Error, match="append-only"), database() as conn:
        conn.execute(sql)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-30T09:00:00+08:00", "after_cutoff"),
        ("2026-10-30T15:00:00+08:00", "after_cutoff"),
        ("2026-10-29T16:00:00+08:00", "outside_capture_day"),
    ],
)
def test_late_or_early_capture_never_scores(database, now, expected):
    with database() as conn:
        assert save(conn, now=datetime.fromisoformat(now)) == expected
        assert conn.execute("SELECT count(*) AS n FROM sp_predictions").fetchone()["n"] == 0


def test_exact_close_publication_pending_and_scenario_separation(database):
    with database() as conn:
        save(conn)
        save(conn, "adr")
        early = datetime.fromisoformat("2026-10-30T14:59:59+08:00")
        assert not score.save_actual(conn, "2303.TW", PATH[0], early)
        # A prior session must not be used as the first day's actual close.
        assert score.save_actual(conn, "2303.TW", POINTS[0], NOW)
    client = TestClient(app)
    pending = client.get("/api/scoreboard").json()
    assert all(r["status"] == "pending" for r in pending["predictions"])
    assert all(s["samples"] == 0 and s["mae"] is None for s in pending["summary"])
    with database() as conn:
        published = datetime.fromisoformat("2026-10-30T15:00:00+08:00")
        assert score.save_actual(conn, "2303.TW", {**PATH[0], "close": 102.0}, published)
        score.save_actual(conn, "2303.TW", {**PATH[0], "close": 500.0}, published)
    response = client.get("/api/scoreboard")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    first = [r for r in body["predictions"] if r["horizon"] == 1]
    assert len(first) == 2
    assert all(
        r["actual_close"] == 102 and r["error"] == -1 and r["direction_hit"] is True for r in first
    )
    fifth = [r for r in body["predictions"] if r["horizon"] == 5]
    assert all(r["status"] == "pending" and r["direction_hit"] is None for r in fifth)


def test_flat_direction_and_zero_error(database):
    with database() as conn:
        save(conn, path=[{**p, "close": 100.0} for p in PATH])
        score.save_actual(
            conn,
            "2303.TW",
            {**PATH[0], "close": 100.0},
            datetime.fromisoformat("2026-10-30T15:00:00+08:00"),
        )
    body = TestClient(app).get("/api/scoreboard").json()
    first = next(
        s
        for s in body["summary"]
        if s["symbol"] == "2303.TW" and s["scenario"] == "taiwan" and s["horizon"] == 1
    )
    assert first["samples"] == 1 and first["mae"] == first["mape"] == 0
    assert first["direction_accuracy"] == 1


def test_prediction_detail_exposes_original_inputs_and_exact_observation_status(
    database, monkeypatch
):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat("2026-10-30T14:59:59+08:00").astimezone(tz)

    provenance = {
        "metadata": {"source": "twse"},
        "private_internal_metadata": "do-not-expose",
        "market_context": {
            "status": "ready",
            "data_source": "auto_csv",
            "required_us_session_date": "2026-10-29",
            "quotes": [
                {"symbol": "UMC", "session_date": "2026-10-29", "close": 5, "currency": "USD"}
            ],
        },
    }
    with database() as conn:
        score.save_prediction(conn, "2303.TW", "adr", POINTS, PATH, NOW, provenance)
        row = conn.execute("SELECT * FROM sp_predictions").fetchone()
    monkeypatch.setattr(score, "datetime", Clock)
    client = TestClient(app)
    response = client.get(f"/api/predictions/{row['id']}")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    detail = response.json()
    assert detail["model_version"] == score.MODEL and detail["engine_manifest"]["engine_hash"]
    assert detail["training"] == {"start": "2026-10-29", "end": "2026-10-29", "samples": 1}
    assert detail["reference_quotes"][0]["session_date"] == "2026-10-29"
    assert all(p["pending_reason"] == "awaiting_publication" for p in detail["forecast"])
    assert "do-not-expose" not in response.text
    with database() as conn:
        score.save_actual(
            conn,
            "2303.TW",
            {**PATH[0], "close": 102},
            datetime.fromisoformat("2026-10-30T15:00:00+08:00"),
        )
    published = client.get(f"/api/predictions/{row['id']}").json()
    assert published["forecast"][0]["actual_close"] == 102
    assert published["forecast"][0]["actual_source"] == "TWSE"
    assert published["forecast"][0]["observed_at"]
    assert published["evaluation"][0]["error"] == -1
    assert published["created_at"] == detail["created_at"]
    assert client.get("/api/predictions/999999999").status_code == 404
    with database() as conn:
        assert (
            conn.execute("SELECT snapshot FROM sp_predictions").fetchone()["snapshot"]
            == row["snapshot"]
        )


def test_fifth_trading_day_uses_its_own_actual_and_direction(database):
    with database() as conn:
        save(conn, path=[{**p, "close": 99.0} for p in PATH])
        published = datetime.fromisoformat("2026-11-05T15:00:00+08:00")
        score.save_actual(conn, "2303.TW", {**PATH[0], "close": 90.0}, published)
        score.save_actual(conn, "2303.TW", {**PATH[4], "close": 110.0}, published)
    body = TestClient(app).get("/api/scoreboard").json()
    first = next(r for r in body["predictions"] if r["horizon"] == 1)
    fifth = next(r for r in body["predictions"] if r["horizon"] == 5)
    assert first["direction_hit"] is True and first["error"] == 9
    assert fifth["target_date"] == "2026-11-05"
    assert fifth["direction_hit"] is False and fifth["error"] == -11
    assert fifth["absolute_error_pct"] == pytest.approx(10)


def test_storage_unavailable_is_explicit_without_leaking_credentials(monkeypatch):
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(app).get("/api/scoreboard")
    assert response.status_code == 503
    assert response.json()["reason"] == "scoreboard_storage_unavailable"
    assert response.json()["predictions"] == []


def test_invalid_price_or_nontrading_path_rejected(database):
    with database() as conn:
        with pytest.raises(ValueError):
            save(conn, path=[{**p, "close": float("nan")} for p in PATH])
        with pytest.raises(ValueError):
            save(conn, path=[{**p, "date": "2026-10-31"} for p in PATH])


def test_monitor_health_is_read_only_and_does_not_return_archive(database):
    response = TestClient(app).get("/api/scoreboard/health")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "ready" and body["alerts"][0]["code"] == "no_checks"
    assert set(body) == {"status", "alerts", "last_checked_at"}


def test_concurrent_captures_have_one_winner(database):
    from concurrent.futures import ThreadPoolExecutor

    def capture():
        with database() as conn:
            return save(conn)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: capture(), range(2))) == ["already_saved", "saved"]


def test_job_captures_both_scenarios_and_reports_provider_failure(database, monkeypatch):
    import stockpredict.main as main
    import stockpredict.twse as twse

    class Clock:
        @staticmethod
        def now(tz):
            return NOW.astimezone(tz)

    monkeypatch.setattr(score, "datetime", Clock)
    monkeypatch.setattr(twse, "twse_data", lambda symbol: (POINTS, {"source": "twse"}))
    monkeypatch.setattr(
        main,
        "_market_analysis",
        lambda *a, **kw: {
            "history": POINTS,
            "forecast": PATH,
            "market_context": {"status": "ready", "scenario_forecast": PATH},
        },
    )
    first = score.run_job()
    assert all(c[s] == "saved" for c in first for s in score.scenarios_for(c["symbol"]))
    assert all(
        c[s] == "already_saved" for c in score.run_job() for s in score.scenarios_for(c["symbol"])
    )

    def unavailable(symbol):
        from stockpredict.data import DataSourceError

        raise DataSourceError("Provider failed")

    monkeypatch.setattr(twse, "twse_data", unavailable)
    checks = score.run_job()
    assert all(c["status"] == "unavailable" and c["checked_at"] for c in checks)
    body = TestClient(app).get("/api/scoreboard").json()
    assert len(body["predictions"]) == 10
    assert body["last_check"]["details"] == checks


def test_job_after_cutoff_collects_actuals_without_generating_forecasts(database, monkeypatch):
    import stockpredict.main as main
    import stockpredict.twse as twse

    class Clock:
        @staticmethod
        def now(tz):
            return datetime.fromisoformat("2026-10-30T10:00:00+08:00").astimezone(tz)

    monkeypatch.setattr(score, "datetime", Clock)
    monkeypatch.setattr(twse, "twse_data", lambda symbol: (POINTS, {"source": "twse"}))
    monkeypatch.setattr(main, "_market_analysis", lambda *a, **kw: pytest.fail("Late forecast"))
    checks = score.run_job()
    assert all(c[s] == "after_cutoff" for c in checks for s in score.scenarios_for(c["symbol"]))
    with database() as conn:
        assert conn.execute("SELECT count(*) AS n FROM sp_predictions").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM sp_actual_closes").fetchone()["n"] == len(
            score.SYMBOLS
        )


def test_full_trading_week_lifecycle_uses_real_models_and_immutable_postgres(database, monkeypatch):
    """Exercise the production job/API over five sessions; only clocks/feeds are simulated."""
    from copy import deepcopy
    from datetime import date

    import stockpredict.calendar as sessions
    import stockpredict.main as main
    import stockpredict.overnight as overnight
    import stockpredict.twse as twse
    from stockpredict.monitoring import health_alerts

    clock = {"now": datetime.fromisoformat("2026-11-02T08:10:00+08:00"), "correction": 0}
    origin = date(2026, 11, 2)
    days = [
        d.date() for d in sessions.calendar("XTAI").sessions_in_range("2026-03-01", "2026-11-06")
    ]
    past = [d for d in days if d < origin][-150:]
    future = [d for d in days if d >= origin]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz)

    def feed(symbol):
        base = 100.0 if symbol == "2303.TW" else 900.0
        rows = [
            {"date": str(d), "close": base + (clock["correction"] if d == past[-1] else 0)}
            for d in past
        ]
        # Deliberately deliver a same-day mutable bar to test the publication gate.
        rows.extend(
            {"date": str(d), "close": base + i + 2}
            for i, d in enumerate(future)
            if d <= clock["now"].date()
        )
        if clock["now"].hour < 13:
            rows = [p for p in rows if p["date"] < str(clock["now"].date())]
        return deepcopy(rows), {
            "source": "twse",
            "name": symbol,
            "source_label": "TWSE",
            "currency": "TWD",
        }

    def factors(symbols, required):
        dates = sessions.calendar("XNYS").sessions_in_range("2026-01-01", required)
        return (
            {s: [{"date": str(d.date()), "close": 100.0} for d in dates] for s in symbols},
            {"fixture": True, "session_date": required},
        )

    monkeypatch.setattr(score, "datetime", Clock)
    monkeypatch.setattr(overnight, "datetime", Clock)
    monkeypatch.setattr(sessions, "datetime", Clock)
    monkeypatch.setattr(twse, "twse_data", feed)
    monkeypatch.setattr(main, "twse_data", feed)
    monkeypatch.setattr(main, "auto_csv_factors", factors)
    client = TestClient(app)

    checks = score.run_job()
    assert all(c[s] == "saved" for c in checks for s in score.scenarios_for(c["symbol"]))
    with database() as conn:
        originals = conn.execute("SELECT id,snapshot FROM sp_predictions ORDER BY id").fetchall()
    assert len(originals) == 5

    clock.update(now=datetime.fromisoformat("2026-11-02T08:30:00+08:00"), correction=0.5)
    assert all(
        c[s] == "already_saved" for c in score.run_job() for s in score.scenarios_for(c["symbol"])
    )

    clock["now"] = datetime.fromisoformat("2026-11-02T14:59:59+08:00")
    score.run_job()
    pending = client.get("/api/scoreboard").json()
    assert len(pending["predictions"]) == 10
    assert all(r["status"] == "pending" for r in pending["predictions"])
    assert all(c["paired_samples"] == 0 for c in pending["comparison"])

    clock["now"] = datetime.fromisoformat("2026-11-02T15:30:00+08:00")
    score.run_job()
    day_one = client.get("/api/scoreboard").json()
    assert all(
        r["status"] == ("scored" if r["horizon"] == 1 else "pending")
        for r in day_one["predictions"]
    )
    assert all(
        c["paired_samples"] == (1 if c["horizon"] == 1 else 0) for c in day_one["comparison"]
    )

    clock["now"] = datetime.fromisoformat("2026-11-03T09:00:00+08:00")
    assert all(
        c[s] == "after_cutoff" for c in score.run_job() for s in score.scenarios_for(c["symbol"])
    )
    with database() as conn:
        assert conn.execute("SELECT count(*) AS n FROM sp_predictions").fetchone()["n"] == 5
    late = client.get("/api/scoreboard").json()
    alerts = health_alerts(
        late["predictions"],
        late["last_check"],
        datetime.fromisoformat("2026-11-02T08:10:00+08:00"),
        now=datetime.fromisoformat("2026-11-03T09:45:00+08:00"),
    )
    assert len([a for a in alerts if a["code"] == "preopen_missing"]) == 5

    for d in future[1:]:
        clock["now"] = datetime.fromisoformat(f"{d}T15:30:00+08:00")
        score.run_job()
    completed = client.get("/api/scoreboard").json()
    assert len(completed["predictions"]) == 10
    assert all(r["status"] == "scored" for r in completed["predictions"])
    assert all(c["paired_samples"] == 1 and c["adr_coverage"] == 1 for c in completed["comparison"])
    for r in completed["predictions"]:
        assert r["target_date"] == ("2026-11-02" if r["horizon"] == 1 else "2026-11-06")
    with database() as conn:
        assert (
            conn.execute("SELECT id,snapshot FROM sp_predictions ORDER BY id").fetchall()
            == originals
        )


def test_delta_archive_migrates_legacy_constraint_and_rejects_adr(database):
    with database() as conn:
        conn.execute("ALTER TABLE sp_predictions DROP CONSTRAINT sp_predictions_symbol_check")
        conn.execute(
            "ALTER TABLE sp_predictions ADD CONSTRAINT sp_predictions_symbol_check "
            "CHECK (symbol IN ('2303.TW','2330.TW'))"
        )
        save(conn)
    with database() as conn:
        score.initialize(conn)
        assert score.save_prediction(conn, "2308.TW", "taiwan", POINTS, PATH, NOW, {}) == "saved"
        with pytest.raises(ValueError):
            score.save_prediction(conn, "2308.TW", "adr", POINTS, PATH, NOW, {})
        assert conn.execute("SELECT count(*) AS n FROM sp_predictions").fetchone()["n"] == 2
    body = TestClient(app).get("/api/scoreboard").json()
    delta = [s for s in body["summary"] if s["symbol"] == "2308.TW"]
    assert len(delta) == 2
    assert {s["scenario"] for s in delta} == {"taiwan"}
    assert all(s["samples"] == 0 and s["pending"] == 1 for s in delta)
