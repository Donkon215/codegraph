"""CLI integration tests using Click's CliRunner.

Tasks N-030, O-020 through O-024.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from codegraph.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def built_project(initialized_project: Path) -> Path:
    """Run a full build on the sample project and return the root."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        pass  # ensure clean
    result = runner.invoke(main, ["build"], catch_exceptions=False,
                           env={"CODEGRAPH_ROOT": str(initialized_project)})
    # Build may or may not succeed depending on project state; just return root
    return initialized_project


# ── N-030: Command tests ──────────────────────────────────────────────


class TestCLIBasics:
    """Test basic CLI framework (N-001)."""

    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "codegraph" in result.output.lower()

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "codegraph" in result.output.lower()

    def test_version_command(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert "codegraph" in result.output
        assert "Python" in result.output

    def test_global_verbose(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["-v", "--help"])
        assert result.exit_code == 0

    def test_global_quiet(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["-q", "--help"])
        assert result.exit_code == 0


class TestInitCommand:
    """Test init command (N-026)."""

    def test_init_creates_codegraph_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(main, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".codegraph").is_dir()
        assert "Initialized" in result.output


class TestSchemaCommand:
    """Test schema command (N-019)."""

    def test_schema_graph0(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["schema", "graph0"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "properties" in data or "$schema" in data or "type" in data

    def test_schema_all_types(self, runner: CliRunner) -> None:
        for schema_type in ["graph0", "graph1", "workflow", "tasks", "agent_response", "delta"]:
            result = runner.invoke(main, ["schema", schema_type])
            assert result.exit_code == 0, f"schema {schema_type} failed"


class TestStatusCommand:
    """Test status command (N-003)."""

    def test_status_no_project(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["status"])
        # Should fail or show error when no project
        assert result.exit_code != 0 or "not found" in (result.output + result.stderr).lower() or "error" in (result.output + result.stderr).lower()


class TestBuildCommand:
    """Test build command (N-002)."""

    def test_build_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["build", "--help"])
        assert result.exit_code == 0
        assert "no-cache" in result.output.lower() or "Extract" in result.output


class TestSuggestCommand:
    """Test suggest command group (N-007)."""

    def test_suggest_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["suggest", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "remove" in result.output
        assert "list" in result.output

    def test_suggest_list_no_project(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["suggest", "list"])
        assert result.exit_code != 0


class TestIndexCommand:
    """Test index command group (N-018)."""

    def test_index_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["index", "--help"])
        assert result.exit_code == 0
        assert "rebuild" in result.output


class TestDiffCommand:
    """Test diff command (N-013)."""

    def test_diff_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["diff", "--help"])
        assert result.exit_code == 0
        assert "graph" in result.output.lower()


class TestRepairCommand:
    """Test repair command (N-032)."""

    def test_repair_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["repair", "--help"])
        assert result.exit_code == 0
        assert "max-cycles" in result.output.lower() or "dry-run" in result.output.lower()


class TestQueryCommand:
    """Test query command (N-006)."""

    def test_query_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["query", "--help"])
        assert result.exit_code == 0
        assert "depth" in result.output.lower()

    def test_explain_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["explain", "--help"])
        assert result.exit_code == 0


class TestArchiTestCommand:
    """Test archi-test command (N-014)."""

    def test_archi_test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["archi-test", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output.lower()


class TestTestImpactCommand:
    """Test test-impact command (N-031)."""

    def test_test_impact_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["test-impact", "--help"])
        assert result.exit_code == 0
        assert "from-delta" in result.output.lower() or "gaps" in result.output.lower()


class TestCompletionCommand:
    """Test completion command (N-025)."""

    def test_completion_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["completion", "--help"])
        assert result.exit_code == 0
        assert "bash" in result.output.lower()


class TestApplyCommand:
    """Test apply command (N-008)."""

    def test_apply_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["apply", "--help"])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower() or "response" in result.output.lower()


class TestDeltaCommand:
    """Test delta command (N-009)."""

    def test_delta_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["delta", "--help"])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()


class TestWorkflowCommand:
    """Test workflow command (N-010)."""

    def test_workflow_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "trace" in result.output.lower()


class TestValidateCommand:
    """Test validate command (N-012)."""

    def test_validate_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["validate", "--help"])
        assert result.exit_code == 0


class TestAnalyzeCommand:
    """Test analyze command (N-017)."""

    def test_analyze_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "json" in result.output.lower()


class TestTasksCommand:
    """Test tasks command (N-004)."""

    def test_tasks_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["tasks", "--help"])
        assert result.exit_code == 0


class TestPruneCommand:
    """Test prune command (N-011)."""

    def test_prune_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["prune", "--help"])
        assert result.exit_code == 0


class TestIntentCommands:
    """Test intent commands (N-015, N-016)."""

    def test_intent_missing_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["intent-missing", "--help"])
        assert result.exit_code == 0

    def test_intent_apply_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["intent-apply", "--help"])
        assert result.exit_code == 0


class TestAnnotateCommand:
    """Test annotate command."""

    def test_annotate_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["annotate", "--help"])
        assert result.exit_code == 0
        assert "node" in result.output.lower()


# ── CAS CLI Commands ──────────────────────────────────────────────────


class TestCASCommands:
    """Test cas CLI group commands."""

    def test_cas_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cas", "--help"])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "verify" in result.output
        assert "impact" in result.output

    def test_cas_build_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cas", "build", "--help"])
        assert result.exit_code == 0

    def test_cas_verify_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cas", "verify", "--help"])
        assert result.exit_code == 0

    def test_cas_impact_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cas", "impact", "--help"])
        assert result.exit_code == 0


# ── Semantic CLI Commands ─────────────────────────────────────────────


class TestSemanticCommands:
    """Test semantic CLI group commands."""

    def test_semantic_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["semantic", "--help"])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "show" in result.output
        assert "summary" in result.output
        assert "check" in result.output

    def test_semantic_build_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["semantic", "build", "--help"])
        assert result.exit_code == 0

    def test_semantic_show_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["semantic", "show", "--help"])
        assert result.exit_code == 0

    def test_semantic_summary_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["semantic", "summary", "--help"])
        assert result.exit_code == 0

    def test_semantic_check_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["semantic", "check", "--help"])
        assert result.exit_code == 0
