"""Tests for codegraph.arch_schema — architecture definition models."""

import json
import tempfile
from pathlib import Path

import pytest

from codegraph.arch_schema import (
    ArchComponent,
    ArchConstraint,
    ArchEdge,
    SubsystemDef,
    SystemArchitecture,
    init_architecture,
)


class TestArchComponent:
    def test_to_dict_minimal(self):
        c = ArchComponent(name="extractor")
        d = c.to_dict()
        assert d == {"name": "extractor"}

    def test_to_dict_full(self):
        c = ArchComponent(
            name="extractor",
            module="codegraph/extractor.py",
            functions=["extract_nodes", "parse_file"],
            description="AST extraction",
        )
        d = c.to_dict()
        assert d["name"] == "extractor"
        assert d["module"] == "codegraph/extractor.py"
        assert len(d["functions"]) == 2
        assert d["description"] == "AST extraction"

    def test_from_dict(self):
        d = {"name": "models", "module": "codegraph/models/", "functions": ["Graph0"]}
        c = ArchComponent.from_dict(d)
        assert c.name == "models"
        assert c.module == "codegraph/models/"
        assert c.functions == ["Graph0"]

    def test_roundtrip(self):
        c = ArchComponent(name="x", module="x.py", functions=["f"], description="d")
        assert ArchComponent.from_dict(c.to_dict()).name == "x"


class TestArchEdge:
    def test_to_dict_default_type(self):
        e = ArchEdge(source="a", target="b")
        d = e.to_dict()
        assert d == {"source": "a", "target": "b"}
        assert "edge_type" not in d

    def test_to_dict_custom_type(self):
        e = ArchEdge(source="a", target="b", edge_type="data_flow")
        d = e.to_dict()
        assert d["edge_type"] == "data_flow"

    def test_from_dict_object(self):
        e = ArchEdge.from_dict({"source": "a", "target": "b", "edge_type": "call"})
        assert e.source == "a"
        assert e.edge_type == "call"

    def test_from_dict_list(self):
        e = ArchEdge.from_dict(["a", "b"])
        assert e.source == "a"
        assert e.target == "b"
        assert e.edge_type == "dependency"


class TestArchConstraint:
    def test_to_dict(self):
        c = ArchConstraint(constraint_type="forbidden", source="ui", target="database",
                           reason="No direct DB access from UI")
        d = c.to_dict()
        assert d["type"] == "forbidden"
        assert d["source"] == "ui"
        assert d["reason"] == "No direct DB access from UI"

    def test_from_dict(self):
        c = ArchConstraint.from_dict({
            "type": "forbidden", "source": "ui", "target": "db"
        })
        assert c.constraint_type == "forbidden"
        assert c.source == "ui"

    def test_from_dict_no_reason(self):
        c = ArchConstraint.from_dict({"type": "required", "source": "a", "target": "b"})
        assert c.reason == ""


class TestSubsystemDef:
    def test_empty(self):
        s = SubsystemDef(name="core")
        d = s.to_dict()
        assert d["name"] == "core"
        assert "components" not in d
        assert "edges" not in d

    def test_with_components(self):
        s = SubsystemDef(
            name="auth",
            description="Authentication",
            components=[ArchComponent(name="validator", module="auth/validator.py")],
            edges=[ArchEdge(source="validator", target="hasher")],
        )
        d = s.to_dict()
        assert len(d["components"]) == 1
        assert d["components"][0]["name"] == "validator"
        assert len(d["edges"]) == 1

    def test_from_dict(self):
        d = {
            "name": "auth",
            "components": [{"name": "v", "module": "v.py"}],
            "edges": [{"source": "a", "target": "b"}],
        }
        s = SubsystemDef.from_dict(d)
        assert s.name == "auth"
        assert len(s.components) == 1
        assert len(s.edges) == 1

    def test_component_names(self):
        s = SubsystemDef(
            name="x",
            components=[
                ArchComponent(name="a", module="a.py"),
                ArchComponent(name="b", module="b.py"),
            ],
        )
        assert s.component_names == ["a", "b"]

    def test_module_paths(self):
        s = SubsystemDef(
            name="x",
            components=[
                ArchComponent(name="a", module="a.py"),
                ArchComponent(name="b"),  # no module
            ],
        )
        assert s.module_paths == ["a.py"]

    def test_all_functions(self):
        s = SubsystemDef(
            name="x",
            components=[
                ArchComponent(name="a", module="a.py", functions=["foo", "bar"]),
            ],
        )
        fns = s.all_functions
        assert "a.py::foo" in fns
        assert "a.py::bar" in fns


class TestSystemArchitecture:
    def test_empty(self):
        a = SystemArchitecture(name="proj")
        d = a.to_dict()
        assert d["name"] == "proj"
        assert d["version"] == 1

    def test_full_roundtrip(self):
        a = SystemArchitecture(
            name="myapp",
            description="Test app",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[ArchComponent(name="main", module="main.py")],
                ),
            ],
            edges=[ArchEdge(source="core", target="db")],
            constraints=[ArchConstraint("forbidden", "ui", "db")],
            version=2,
        )
        d = a.to_dict()
        a2 = SystemArchitecture.from_dict(d)
        assert a2.name == "myapp"
        assert len(a2.subsystems) == 1
        assert len(a2.edges) == 1
        assert len(a2.constraints) == 1
        assert a2.version == 2

    def test_get_subsystem(self):
        a = SystemArchitecture(
            name="x",
            subsystems=[SubsystemDef(name="core"), SubsystemDef(name="data")],
        )
        assert a.get_subsystem("core") is not None
        assert a.get_subsystem("core").name == "core"
        assert a.get_subsystem("missing") is None

    def test_subsystem_names(self):
        a = SystemArchitecture(
            name="x",
            subsystems=[SubsystemDef(name="a"), SubsystemDef(name="b")],
        )
        assert a.subsystem_names == ["a", "b"]

    def test_all_modules(self):
        a = SystemArchitecture(
            name="x",
            subsystems=[
                SubsystemDef(
                    name="core",
                    components=[ArchComponent(name="m", module="core/m.py")],
                ),
            ],
        )
        assert a.all_modules == ["core/m.py"]

    def test_all_components(self):
        a = SystemArchitecture(
            name="x",
            subsystems=[
                SubsystemDef(
                    name="s1",
                    components=[ArchComponent(name="c1"), ArchComponent(name="c2")],
                ),
            ],
        )
        assert len(a.all_components) == 2

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = SystemArchitecture(name="test", description="desc")
            a.save(root)

            loaded = SystemArchitecture.load(root)
            assert loaded is not None
            assert loaded.name == "test"
            assert loaded.description == "desc"

    def test_load_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assert SystemArchitecture.load(root) is None

    def test_constraint_violations(self):
        a = SystemArchitecture(
            name="x",
            subsystems=[
                SubsystemDef(
                    name="ui",
                    components=[ArchComponent(name="views", module="ui/views.py")],
                ),
                SubsystemDef(
                    name="db",
                    components=[ArchComponent(name="store", module="db/store.py")],
                ),
            ],
            constraints=[
                ArchConstraint("forbidden", "ui", "db", "No UI→DB access"),
            ],
        )
        # Violation: ui/views.py → db/store.py
        violations = a.get_constraint_violations([("ui/views.py", "db/store.py")])
        assert len(violations) == 1
        assert violations[0]["source_file"] == "ui/views.py"

    def test_no_constraint_violations(self):
        a = SystemArchitecture(
            name="x",
            constraints=[ArchConstraint("forbidden", "ui", "db")],
        )
        violations = a.get_constraint_violations([("api/app.py", "db/store.py")])
        assert len(violations) == 0


class TestInitArchitecture:
    def test_creates_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arch = init_architecture(root, name="myproj")
            assert arch.name == "myproj"
            assert len(arch.subsystems) == 1

            # File should exist
            path = root / ".codegraph" / "architecture" / "system.json"
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["name"] == "myproj"
