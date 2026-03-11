"""codegraph.extractors.api_routes — Cross-language API endpoint linker.

Detects HTTP API endpoints in backend code (Python) and API calls in
frontend code (JavaScript/TypeScript) and creates cross-language edges
in the workflow graph.

Supports:
  - Python: FastAPI, Flask, Django REST, Starlette decorators
  - JavaScript/TypeScript: fetch(), axios, XMLHttpRequest patterns

This enables full-stack architecture visibility where frontend API
calls are linked to their corresponding backend handlers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codegraph.logging_config import get_logger
from codegraph.types import WorkflowEdge

logger = get_logger("api_routes")


# ═══════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ApiEndpoint:
    """A backend HTTP endpoint definition."""

    path: str  # e.g. "/api/login"
    method: str  # GET, POST, PUT, DELETE, PATCH, etc.
    handler_node: str  # Graph node ID  e.g. "backend/api.py::login"
    file: str  # source file path
    line: int  # line number
    framework: str = ""  # flask, fastapi, django, starlette

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method.upper(),
            "handler_node": self.handler_node,
            "file": self.file,
            "line": self.line,
            "framework": self.framework,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApiEndpoint":
        return cls(
            path=d["path"],
            method=d["method"],
            handler_node=d["handler_node"],
            file=d["file"],
            line=d["line"],
            framework=d.get("framework", ""),
        )


@dataclass
class ApiCall:
    """A frontend HTTP API call."""

    path: str  # e.g. "/api/login"
    method: str  # GET, POST, etc.
    caller_node: str  # Graph node ID  e.g. "frontend/api.ts::loginRequest"
    file: str
    line: int
    library: str = ""  # fetch, axios, xhr

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method.upper(),
            "caller_node": self.caller_node,
            "file": self.file,
            "line": self.line,
            "library": self.library,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApiCall":
        return cls(
            path=d["path"],
            method=d["method"],
            caller_node=d["caller_node"],
            file=d["file"],
            line=d["line"],
            library=d.get("library", ""),
        )


@dataclass
class ApiLinkReport:
    """Result of cross-language API linking."""

    endpoints: List[ApiEndpoint] = field(default_factory=list)
    api_calls: List[ApiCall] = field(default_factory=list)
    linked_edges: List[WorkflowEdge] = field(default_factory=list)
    unlinked_calls: List[ApiCall] = field(default_factory=list)
    unlinked_endpoints: List[ApiEndpoint] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoints": [e.to_dict() for e in self.endpoints],
            "api_calls": [c.to_dict() for c in self.api_calls],
            "linked_edges": [e.to_dict() for e in self.linked_edges],
            "unlinked_calls": [c.to_dict() for c in self.unlinked_calls],
            "unlinked_endpoints": [e.to_dict() for e in self.unlinked_endpoints],
            "summary": {
                "total_endpoints": len(self.endpoints),
                "total_api_calls": len(self.api_calls),
                "linked": len(self.linked_edges),
                "unlinked_calls": len(self.unlinked_calls),
                "unlinked_endpoints": len(self.unlinked_endpoints),
            },
        }

    def format(self) -> str:
        lines = [
            f"API Link Report: {len(self.linked_edges)} links",
            f"  Endpoints:    {len(self.endpoints)}",
            f"  API calls:    {len(self.api_calls)}",
            f"  Linked:       {len(self.linked_edges)}",
            f"  Unlinked calls:     {len(self.unlinked_calls)}",
            f"  Unlinked endpoints: {len(self.unlinked_endpoints)}",
        ]
        if self.linked_edges:
            lines.append("\nLinked:")
            for e in self.linked_edges:
                lines.append(f"  {e.source} → {e.target}")
        if self.unlinked_calls:
            lines.append("\nUnlinked API calls:")
            for c in self.unlinked_calls:
                lines.append(f"  {c.method} {c.path} ({c.caller_node})")
        if self.unlinked_endpoints:
            lines.append("\nUnlinked endpoints:")
            for ep in self.unlinked_endpoints:
                lines.append(f"  {ep.method} {ep.path} ({ep.handler_node})")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Python endpoint detection
# ═══════════════════════════════════════════════════════════════════════

# FastAPI / Starlette: @app.get("/path"), @router.post("/path")
_RE_PY_DECORATOR_ROUTE = re.compile(
    r"""^[ \t]*@\s*\w+\.(get|post|put|delete|patch|options|head)\s*\(\s*["']([^"']+)["']""",
    re.MULTILINE | re.IGNORECASE,
)

# Flask: @app.route("/path", methods=["GET", "POST"])
_RE_PY_FLASK_ROUTE = re.compile(
    r"""^[ \t]*@\s*\w+\.route\s*\(\s*["']([^"']+)["'](?:.*?methods\s*=\s*\[([^\]]*)\])?""",
    re.MULTILINE | re.IGNORECASE,
)

# Django: path("api/login", views.login_view) in urls.py
_RE_PY_DJANGO_PATH = re.compile(
    r"""(?:path|re_path)\s*\(\s*["']([^"']+)["']\s*,\s*(\w+(?:\.\w+)*)""",
    re.MULTILINE,
)

# Function def after a decorator
_RE_PY_FUNC_DEF = re.compile(
    r"""^[ \t]*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(""",
    re.MULTILINE,
)


def extract_python_endpoints(
    file_path: Path,
    project_root: Path,
) -> List[ApiEndpoint]:
    """Extract HTTP endpoint definitions from a Python source file."""
    if not file_path.exists() or file_path.suffix != ".py":
        return []

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        rel_path = str(file_path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        rel_path = file_path.name

    endpoints: List[ApiEndpoint] = []
    lines = source.split("\n")

    # FastAPI / Starlette / Flask-RESTful decorators
    for m in _RE_PY_DECORATOR_ROUTE.finditer(source):
        method = m.group(1).upper()
        path = m.group(2)
        line_no = source[:m.start()].count("\n") + 1
        handler = _find_handler_after(lines, line_no - 1)
        node_id = f"{rel_path}::{handler}" if handler else rel_path
        endpoints.append(ApiEndpoint(
            path=_normalize_path(path),
            method=method,
            handler_node=node_id,
            file=rel_path,
            line=line_no,
            framework="fastapi",
        ))

    # Flask @app.route()
    for m in _RE_PY_FLASK_ROUTE.finditer(source):
        path = m.group(1)
        methods_str = m.group(2)
        line_no = source[:m.start()].count("\n") + 1
        handler = _find_handler_after(lines, line_no - 1)
        node_id = f"{rel_path}::{handler}" if handler else rel_path

        if methods_str:
            methods = re.findall(r'["\'](GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)["\']',
                                 methods_str, re.IGNORECASE)
        else:
            methods = ["GET"]

        for method in methods:
            endpoints.append(ApiEndpoint(
                path=_normalize_path(path),
                method=method.upper(),
                handler_node=node_id,
                file=rel_path,
                line=line_no,
                framework="flask",
            ))

    # Django path() / re_path()
    for m in _RE_PY_DJANGO_PATH.finditer(source):
        path = "/" + m.group(1).strip("/")
        view_ref = m.group(2)
        line_no = source[:m.start()].count("\n") + 1
        node_id = f"{rel_path}::{view_ref.split('.')[-1]}"
        endpoints.append(ApiEndpoint(
            path=_normalize_path(path),
            method="ANY",
            handler_node=node_id,
            file=rel_path,
            line=line_no,
            framework="django",
        ))

    return endpoints


def _find_handler_after(lines: List[str], decorator_line_idx: int) -> Optional[str]:
    """Find the function name defined after a decorator line."""
    for i in range(decorator_line_idx + 1, min(decorator_line_idx + 10, len(lines))):
        m = _RE_PY_FUNC_DEF.match(lines[i])
        if m:
            return m.group(1)
    return None


# ═══════════════════════════════════════════════════════════════════════
# JavaScript/TypeScript API call detection
# ═══════════════════════════════════════════════════════════════════════

# fetch("/api/path") or fetch(`/api/path`)
_RE_JS_FETCH = re.compile(
    r"""fetch\s*\(\s*["`']([^"`']+)["`']""",
    re.MULTILINE,
)

# axios.get("/path"), axios.post("/path"), axios("/path"), axios({url: "/path"})
_RE_JS_AXIOS_METHOD = re.compile(
    r"""axios\s*\.\s*(get|post|put|delete|patch|head|options)\s*\(\s*["`']([^"`']+)["`']""",
    re.MULTILINE | re.IGNORECASE,
)

# axios("/path") or axios({url: "/path"})
_RE_JS_AXIOS_DIRECT = re.compile(
    r"""axios\s*\(\s*["`']([^"`']+)["`']""",
    re.MULTILINE,
)

# fetch with method option: fetch("/path", { method: "POST" })
_RE_JS_FETCH_METHOD = re.compile(
    r"""fetch\s*\(\s*["`']([^"`']+)["`']\s*,\s*\{[^}]*?method\s*:\s*["`'](GET|POST|PUT|DELETE|PATCH)["`']""",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)

# Function/arrow containing the call (context for node ID)
_RE_JS_FUNC_CONTEXT = re.compile(
    r"""(?:(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)|"""
    r"""(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|function))""",
    re.MULTILINE,
)


def extract_js_api_calls(
    file_path: Path,
    project_root: Path,
) -> List[ApiCall]:
    """Extract HTTP API calls from a JavaScript/TypeScript source file."""
    if not file_path.exists() or file_path.suffix not in (
        ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ):
        return []

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        rel_path = str(file_path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        rel_path = file_path.name

    calls: List[ApiCall] = []
    func_ranges = _build_func_ranges(source, rel_path)

    # fetch with explicit method
    for m in _RE_JS_FETCH_METHOD.finditer(source):
        path = m.group(1)
        method = m.group(2).upper()
        line_no = source[:m.start()].count("\n") + 1
        caller = _find_enclosing_func(func_ranges, line_no, rel_path)
        calls.append(ApiCall(
            path=_normalize_api_path(path),
            method=method,
            caller_node=caller,
            file=rel_path,
            line=line_no,
            library="fetch",
        ))

    # fetch without explicit method (default GET) — skip if already matched
    fetched_positions: Set[int] = {m.start() for m in _RE_JS_FETCH_METHOD.finditer(source)}
    for m in _RE_JS_FETCH.finditer(source):
        if m.start() in fetched_positions:
            continue
        path = m.group(1)
        if not _looks_like_api_path(path):
            continue
        line_no = source[:m.start()].count("\n") + 1
        caller = _find_enclosing_func(func_ranges, line_no, rel_path)
        calls.append(ApiCall(
            path=_normalize_api_path(path),
            method="GET",
            caller_node=caller,
            file=rel_path,
            line=line_no,
            library="fetch",
        ))

    # axios.method()
    for m in _RE_JS_AXIOS_METHOD.finditer(source):
        method = m.group(1).upper()
        path = m.group(2)
        if not _looks_like_api_path(path):
            continue
        line_no = source[:m.start()].count("\n") + 1
        caller = _find_enclosing_func(func_ranges, line_no, rel_path)
        calls.append(ApiCall(
            path=_normalize_api_path(path),
            method=method,
            caller_node=caller,
            file=rel_path,
            line=line_no,
            library="axios",
        ))

    # axios("/path") — direct call, default method
    axios_method_positions: Set[int] = set()
    for m in _RE_JS_AXIOS_METHOD.finditer(source):
        axios_method_positions.add(source[:m.start()].rfind("axios"))
    for m in _RE_JS_AXIOS_DIRECT.finditer(source):
        if m.start() in axios_method_positions:
            continue
        path = m.group(1)
        if not _looks_like_api_path(path):
            continue
        line_no = source[:m.start()].count("\n") + 1
        caller = _find_enclosing_func(func_ranges, line_no, rel_path)
        calls.append(ApiCall(
            path=_normalize_api_path(path),
            method="GET",
            caller_node=caller,
            file=rel_path,
            line=line_no,
            library="axios",
        ))

    return calls


def _build_func_ranges(
    source: str,
    rel_path: str,
) -> List[Tuple[int, str]]:
    """Build a list of (line_no, node_id) for function contexts."""
    ranges: List[Tuple[int, str]] = []
    for m in _RE_JS_FUNC_CONTEXT.finditer(source):
        name = m.group(1) or m.group(2)
        line_no = source[:m.start()].count("\n") + 1
        ranges.append((line_no, f"{rel_path}::{name}"))
    return sorted(ranges, key=lambda x: x[0])


def _find_enclosing_func(
    func_ranges: List[Tuple[int, str]],
    line_no: int,
    fallback: str,
) -> str:
    """Find the function that encloses a given line number."""
    result = fallback
    for fl, node_id in func_ranges:
        if fl <= line_no:
            result = node_id
        else:
            break
    return result


# ═══════════════════════════════════════════════════════════════════════
# Cross-language linker
# ═══════════════════════════════════════════════════════════════════════


def link_api_routes(
    project_root: Path,
    source_files: Optional[List[Path]] = None,
) -> ApiLinkReport:
    """Scan project files for API endpoints and calls, then link them.

    Returns an :class:`ApiLinkReport` containing:
      - All detected endpoints (Python backend)
      - All detected API calls (JS/TS frontend)
      - Linked edges (matching path patterns)
      - Unlinked calls/endpoints (no match found)
    """
    if source_files is None:
        source_files = _discover_files(project_root)

    report = ApiLinkReport()

    for fp in source_files:
        if fp.suffix == ".py":
            report.endpoints.extend(extract_python_endpoints(fp, project_root))
        elif fp.suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            report.api_calls.extend(extract_js_api_calls(fp, project_root))

    # Build endpoint index: normalized_path → list of endpoints
    endpoint_index: Dict[str, List[ApiEndpoint]] = {}
    for ep in report.endpoints:
        key = _normalize_path(ep.path)
        endpoint_index.setdefault(key, []).append(ep)

    # Link calls to endpoints
    linked_call_indices: Set[int] = set()
    linked_endpoint_keys: Set[str] = set()

    for i, call in enumerate(report.api_calls):
        call_path = _normalize_path(call.path)
        matched = endpoint_index.get(call_path, [])

        # Also try pattern matching for path parameters
        if not matched:
            matched = _match_parameterized(call_path, endpoint_index)

        for ep in matched:
            # Method matching: ANY matches all, otherwise must match
            if ep.method != "ANY" and call.method != ep.method:
                continue

            edge = WorkflowEdge(
                source=call.caller_node,
                target=ep.handler_node,
                edge_type="call",
                confidence="static",
            )
            report.linked_edges.append(edge)
            linked_call_indices.add(i)
            linked_endpoint_keys.add(_normalize_path(ep.path))

    # Collect unlinked
    for i, call in enumerate(report.api_calls):
        if i not in linked_call_indices:
            report.unlinked_calls.append(call)

    for ep in report.endpoints:
        if _normalize_path(ep.path) not in linked_endpoint_keys:
            report.unlinked_endpoints.append(ep)

    logger.info(
        "API linking: %d endpoints, %d calls, %d linked",
        len(report.endpoints),
        len(report.api_calls),
        len(report.linked_edges),
    )

    return report


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _normalize_path(path: str) -> str:
    """Normalize an API path for matching."""
    # Strip trailing slash, lowercase
    path = path.rstrip("/").lower()
    if not path.startswith("/"):
        path = "/" + path
    # Normalize path params: /users/{id} → /users/:param
    path = re.sub(r"\{[^}]+\}", ":param", path)
    # Also normalize :param_name style
    path = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", ":param", path)
    return path


def _normalize_api_path(path: str) -> str:
    """Normalize a frontend API call path."""
    # Remove template literal interpolation: `/api/users/${id}` → `/api/users/:param`
    path = re.sub(r"\$\{[^}]+\}", ":param", path)
    return _normalize_path(path)


def _looks_like_api_path(path: str) -> bool:
    """Heuristic: does this string look like an API URL path?"""
    if not path:
        return False
    # Must start with / or contain /api/ or be a relative path
    if path.startswith("/"):
        return True
    if "/api/" in path.lower():
        return True
    # Skip obvious non-URL strings
    if path.startswith("http://") or path.startswith("https://"):
        # Full URLs — extract path part
        return True
    return False


def _match_parameterized(
    call_path: str,
    endpoint_index: Dict[str, List[ApiEndpoint]],
) -> List[ApiEndpoint]:
    """Match a call path against parameterized endpoint patterns."""
    matches: List[ApiEndpoint] = []
    call_parts = call_path.strip("/").split("/")

    for ep_path, endpoints in endpoint_index.items():
        ep_parts = ep_path.strip("/").split("/")
        if len(call_parts) != len(ep_parts):
            continue
        if all(
            cp == ep or ep == ":param" or cp == ":param"
            for cp, ep in zip(call_parts, ep_parts)
        ):
            matches.extend(endpoints)

    return matches


def _discover_files(project_root: Path) -> List[Path]:
    """Discover Python and JS/TS files for API scanning."""
    extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    files: List[Path] = []
    for fp in project_root.rglob("*"):
        if fp.suffix in extensions and not _should_skip(fp, project_root):
            files.append(fp)
    return sorted(files)


def _should_skip(fp: Path, project_root: Path) -> bool:
    """Skip files in excluded directories."""
    try:
        rel = fp.relative_to(project_root)
    except ValueError:
        return True
    parts = rel.parts
    skip_dirs = {
        "node_modules", ".git", "__pycache__", ".codegraph",
        "dist", "build", ".tox", ".eggs", "venv", ".venv",
    }
    return bool(skip_dirs.intersection(parts))
