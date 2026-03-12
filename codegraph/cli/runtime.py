"""codegraph.cli.runtime — Runtime, testing, and lifecycle CLI commands.

Commands: archi-test, test-impact, simulate, api-link, runtime-graph,
pre-commit.
Groups: branch, lifecycle, cas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from codegraph.config import find_project_root, load_config
from codegraph.cli.core import handle_error, timed_command, EXIT_ERROR, EXIT_VALIDATION_FAIL


# ── Architecture Tests ────────────────────────────────────────────────
@click.command("archi-test")
@click.option("--generate", is_flag=True, help="Generate architecture tests.")
@click.option("--run", "run_tests", is_flag=True, help="Run architecture tests.")
@click.option("--cleanup", is_flag=True, help="Remove stale architecture tests.")
@click.option("--coverage", is_flag=True, help="Show test coverage report.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def archi_test_cmd(ctx: click.Context, generate: bool, run_tests: bool,
                   cleanup: bool, coverage: bool, json_output: bool) -> None:
    """Manage architecture tests."""
    from codegraph.archi_test import (
        generate_archi_tests, write_archi_tests, format_archi_result,
        run_archi_tests, cleanup_archi_tests, archi_test_coverage,
    )
    from codegraph.extractor import load_graph0
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    graph0 = load_graph0(root)
    wf = load_workflow(root)

    if generate:
        tests = generate_archi_tests(graph0, wf, root)
        written = write_archi_tests(tests, root)
        click.echo(format_archi_result(tests, as_json=json_output))
        click.echo(f"\n{written} tests written to disk")

    elif run_tests:
        result = run_archi_tests(root)
        click.echo(
            f"Archi tests: {result.passed} passed, {result.failed} failed, "
            f"{result.errors} errors ({result.elapsed_seconds:.1f}s)"
        )

    elif cleanup:
        result = cleanup_archi_tests(graph0, root)
        click.echo(f"Removed {len(result.removed)} stale tests, kept {result.kept}")

    elif coverage:
        report = archi_test_coverage(wf, root)
        click.echo(
            f"Edge coverage: {report.coverage_pct:.1f}%\n"
            f"  Project tests: {report.covered_by_project}\n"
            f"  Archi tests:   {report.covered_by_archi}\n"
            f"  Uncovered:     {report.uncovered}\n"
            f"  Total edges:   {report.total_edges}"
        )
    else:
        click.echo("Specify --generate, --run, --cleanup, or --coverage")


# ── Test Impact ───────────────────────────────────────────────────────
@click.command("test-impact")
@click.option("--from-delta", is_flag=True, help="Analyze impact from last delta.")
@click.option("--nodes", multiple=True, help="Specific node IDs to analyze.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--gaps", is_flag=True, help="Show coverage gaps.")
@click.pass_context
def test_impact_cmd(ctx: click.Context, from_delta: bool, nodes: tuple,
                    json_output: bool, gaps: bool) -> None:
    """Analyze test impact from code changes."""
    from codegraph.test_impact import (
        analyze_test_impact, format_test_impact, find_coverage_gaps,
        impact_from_delta,
    )
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    with IndexStore(root) as index:
        if gaps:
            from codegraph.extractor import load_graph0
            graph0 = load_graph0(root)
            gap_list = find_coverage_gaps(graph0, index)
            if json_output:
                import json as _json
                click.echo(_json.dumps([{
                    "node_id": g.node_id, "file": g.file, "gap_type": g.gap_type,
                } for g in gap_list], indent=2))
            else:
                click.echo(f"Coverage gaps: {len(gap_list)}")
                for g in gap_list[:30]:
                    click.echo(f"  {g.node_id} [{g.gap_type}]")
                if len(gap_list) > 30:
                    click.echo(f"  … and {len(gap_list) - 30} more")
            return

        if from_delta:
            import json as _json
            delta_path = root / ".codegraph" / "delta" / "delta.json"
            if not delta_path.exists():
                click.echo("No delta result found — run 'codegraph delta' first", err=True)
                sys.exit(1)
            from codegraph.models.delta import DeltaResult
            delta_data = _json.loads(delta_path.read_text(encoding="utf-8"))
            delta_result = DeltaResult.from_json(_json.dumps(delta_data))
            result = impact_from_delta(delta_result, index)
        elif nodes:
            result = analyze_test_impact(set(nodes), index)
        else:
            click.echo("Specify --from-delta or --nodes NODE_ID", err=True)
            sys.exit(1)

        click.echo(format_test_impact(result, as_json=json_output))


# ── Simulate ──────────────────────────────────────────────────────────
@click.command("simulate")
@click.argument("response_file", type=click.Path(exists=True))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def simulate_cmd(ctx: click.Context, response_file: str,
                 json_output: bool) -> None:
    """Simulate an agent_response.json to check for regressions."""
    import json as _json

    from codegraph.index import IndexStore
    from codegraph.simulator import simulate_agent_response

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    response_path = Path(response_file).resolve()
    response_data = _json.loads(response_path.read_text(encoding="utf-8"))

    with IndexStore(root) as index:
        result = simulate_agent_response(response_data, index)

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        if result.safe:
            click.echo("Simulation PASSED — no violations detected.")
        else:
            click.echo(f"Simulation FAILED — {len(result.violations)} violation(s):")
            for v in result.violations:
                click.echo(f"  [{v.severity}] {v.type}: {v.description}")
        click.echo(f"  New cycles: {result.new_cycle_count}")
        click.echo(f"  Coupling delta: {result.coupling_delta:+.4f}")


# ── API Link (Cross-Language) ─────────────────────────────────────────
@click.command("api-link")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save report to .codegraph/planning/api_link_report.json.")
@click.pass_context
def api_link_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Detect cross-language API links (backend endpoints ↔ frontend calls)."""
    import json as _json
    from codegraph.extractors.api_routes import link_api_routes

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    report = link_api_routes(root)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if save:
        planning_dir = root / ".codegraph" / "planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        out_path = planning_dir / "api_link_report.json"
        out_path.write_text(
            _json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        click.echo(f"API link report saved to {out_path}")


# ── Pre-Commit Gate ──────────────────────────────────────────────────
@click.command("pre-commit")
@click.option("--strict", is_flag=True,
              help="Treat warnings as failures.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save-baseline", is_flag=True,
              help="Save current metrics as the new baseline.")
@click.pass_context
def pre_commit_cmd(ctx: click.Context, strict: bool, json_output: bool,
                   save_baseline: bool) -> None:
    """Run pre-commit simulation gate.

    Compares current architecture metrics against baseline to
    detect regressions before committing.
    """
    import json as _json
    from codegraph.precommit import (
        run_pre_commit_check, _save_baseline, _compute_current_metrics,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if save_baseline:
        metrics = _compute_current_metrics(root)
        _save_baseline(root, metrics)
        click.echo("Baseline metrics saved.")
        return

    report = run_pre_commit_check(root, strict=strict)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if report.blocked:
        sys.exit(EXIT_VALIDATION_FAIL)


# ── Runtime Graph ─────────────────────────────────────────────────────
@click.command("runtime-graph")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save runtime graph to .codegraph/graphs/.")
@click.pass_context
def runtime_graph_cmd(ctx: click.Context, json_output: bool,
                      save: bool) -> None:
    """Extract runtime dependency edges (HTTP, DB, MQ, env vars)."""
    import json as _json
    from codegraph.runtime_graph import (
        extract_runtime_edges, save_runtime_graph,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph = extract_runtime_edges(root)

    if json_output:
        click.echo(_json.dumps(graph.to_dict(), indent=2))
    else:
        click.echo(graph.format())

    if save:
        path = save_runtime_graph(root, graph)
        click.echo(f"Runtime graph saved to {path}")


# ── Branch Group ──────────────────────────────────────────────────────
@click.group("branch")
def branch_group() -> None:
    """Manage architecture branches for safe evolution."""
    pass


@branch_group.command("create")
@click.argument("name")
@click.option("--base", default="main", help="Base branch to branch from.")
@click.pass_context
def branch_create(ctx: click.Context, name: str, base: str) -> None:
    """Create a new architecture branch."""
    from codegraph.branch_executor import create_branch

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    state = create_branch(root, name, base)
    click.echo(f"Created branch: {state.branch_name}")
    click.echo(f"  Base: {state.base_branch}")
    click.echo(f"  Status: {state.status}")


@branch_group.command("validate")
@click.pass_context
def branch_validate(ctx: click.Context) -> None:
    """Validate the current architecture branch."""
    from codegraph.branch_executor import (
        capture_metrics,
        load_branch_state,
        update_branch_status,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    state = load_branch_state(root)
    if not state:
        click.echo("No active branch state found.", err=True)
        sys.exit(EXIT_ERROR)

    metrics = capture_metrics(root)
    update_branch_status(root, "validating")
    click.echo(f"Branch: {state.branch_name}")
    click.echo(f"  Nodes: {metrics.node_count}")
    click.echo(f"  Edges: {metrics.edge_count}")
    click.echo(f"  Violations: {metrics.policy_violations}")
    click.echo(f"  Cycles: {metrics.cycles}")
    click.echo(f"  Health: {metrics.health_score:.2f}")


@branch_group.command("compare")
@click.pass_context
def branch_compare(ctx: click.Context) -> None:
    """Compare current branch metrics against base."""
    from codegraph.branch_executor import compare_branches, load_branch_state

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    state = load_branch_state(root)
    if not state or not state.base_metrics or not state.branch_metrics:
        click.echo("Run 'branch validate' first to capture metrics.", err=True)
        sys.exit(EXIT_ERROR)

    comparison = compare_branches(state.base_metrics, state.branch_metrics)
    click.echo(f"Branch: {state.branch_name}")
    click.echo(f"  Health delta: {comparison.health_delta:+.2f}")
    click.echo(f"  Cycle delta: {comparison.cycle_delta:+d}")
    click.echo(f"  Violation delta: {comparison.violation_delta:+d}")
    click.echo(f"  Recommendation: {comparison.recommendation}")
    for r in comparison.reasons:
        click.echo(f"    - {r}")


@branch_group.command("merge")
@click.pass_context
def branch_merge(ctx: click.Context) -> None:
    """Merge current architecture branch to base."""
    from codegraph.branch_executor import load_branch_state, merge_branch

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    state = load_branch_state(root)
    if not state:
        click.echo("No active branch state found.", err=True)
        sys.exit(EXIT_ERROR)

    merge_branch(root)
    click.echo(f"Merged {state.branch_name} → {state.base_branch}")


@branch_group.command("discard")
@click.pass_context
def branch_discard(ctx: click.Context) -> None:
    """Discard the current architecture branch."""
    from codegraph.branch_executor import discard_branch, load_branch_state

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    state = load_branch_state(root)
    if not state:
        click.echo("No active branch state found.", err=True)
        sys.exit(EXIT_ERROR)

    discard_branch(root)
    click.echo(f"Discarded branch: {state.branch_name}")


@branch_group.command("list")
@click.pass_context
def branch_list(ctx: click.Context) -> None:
    """List architecture branches."""
    from codegraph.branch_executor import list_architecture_branches

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    branches = list_architecture_branches(root)
    if not branches:
        click.echo("No architecture branches found.")
        return
    for b in branches:
        click.echo(f"  {b}")


# ── Lifecycle Group ───────────────────────────────────────────────────
@click.group("lifecycle")
def lifecycle_group() -> None:
    """Manage subsystem lifecycle (create, split, merge, move)."""
    pass


@lifecycle_group.command("create")
@click.argument("name")
@click.option("--description", "-d", default="",
              help="Description for the new subsystem.")
@click.pass_context
def lifecycle_create(ctx: click.Context, name: str, description: str) -> None:
    """Create a new subsystem in the architecture."""
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.subsystem_lifecycle import create_subsystem

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    create_subsystem(arch, name, description=description)
    arch.save(root)
    click.echo(f"Created subsystem: {name}")


@lifecycle_group.command("split")
@click.argument("source")
@click.argument("new_name")
@click.argument("components", nargs=-1, required=True)
@click.option("--description", "-d", default="",
              help="Description for the new subsystem.")
@click.pass_context
def lifecycle_split(ctx: click.Context, source: str, new_name: str,
                    components: tuple[str, ...], description: str) -> None:
    """Split a subsystem by moving components to a new subsystem."""
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.subsystem_lifecycle import split_subsystem

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    split_subsystem(arch, source, new_name, list(components),
                    new_description=description)
    arch.save(root)
    click.echo(f"Split {source} → {source} + {new_name}")


@lifecycle_group.command("merge")
@click.argument("name_a")
@click.argument("name_b")
@click.option("--as", "merged_name", default=None,
              help="Name for the merged subsystem.")
@click.pass_context
def lifecycle_merge(ctx: click.Context, name_a: str, name_b: str,
                    merged_name: str | None) -> None:
    """Merge two subsystems into one."""
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.subsystem_lifecycle import merge_subsystems

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    merge_subsystems(arch, name_a, name_b, merged_name=merged_name)
    arch.save(root)
    click.echo(f"Merged {name_a} + {name_b}")


@lifecycle_group.command("move")
@click.argument("component")
@click.argument("from_subsystem")
@click.argument("to_subsystem")
@click.pass_context
def lifecycle_move(ctx: click.Context, component: str, from_subsystem: str,
                   to_subsystem: str) -> None:
    """Move a component from one subsystem to another."""
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.subsystem_lifecycle import move_component

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    move_component(arch, component, from_subsystem, to_subsystem)
    arch.save(root)
    click.echo(f"Moved {component}: {from_subsystem} → {to_subsystem}")


@lifecycle_group.command("generate-files")
@click.pass_context
def lifecycle_generate_files(ctx: click.Context) -> None:
    """Generate per-subsystem JSON files from architecture definition."""
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.subsystem_lifecycle import generate_subsystem_files

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    paths = generate_subsystem_files(arch, root)
    for p in paths:
        click.echo(f"  {p}")
    click.echo(f"Generated {len(paths)} subsystem files.")


# ── CAS commands ──────────────────────────────────────────────────────

@click.group("cas")
def cas_group() -> None:
    """Manage the Content Addressed Store (CAS) graph."""


@cas_group.command("build")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cas_build(ctx: click.Context, json_output: bool) -> None:
    """Compute dependency hashes for all nodes."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.cas import build_dependency_hashes, save_hash_snapshot
    from codegraph.extractor import load_graph0, save_graph0
    from codegraph.workflow import load_workflow
    from codegraph.storage import get_graph_version

    graph0 = load_graph0(root)
    workflow = load_workflow(root)
    hashes = build_dependency_hashes(graph0, workflow)
    graph0.update_dependency_hashes(hashes)
    save_graph0(graph0, root)
    version = get_graph_version(root)
    save_hash_snapshot(hashes, root, version)

    if json_output:
        click.echo(_json.dumps({"nodes_hashed": len(hashes)}, indent=2))
    else:
        click.echo(f"Computed dependency hashes for {len(hashes)} nodes.")


@cas_group.command("verify")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cas_verify(ctx: click.Context, json_output: bool) -> None:
    """Verify CAS hash integrity."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.cas import verify_cas_integrity
    from codegraph.extractor import load_graph0
    from codegraph.workflow import load_workflow

    graph0 = load_graph0(root)
    workflow = load_workflow(root)
    result = verify_cas_integrity(graph0, workflow)

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    elif result.passed:
        click.echo(f"CAS integrity OK \u2014 {result.checked} nodes verified.")
    else:
        click.echo(f"CAS integrity FAILED \u2014 {len(result.mismatches)} mismatch(es)")
        for nid, (stored, computed) in list(result.mismatches.items())[:10]:
            click.echo(f"  {nid}: stored={stored[:12]}\u2026 computed={computed[:12]}\u2026")
        sys.exit(EXIT_VALIDATION_FAIL)


@cas_group.command("impact")
@click.argument("node_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def cas_impact(ctx: click.Context, node_id: str, json_output: bool) -> None:
    """Show what would be affected if a node changed."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.cas import explain_cas
    from codegraph.extractor import load_graph0
    from codegraph.workflow import load_workflow

    graph0 = load_graph0(root)
    workflow = load_workflow(root)
    info = explain_cas(node_id, graph0, workflow)

    if json_output:
        click.echo(_json.dumps(info.to_dict(), indent=2))
    else:
        click.echo(f"Node: {info.node_id}")
        click.echo(f"Body hash:       {info.body_hash[:16]}\u2026" if info.body_hash else "Body hash: N/A")
        click.echo(f"Dependency hash: {info.dependency_hash[:16]}\u2026" if info.dependency_hash else "Dependency hash: not computed")
        click.echo(f"Direct callees:  {len(info.direct_callees)}")
        click.echo(f"Direct callers:  {len(info.direct_callers)}")
        click.echo(f"Would invalidate: {info.transitive_dependents_count} node(s)")
        if info.would_invalidate:
            for dep in info.would_invalidate[:10]:
                click.echo(f"  \u2192 {dep}")


# ── Registration ──────────────────────────────────────────────────────

COMMANDS = [
    archi_test_cmd,
    test_impact_cmd,
    simulate_cmd,
    api_link_cmd,
    pre_commit_cmd,
    runtime_graph_cmd,
]

GROUPS = [
    branch_group,
    lifecycle_group,
    cas_group,
]
