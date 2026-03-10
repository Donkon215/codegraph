"""Tests for codegraph.subsystem_lifecycle — subsystem lifecycle management."""

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
)
from codegraph.subsystem_lifecycle import (
    SubsystemChange,
    SubsystemFile,
    create_subsystem,
    split_subsystem,
    merge_subsystems,
    move_component,
    generate_subsystem_files,
    load_subsystem_file,
    list_subsystem_files,
)


def _make_arch() -> SystemArchitecture:
    """Build a test architecture."""
    ss_a = SubsystemDef(
        name="core",
        description="Core engine",
        components=[
            ArchComponent(name="extractor", module="core/ext.py", functions=["extract"]),
            ArchComponent(name="builder", module="core/build.py", functions=["build"]),
            ArchComponent(name="parser", module="core/parse.py", functions=["parse"]),
        ],
        edges=[
            ArchEdge(source="builder", target="extractor"),
            ArchEdge(source="builder", target="parser"),
        ],
    )
    ss_b = SubsystemDef(
        name="models",
        description="Data models",
        components=[
            ArchComponent(name="graph0", module="models/g0.py"),
        ],
    )
    return SystemArchitecture(
        name="test",
        subsystems=[ss_a, ss_b],
        edges=[ArchEdge(source="core", target="models")],
        constraints=[
            ArchConstraint("forbidden", "models", "core", "Models can't import core"),
        ],
    )


class TestSubsystemChange:
    def test_to_dict(self):
        c = SubsystemChange(
            operation="split",
            subsystem="core",
            target_subsystem="parsing",
            reason="Too large",
        )
        d = c.to_dict()
        assert d["operation"] == "split"
        assert d["subsystem"] == "core"
        assert d["reason"] == "Too large"

    def test_minimal(self):
        c = SubsystemChange(operation="create")
        d = c.to_dict()
        assert "subsystem" not in d
        assert "component" not in d


class TestSubsystemFile:
    def test_to_dict(self):
        sf = SubsystemFile(
            name="core",
            description="Core engine",
            intent="Extracts and builds",
            components=[{"name": "extractor"}],
            edges=[["builder", "extractor"]],
        )
        d = sf.to_dict()
        assert d["name"] == "core"
        assert d["intent"] == "Extracts and builds"
        assert len(d["components"]) == 1

    def test_minimal(self):
        sf = SubsystemFile(name="test")
        d = sf.to_dict()
        assert d["name"] == "test"
        assert "description" not in d
        assert "components" not in d


class TestCreateSubsystem:
    def test_creates_new(self):
        arch = _make_arch()
        ss = create_subsystem(arch, "query", description="Query engine")
        assert ss.name == "query"
        assert len(arch.subsystems) == 3
        assert arch.get_subsystem("query") is not None

    def test_duplicate_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="already exists"):
            create_subsystem(arch, "core")


class TestSplitSubsystem:
    def test_basic_split(self):
        arch = _make_arch()
        source, new = split_subsystem(
            arch, "core", "parsing", ["parser"],
            new_description="Parsing subsystem",
        )
        assert len(source.components) == 2  # extractor + builder
        assert len(new.components) == 1  # parser
        assert new.name == "parsing"
        assert arch.get_subsystem("parsing") is not None

    def test_splits_edges(self):
        arch = _make_arch()
        source, new = split_subsystem(arch, "core", "parsing", ["parser"])
        # builder → parser was internal, now cross-subsystem
        # builder → extractor stays internal to core
        assert any(e.source == "builder" and e.target == "extractor"
                    for e in source.edges)
        # parser was moved so builder → parser becomes inter-subsystem
        inter = [e for e in arch.edges if
                 (e.source == "core" and e.target == "parsing")]
        assert len(inter) >= 1

    def test_nonexistent_source_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="not found"):
            split_subsystem(arch, "nonexistent", "new", ["comp"])

    def test_duplicate_target_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="already exists"):
            split_subsystem(arch, "core", "models", ["parser"])

    def test_no_matching_components_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="No matching"):
            split_subsystem(arch, "core", "new", ["nonexistent"])


class TestMergeSubsystems:
    def test_basic_merge(self):
        arch = _make_arch()
        merged = merge_subsystems(arch, "core", "models")
        assert merged.name == "core"
        assert len(merged.components) == 4  # 3 from core + 1 from models
        assert arch.get_subsystem("models") is None
        assert arch.get_subsystem("core") is not None

    def test_custom_name(self):
        arch = _make_arch()
        merged = merge_subsystems(arch, "core", "models", merged_name="everything")
        assert merged.name == "everything"
        assert arch.get_subsystem("core") is None
        assert arch.get_subsystem("models") is None
        assert arch.get_subsystem("everything") is not None

    def test_constraints_updated(self):
        arch = _make_arch()
        merge_subsystems(arch, "core", "models")
        # The forbidden constraint had models → core which is now self-edge
        # It should be removed
        self_constraints = [c for c in arch.constraints
                           if c.source == c.target]
        assert len(self_constraints) == 0

    def test_self_edges_removed(self):
        arch = _make_arch()
        merge_subsystems(arch, "core", "models")
        self_edges = [e for e in arch.edges if e.source == e.target]
        assert len(self_edges) == 0

    def test_nonexistent_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="not found"):
            merge_subsystems(arch, "core", "nonexistent")


class TestMoveComponent:
    def test_basic_move(self):
        arch = _make_arch()
        move_component(arch, "parser", "core", "models")
        core = arch.get_subsystem("core")
        models = arch.get_subsystem("models")
        assert len(core.components) == 2
        assert len(models.components) == 2
        assert any(c.name == "parser" for c in models.components)
        assert not any(c.name == "parser" for c in core.components)

    def test_related_edges_moved(self):
        arch = _make_arch()
        move_component(arch, "parser", "core", "models")
        models = arch.get_subsystem("models")
        # builder → parser edge should move to models
        assert any(e.target == "parser" for e in models.edges)

    def test_nonexistent_component_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="not found"):
            move_component(arch, "nonexistent", "core", "models")

    def test_nonexistent_source_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="Source subsystem not found"):
            move_component(arch, "parser", "nonexistent", "models")

    def test_nonexistent_target_raises(self):
        arch = _make_arch()
        with pytest.raises(ValueError, match="Target subsystem not found"):
            move_component(arch, "parser", "core", "nonexistent")


class TestGenerateSubsystemFiles:
    def test_generates_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            arch = _make_arch()
            paths = generate_subsystem_files(arch, root)
            assert len(paths) == 2  # core + models

            core_path = root / ".codegraph" / "architecture" / "subsystems" / "core.json"
            assert core_path.exists()
            data = json.loads(core_path.read_text(encoding="utf-8"))
            assert data["name"] == "core"
            assert len(data["components"]) == 3

    def test_includes_constraints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            arch = _make_arch()
            generate_subsystem_files(arch, root)

            # models has a constraint referencing it
            models_path = root / ".codegraph" / "architecture" / "subsystems" / "models.json"
            data = json.loads(models_path.read_text(encoding="utf-8"))
            assert len(data["rules"]) >= 1


class TestLoadSubsystemFile:
    def test_load_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            arch = _make_arch()
            generate_subsystem_files(arch, root)

            sf = load_subsystem_file(root, "core")
            assert sf is not None
            assert sf.name == "core"
            assert len(sf.components) == 3

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert load_subsystem_file(Path(tmpdir), "none") is None


class TestListSubsystemFiles:
    def test_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            arch = _make_arch()
            generate_subsystem_files(arch, root)

            names = list_subsystem_files(root)
            assert "core" in names
            assert "models" in names

    def test_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert list_subsystem_files(Path(tmpdir)) == []
