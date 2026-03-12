"""Tests for the CLI package split — verifies all commands are registered."""

import pytest
from click.testing import CliRunner

from codegraph.cli import main


class TestCLIPackageRegistration:
    """Verify the CLI package split preserved all commands."""

    def test_main_is_click_group(self):
        assert hasattr(main, "commands")

    def test_all_commands_registered(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0

        # Check representative commands from each sub-module
        output = result.output

        # From core
        assert "build" in output
        assert "query" in output
        assert "status" in output

        # From architecture
        assert "architect" in output
        assert "compile" in output
        assert "arch-search" in output

        # From governance
        assert "analyze" in output
        assert "tasks" in output
        assert "apply" in output
        assert "suggest" in output

        # From intelligence
        assert "evolution" in output
        assert "health" in output
        assert "metrics" in output

        # From runtime
        assert "simulate" in output
        assert "pre-commit" in output
        assert "branch" in output

    def test_import_from_package(self):
        from codegraph.cli.core import main as core_main
        assert core_main is main

    def test_architecture_commands_list(self):
        from codegraph.cli.architecture import COMMANDS
        assert len(COMMANDS) >= 10

    def test_governance_commands_and_groups(self):
        from codegraph.cli.governance import COMMANDS, GROUPS
        assert len(COMMANDS) >= 6
        assert len(GROUPS) >= 1

    def test_intelligence_commands_list(self):
        from codegraph.cli.intelligence import COMMANDS
        assert len(COMMANDS) >= 8

    def test_runtime_commands_and_groups(self):
        from codegraph.cli.runtime import COMMANDS, GROUPS
        assert len(COMMANDS) >= 4
        assert len(GROUPS) >= 1
