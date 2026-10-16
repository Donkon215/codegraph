"""Regression for #61: CLI output must not crash on non-ASCII on cp1252 consoles."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from codegraph.cli.core import _force_utf8_streams


def _cp1252_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", write_through=True)


def test_arrow_is_writable_after_forcing_utf8(monkeypatch) -> None:
    out = _cp1252_stream()
    err = _cp1252_stream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    # Precondition: the stream really cannot encode the arrow.
    try:
        "→".encode("cp1252")
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("cp1252 unexpectedly encodes the arrow")

    _force_utf8_streams()

    sys.stdout.write("a → b\n")
    sys.stderr.write("a → b\n")
    sys.stdout.flush()
    sys.stderr.flush()
    assert out.encoding == "utf-8"
    assert err.encoding == "utf-8"


def test_build_cli_reconfigures_cp1252_streams_without_encoding_env() -> None:
    """Exercise the real CLI callback with legacy-encoded streams in a child."""
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=".test_cli_utf8_", dir=repository) as fixture_dir:
        project = Path(fixture_dir)
        (project / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        (project / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        support = project / ".test_support"
        support.mkdir()
        (support / "sitecustomize.py").write_text(
            "import sys\n"
            "sys.stdout.reconfigure(encoding='cp1252', errors='strict')\n"
            "sys.stderr.reconfigure(encoding='cp1252', errors='strict')\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        env["PYTHONPATH"] = os.pathsep.join((str(support), str(repository)))
        for command in ("build", "analyze"):
            result = subprocess.run(
                [sys.executable, "-m", "codegraph", command],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            assert result.returncode == 0, result.stdout + result.stderr
            if command == "build":
                assert "Building graphs for" in result.stdout
