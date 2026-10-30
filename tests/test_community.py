"""Persistent statistics, private feedback, and authenticated owner administration."""

import hashlib
import secrets
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import stockpredict.community as community


@pytest.fixture
def configuration(monkeypatch, tmp_path):
    path = tmp_path / "private" / "community.sqlite3"
    monkeypatch.delenv("COMMUNITY_DATABASE_URL", raising=False)
    monkeypatch.delenv("COMMUNITY_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("COMMUNITY_MODERATION", raising=False)
    monkeypatch.setenv("COMMUNITY_SQLITE_PATH", str(path))
    monkeypatch.setenv("RENDER", "false")
    community._configured_store.cache_clear()
    yield path
    community._configured_store.cache_clear()


@pytest.fixture
def app(configuration):
    application = FastAPI()
    application.include_router(community.router)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as instance:
        yield instance


@pytest.fixture
def admin_headers(monkeypatch):
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("COMMUNITY_ADMIN_TOKEN", token)
    return {"Authorization": "Bearer " + token}


def visit(client, page_id=None):
    return client.post("/api/community/visits", json={"page_id": str(page_id or uuid4())})


def feedback(client, body="Please add another chart", **kwargs):
    return client.post("/api/community/comments", json={"body": body, **kwargs})


def test_unconfigured_features_are_disabled_instead_of_reporting_fake_zero(client, monkeypatch):
    monkeypatch.delenv("COMMUNITY_SQLITE_PATH")
    assert client.get("/api/community/stats").json() == {
        "enabled": False,
        "page_views": None,
        "unique_visitors": None,
        "comments_count": None,
        "moderation": "private",
    }
    assert client.get("/api/community/comments").json()["items"] == []
    response = visit(client)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_configured"
    assert community.COOKIE_NAME not in client.cookies


def test_visit_counts_distinguish_page_views_from_browser_cookies(client, app):
    page = uuid4()
    first = visit(client, page)
    assert first.status_code == 200
    assert first.json()["page_views"] == first.json()["unique_visitors"] == 1
    assert visit(client, page).json()["page_views"] == 1
    second = visit(client)
    assert second.json()["page_views"] == 2 and second.json()["unique_visitors"] == 1
    with TestClient(app) as another_browser:
        third = visit(another_browser)
    assert third.json()["page_views"] == 3 and third.json()["unique_visitors"] == 2


def test_browser_cookie_is_opaque_http_only_and_only_hash_is_stored(client, configuration):
    response = visit(client)
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header and "SameSite=lax" in cookie_header
    assert "Max-Age=31536000" in cookie_header
    token = client.cookies[community.COOKIE_NAME]
    with sqlite3.connect(configuration) as connection:
        stored = connection.execute("SELECT visitor_hash FROM sp_visits").fetchone()[0]
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in configuration.read_bytes().decode(errors="ignore")
    assert "visitor_hash" not in response.text and token not in response.text


def test_render_browser_cookie_is_secure(app, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    with TestClient(app, base_url="https://testserver") as browser:
        response = visit(browser)
        assert "Secure" in response.headers["set-cookie"]
        assert visit(browser).json()["unique_visitors"] == 1


def test_invalid_visitor_cookie_is_replaced(client):
    client.cookies.set(community.COOKIE_NAME, "not-a-valid-visitor")
    response = visit(client)
    assert response.status_code == 200 and "set-cookie" in response.headers


def test_statistics_and_feedback_survive_store_recreation(client, configuration, admin_headers):
    visit(client)
    submitted = feedback(client).json()["comment"]
    community._configured_store.cache_clear()
    assert client.get("/api/community/stats").json()["page_views"] == 1
    entries = client.get("/api/community/admin/comments", headers=admin_headers).json()["items"]
    assert [item["id"] for item in entries] == [submitted["id"]]
    assert configuration.exists()
    assert stat.S_IMODE(configuration.stat().st_mode) == 0o600


def test_feedback_is_private_by_default_even_if_owner_marks_it_published(client, admin_headers):
    submitted = feedback(client, name="Visitor").json()["comment"]
    assert submitted["status"] == "pending"
    assert client.get("/api/community/comments").json()["items"] == []
    assert client.get("/api/community/stats").json()["comments_count"] == 0
    response = client.patch(
        f"/api/community/admin/comments/{submitted['id']}",
        json={"status": "published"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert client.get("/api/community/comments").json()["items"] == []
    assert client.get("/api/community/stats").json()["comments_count"] == 0
    assert "visitor_hash" not in response.text


def test_owner_can_read_mark_handled_and_delete_private_feedback(client, admin_headers):
    submitted = feedback(client, name="Anonymous", category="bug").json()["comment"]
    listing = client.get("/api/community/admin/comments", headers=admin_headers)
    assert listing.status_code == 200 and listing.json()["items"][0]["body"] == submitted["body"]
    assert "visitor_hash" not in listing.text
    path = f"/api/community/admin/comments/{submitted['id']}"
    assert client.patch(path, json={"status": "hidden"}, headers=admin_headers).status_code == 200
    assert client.get("/api/community/admin/comments", headers=admin_headers).json()["items"] == []
    assert client.get("/api/community/admin/comments?status=hidden", headers=admin_headers).json()[
        "items"
    ]
    assert client.delete(path, headers=admin_headers).status_code == 204
    assert client.delete(path, headers=admin_headers).status_code == 404


@pytest.mark.parametrize("value", [None, "", "short"])
def test_missing_or_short_admin_configuration_is_unavailable(client, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("COMMUNITY_ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("COMMUNITY_ADMIN_TOKEN", value)
    response = client.get("/api/community/admin/comments")
    assert (
        response.status_code == 503 and response.json()["detail"]["code"] == "admin_not_configured"
    )


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic unsupported"])
def test_bad_admin_authentication_does_not_reveal_feedback(client, admin_headers, header):
    feedback(client)
    response = client.get(
        "/api/community/admin/comments", headers={"Authorization": header} if header else {}
    )
    assert response.status_code == 401 and "Please add" not in response.text


def test_query_string_cannot_supply_admin_authentication(client, admin_headers):
    token = admin_headers["Authorization"].split(" ", 1)[1]
    assert client.get("/api/community/admin/comments", params={"token": token}).status_code == 401


def test_rate_limit_persists_in_database_and_expires(client, monkeypatch, admin_headers):
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(community, "_now", lambda: now)
    for _ in range(3):
        assert feedback(client).status_code == 201
    community._configured_store.cache_clear()
    fourth = feedback(client)
    assert fourth.status_code == 429 and fourth.json()["detail"]["code"] == "rate_limited"
    now += timedelta(minutes=10, seconds=1)
    assert feedback(client).status_code == 201


@pytest.mark.parametrize(
    "origin", ["https://other.example", "null", "https://testserver.attacker.example"]
)
def test_cross_origin_mutations_are_rejected(client, origin):
    response = client.post(
        "/api/community/visits", json={"page_id": str(uuid4())}, headers={"Origin": origin}
    )
    assert response.status_code == 403 and response.json()["detail"]["code"] == "forbidden_origin"
    assert client.get("/api/community/stats").json()["page_views"] == 0


def test_same_authority_origin_accepts_https_behind_render_proxy(client):
    response = client.post(
        "/api/community/visits",
        json={"page_id": str(uuid4())},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("body", ["", "   ", "a" * 2001, "contains\x00control"])
def test_feedback_validation(client, body):
    assert feedback(client, body=body).status_code == 422


def test_names_categories_and_unknown_fields_are_validated(client):
    assert feedback(client, name="a" * 81).status_code == 422
    assert feedback(client, category="unknown").status_code == 422
    assert feedback(client, extra="not-supported").status_code == 422


def test_html_and_sql_remain_plain_text_and_do_not_execute(client, admin_headers):
    content = "<script>alert(1)</script>'); DROP TABLE sp_visits; --"
    response = feedback(client, body=content)
    assert response.status_code == 201
    assert (
        client.get("/api/community/admin/comments", headers=admin_headers).json()["items"][0][
            "body"
        ]
        == content
    )
    assert visit(client).json()["page_views"] == 1


def test_readonly_or_invalid_database_error_is_sanitized(client, monkeypatch):
    def unavailable(self):
        raise RuntimeError("DO_NOT_EXPOSE_CONNECTION_DETAILS")

    community._configured_store.cache_clear()
    monkeypatch.setattr(community.CommunityStore, "_open", unavailable)
    response = client.get("/api/community/stats")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "community_unavailable"
    assert "DO_NOT_EXPOSE" not in response.text


def test_atomic_concurrent_visits_do_not_lose_counts(configuration):
    store = community.get_store()
    page_ids = [str(uuid4()) for _ in range(30)]
    visitor = hashlib.sha256(b"test-browser").hexdigest()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda page: store.visit(page, visitor, "private"), page_ids))
    assert all(result["enabled"] for result in results)
    assert store.stats("private")["page_views"] == 30
    assert store.stats("private")["unique_visitors"] == 1


def test_public_and_review_modes_require_explicit_configuration(client, monkeypatch, admin_headers):
    monkeypatch.setenv("COMMUNITY_MODERATION", "review")
    entry = feedback(client).json()["comment"]
    assert client.get("/api/community/comments").json()["items"] == []
    client.patch(
        f"/api/community/admin/comments/{entry['id']}",
        json={"status": "published"},
        headers=admin_headers,
    )
    assert len(client.get("/api/community/comments").json()["items"]) == 1
    monkeypatch.setenv("COMMUNITY_MODERATION", "public")
    assert feedback(client).json()["comment"]["status"] == "published"
    assert client.get("/api/community/stats").json()["comments_count"] == 2


def test_cursor_pagination_has_no_duplicates(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_MODERATION", "public")
    for _ in range(3):
        assert feedback(client).status_code == 201
    first = client.get("/api/community/comments?limit=2").json()
    second = client.get(
        "/api/community/comments", params={"limit": 2, "before": first["next_cursor"]}
    ).json()
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 3 and second["next_cursor"] is None
    assert client.get("/api/community/comments?limit=51").status_code == 422
