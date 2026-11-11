from fastapi.testclient import TestClient

import stockpredict.main as main
from stockpredict.data import DataSourceError


def test_latest_quotes_endpoint_selects_profile_and_marks_no_store(monkeypatch):
    def latest(pair):
        assert pair == ("TSM", "SOXX")
        return {"status": "ready", "display_only": True, "quotes": []}

    monkeypatch.setattr(main, "latest_snapshot_quotes", latest)
    response = TestClient(main.app).get("/api/reference-quotes/latest?symbol=2330")
    assert response.status_code == 200
    assert response.json()["display_only"] is True
    assert response.headers["cache-control"] == "no-store"


def test_latest_quotes_failure_is_safe_and_does_not_return_model_inputs(monkeypatch):
    def failed(pair):
        raise DataSourceError("private provider payload", code="auto_csv_unavailable")

    monkeypatch.setattr(main, "latest_snapshot_quotes", failed)
    client = TestClient(main.app)
    assert client.get("/api/reference-quotes/latest?symbol=AAPL").status_code == 422
    response = client.get("/api/reference-quotes/latest?symbol=2303")
    assert response.status_code == 503
    assert response.json() == {"reason": "auto_csv_unavailable"}
