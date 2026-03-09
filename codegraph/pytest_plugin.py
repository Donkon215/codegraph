"""codegraph.pytest_plugin — Pytest plugin hook for coverage.py tracing (F-025).

Configures coverage.py to capture function-level execution traces during
``codegraph workflow --trace``.  The plugin is loaded programmatically by
:func:`codegraph.workflow.run_trace`, not as a pytest plugin entry point.

If pytest or coverage.py is not installed, workflow.run_trace handles
the error gracefully.
"""

from __future__ import annotations


def pytest_configure(config: object) -> None:
    """Hook: configure coverage for codegraph tracing.

    This is invoked when pytest loads this as a plugin.  We ensure the
    coverage plugin is active and recording branch-level data.
    """
    # The actual coverage configuration is handled by run_trace()
    # via --cov flags.  This plugin is reserved for any additional
    # codegraph-specific post-processing hooks in the future.
    pass


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    """Hook: post-process coverage data after test session ends."""
    # Coverage data is processed by workflow.parse_trace_data()
    # after pytest exits.  No additional processing needed here.
    pass
