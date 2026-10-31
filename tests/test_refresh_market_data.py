"""The scheduled job must never publish partial, stale, or unfinished closes."""

import hashlib
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import stockpredict.refresh_market_data as refresh_job
from stockpredict.data import DataSourceError, parse_csv

NOW = datetime.fromisoformat("2026-10-30T16:30:00-04:00")


def observations(end=date(2026, 10, 30)):
    days = []
    day = end
    while len(days) < 70:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return [
        {"date": day.isoformat(), "close": 100.0 + index / 10}
        for index, day in enumerate(reversed(days))
    ]


def fake_provider(monkeypatch, *, end=date(2026, 10, 30), metadata=None):
    calls, sleeps = [], []
    points = observations(end)

    def fetch(symbol):
        calls.append(symbol)
        return deepcopy(points), {
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            **(metadata or {}),
        }

    monkeypatch.setattr(refresh_job, "yahoo_data", fetch)
    monkeypatch.setattr(refresh_job, "_sleep", sleeps.append)
    return calls, sleeps


def tree_bytes(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("2026-10-30T16:14:59-04:00", "waiting"),
        ("2026-12-04T20:30:00+00:00", "waiting"),  # 15:30 NY in standard time.
        ("2026-10-31T17:00:00-04:00", "no_session"),
        ("2026-11-01T17:00:00-05:00", "no_session"),
    ],
)
def test_before_close_or_weekend_never_fetches_or_mutates_files(
    monkeypatch, tmp_path, text, status
):
    monkeypatch.setattr(refresh_job, "yahoo_data", lambda _: pytest.fail("Unexpected request"))
    output = tmp_path / "not-created"
    result = refresh_job.refresh(output, now=datetime.fromisoformat(text))
    assert result["status"] == status
    assert not output.exists()


def test_complete_snapshot_has_exact_dates_hashes_and_immutable_paths(monkeypatch, tmp_path):
    calls, sleeps = fake_provider(monkeypatch)
    result = refresh_job.refresh(tmp_path, now=NOW)
    assert result["status"] == "updated"
    assert calls == list(refresh_job.SYMBOLS)
    assert sleeps == [3.0] * 4
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    assert manifest["session_date"] == "2026-10-30"
    assert manifest["generated_at"] == "2026-10-30T20:30:00+00:00"
    assert manifest["source"] == refresh_job.SOURCE
    assert set(manifest["files"]) == set(refresh_job.SYMBOLS)
    assert re.fullmatch(r"2026-10-30-[a-f0-9]{16}", manifest["snapshot_id"])
    contents = {}
    for symbol, record in manifest["files"].items():
        assert record["path"] == f"snapshots/{manifest['snapshot_id']}/{symbol}.csv"
        raw = (tmp_path / record["path"]).read_bytes()
        assert raw.startswith(b"Date,Close\n") and b"\r" not in raw
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        parsed = parse_csv(raw.decode())
        assert len(parsed) == record["rows"] == 70
        assert parsed[-1]["date"] == record["last_date"] == "2026-10-30"
        assert parsed[0]["date"] == record["first_date"]
        contents[symbol] = raw
    digest = hashlib.sha256()
    for symbol in refresh_job.SYMBOLS:
        digest.update((symbol + "\n").encode())
        digest.update(contents[symbol])
    assert manifest["snapshot_id"] == "2026-10-30-" + digest.hexdigest()[:16]


def test_intact_current_snapshot_skips_second_cron_without_requests(monkeypatch, tmp_path):
    fake_provider(monkeypatch)
    first = refresh_job.refresh(tmp_path, now=NOW)
    before = tree_bytes(tmp_path)
    monkeypatch.setattr(refresh_job, "yahoo_data", lambda _: pytest.fail("Duplicate request"))
    monkeypatch.setattr(refresh_job, "_sleep", lambda _: pytest.fail("Unexpected pacing"))
    result = refresh_job.refresh(tmp_path, now=NOW + timedelta(hours=1))
    assert result == {**first, "status": "already_current"}
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("generated_at", "2026-10-30T16:14:59-04:00"),
        ("generated_at", "2026-10-30T20:35:01+00:00"),
        ("generated_at", "2026-10-30T20:30:00"),
    ],
)
def test_invalid_current_manifest_is_rebuilt_instead_of_skipping(
    monkeypatch, tmp_path, field, value
):
    fake_provider(monkeypatch)
    refresh_job.refresh(tmp_path, now=NOW)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    calls, _ = fake_provider(monkeypatch)
    result = refresh_job.refresh(tmp_path, now=NOW)
    assert result["status"] == "updated" and calls == list(refresh_job.SYMBOLS)
    repaired = json.loads(path.read_bytes())
    assert type(repaired["schema_version"]) is int and repaired["schema_version"] == 1
    assert repaired["generated_at"] == "2026-10-30T20:30:00+00:00"


def test_new_york_date_not_utc_date_controls_snapshot(monkeypatch, tmp_path):
    fake_provider(monkeypatch)
    result = refresh_job.refresh(tmp_path, now=datetime.fromisoformat("2026-10-31T00:30:00+00:00"))
    assert result["session_date"] == "2026-10-30" and result["status"] == "updated"


@pytest.mark.parametrize("end", [date(2026, 10, 29), date(2026, 11, 2)])
def test_previous_or_future_session_cannot_be_published(monkeypatch, tmp_path, end):
    calls, _ = fake_provider(monkeypatch, end=end)
    output = tmp_path / "data"
    with pytest.raises(DataSourceError):
        refresh_job.refresh(output, now=NOW)
    assert calls == ["UMC"] and not output.exists()


@pytest.mark.parametrize("metadata", [{"currency": "TWD"}, {"exchange_timezone": "UTC"}])
def test_wrong_currency_or_timezone_cannot_be_published(monkeypatch, tmp_path, metadata):
    fake_provider(monkeypatch, metadata=metadata)
    with pytest.raises(DataSourceError):
        refresh_job.refresh(tmp_path, now=NOW)
    assert not (tmp_path / "manifest.json").exists()


def test_late_symbol_failure_preserves_previous_snapshot_and_stops(monkeypatch, tmp_path):
    fake_provider(monkeypatch, end=date(2026, 10, 29))
    refresh_job.refresh(tmp_path, now=NOW - timedelta(days=1))
    before = tree_bytes(tmp_path)
    calls, sleeps = [], []

    def fetch(symbol):
        calls.append(symbol)
        if symbol == "TSM":
            raise DataSourceError(
                "No retry", code="us_rate_limited", http_status=429, retry_after=900
            )
        return observations(), {"currency": "USD", "exchange_timezone": "America/New_York"}

    monkeypatch.setattr(refresh_job, "yahoo_data", fetch)
    monkeypatch.setattr(refresh_job, "_sleep", sleeps.append)
    with pytest.raises(DataSourceError) as caught:
        refresh_job.refresh(tmp_path, now=NOW)
    assert caught.value.code == "us_rate_limited" and caught.value.retry_after == 900
    assert calls == ["UMC", "TSM"] and sleeps == [3.0]
    assert tree_bytes(tmp_path) == before


def test_bad_hash_is_not_treated_as_current_or_overwritten_under_same_id(monkeypatch, tmp_path):
    fake_provider(monkeypatch)
    refresh_job.refresh(tmp_path, now=NOW)
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    (tmp_path / manifest["files"]["UMC"]["path"]).write_text("corrupt")
    before = tree_bytes(tmp_path)
    calls, _ = fake_provider(monkeypatch)
    with pytest.raises(ValueError, match="incompatible"):
        refresh_job.refresh(tmp_path, now=NOW)
    assert calls == list(refresh_job.SYMBOLS)
    assert tree_bytes(tmp_path) == before


def test_untrusted_manifest_path_is_not_read_and_is_rebuilt(monkeypatch, tmp_path):
    fake_provider(monkeypatch)
    refresh_job.refresh(tmp_path, now=NOW)
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest["files"]["UMC"]["path"] = "../../outside.csv"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    calls, _ = fake_provider(monkeypatch)
    result = refresh_job.refresh(tmp_path, now=NOW)
    assert result["status"] == "updated" and calls == list(refresh_job.SYMBOLS)
    repaired = json.loads((tmp_path / "manifest.json").read_bytes())
    assert repaired["files"]["UMC"]["path"].startswith("snapshots/")


def test_prunes_only_safe_snapshot_directories_and_keeps_five_prior(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    for day in range(20, 28):
        old = snapshots / f"2026-10-{day:02}-{'a' * 16}"
        old.mkdir()
        (old / "old.csv").write_text("old")
    unsafe = snapshots / "leave-this-alone"
    unsafe.mkdir()
    (unsafe / "value").write_text("keep")
    fake_provider(monkeypatch)
    result = refresh_job.refresh(tmp_path, now=NOW)
    valid = [
        path for path in snapshots.iterdir() if refresh_job.SNAPSHOT_PATTERN.fullmatch(path.name)
    ]
    assert len(valid) == 6
    assert (snapshots / result["snapshot_id"]).is_dir()
    assert (unsafe / "value").read_text() == "keep"


def test_symlink_output_directory_rejected_before_network(monkeypatch, tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir()
    link = tmp_path / "link"
    link.symlink_to(destination, target_is_directory=True)
    monkeypatch.setattr(refresh_job, "yahoo_data", lambda _: pytest.fail("Unexpected request"))
    with pytest.raises(ValueError, match="symbolic"):
        refresh_job.refresh(link, now=NOW)
    assert list(destination.iterdir()) == []


def test_cli_error_reports_only_safe_fields(monkeypatch, capsys, tmp_path):
    def unavailable(*args, **kwargs):
        raise DataSourceError(
            "do-not-print-provider-body", code="us_rate_limited", http_status=429, retry_after=600
        )

    monkeypatch.setattr(refresh_job, "refresh", unavailable)
    monkeypatch.setattr(sys, "argv", ["refresh", "--output-dir", str(tmp_path)])
    assert refresh_job.main() == 1
    output = capsys.readouterr().out
    assert "do-not-print" not in output
    assert json.loads(output) == {
        "status": "unavailable",
        "reason": "us_rate_limited",
        "http_status": 429,
        "retry_after_seconds": 600,
    }


def _workflow_shell(name):
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/update-market-data.yml"
    lines = workflow.read_text().splitlines()
    start = lines.index("      - name: " + name)
    run = next(index for index in range(start + 1, len(lines)) if lines[index] == "        run: |")
    end = run + 1
    while end < len(lines) and (lines[end].startswith("          ") or not lines[end]):
        end += 1
    return "\n".join(line[10:] for line in lines[run + 1 : end])


def _git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_every_workflow_run_block_has_valid_shell_syntax():
    for name in (
        "Prepare a separate data-branch worktree",
        "Generate a complete snapshot",
        "Publish only validated CSV data",
    ):
        subprocess.run(
            ["bash", "-n"], input=_workflow_shell(name), text=True, check=True, capture_output=True
        )


def test_workflow_new_and_existing_data_branch_never_touch_main(monkeypatch, tmp_path):
    """Execute the workflow's actual shell against a local bare remote."""
    remote, source, runner = tmp_path / "remote.git", tmp_path / "source", tmp_path / "runner"
    runner.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
    _git(source, "config", "user.name", "Test")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "main-only.txt").write_text("Do not publish app files to the data branch.")
    _git(source, "add", "main-only.txt")
    _git(source, "commit", "-m", "Initial main")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "main")
    python = source / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    head, status = _git(source, "rev-parse", "HEAD"), _git(source, "status", "--porcelain")
    environment = {**os.environ, "RUNNER_TEMP": str(runner), "GITHUB_WORKSPACE": str(source)}
    calls, _ = fake_provider(monkeypatch)
    previous_remote_head = None
    for iteration in range(2):
        output = runner / f"output-{iteration}"
        environment["GITHUB_OUTPUT"] = str(output)
        subprocess.run(
            ["bash", "-c", _workflow_shell("Prepare a separate data-branch worktree")],
            cwd=source,
            env=environment,
            check=True,
            capture_output=True,
        )
        data_dir = Path(output.read_text().strip().split("=", 1)[1])
        result = refresh_job.refresh(data_dir, now=NOW)
        assert result["status"] == ("updated" if iteration == 0 else "already_current")
        environment["CSV_DATA_DIR"] = str(data_dir)
        subprocess.run(
            ["bash", "-c", _workflow_shell("Publish only validated CSV data")],
            cwd=source,
            env=environment,
            check=True,
            capture_output=True,
        )
        remote_head = _git(remote, "rev-parse", "refs/heads/market-data")
        if iteration:
            assert remote_head == previous_remote_head
        previous_remote_head = remote_head
        paths = _git(remote, "ls-tree", "-r", "--name-only", "refs/heads/market-data").splitlines()
        assert len(paths) == 6 and "manifest.json" in paths
        assert all(path == "manifest.json" or path.startswith("snapshots/") for path in paths)
        assert _git(source, "rev-parse", "HEAD") == head
        assert _git(source, "status", "--porcelain") == status
        assert (source / "main-only.txt").is_file()
    assert calls == list(refresh_job.SYMBOLS)
