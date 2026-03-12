"""codegraph.cli — CLI package for codegraph.

Re-exports ``main`` so that ``codegraph.cli:main`` continues to work
as the entry-point after the package was split from a single file into
a multi-module package.
"""

from codegraph.cli.core import main  # noqa: F401

__all__ = ["main"]
