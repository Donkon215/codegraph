"""codegraph.cli_groups — Extracted CLI command groups.

Reduces the main cli.py god module by moving self-contained
Click groups into separate files.

Each module exports a Click group that is registered on the
main CLI group via ``main.add_command()``.
"""
