"""Persistent anonymous visit counts and private-by-default visitor feedback.

Only explicitly configured databases are used: PostgreSQL for deployment or a
SQLite file for development/persistent-disk installations. An unconfigured
service never pretends that an ephemeral zero counter is a working counter.
"""

import hashlib
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(prefix="/api/community", tags=["Community"])

COOKIE_NAME = "sp_visitor"
COOKIE_AGE = 365 * 24 * 60 * 60
MAX_ID = 9_223_372_036_854_775_807
SCHEMA_LOCK_ID = 737_862_528_719
_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def moderation_mode() -> str:
    value = os.getenv("COMMUNITY_MODERATION", "private").strip().lower()
    return value if value in {"private", "review", "public"} else "private"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


class StorageUnavailable(Exception):
    """Internal marker that deliberately contains no database or credential details."""


class CommunityStore:
    """DB-API storage with parameterized SQL and atomic write transactions."""

    def __init__(self, *, database_url: str = "", sqlite_path: str = ""):
        if database_url:
            if not database_url.startswith(("postgres://", "postgresql://")):
                raise StorageUnavailable()
            self.kind = "postgres"
            self._location = database_url
        elif sqlite_path and sqlite_path != ":memory:":
            self.kind = "sqlite"
            self._location = str(Path(sqlite_path).expanduser().resolve())
        else:
            raise StorageUnavailable()
        self._initialized = False
        self._schema_lock = Lock()

    def _open(self):
        if self.kind == "sqlite":
            connection = sqlite3.connect(self._location, timeout=5, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self._location, connect_timeout=5, row_factory=dict_row)

    def _execute(self, connection, query: str, params=()):
        if self.kind == "postgres":
            query = query.replace("?", "%s")
        return connection.execute(query, params)

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._schema_lock:
            if self._initialized:
                return
            connection = None
            try:
                new_sqlite_file = False
                if self.kind == "sqlite":
                    location = Path(self._location)
                    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    new_sqlite_file = not location.exists()
                connection = self._open()
                if self.kind == "sqlite":
                    if new_sqlite_file:
                        os.chmod(self._location, 0o600)
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("BEGIN IMMEDIATE")
                else:
                    self._execute(connection, "SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK_ID,))
                self._execute(
                    connection,
                    """CREATE TABLE IF NOT EXISTS sp_visits (
                        page_id TEXT PRIMARY KEY,
                        visitor_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )""",
                )
                id_type = (
                    "INTEGER PRIMARY KEY AUTOINCREMENT"
                    if self.kind == "sqlite"
                    else "BIGSERIAL PRIMARY KEY"
                )
                self._execute(
                    connection,
                    f"""CREATE TABLE IF NOT EXISTS sp_comments (
                        id {id_type},
                        name TEXT NOT NULL,
                        body TEXT NOT NULL,
                        category TEXT NOT NULL,
                        status TEXT NOT NULL,
                        visitor_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )""",
                )
                self._execute(
                    connection,
                    "CREATE INDEX IF NOT EXISTS sp_visits_visitor ON sp_visits(visitor_hash)",
                )
                self._execute(
                    connection,
                    "CREATE INDEX IF NOT EXISTS sp_comments_status ON sp_comments(status, id)",
                )
                self._execute(
                    connection,
                    "CREATE INDEX IF NOT EXISTS sp_comments_rate "
                    "ON sp_comments(visitor_hash, created_at)",
                )
                connection.commit()
                self._initialized = True
            except Exception:
                if connection is not None:
                    with suppress(Exception):
                        connection.rollback()
                raise StorageUnavailable() from None
            finally:
                if connection is not None:
                    with suppress(Exception):
                        connection.close()

    @contextmanager
    def _transaction(self, *, write: bool = False):
        self.initialize()
        connection = None
        try:
            connection = self._open()
            if self.kind == "sqlite":
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except HTTPException:
            if connection is not None:
                with suppress(Exception):
                    connection.rollback()
            raise
        except Exception:
            if connection is not None:
                with suppress(Exception):
                    connection.rollback()
            raise StorageUnavailable() from None
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.close()

    def _stats(self, connection, mode: str) -> dict:
        row = self._execute(
            connection,
            "SELECT COUNT(*) AS page_views, COUNT(DISTINCT visitor_hash) AS unique_visitors "
            "FROM sp_visits",
        ).fetchone()
        count = 0
        if mode != "private":
            count = self._execute(
                connection, "SELECT COUNT(*) AS n FROM sp_comments WHERE status = ?", ("published",)
            ).fetchone()["n"]
        return {
            "enabled": True,
            "page_views": row["page_views"],
            "unique_visitors": row["unique_visitors"],
            "comments_count": count,
            "moderation": mode,
        }

    def stats(self, mode: str) -> dict:
        with self._transaction() as connection:
            return self._stats(connection, mode)

    def visit(self, page_id: str, visitor_hash: str, mode: str) -> dict:
        with self._transaction(write=True) as connection:
            self._execute(
                connection,
                "INSERT INTO sp_visits(page_id, visitor_hash, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(page_id) DO NOTHING",
                (page_id, visitor_hash, _stamp(_now())),
            )
            return self._stats(connection, mode)

    @staticmethod
    def _public_comment(row) -> dict:
        return {key: row[key] for key in ("id", "name", "body", "category", "created_at")}

    def _comment_counts(self, connection) -> dict:
        counts = {"total": 0, "pending": 0, "handled": 0, "published": 0}
        rows = self._execute(
            connection, "SELECT status, COUNT(*) AS n FROM sp_comments GROUP BY status"
        ).fetchall()
        for row in rows:
            count = int(row["n"])
            counts["total"] += count
            key = {"pending": "pending", "hidden": "handled", "published": "published"}.get(
                row["status"]
            )
            if key:
                counts[key] += count
        return counts

    def comment_counts(self) -> dict:
        with self._transaction() as connection:
            return self._comment_counts(connection)

    def comments(
        self,
        *,
        status: str = "published",
        limit: int = 10,
        before: int | None = None,
        include_counts: bool = False,
    ) -> dict:
        with self._transaction() as connection:
            where = "status = ?" + (" AND id < ?" if before is not None else "")
            params = (status, before, limit + 1) if before is not None else (status, limit + 1)
            rows = self._execute(
                connection,
                "SELECT id, name, body, category, status, created_at FROM sp_comments "
                f"WHERE {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            items = [{**self._public_comment(row), "status": row["status"]} for row in rows[:limit]]
            result = {
                "items": items,
                "next_cursor": items[-1]["id"] if len(rows) > limit else None,
            }
            if include_counts:
                counts = self._comment_counts(connection)
                result["counts"] = counts
                result["filtered_total"] = counts["handled" if status == "hidden" else status]
            return result

    def add_comment(
        self, visitor_hash: str, *, name: str, body: str, category: str, mode: str
    ) -> dict:
        with self._transaction(write=True) as connection:
            if self.kind == "postgres":
                # Same anonymous browser cannot race multiple submissions past its quota.
                self._execute(
                    connection,
                    "SELECT pg_advisory_xact_lock(?)",
                    (int(visitor_hash[:15], 16),),
                )
            current = _now()
            count = self._execute(
                connection,
                "SELECT COUNT(*) AS n FROM sp_comments WHERE visitor_hash = ? AND created_at >= ?",
                (visitor_hash, _stamp(current - timedelta(minutes=10))),
            ).fetchone()["n"]
            if count >= 3:
                raise _error(429, "rate_limited", "Please wait before sending another suggestion.")
            status = "published" if mode == "public" else "pending"
            row = self._execute(
                connection,
                "INSERT INTO sp_comments(name, body, category, status, visitor_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (name, body, category, status, visitor_hash, _stamp(current)),
            ).fetchone()
            return {
                "id": row["id"],
                "name": name,
                "body": body,
                "category": category,
                "status": status,
                "created_at": _stamp(current),
            }

    def update_comment(self, comment_id: int, status: str) -> dict:
        with self._transaction(write=True) as connection:
            row = self._execute(
                connection,
                "UPDATE sp_comments SET status = ? WHERE id = ? "
                "RETURNING id, name, body, category, status, created_at",
                (status, comment_id),
            ).fetchone()
            if row is None:
                raise _error(404, "not_found", "Feedback was not found.")
            return {**self._public_comment(row), "status": row["status"]}

    def delete_comment(self, comment_id: int) -> None:
        with self._transaction(write=True) as connection:
            row = self._execute(
                connection, "DELETE FROM sp_comments WHERE id = ? RETURNING id", (comment_id,)
            ).fetchone()
            if row is None:
                raise _error(404, "not_found", "Feedback was not found.")


@lru_cache(maxsize=8)
def _configured_store(database_url: str, sqlite_path: str) -> CommunityStore:
    return CommunityStore(database_url=database_url, sqlite_path=sqlite_path)


def get_store() -> CommunityStore | None:
    database_url = os.getenv("COMMUNITY_DATABASE_URL", "").strip()
    sqlite_path = os.getenv("COMMUNITY_SQLITE_PATH", "").strip()
    if not database_url and not sqlite_path:
        return None
    return _configured_store(database_url, sqlite_path)


def _required_store() -> CommunityStore:
    store = get_store()
    if store is None:
        raise _error(
            503, "not_configured", "Visitor statistics and feedback are not configured yet."
        )
    return store


def _storage_error() -> HTTPException:
    return _error(
        503, "community_unavailable", "Visitor statistics and feedback are temporarily unavailable."
    )


def _origin_check(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return
    try:
        value = urlsplit(origin)
        same = (
            value.scheme in {"http", "https"}
            and value.netloc.lower() == request.headers.get("host", "").lower()
        )
        same = same and not value.username and not value.password and value.path in {"", "/"}
    except ValueError:
        same = False
    if not same:
        raise _error(403, "forbidden_origin", "Requests must come from this website.")


def _visitor(request: Request, response: Response) -> str:
    token = request.cookies.get(COOKIE_NAME, "")
    if not _COOKIE_RE.fullmatch(token):
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=COOKIE_AGE,
            httponly=True,
            samesite="lax",
            secure=os.getenv("RENDER", "").lower() == "true" or request.url.scheme == "https",
            path="/",
        )
    return hashlib.sha256(token.encode()).hexdigest()


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("COMMUNITY_ADMIN_TOKEN", "")
    if len(expected.encode()) < 32:
        raise _error(503, "admin_not_configured", "Feedback administration is not configured yet.")
    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        provided.encode(), expected.encode()
    ):
        raise _error(401, "unauthorized", "Administrator authentication is required.")


class VisitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: UUID


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=80, strict=True)
    body: str = Field(min_length=1, max_length=2000, strict=True)
    category: Literal["suggestion", "bug", "other"] = "suggestion"

    @field_validator("name", "body")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Control characters are not supported.")
        return value.strip()

    @field_validator("body")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("Please enter your feedback.")
        return value


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["published", "hidden"]


def _disabled_stats() -> dict:
    return {
        "enabled": False,
        "page_views": None,
        "unique_visitors": None,
        "comments_count": None,
        "moderation": moderation_mode(),
    }


@router.get("/stats")
def stats():
    try:
        store = get_store()
        return store.stats(moderation_mode()) if store else _disabled_stats()
    except StorageUnavailable:
        raise _storage_error() from None


@router.post("/visits")
def visit(body: VisitInput, request: Request, response: Response):
    _origin_check(request)
    try:
        return _required_store().visit(
            str(body.page_id), _visitor(request, response), moderation_mode()
        )
    except StorageUnavailable:
        raise _storage_error() from None


@router.get("/comments")
def comments(
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    before: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
):
    mode = moderation_mode()
    try:
        store = get_store()
        if store is None or mode == "private":
            return {
                "enabled": store is not None,
                "items": [],
                "next_cursor": None,
                "moderation": mode,
            }
        result = store.comments(limit=limit, before=before)
        for item in result["items"]:
            item.pop("status")
        return {"enabled": True, "moderation": mode, **result}
    except StorageUnavailable:
        raise _storage_error() from None


@router.post("/comments", status_code=201)
def add_comment(body: CommentInput, request: Request, response: Response):
    _origin_check(request)
    try:
        result = _required_store().add_comment(
            _visitor(request, response),
            name=body.name,
            body=body.body,
            category=body.category,
            mode=moderation_mode(),
        )
        return {"comment": result}
    except StorageUnavailable:
        raise _storage_error() from None


@router.get("/admin/comments", dependencies=[Depends(require_admin)])
def admin_comments(
    status: Literal["pending", "published", "hidden"] = "pending",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    before: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
):
    try:
        return _required_store().comments(
            status=status, limit=limit, before=before, include_counts=True
        )
    except StorageUnavailable:
        raise _storage_error() from None


@router.get("/admin/comments/counts", dependencies=[Depends(require_admin)])
def admin_comment_counts():
    try:
        return {"counts": _required_store().comment_counts()}
    except StorageUnavailable:
        raise _storage_error() from None


@router.patch("/admin/comments/{comment_id}", dependencies=[Depends(require_admin)])
def update_comment(
    comment_id: Annotated[int, Field(ge=1, le=MAX_ID)], body: CommentUpdate, request: Request
):
    _origin_check(request)
    try:
        return {"comment": _required_store().update_comment(comment_id, body.status)}
    except StorageUnavailable:
        raise _storage_error() from None


@router.delete(
    "/admin/comments/{comment_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_comment(comment_id: Annotated[int, Field(ge=1, le=MAX_ID)], request: Request):
    _origin_check(request)
    try:
        _required_store().delete_comment(comment_id)
    except StorageUnavailable:
        raise _storage_error() from None
