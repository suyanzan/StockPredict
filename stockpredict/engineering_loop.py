"""Bounded engineering verification and evidence ledger; reasoning stays with the engineer.

This command runs one iteration, not a background AI service. Failed unchanged
code is never retried. Passed unchanged code can refresh read-only live evidence.
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from stockpredict.calendar import available_at, date_path, is_session, opens_at, previous_session

MAX_ROUNDS = 3
GOAL = "trading_day_lifecycle"
CHECKS = (
    ("lint", ("-m", "ruff", "check", ".")),
    ("format", ("-m", "ruff", "format", "--check", ".")),
    ("tests", ("-m", "pytest", "-q", "--tb=short")),
)


def local_test_database(url):
    """The automated loop must not use a remote/production database for tests."""
    try:
        parsed = urlsplit(url.strip())
        return (
            parsed.scheme in ("postgres", "postgresql")
            and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            and not ({"host", "hostaddr", "service"} & parse_qs(parsed.query).keys())
            and bool(parsed.path.strip("/"))
        )
    except ValueError:
        return False


def redact(text):
    return re.sub(r"postgres(?:ql)?://[^\s\"']+", "<redacted-database-url>", text)


def fingerprint(root):
    files = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "stockpredict",
            "tests",
            ".github",
            "pyproject.toml",
            "uv.lock",
            ".gitignore",
        ],
        cwd=root,
        text=True,
    ).splitlines()
    digest = hashlib.sha256()
    for name in sorted(set(files)):
        digest.update(name.encode())
        path = root / name
        digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
    return digest.hexdigest()


def iteration_decision(state, current):
    rounds = state.get("rounds", [])
    if rounds and rounds[-1]["fingerprint"] == current:
        return "refresh_evidence" if rounds[-1]["passed"] else "no_progress"
    return "run_checks" if len(rounds) < MAX_ROUNDS else "budget_exhausted"


def run_checks(root):
    results = []
    for name, args in CHECKS:
        print(f"Checking {name}...", flush=True)
        started = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, *args],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=600,
                env={**os.environ, "PY_COLORS": "0"},
            )
            code, output = result.returncode, result.stdout + result.stderr
            if name == "tests" and re.search(r"\b\d+ skipped\b", output):
                code = 1
                output += "\nIncomplete verification: skipped tests require engineer review."
        except subprocess.TimeoutExpired:
            code, output = 124, "Check exceeded its time budget"
        results.append(
            {
                "name": name,
                "exit_code": code,
                "seconds": round(time.monotonic() - started, 2),
                "output_tail": redact(output[-5000:]),
            }
        )
        if code:
            break
    return results


def live_acceptance(report, *, now=None):
    """A complete live cohort needs both stocks/scenarios and actual days 1 and 5."""
    if report.get("status") != "ready":
        return {"status": "blocked", "reason": "live_storage_unavailable"}
    critical = [a["code"] for a in report.get("alerts", []) if a.get("severity") == "critical"]
    if critical:
        return {"status": "blocked", "reason": "live_critical_alerts", "alerts": critical}
    now = now or datetime.now(timezone.utc)
    cohorts = {}
    for row in report.get("predictions", []):
        origin = row.get("origin_date")
        try:
            day = date.fromisoformat(origin)
            saved_at = datetime.fromisoformat(row["created_at"])
            horizon = row["horizon"]
            expected = date_path([{}] * 5, str(previous_session(day)), "XTAI")
            valid = (
                saved_at.utcoffset() is not None
                and is_session(day)
                and saved_at.astimezone(ZoneInfo("Asia/Taipei")).date() == day
                and saved_at < opens_at(day)
                and horizon in (1, 5)
                and row["target_date"] == expected[horizon - 1]["date"]
                and now >= available_at(date.fromisoformat(row["target_date"]))
                and math.isfinite(row["actual_close"])
                and row["actual_close"] > 0
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if valid and row.get("status") == "scored":
            cohorts.setdefault(origin, {})[(row["symbol"], row["scenario"], row["horizon"])] = row
    required = {
        (s, c, h) for s in ("2303.TW", "2330.TW") for c in ("taiwan", "adr") for h in (1, 5)
    }
    complete = []
    for origin, cohort in cohorts.items():
        if not required <= cohort.keys():
            continue
        if all(
            cohort[s, c, 1][field] == cohort[s, c, 5][field]
            for s in ("2303.TW", "2330.TW")
            for c in ("taiwan", "adr")
            for field in ("id", "created_at", "base_close")
        ):
            complete.append(origin)
    complete.sort()
    if complete:
        return {
            "status": "passed",
            "completed_origin": complete[-1],
            "required_scored_records": len(required),
        }
    return {
        "status": "pending",
        "reason": "await_live_preopen_and_day5_cohort",
        "live_records": len(report.get("predictions", [])),
        "last_checked_at": report.get("last_check", {}).get("checked_at")
        if report.get("last_check")
        else None,
    }


def probe(site):
    parsed = urlsplit(site)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        return {"status": "blocked", "reason": "public_https_site_required"}
    try:
        with urlopen(
            Request(site.rstrip("/") + "/api/scoreboard", headers={"Accept": "application/json"}),
            timeout=45,
        ) as response:
            report = json.loads(response.read(5_000_001))
        return live_acceptance(report)
    except Exception:
        return {"status": "blocked", "reason": "live_probe_failed"}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def execute(root, state_path, report_path, site):
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {
            "protocol": 1,
            "goal": GOAL,
            "rounds": [],
        }
    )
    if state.get("goal") != GOAL or state.get("protocol") != 1:
        raise ValueError("State belongs to a different loop protocol or goal")
    current = fingerprint(root)
    decision = iteration_decision(state, current)
    report = {
        "goal": GOAL,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": current,
        "max_rounds": MAX_ROUNDS,
        "decision": decision,
        "engineering_passed": False,
        "notification_delivery": "not_verified",
        "publishes_code": False,
        "writes_live_archive": False,
    }
    if decision in ("no_progress", "budget_exhausted"):
        report.update(status=decision, rounds_used=len(state["rounds"]))
        save_json(report_path, report)
        return 2, report
    if decision == "run_checks":
        if not local_test_database(os.getenv("TEST_POSTGRES_URL", "")):
            report.update(
                status="blocked_local_test_database_required", rounds_used=len(state["rounds"])
            )
            save_json(report_path, report)
            return 2, report
        checks = run_checks(root)
        passed = len(checks) == len(CHECKS) and all(c["exit_code"] == 0 for c in checks)
        state["rounds"].append(
            {
                "number": len(state["rounds"]) + 1,
                "fingerprint": current,
                "passed": passed,
                "checks": checks,
            }
        )
    latest = state["rounds"][-1]
    report.update(
        engineering_passed=latest["passed"],
        rounds_used=len(state["rounds"]),
        checks=latest["checks"],
    )
    if not latest["passed"]:
        report["status"] = "needs_engineer"
        code = 1
    else:
        evidence = probe(site)
        report["live_acceptance"] = evidence
        report["status"] = {
            "passed": "complete",
            "pending": "waiting_market",
            "blocked": "needs_engineer",
        }[evidence["status"]]
        code = {"passed": 0, "pending": 3, "blocked": 1}[evidence["status"]]
    state["latest_status"] = report["status"]
    save_json(state_path, state)
    save_json(report_path, report)
    return code, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="https://stockpredict-xwar.onrender.com")
    parser.add_argument("--state", type=Path, default=Path(".engineering-loop/lifecycle.json"))
    parser.add_argument(
        "--report", type=Path, default=Path("artifacts/engineering-loop/latest.json")
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    code, report = execute(root, root / args.state, root / args.report, args.site)
    print(
        json.dumps({k: v for k, v in report.items() if k != "checks"}, ensure_ascii=False, indent=2)
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
