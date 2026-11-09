import json

import stockpredict.provenance as provenance


def test_manifest_records_source_libraries_parameters_and_timezone_data(monkeypatch):
    original = provenance.model_manifest()
    assert original["parameters"]["ar5"]["lags"] == 5
    assert original["libraries"]["numpy"]
    assert "reference_profiles" in original["source_files"]
    assert "scoreboard" in original["source_files"]
    monkeypatch.setattr(provenance.zoneinfo, "TZPATH", ())
    fallback = provenance.model_manifest()
    assert set(fallback["timezone_data"]) == {"Asia/Taipei", "America/New_York"}
    assert all(len(v) == 64 for v in fallback["timezone_data"].values())
    assert json.loads(provenance.canonical(fallback)) == fallback


def test_replay_checks_engine_environment_but_not_informational_build_commit():
    from stockpredict.backtest_runs import compatible

    manifest = provenance.model_manifest()
    manifest["build_commit"] = "f" * 40
    assert compatible(manifest)
    manifest["engine_hash"] = "changed"
    assert not compatible(manifest)


def test_release_identity_exposes_only_valid_commit_identifiers(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "invalid-sensitive-value")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    release = provenance.release_identity()
    assert release["commit"] is None
    assert len(release["source_hash"]) == 64
    monkeypatch.setenv("GITHUB_SHA", "A" * 40)
    assert provenance.release_identity()["commit"] == "a" * 40
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b" * 40)
    assert provenance.release_identity()["commit"] == "b" * 40
    assert provenance.release_identity()["source_hash"] == release["source_hash"]
