from __future__ import annotations

import json

from codegraph.system_graph_builder import build_system_graph


def test_system_graph_builder_detects_cross_repo_api_edge(tmp_path):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()

    (backend / "api.py").write_text("route = '/api/orders'\n", encoding="utf-8")
    (frontend / "app.tsx").write_text("fetch('/api/orders')\n", encoding="utf-8")

    cfg_dir = tmp_path / ".codegraph"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "system.json").write_text(
        json.dumps(
            {
                "repositories": {
                    "frontend": "frontend",
                    "backend": "backend",
                }
            }
        ),
        encoding="utf-8",
    )

    graph = build_system_graph(tmp_path)
    assert any(n["id"] == "repo:frontend" for n in graph.nodes)
    assert any(n["id"] == "repo:backend" for n in graph.nodes)
    assert any(e["source"] == "repo:frontend" and e["target"] == "repo:backend" for e in graph.edges)
