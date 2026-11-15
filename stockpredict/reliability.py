"""Additional read-only health evidence; a successful check is not acceptance."""

from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from stockpredict import scoreboard
from stockpredict.monitoring import collection_failures

router = APIRouter()


def successful_check(check):
    details = check.get("details", [])
    return (
        len(details) == len(scoreboard.SYMBOLS)
        and {d.get("symbol") for d in details} == set(scoreboard.SYMBOLS)
        and all(d.get("status") == "current" for d in details)
        and not collection_failures(details)
    )


@router.get("/api/reliability/health")
def reliability_health():
    health = scoreboard.scoreboard_health()
    if isinstance(health, JSONResponse):
        return health
    try:
        with scoreboard.connect() as connection:
            checks = connection.execute(
                "SELECT checked_at,details FROM sp_scoreboard_checks ORDER BY id DESC LIMIT 100"
            ).fetchall()
        return {
            **health,
            "last_successful_checked_at": next(
                (c["checked_at"] for c in checks if successful_check(c)), None
            ),
            "success_search_limit": 100,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except (psycopg.Error, RuntimeError):
        return JSONResponse(status_code=503, content={"reason": "health_evidence_unavailable"})
