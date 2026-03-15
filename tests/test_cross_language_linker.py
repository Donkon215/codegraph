from __future__ import annotations

from codegraph.cross_language_linker import build_cross_language_links


class TestCrossLanguageLinker:
    def test_frontend_to_backend_and_contract_mapping(self, tmp_path):
        frontend = tmp_path / "frontend" / "src"
        backend = tmp_path / "backend"
        frontend.mkdir(parents=True)
        backend.mkdir(parents=True)

        (frontend / "orders.ts").write_text(
            """
interface OrderDTO { id: string }
export const loadOrders = () => fetch('/api/orders')
            """,
            encoding="utf-8",
        )
        (backend / "api.py").write_text(
            """
from fastapi import APIRouter
router = APIRouter()

@router.get('/api/orders')
def get_orders():
    return []

class OrderModel:
    pass
            """,
            encoding="utf-8",
        )

        report = build_cross_language_links(tmp_path)
        edge_types = {edge.edge_type for edge in report.edges}
        assert "frontend_to_backend" in edge_types
        assert "contract_mapping" in edge_types

    def test_service_boundary_nodes(self, tmp_path):
        (tmp_path / "frontend" / "src" / "comp.tsx").parent.mkdir(parents=True)
        (tmp_path / "backend" / "service.py").parent.mkdir(parents=True)
        (tmp_path / "workers" / "queue_worker.py").parent.mkdir(parents=True)

        (tmp_path / "frontend" / "src" / "comp.tsx").write_text("export const A = 1", encoding="utf-8")
        (tmp_path / "backend" / "service.py").write_text("def run():\n    pass", encoding="utf-8")
        (tmp_path / "workers" / "queue_worker.py").write_text("def run():\n    pass", encoding="utf-8")

        report = build_cross_language_links(tmp_path)
        service_types = {node.get("service_type") for node in report.service_nodes}
        assert "frontend" in service_types
        assert "backend" in service_types or "worker" in service_types
