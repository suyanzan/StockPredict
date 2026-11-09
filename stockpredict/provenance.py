"""Stable engine manifest for audit and conservative replay compatibility checks."""

import hashlib
import json
import os
import platform
import re
import zoneinfo
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def model_manifest():
    root = Path(__file__).parent
    names = (
        "forecast",
        "adr_scenario",
        "calendar",
        "overnight",
        "comparison",
        "model_review",
        "historical",
        "corporate_actions",
        "backtest_runs",
        "provenance",
        "reference_profiles",
        "scoreboard",
    )
    files = {
        name: hashlib.sha256((root / f"{name}.py").read_bytes()).hexdigest()
        for name in names
        if (root / f"{name}.py").exists()
    }
    zones = {}
    for name in ("Asia/Taipei", "America/New_York"):
        for base in zoneinfo.TZPATH:
            path = Path(base) / name
            if path.is_file():
                zones[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                break
        else:
            from importlib.resources import files as resource_files

            zones[name] = hashlib.sha256(
                resource_files("tzdata.zoneinfo").joinpath(name).read_bytes()
            ).hexdigest()
    return {
        "schema_version": 1,
        "build_commit": (
            os.getenv("RENDER_GIT_COMMIT")
            if re.fullmatch(r"[a-fA-F0-9]{40}", os.getenv("RENDER_GIT_COMMIT", ""))
            else None
        ),
        "engine_hash": digest(files),
        "source_files": files,
        "python": platform.python_version(),
        "timezone_data": zones,
        "libraries": {
            name: version(name) for name in ("numpy", "pandas", "exchange_calendars", "tzdata")
        },
        "parameters": {
            "ar5": {"lags": 5, "ridge_penalty": 0.01, "return_clip": 0.2, "minimum_points": 60},
            "adr": {"sensitivity": 0.5, "daily_decay": 0.8, "max_adjustment_pct": 5.0},
            "horizons": [1, 5],
            "prices": "provider_daily_close_snapshot",
        },
    }


def release_identity():
    """Public code identity; environment values are returned only if valid commit SHAs."""
    commit = next(
        (
            value.lower()
            for name in ("RENDER_GIT_COMMIT", "GITHUB_SHA")
            if re.fullmatch(r"[a-fA-F0-9]{40}", value := os.getenv(name, ""))
        ),
        None,
    )
    return {"commit": commit, "source_hash": _release_source_hash()}


@lru_cache(maxsize=1)
def _release_source_hash():
    root = Path(__file__).parent
    return digest(
        {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
        }
    )
