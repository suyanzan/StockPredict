"""Owner-only feedback totals must cover all pages without leaking private counts."""

import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import stockpredict.community as community


@pytest.fixture
def owner_client(monkeypatch, tmp_path):
    for name in (
        "COMMUNITY_DATABASE_URL",
        "DATABASE_URL",
        "DATABASE_URL_UNPOOLED",
        "COMMUNITY_SCHEMA_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COMMUNITY_SQLITE_PATH", str(tmp_path / "feedback.sqlite3"))
    monkeypatch.setenv("COMMUNITY_MODERATION", "private")
    monkeypatch.setenv("RENDER", "false")
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("COMMUNITY_ADMIN_TOKEN", token)
    community._configured_store.cache_clear()
    app = FastAPI()
    app.include_router(community.router)
    with TestClient(app) as client:
        yield client, {"Authorization": "Bearer " + token}
    community._configured_store.cache_clear()


def submit(client, number):
    response = client.post("/api/community/comments", json={"body": f"Private suggestion {number}"})
    assert response.status_code == 201, response.text
    return response.json()["comment"]["id"]


def owner_list(client, headers, **params):
    response = client.get("/api/community/admin/comments", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_database_reports_actual_zero_counts(owner_client):
    client, headers = owner_client
    data = owner_list(client, headers)
    assert data["counts"] == {"total": 0, "pending": 0, "handled": 0, "published": 0}
    assert data["filtered_total"] == 0
    assert data["items"] == []


def test_owner_counts_endpoint_updates_without_loading_feedback_bodies(owner_client):
    client, headers = owner_client
    identifier = submit(client, 1)
    response = client.get("/api/community/admin/comments/counts", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"counts": {"total": 1, "pending": 1, "handled": 0, "published": 0}}
    assert "Private suggestion" not in response.text
    assert (
        client.patch(
            f"/api/community/admin/comments/{identifier}",
            headers=headers,
            json={"status": "hidden"},
        ).status_code
        == 200
    )
    counts = client.get("/api/community/admin/comments/counts", headers=headers).json()["counts"]
    assert counts == {"total": 1, "pending": 0, "handled": 1, "published": 0}
    assert (
        client.delete(f"/api/community/admin/comments/{identifier}", headers=headers).status_code
        == 204
    )
    assert (
        client.get("/api/community/admin/comments/counts", headers=headers).json()["counts"][
            "total"
        ]
        == 0
    )


@pytest.mark.parametrize("authentication", [None, "Bearer invalid"])
def test_owner_counts_endpoint_requires_administration_key(owner_client, authentication):
    client, _ = owner_client
    submit(client, 1)
    response = client.get(
        "/api/community/admin/comments/counts",
        headers={"Authorization": authentication} if authentication else {},
    )
    assert response.status_code == 401
    assert "counts" not in response.json()


def test_admin_counts_cover_all_rows_and_do_not_shrink_with_cursor(owner_client):
    client, headers = owner_client
    ids = [submit(client, number) for number in range(3)]
    first = owner_list(client, headers, limit=2)
    assert len(first["items"]) == 2
    assert first["counts"] == {"total": 3, "pending": 3, "handled": 0, "published": 0}
    assert first["filtered_total"] == 3
    second = owner_list(client, headers, limit=2, before=first["next_cursor"])
    assert len(second["items"]) == 1
    assert second["counts"] == first["counts"]
    assert second["filtered_total"] == 3
    assert second["next_cursor"] is None
    returned_ids = [item["id"] for item in first["items"] + second["items"]]
    assert sorted(returned_ids) == sorted(ids)


def test_marking_handled_moves_status_counts_without_changing_total(owner_client):
    client, headers = owner_client
    ids = [submit(client, number) for number in range(3)]
    response = client.patch(
        f"/api/community/admin/comments/{ids[0]}",
        headers=headers,
        json={"status": "hidden"},
    )
    assert response.status_code == 200
    pending = owner_list(client, headers)
    assert pending["counts"] == {"total": 3, "pending": 2, "handled": 1, "published": 0}
    assert pending["filtered_total"] == 2
    handled = owner_list(client, headers, status="hidden")
    assert handled["counts"] == pending["counts"]
    assert handled["filtered_total"] == 1
    assert [item["id"] for item in handled["items"]] == [ids[0]]


def test_published_records_are_in_total_and_their_own_filter(owner_client):
    client, headers = owner_client
    ids = [submit(client, number) for number in range(3)]
    for identifier, status in zip(ids[:2], ["hidden", "published"]):
        response = client.patch(
            f"/api/community/admin/comments/{identifier}",
            headers=headers,
            json={"status": status},
        )
        assert response.status_code == 200
    for status in ("pending", "hidden", "published"):
        result = owner_list(client, headers, status=status)
        assert result["counts"] == {"total": 3, "pending": 1, "handled": 1, "published": 1}
        assert result["filtered_total"] == 1
        assert len(result["items"]) == 1


def test_delete_reduces_total_and_affected_status_after_store_recreation(owner_client):
    client, headers = owner_client
    ids = [submit(client, number) for number in range(2)]
    client.patch(
        f"/api/community/admin/comments/{ids[0]}",
        headers=headers,
        json={"status": "hidden"},
    )
    deleted = client.delete(f"/api/community/admin/comments/{ids[0]}", headers=headers)
    assert deleted.status_code == 204
    community._configured_store.cache_clear()
    remaining = owner_list(client, headers)
    assert remaining["counts"] == {"total": 1, "pending": 1, "handled": 0, "published": 0}
    assert remaining["filtered_total"] == 1
    assert (
        client.delete(f"/api/community/admin/comments/{ids[1]}", headers=headers).status_code == 204
    )
    assert owner_list(client, headers)["counts"]["total"] == 0


@pytest.mark.parametrize("authentication", [None, "Bearer invalid"])
def test_unauthorized_requests_do_not_reveal_counts(owner_client, authentication):
    client, _ = owner_client
    submit(client, 1)
    response = client.get(
        "/api/community/admin/comments",
        headers={"Authorization": authentication} if authentication else {},
    )
    assert response.status_code == 401
    assert "counts" not in response.json()
    assert "filtered_total" not in response.json()
    assert "Private suggestion" not in response.text


def test_private_totals_do_not_leak_through_public_endpoints(owner_client):
    client, headers = owner_client
    identifier = submit(client, 1)
    client.patch(
        f"/api/community/admin/comments/{identifier}",
        headers=headers,
        json={"status": "published"},
    )
    assert owner_list(client, headers, status="published")["counts"]["total"] == 1
    response = client.get("/api/community/comments", params={"include_counts": "true"})
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert "counts" not in data and "filtered_total" not in data
    public_stats = client.get("/api/community/stats").json()
    assert public_stats["comments_count"] == 0
    assert "counts" not in public_stats and "filtered_total" not in public_stats


def test_public_mode_does_not_expose_pending_or_handled_owner_totals(owner_client, monkeypatch):
    client, headers = owner_client
    ids = [submit(client, number) for number in range(3)]
    for identifier, status in zip(ids[:2], ["hidden", "published"]):
        client.patch(
            f"/api/community/admin/comments/{identifier}",
            headers=headers,
            json={"status": status},
        )
    monkeypatch.setenv("COMMUNITY_MODERATION", "public")
    public = client.get("/api/community/comments").json()
    assert len(public["items"]) == 1
    assert "counts" not in public and "filtered_total" not in public
    assert client.get("/api/community/stats").json()["comments_count"] == 1
    assert owner_list(client, headers)["counts"]["total"] == 3
