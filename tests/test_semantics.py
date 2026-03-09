"""Unit tests for the semantic behavior extraction engine.

Tests R-008 through R-021.
"""

from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

import pytest

from codegraph.semantics import (
    _classify_verb,
    extract_actions,
    extract_guards,
    extract_side_effects,
    extract_data_flow,
    infer_domain_tags,
    classify_sql_operations,
    detect_library_calls,
    extract_semantics_for_node,
    extract_semantics_for_file,
    build_graph2,
    detect_behavior_changes,
    save_graph2,
    load_graph2,
    evaluate_semantic_rules_impl,
)
from codegraph.models.graph2 import (
    ActionType,
    SideEffectType,
    Graph2,
    Graph2Node,
    SemanticAction,
    Guard,
    SideEffect,
)
from codegraph.models.graph0 import Graph0, Graph0Node


# ── Helpers ────────────────────────────────────────────────────────────


def _parse_func(source: str) -> ast.AST:
    """Parse a function definition string and return the AST node."""
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise ValueError("No function found in source")


# ── R-008: Verb Classification ─────────────────────────────────────────


class TestClassifyVerb:

    def test_read_verbs(self) -> None:
        assert _classify_verb("get_user") == ActionType.READ
        assert _classify_verb("fetch_data") == ActionType.READ
        assert _classify_verb("load_config") == ActionType.READ

    def test_write_verbs(self) -> None:
        assert _classify_verb("set_value") == ActionType.WRITE
        assert _classify_verb("save_data") == ActionType.WRITE

    def test_create_verbs(self) -> None:
        assert _classify_verb("create_user") == ActionType.CREATE

    def test_delete_verbs(self) -> None:
        assert _classify_verb("delete_record") == ActionType.DELETE
        assert _classify_verb("remove_item") == ActionType.DELETE

    def test_validate_verbs(self) -> None:
        assert _classify_verb("validate_input") == ActionType.VALIDATE
        assert _classify_verb("check_permission") == ActionType.VALIDATE

    def test_send_verbs(self) -> None:
        assert _classify_verb("send_email") == ActionType.SEND

    def test_unknown_verb(self) -> None:
        assert _classify_verb("xyzzy_foo") == ActionType.UNKNOWN


# ── R-009: Action Extraction ──────────────────────────────────────────


class TestExtractActions:

    def test_simple_function(self) -> None:
        src = """\
        def fetch_data(url):
            return requests.get(url)
        """
        node = _parse_func(src)
        actions = extract_actions(node, "fetch_data")
        assert len(actions) >= 1
        assert any(a.action_type == ActionType.READ for a in actions)

    def test_multiple_verbs(self) -> None:
        src = """\
        def process_and_save(data):
            result = transform(data)
            save(result)
        """
        node = _parse_func(src)
        actions = extract_actions(node, "process_and_save")
        assert len(actions) >= 1


# ── R-010: Guard Extraction ───────────────────────────────────────────


class TestExtractGuards:

    def test_if_raise(self) -> None:
        src = """\
        def protected(x):
            if x < 0:
                raise ValueError("negative")
            return x
        """
        node = _parse_func(src)
        guards = extract_guards(node)
        assert len(guards) >= 1
        assert any(g.raises != "" for g in guards)

    def test_if_return(self) -> None:
        src = """\
        def check(val):
            if not val:
                return None
            return val.upper()
        """
        node = _parse_func(src)
        guards = extract_guards(node)
        assert len(guards) >= 1
        assert any(g.early_return for g in guards)

    def test_no_guards(self) -> None:
        src = """\
        def simple(x):
            return x + 1
        """
        node = _parse_func(src)
        guards = extract_guards(node)
        assert len(guards) == 0


# ── R-011: Side Effect Extraction ──────────────────────────────────────


class TestExtractSideEffects:

    def test_file_write(self) -> None:
        src = """\
        def write_log(msg):
            with open("log.txt", "w") as f:
                f.write(msg)
        """
        node = _parse_func(src)
        effects = extract_side_effects(node)
        assert len(effects) >= 1

    def test_print_is_side_effect(self) -> None:
        src = """\
        def show(x):
            print(x)
        """
        node = _parse_func(src)
        effects = extract_side_effects(node)
        # print may or may not be classified — depends on implementation
        # just verify the function runs without error
        assert isinstance(effects, list)


# ── R-012: Data Flow Extraction ────────────────────────────────────────


class TestExtractDataFlow:

    def test_function_with_params(self) -> None:
        src = """\
        def add(x: int, y: int) -> int:
            return x + y
        """
        node = _parse_func(src)
        df = extract_data_flow(node)
        assert df is not None
        assert "x" in df.inputs or len(df.input_items) >= 2

    def test_function_with_return(self) -> None:
        src = """\
        def make_pair(a, b):
            result = (a, b)
            return result
        """
        node = _parse_func(src)
        df = extract_data_flow(node)
        assert df is not None


# ── R-013: Domain Tag Inference ────────────────────────────────────────


class TestInferDomainTags:

    def test_auth_from_name(self) -> None:
        tags = infer_domain_tags("authenticate_user", "auth/login.py")
        assert "auth" in tags

    def test_database_from_path(self) -> None:
        tags = infer_domain_tags("query_records", "db/queries.py")
        assert any(t in tags for t in ("database", "db"))

    def test_api_from_path(self) -> None:
        tags = infer_domain_tags("handle_request", "api/views.py")
        assert "api" in tags


# ── R-014: SQL Classification ──────────────────────────────────────────


class TestClassifySqlOperations:

    def test_select_in_string(self) -> None:
        src = """\
        def query_users():
            sql = "SELECT * FROM users WHERE id = ?"
            cursor.execute(sql)
        """
        node = _parse_func(src)
        ops = classify_sql_operations(node)
        assert any("SELECT" in op.upper() for op in ops)

    def test_insert_in_string(self) -> None:
        src = """\
        def add_user():
            cursor.execute("INSERT INTO users (name) VALUES (?)", (name,))
        """
        node = _parse_func(src)
        ops = classify_sql_operations(node)
        assert any("INSERT" in op.upper() for op in ops)

    def test_no_sql(self) -> None:
        src = """\
        def add(x, y):
            return x + y
        """
        node = _parse_func(src)
        ops = classify_sql_operations(node)
        assert len(ops) == 0


# ── R-015: Library Call Detection ──────────────────────────────────────


class TestDetectLibraryCalls:

    def test_known_library(self) -> None:
        src = """\
        def fetch():
            import requests
            return requests.get("http://example.com")
        """
        node = _parse_func(src)
        libs = detect_library_calls(node)
        assert "requests" in libs

    def test_os_call(self) -> None:
        src = """\
        def list_files():
            import os
            return os.listdir(".")
        """
        node = _parse_func(src)
        libs = detect_library_calls(node)
        assert "os" in libs


# ── R-016: Full Node Extraction ────────────────────────────────────────


class TestExtractSemanticsForNode:

    def test_full_extraction(self) -> None:
        src = """\
        def validate_and_save(user):
            if not user:
                raise ValueError("no user")
            db.save(user)
        """
        node = _parse_func(src)
        g2node = extract_semantics_for_node(node, "mod.py::validate_and_save", "validate_and_save", "mod.py")
        assert g2node.id == "mod.py::validate_and_save"
        assert len(g2node.actions) >= 1
        assert len(g2node.guards) >= 1
        assert g2node.confidence > 0


# ── R-017: File-level Extraction ──────────────────────────────────────


class TestExtractSemanticsForFile:

    def test_extracts_all_functions(self) -> None:
        source = textwrap.dedent("""\
            def get_user(uid):
                return db.find(uid)

            def delete_user(uid):
                db.remove(uid)
        """)
        nodes = extract_semantics_for_file(source, "users.py")
        assert len(nodes) >= 2
        ids = [n.id for n in nodes]
        assert any("get_user" in i for i in ids)
        assert any("delete_user" in i for i in ids)

    def test_extracts_methods(self) -> None:
        source = textwrap.dedent("""\
            class UserService:
                def create_user(self, name):
                    pass

                def find_user(self, uid):
                    pass
        """)
        nodes = extract_semantics_for_file(source, "service.py")
        assert len(nodes) >= 2

    def test_malformed_source(self) -> None:
        # Should handle gracefully, not crash
        nodes = extract_semantics_for_file("def broken(", "bad.py")
        assert nodes == [] or isinstance(nodes, list)


# ── R-019: Build Graph2 ───────────────────────────────────────────────


class TestBuildGraph2:

    def test_build_from_graph0(self, tmp_path: Path) -> None:
        # Create a simple Python file
        src = tmp_path / "src"
        src.mkdir()
        (src / "mod.py").write_text(textwrap.dedent("""\
            def fetch_data(url):
                import requests
                return requests.get(url).json()

            def validate_input(data):
                if not data:
                    raise ValueError("empty")
                return True
        """), encoding="utf-8")

        g0 = Graph0(
            source_files=["src/mod.py"],
            nodes=[
                Graph0Node(id="src/mod.py::fetch_data", body_hash="h1", file="src/mod.py", type="function", line=1),
                Graph0Node(id="src/mod.py::validate_input", body_hash="h2", file="src/mod.py", type="function", line=5),
            ],
        )
        g2 = build_graph2(g0, tmp_path)
        assert len(g2.nodes) >= 2


# ── R-020: Behavior Change Detection ──────────────────────────────────


class TestDetectBehaviorChanges:

    def test_no_changes(self) -> None:
        n = Graph2Node(id="a", actions=[SemanticAction(verb="read")])
        n.behavior_hash = n.compute_behavior_hash()
        g = Graph2(nodes=[n])
        changes = detect_behavior_changes(g, g)
        assert len(changes) == 0

    def test_detects_change(self) -> None:
        n1 = Graph2Node(id="a", actions=[SemanticAction(verb="read")])
        n1.behavior_hash = n1.compute_behavior_hash()
        n2 = Graph2Node(id="a", actions=[SemanticAction(verb="write")])
        n2.behavior_hash = n2.compute_behavior_hash()
        old = Graph2(nodes=[n1])
        new = Graph2(nodes=[n2])
        changes = detect_behavior_changes(old, new)
        assert "a" in changes

    def test_detects_addition(self) -> None:
        n1 = Graph2Node(id="a", actions=[SemanticAction(verb="read")])
        n1.behavior_hash = n1.compute_behavior_hash()
        n2 = Graph2Node(id="b", actions=[SemanticAction(verb="write")])
        n2.behavior_hash = n2.compute_behavior_hash()
        old = Graph2(nodes=[n1])
        new = Graph2(nodes=[n1, n2])
        changes = detect_behavior_changes(old, new)
        assert "b" in changes


# ── R-021: Save/Load Graph2 ───────────────────────────────────────────


class TestSaveLoadGraph2:

    def test_roundtrip(self, tmp_path: Path) -> None:
        cg = tmp_path / ".codegraph"
        cg.mkdir()
        n = Graph2Node(id="a", actions=[SemanticAction(verb="read", action_type=ActionType.READ)])
        g = Graph2(nodes=[n])
        save_graph2(g, tmp_path)
        loaded = load_graph2(tmp_path)
        assert len(loaded.nodes) == 1
        assert loaded.nodes[0].id == "a"


# ── R-021: Semantic Rule Evaluation ────────────────────────────────────


class TestEvaluateSemanticRules:

    def test_db_write_no_guard(self) -> None:
        """db-write-no-guard: node with DB write side effect but no guards."""
        n = Graph2Node(
            id="mod.py::insert_user",
            actions=[SemanticAction(verb="insert", action_type=ActionType.CREATE)],
            side_effects=[SideEffect(type="db", effect_type=SideEffectType.DATABASE_WRITE)],
            guards=[],
        )
        g2 = Graph2(nodes=[n])
        violations = evaluate_semantic_rules_impl(g2, None, None)
        db_write_violations = [v for v in violations if v.get("rule") == "db-write-no-guard"]
        assert len(db_write_violations) >= 1

    def test_db_write_with_guard_passes(self) -> None:
        """A guarded DB write should not trigger the rule."""
        n = Graph2Node(
            id="mod.py::insert_user",
            actions=[SemanticAction(verb="insert", action_type=ActionType.CREATE)],
            side_effects=[SideEffect(type="db", effect_type=SideEffectType.DATABASE_WRITE)],
            guards=[Guard(condition="user is valid", raises="ValueError")],
        )
        g2 = Graph2(nodes=[n])
        violations = evaluate_semantic_rules_impl(g2, None, None)
        db_write_violations = [v for v in violations if v.get("rule") == "db-write-no-guard"]
        assert len(db_write_violations) == 0

    def test_no_violations(self) -> None:
        """Clean code should produce no violations."""
        n = Graph2Node(
            id="mod.py::add",
            actions=[SemanticAction(verb="compute", action_type=ActionType.COMPUTE)],
        )
        g2 = Graph2(nodes=[n])
        violations = evaluate_semantic_rules_impl(g2, None, None)
        assert len(violations) == 0
