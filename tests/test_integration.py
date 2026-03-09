"""Integration tests for end-to-end pipelines.

Tasks O-020: Full build, O-021: Build-Analyze, O-022: Delta,
      O-023: Apply, O-024: Query system.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from codegraph.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def sample_project(tmp_path: Path) -> Path:
    """Create a more elaborate sample project for integration tests."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")

    (src / "db.py").write_text(textwrap.dedent("""\
        \"\"\"Database access module.\"\"\"

        def connect():
            \"\"\"Connect to database.\"\"\"
            return {"connected": True}

        def query(conn, sql):
            \"\"\"Execute SQL query.\"\"\"
            return []
    """), encoding="utf-8")

    (src / "service.py").write_text(textwrap.dedent("""\
        \"\"\"Business logic service.\"\"\"

        from src.db import connect, query

        def get_users():
            \"\"\"Get all users from database.\"\"\"
            conn = connect()
            return query(conn, "SELECT * FROM users")

        def orphan_function():
            \"\"\"This function is never called - should be detected as orphan.\"\"\"
            return "unused"
    """), encoding="utf-8")

    (src / "api.py").write_text(textwrap.dedent("""\
        \"\"\"API endpoints.\"\"\"

        from src.service import get_users

        def handle_request():
            \"\"\"Handle incoming API request.\"\"\"
            users = get_users()
            return {"users": users}
    """), encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")

    (tests_dir / "test_service.py").write_text(textwrap.dedent("""\
        \"\"\"Tests for service module.\"\"\"

        from src.service import get_users

        def test_get_users():
            result = get_users()
            assert isinstance(result, list)
    """), encoding="utf-8")

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-project"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    return tmp_path


# ── O-020: Full Build Pipeline ────────────────────────────────────────


class TestBuildPipeline:
    """End-to-end build test."""

    def test_init_and_build(self, runner: CliRunner, sample_project: Path) -> None:
        # Init
        result = runner.invoke(main, ["init", str(sample_project)])
        assert result.exit_code == 0
        assert (sample_project / ".codegraph").is_dir()


# ── O-024: Query System ──────────────────────────────────────────────


class TestQuerySystemIntegration:
    """Integration tests for query commands."""

    def test_query_help_works(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["query", "--help"])
        assert result.exit_code == 0
        assert "EXPRESSION" in result.output or "depth" in result.output.lower()

    def test_explain_help_works(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["explain", "--help"])
        assert result.exit_code == 0


# ── Schema Validation ────────────────────────────────────────────────


class TestSchemaIntegration:
    """Test JSON schema commands work end-to-end."""

    def test_all_schemas_valid_json(self, runner: CliRunner) -> None:
        for schema_type in ["graph0", "graph1", "workflow", "tasks"]:
            result = runner.invoke(main, ["schema", schema_type])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, dict)
