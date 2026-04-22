"""Tests for drt test --output json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from drt.cli.main import app

runner = CliRunner()


def _write_sync(tmp_path: Path, data: dict) -> None:
    syncs_dir = tmp_path / "syncs"
    syncs_dir.mkdir(exist_ok=True)
    with (syncs_dir / "sync.yml").open("w") as f:
        yaml.dump(data, f)


def _write_credentials(tmp_path: Path) -> None:
    """Write minimal credentials for tests."""
    creds_dir = tmp_path / ".drt"
    creds_dir.mkdir(exist_ok=True)
    with (creds_dir / "credentials.yml").open("w") as f:
        yaml.dump(
            {"profiles": {"default": {"type": "duckdb", "path": "/tmp/test.db"}}},
            f,
        )


def test_test_json_no_syncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """test --output json with no syncs should return empty results."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "no_syncs"
    assert data["results"] == []


def test_test_json_no_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """test --output json with syncs but no tests defined."""
    monkeypatch.chdir(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "no-tests",
            "model": "SELECT 1",
            "destination": {
                "type": "rest_api",
                "url": "http://example.com",
                "method": "POST",
            },
        },
    )
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "no_tests"
    assert data["results"] == []


def test_test_json_non_queryable_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test --output json with non-queryable destination marks sync as skipped."""
    monkeypatch.chdir(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "api-sync",
            "model": "SELECT 1",
            "destination": {
                "type": "rest_api",
                "url": "http://example.com",
                "method": "POST",
            },
            "tests": [{"row_count": {"min": 1}}],
        },
    )
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "passed"
    assert len(data["results"]) == 1
    assert data["results"][0]["sync"] == "api-sync"
    assert data["results"][0]["skipped"] is True


def test_test_json_no_rich_markup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON output should not contain Rich markup."""
    monkeypatch.chdir(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "test-sync",
            "model": "SELECT 1",
            "destination": {
                "type": "rest_api",
                "url": "http://example.com",
                "method": "POST",
            },
            "tests": [{"row_count": {"min": 1}}],
        },
    )
    result = runner.invoke(app, ["test", "--output", "json"])
    # Should not contain rich markup
    assert "[dim]" not in result.output
    assert "[bold" not in result.output
    # Should be valid JSON
    json.loads(result.output)


def test_test_json_output_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test --output json returns correct top-level structure."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert "status" in data
    assert "results" in data
    assert isinstance(data["results"], list)


def test_test_json_queryable_with_passing_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test --output json with queryable destination and passing tests."""
    monkeypatch.chdir(tmp_path)
    _write_credentials(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "duck-sync",
            "model": "SELECT 1 AS id",
            "destination": {
                "type": "duckdb",
                "path": ":memory:",
            },
            "tests": [{"row_count": {"min": 1}}],
        },
    )
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "passed"
    assert len(data["results"]) == 1
    assert data["results"][0]["sync"] == "duck-sync"
    assert data["results"][0]["skipped"] is False
    assert "tests" in data["results"][0]


def test_test_json_queryable_with_failing_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test --output json with queryable destination and failing tests."""
    monkeypatch.chdir(tmp_path)
    _write_credentials(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "duck-sync-fail",
            "model": "SELECT 1 AS id",
            "destination": {
                "type": "duckdb",
                "path": ":memory:",
            },
            "tests": [{"row_count": {"min": 100}}],
        },
    )
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "failed"
    assert len(data["results"]) == 1
    assert data["results"][0]["sync"] == "duck-sync-fail"
    assert "tests" in data["results"][0]
    assert data["results"][0]["status"] == "failed"


def test_test_json_multiple_syncs_mixed_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test --output json with multiple syncs having mixed results."""
    monkeypatch.chdir(tmp_path)
    _write_credentials(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "pass-sync",
            "model": "SELECT 1 AS id",
            "destination": {"type": "duckdb", "path": ":memory:"},
            "tests": [{"row_count": {"min": 1}}],
        },
    )
    _write_sync(
        tmp_path,
        {
            "name": "fail-sync",
            "model": "SELECT 1 AS id",
            "destination": {"type": "duckdb", "path": ":memory:"},
            "tests": [{"row_count": {"min": 100}}],
        },
    )
    result = runner.invoke(app, ["test", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "failed"
    assert len(data["results"]) == 2
    statuses = {r["sync"]: r["status"] for r in data["results"]}
    assert statuses["pass-sync"] == "success"
    assert statuses["fail-sync"] == "failed"


def test_test_json_with_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test --output json respects dry-run flag."""
    monkeypatch.chdir(tmp_path)
    _write_credentials(tmp_path)
    _write_sync(
        tmp_path,
        {
            "name": "dry-sync",
            "model": "SELECT 1 AS id",
            "destination": {"type": "duckdb", "path": ":memory:"},
            "tests": [{"row_count": {"min": 1}}],
        },
    )
    result = runner.invoke(app, ["test", "--output", "json", "--dry-run"])
    data = json.loads(result.output)
    assert data["status"] == "passed"
    assert len(data["results"]) == 1
    assert data["results"][0]["dry_run"] is True
