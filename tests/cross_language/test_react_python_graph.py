"""
Cross-language integration test: React (TypeScript) frontend + Python backend.

Validates that codegraph correctly builds a single unified graph connecting:
  - React components (TSX) → Python API routes (FastAPI)
  - TypeScript interface contracts → Python model classes
  - Service boundary detection (frontend / backend / worker nodes)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.cross_language_linker import build_cross_language_links


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def full_stack_project(tmp_path: Path) -> Path:
    """
    Minimal full-stack project that mimics:

        frontend/
            src/
                components/
                    OrderList.tsx      <- calls /api/orders, /api/users
                    UserProfile.tsx    <- calls /api/users/{id}
                hooks/
                    useOrders.ts       <- calls /api/orders via axios
        backend/
            api.py                     <- FastAPI routes /api/orders, /api/users
            services/
                order_service.py       <- business logic
        workers/
            notification_worker.py     <- background worker
    """
    # ── backend ──────────────────────────────────────────────────────────────
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    services_dir = backend_dir / "services"
    services_dir.mkdir()

    (backend_dir / "api.py").write_text(
        """
from fastapi import APIRouter

router = APIRouter()


class OrderModel:
    \"\"\"Shared contract — mirrors OrderDTO in TypeScript frontend.\"\"\"
    id: str
    user_id: str
    items: list
    total: float


class UserModel:
    \"\"\"Shared contract — mirrors UserDTO in TypeScript frontend.\"\"\"
    id: str
    name: str
    email: str


@router.get('/api/orders')
def get_orders():
    return []


@router.post('/api/orders')
def create_order(payload: dict):
    return {"id": "ord_001", "total": 42.0}


@router.get('/api/users')
def get_users():
    return []
""",
        encoding="utf-8",
    )

    (services_dir / "order_service.py").write_text(
        """
class OrderSchema:
    \"\"\"Pydantic schema matched to frontend OrderDTO.\"\"\"
    pass
""",
        encoding="utf-8",
    )

    # ── frontend ─────────────────────────────────────────────────────────────
    components_dir = tmp_path / "frontend" / "src" / "components"
    components_dir.mkdir(parents=True)
    hooks_dir = tmp_path / "frontend" / "src" / "hooks"
    hooks_dir.mkdir(parents=True)

    (components_dir / "OrderList.tsx").write_text(
        """
interface OrderDTO {
  id: string;
  user_id: string;
  items: string[];
  total: number;
}

interface UserDTO {
  id: string;
  name: string;
}

export const OrderList = () => {
  // fetch link: /api/orders -> backend/api.py::get_orders
  const [orders, setOrders] = React.useState([]);

  React.useEffect(() => {
    fetch('/api/orders').then(r => r.json()).then(setOrders);
  }, []);

  return <ul>{orders.map(o => <li key={o.id}>{o.id}</li>)}</ul>;
};
""",
        encoding="utf-8",
    )

    (components_dir / "UserProfile.tsx").write_text(
        """
import axios from 'axios';

interface UserDTO {
  id: string;
  name: string;
  email: string;
}

export const UserProfile = ({ userId }: { userId: string }) => {
  const [user, setUser] = React.useState(null);

  React.useEffect(() => {
    // axios link: /api/users -> backend/api.py::get_users
    axios.get('/api/users').then(r => setUser(r.data[0]));
  }, [userId]);

  return <div>{user?.name}</div>;
};
""",
        encoding="utf-8",
    )

    (hooks_dir / "useOrders.ts").write_text(
        """
import axios from 'axios';

type OrderDTO = {
  id: string;
  total: number;
};

export const useOrders = () => {
  // axios link: /api/orders -> backend/api.py::get_orders
  const load = () => axios.get('/api/orders');
  const create = (payload: Partial<OrderDTO>) => axios.post('/api/orders', payload);
  return { load, create };
};
""",
        encoding="utf-8",
    )

    # ── workers ───────────────────────────────────────────────────────────────
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir()
    (workers_dir / "notification_worker.py").write_text(
        "def run(): pass\n",
        encoding="utf-8",
    )

    return tmp_path


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestReactPythonCrossLanguageGraph:
    """Validate the unified React + Python architecture graph."""

    def test_frontend_to_backend_links_detected(self, full_stack_project):
        """fetch() and axios calls must produce frontend_to_backend edges."""
        report = build_cross_language_links(full_stack_project)

        routes_linked = {edge.details["route"] for edge in report.edges
                         if edge.edge_type == "frontend_to_backend"}

        assert "/api/orders" in routes_linked, (
            "Expected /api/orders link (OrderList.tsx fetch + useOrders.ts axios)"
        )
        assert "/api/users" in routes_linked, (
            "Expected /api/users link (UserProfile.tsx axios.get)"
        )

    def test_both_axios_and_fetch_detected(self, full_stack_project):
        """Both fetch() and axios.get/post patterns must be captured."""
        report = build_cross_language_links(full_stack_project)

        fb_edges = [e for e in report.edges if e.edge_type == "frontend_to_backend"]
        detectors = {e.details["detector"] for e in fb_edges}

        assert "fetch" in detectors, "fetch() API calls not detected"
        assert "axios" in detectors, "axios calls not detected"

    def test_typescript_python_contract_mapping(self, full_stack_project):
        """TypeScript interfaces must be linked to matching Python model classes."""
        report = build_cross_language_links(full_stack_project)

        contract_keys = {edge.details["contract"] for edge in report.edges
                         if edge.edge_type == "contract_mapping"}

        # OrderDTO (TS) ↔ OrderModel / OrderSchema (Python)
        assert "order" in contract_keys, (
            "OrderDTO ↔ OrderModel contract mapping not found"
        )
        # UserDTO (TS) ↔ UserModel (Python)
        assert "user" in contract_keys, (
            "UserDTO ↔ UserModel contract mapping not found"
        )

    def test_single_graph_has_multiple_edge_types(self, full_stack_project):
        """The unified graph must contain both frontend_to_backend and contract_mapping edges."""
        report = build_cross_language_links(full_stack_project)

        edge_types = {edge.edge_type for edge in report.edges}
        assert "frontend_to_backend" in edge_types
        assert "contract_mapping" in edge_types

    def test_service_boundary_nodes_present(self, full_stack_project):
        """Frontend, backend, and worker service nodes must all be detected."""
        report = build_cross_language_links(full_stack_project)

        service_types = {node["service_type"] for node in report.service_nodes}
        assert "frontend" in service_types, "Frontend service boundary not detected"
        assert "backend" in service_types, "Backend service boundary not detected"
        assert "worker" in service_types, "Worker service boundary not detected"

    def test_graph_serialises_to_json(self, full_stack_project):
        """The report must round-trip through JSON cleanly."""
        report = build_cross_language_links(full_stack_project)
        as_dict = report.to_dict()
        json_str = json.dumps(as_dict)
        parsed = json.loads(json_str)

        assert parsed["stats"]["edge_count"] > 0
        assert len(parsed["edges"]) == parsed["stats"]["edge_count"]
        assert "service_nodes" in parsed

    def test_edge_sources_point_to_frontend_files(self, full_stack_project):
        """frontend_to_backend edge sources should be in frontend/src/."""
        report = build_cross_language_links(full_stack_project)

        frontend_edges = [e for e in report.edges
                          if e.edge_type == "frontend_to_backend"]
        for edge in frontend_edges:
            assert "frontend/" in edge.source, (
                f"Edge source {edge.source!r} is not a frontend path"
            )

    def test_edge_targets_point_to_backend_files(self, full_stack_project):
        """frontend_to_backend edge targets should be in backend/."""
        report = build_cross_language_links(full_stack_project)

        frontend_edges = [e for e in report.edges
                          if e.edge_type == "frontend_to_backend"]
        for edge in frontend_edges:
            assert "backend/" in edge.target, (
                f"Edge target {edge.target!r} is not a backend path"
            )

    def test_post_endpoint_linked(self, full_stack_project):
        """axios.post('/api/orders') must link to the POST handler."""
        report = build_cross_language_links(full_stack_project)

        post_edges = [e for e in report.edges
                      if e.edge_type == "frontend_to_backend"
                      and e.details.get("route") == "/api/orders"]
        assert len(post_edges) >= 2, (
            "Expected at least 2 links to /api/orders (GET from OrderList + POST from useOrders)"
        )
