from copy import deepcopy
from datetime import datetime

import pytest

from stockpredict.calendar import date_path
from stockpredict.engineering_loop import iteration_decision, live_acceptance, local_test_database


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql://u:p@127.0.0.1:55432/test", True),
        ("postgres://u:p@localhost/test?sslmode=require", True),
        ("postgresql://u:p@[::1]/test", True),
        ("postgresql://u:p@production.example/db", False),
        ("postgresql://u:p@localhost/db?host=production.example", False),
        ("postgresql://u:p@localhost/db?hostaddr=203.0.113.1", False),
        ("", False),
    ],
)
def test_runner_only_uses_explicit_local_postgres(url, expected):
    assert local_test_database(url) is expected


def test_loop_requires_changes_after_failure_and_stops_at_budget():
    state = {"rounds": [{"fingerprint": "a", "passed": False}]}
    assert iteration_decision(state, "a") == "no_progress"
    assert iteration_decision(state, "b") == "run_checks"
    state["rounds"][-1]["passed"] = True
    assert iteration_decision(state, "a") == "refresh_evidence"
    state["rounds"] *= 3
    assert iteration_decision(state, "b") == "budget_exhausted"


def cohort():
    path = date_path([{}] * 5, "2026-10-01", "XTAI")
    records = []
    for index, (symbol, scenario) in enumerate(
        (s, c)
        for s in ("2303.TW", "2330.TW", "2308.TW")
        for c in (("taiwan",) if s == "2308.TW" else ("taiwan", "adr"))
    ):
        for h in (1, 5):
            records.append(
                dict(
                    id=index + 1,
                    symbol=symbol,
                    scenario=scenario,
                    horizon=h,
                    origin_date=path[0]["date"],
                    target_date=path[h - 1]["date"],
                    created_at="2026-10-02T08:10:00+08:00",
                    base_close=100,
                    actual_close=102,
                    status="scored",
                )
            )
    return {"status": "ready", "alerts": [], "predictions": records}


def test_live_gate_requires_exact_cohort_and_never_treats_empty_board_as_success():
    now = datetime.fromisoformat("2026-10-31T12:00:00+08:00")
    assert live_acceptance({"status": "ready", "predictions": []}, now=now)["status"] == "pending"
    report = cohort()
    assert live_acceptance(report, now=now)["status"] == "passed"
    report["predictions"].pop()
    assert live_acceptance(report, now=now)["status"] == "pending"


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", "2026-10-02T09:00:00+08:00"),
        ("target_date", "2026-10-05"),
        ("status", "pending"),
        ("actual_close", None),
        ("id", 999),
    ],
)
def test_live_gate_rejects_late_or_mismatched_evidence(field, value):
    report = deepcopy(cohort())
    report["predictions"][1][field] = value
    result = live_acceptance(report, now=datetime.fromisoformat("2026-10-31T12:00:00+08:00"))
    assert result["status"] == "pending"


def test_live_critical_alert_blocks_acceptance():
    report = cohort()
    report["alerts"] = [{"code": "schedule_stale", "severity": "critical"}]
    assert live_acceptance(report)["status"] == "blocked"


def test_iteration_passes_checks_once_then_refreshes_live_evidence_without_retesting(
    tmp_path, monkeypatch
):
    import stockpredict.engineering_loop as loop

    calls = []
    monkeypatch.setenv("TEST_POSTGRES_URL", "postgresql://u:p@localhost/test")
    monkeypatch.setattr(loop, "fingerprint", lambda root: "fixed-source")

    def checks(root):
        calls.append(root)
        return [{"name": n, "exit_code": 0} for n, _ in loop.CHECKS]

    monkeypatch.setattr(loop, "run_checks", checks)
    monkeypatch.setattr(loop, "probe", lambda site: {"status": "pending"})
    state, report = tmp_path / "state.json", tmp_path / "report.json"
    first_code, first = loop.execute(tmp_path, state, report, "https://example.test")
    second_code, second = loop.execute(tmp_path, state, report, "https://example.test")
    assert first_code == second_code == 3
    assert first["engineering_passed"] and second["decision"] == "refresh_evidence"
    assert len(calls) == second["rounds_used"] == 1
    assert second["notification_delivery"] == "not_verified"
