"""codegraph.cli.architecture — Architecture CLI commands.

Commands: architect, arch-plan, arch-search, arch-simulate, arch-version,
architecture, compile, code-plan, viewer, arch-diff, arch-memory, enrich.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from codegraph.config import find_project_root, load_config
from codegraph.cli.core import handle_error, timed_command, EXIT_ERROR
from codegraph.services import ConfigService, GraphStore, IndexService


def _resolve_root(ctx: click.Context) -> Path:
    try:
        return ConfigService().find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)


# ── Architecture Advisor ──────────────────────────────────────────────
@click.command("architect")
@click.option("--json", "json_output", is_flag=True,
              help="Output advice as JSON.")
@click.option("--save", is_flag=True,
              help="Save advice to .codegraph/architecture/architecture_advice.json.")
@click.option("--god-module-threshold", type=int, default=30,
              help="Node count threshold for god module detection.")
@click.option("--fan-in-threshold", type=int, default=20,
              help="Fan-in threshold for high-coupling detection.")
@click.option("--fan-out-threshold", type=int, default=15,
              help="Fan-out threshold for high-coupling detection.")
@click.pass_context
def architect_cmd(
    ctx: click.Context,
    json_output: bool,
    save: bool,
    god_module_threshold: int,
    fan_in_threshold: int,
    fan_out_threshold: int,
) -> None:
    """Run architecture advisor — detect smells and suggest improvements."""
    from codegraph.architecture_advisor import advise_architecture

    root = _resolve_root(ctx)
    store = GraphStore(root)
    index = IndexService(root)
    graph0 = store.load_graph0()
    try:
        advice = advise_architecture(
            graph0, index,
            project_root=root,
            god_module_threshold=god_module_threshold,
            fan_in_threshold=fan_in_threshold,
            fan_out_threshold=fan_out_threshold,
        )
    finally:
        index.close()

    if save:
        path = advice.save(root)
        click.echo(f"Advice saved: {path}")

    if json_output:
        import json as _json
        click.echo(_json.dumps(advice.to_dict(), indent=2))
    else:
        click.echo(advice.format())


# ── Architecture Definition ──────────────────────────────────────────
@click.command("architecture")
@click.option("--init", "do_init", is_flag=True,
              help="Initialize architecture from detected subsystems.")
@click.option("--validate", "do_validate", is_flag=True,
              help="Validate architecture against actual code.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def architecture_cmd(ctx: click.Context, do_init: bool, do_validate: bool,
                     json_output: bool) -> None:
    """Manage architecture definition (system.json)."""
    import json as _json

    from codegraph.arch_schema import SystemArchitecture, init_architecture

    root = _resolve_root(ctx)
    store = GraphStore(root)

    if do_init:
        graph0 = store.load_graph0()
        index = IndexService(root)
        try:
            arch = init_architecture(graph0, index, project_root=root)
        finally:
            index.close()
        arch.save(root)
        click.echo(f"Architecture initialized with {len(arch.subsystems)} subsystems.")
        return

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined. Use --init to create one.", err=True)
        sys.exit(EXIT_ERROR)

    if do_validate:
        graph0 = store.load_graph0()
        # Build list of actual modules from graph0
        actual_modules = list({n.file for n in graph0.nodes if n.file})
        issues: list[str] = []

        # Check each declared module exists
        for sub in arch.subsystems:
            for comp in sub.components:
                if comp.module and not (root / comp.module).exists():
                    issues.append(
                        f"[{sub.name}] Component '{comp.name}' "
                        f"module not found: {comp.module}"
                    )

        if issues:
            click.echo(f"Architecture validation: {len(issues)} issues")
            for issue in issues:
                click.echo(f"  ⚠ {issue}")
        else:
            click.echo("Architecture validation passed.")
        return

    # Default: show current architecture
    if json_output:
        click.echo(_json.dumps(arch.to_dict(), indent=2))
    else:
        click.echo(f"Architecture: {arch.name}")
        click.echo(f"  Subsystems: {len(arch.subsystems)}")
        click.echo(f"  Edges: {len(arch.edges)}")
        click.echo(f"  Constraints: {len(arch.constraints)}")
        for sub in arch.subsystems:
            n_comp = len(sub.components)
            click.echo(f"\n  [{sub.name}] — {n_comp} components")
            click.echo(f"    {sub.description}")
            for comp in sub.components:
                click.echo(f"    • {comp.name} → {comp.module}")


# ── Architecture Plan ─────────────────────────────────────────────────
@click.command("arch-plan")
@click.option("--output", "output_file", default=None,
              help="Save generated tasks to a file.")
@click.option("--agent-response", "agent_response", is_flag=True,
              help="Output as agent_response.json format.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def arch_plan_cmd(ctx: click.Context, output_file: str | None,
                  agent_response: bool, json_output: bool) -> None:
    """Generate tasks from architecture definition."""
    import json as _json

    from codegraph.arch_planner import plan_architecture, plan_to_agent_response
    from codegraph.arch_schema import SystemArchitecture

    root = _resolve_root(ctx)

    arch = SystemArchitecture.load(root)
    if arch is None:
        click.echo("No architecture defined. Use 'codegraph architecture --init' first.",
                    err=True)
        sys.exit(EXIT_ERROR)

    store = GraphStore(root)
    graph0 = store.load_graph0()
    index = IndexService(root)
    try:
        plan = plan_architecture(arch, graph0, index)
    finally:
        index.close()

    if agent_response:
        graph0_path = root / ".codegraph" / "graphs" / "graph0.json"
        graph_data = _json.loads(graph0_path.read_text(encoding="utf-8"))
        gv = graph_data.get("graph_version", 0)
        response = plan_to_agent_response(plan, gv)
        output = _json.dumps(response, indent=2, ensure_ascii=False)
        if output_file:
            Path(output_file).write_text(output, encoding="utf-8")
            click.echo(f"Agent response written to {output_file}")
        else:
            click.echo(output)
        return

    if output_file:
        Path(output_file).write_text(
            _json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        click.echo(f"Plan written to {output_file}")
    elif json_output:
        click.echo(_json.dumps(plan.to_dict(), indent=2))
    else:
        click.echo(plan.format())


# ── Architecture Viewer ───────────────────────────────────────────────
@click.command("viewer")
@click.option("--output", "output_file", default=None,
              help="Custom output path for HTML file.")
@click.pass_context
def viewer_cmd(ctx: click.Context, output_file: str | None) -> None:
    """Generate interactive HTML architecture dashboard."""
    from codegraph.annotator import load_graph1
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.arch_viewer import generate_viewer
    from codegraph.workflow import load_workflow

    root = _resolve_root(ctx)
    store = GraphStore(root)

    graph0 = store.load_graph0()
    graph1 = load_graph1(root)
    workflow = load_workflow(root)
    architecture = SystemArchitecture.load(root)

    out_path = Path(output_file) if output_file else None
    index = IndexService(root)
    try:
        result_path = generate_viewer(
            root, graph0, graph1, workflow, index,
            architecture=architecture, output_path=out_path,
        )
    finally:
        index.close()
    click.echo(f"Dashboard generated: {result_path}")


# ── Architecture Health ───────────────────────────────────────────────
@click.command("arch-health")
@click.option("--save", is_flag=True,
              help="Save report to .codegraph/architecture/architecture_health.json")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def arch_health_cmd(ctx: click.Context, save: bool, json_output: bool) -> None:
    """Compute architecture health metrics from canonical ArchitectureGraph."""
    import json as _json
    from codegraph.architecture_health import build_health_report

    root = _resolve_root(ctx)
    report = build_health_report(root)

    if save:
        path = report.save(root)
        click.echo(f"Saved architecture health report: {path}")

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        data = report.to_dict()
        click.echo("Architecture Health")
        click.echo(f"  Cycles: {data['cycle_count']}")
        click.echo(f"  Layer violations: {data['layer_violation_count']}")
        click.echo(f"  Orphan nodes: {data['orphan_nodes']}")
        click.echo(f"  Unused services: {data['unused_services']}")
        click.echo(f"  Fan-in entropy: {data['fan_in_entropy']:.4f}")
        click.echo(f"  Fan-out variance: {data['fan_out_variance']:.4f}")
        click.echo(f"  Module complexity variance: {data['module_complexity_variance']:.4f}")
        click.echo(f"  Fan-in buckets: {len(data['fan_in_distribution'])}")
        click.echo(f"  Fan-out buckets: {len(data['fan_out_distribution'])}")


# ── Compile Intent → Architecture ─────────────────────────────────────
@click.command("compile")
@click.argument("intent")
@click.option("--apply", "do_apply", is_flag=True,
              help="Apply plan to architecture (modify system.json).")
@click.option("--save", is_flag=True, help="Save plan to disk.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def compile_cmd(ctx: click.Context, intent: str, do_apply: bool,
                save: bool, json_output: bool) -> None:
    """Compile an architecture intent into a concrete plan."""
    import json as _json
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_compiler import (
        apply_plan, compile_intent, plan_to_target_workflow,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined. Run: codegraph architecture --init",
                    err=True)
        sys.exit(EXIT_ERROR)

    plan = compile_intent(intent, arch)
    if json_output:
        click.echo(_json.dumps(plan.to_dict(), indent=2))
    else:
        click.echo(plan.format())

    if save:
        plan.save(root)
        click.echo(f"\nPlan saved to .codegraph/planning/")

    if do_apply:
        arch = apply_plan(plan, arch)
        arch.save(root)
        click.echo("\nApplied plan to architecture.")
        target = plan_to_target_workflow(plan)
        target.save(root)
        click.echo("Updated target workflow.")


# ── Code Plan ─────────────────────────────────────────────────────────
@click.command("code-plan")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True, help="Save plan to disk.")
@click.pass_context
def code_plan_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Generate a code implementation plan from architecture delta."""
    import json as _json
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.code_planner import generate_plan, validate_plan
    from codegraph.target_architecture import ArchitectureDelta

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    delta_path = root / ".codegraph" / "planning" / "delta.json"
    if not delta_path.exists():
        click.echo("No architecture delta found. Run: codegraph evolve", err=True)
        sys.exit(EXIT_ERROR)

    delta_data = _json.loads(delta_path.read_text(encoding="utf-8"))
    delta = ArchitectureDelta(
        missing_edges=delta_data.get("missing_edges", []),
        extra_edges=delta_data.get("extra_edges", []),
        missing_nodes=delta_data.get("missing_nodes", []),
        extra_nodes=delta_data.get("extra_nodes", []),
    )

    plan = generate_plan(delta, arch)
    violations = validate_plan(plan, arch)
    if violations:
        for v in violations:
            plan.warnings.append(v)

    if json_output:
        click.echo(_json.dumps(plan.to_dict(), indent=2))
    else:
        click.echo(plan.format())

    if save:
        plan.save(root)
        click.echo(f"\nCode plan saved.")


# ── Architecture Diff ─────────────────────────────────────────────────
@click.command("arch-diff")
@click.option("--old", "old_label", default=None,
              help="Label for the old snapshot (default: saved)")
@click.option("--new", "new_label", default=None,
              help="Label for the new snapshot (default: current)")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def arch_diff_cmd(ctx: click.Context, old_label: str | None,
                  new_label: str | None, json_output: bool) -> None:
    """Compare architecture snapshots to detect drift."""
    import json as _json

    from codegraph.arch_diff import compare_architectures
    from codegraph.arch_schema import SystemArchitecture

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    current = SystemArchitecture.load(root)
    if not current:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    # Load saved architecture for comparison
    saved_path = root / ".codegraph" / "architecture" / "system_saved.json"
    if saved_path.exists():
        import json as _json2
        saved_data = _json2.loads(saved_path.read_text(encoding="utf-8"))
        saved = SystemArchitecture.from_dict(saved_data)
    else:
        # Compare against self (no changes)
        saved = current

    result = compare_architectures(
        saved, current,
        old_label=old_label or "saved",
        new_label=new_label or "current",
    )

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format())


# ── Architecture Memory ───────────────────────────────────────────────
@click.command("arch-memory")
@click.option("--decisions", is_flag=True, help="Show architecture decisions.")
@click.option("--experiments", is_flag=True, help="Show experiment results.")
@click.option("--simulations", is_flag=True, help="Show simulation recordings.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def arch_memory_cmd(ctx: click.Context, decisions: bool, experiments: bool,
                    simulations: bool, json_output: bool) -> None:
    """Query architecture memory — decisions, experiments, simulations."""
    import json as _json
    from codegraph.architecture_memory import (
        load_decisions, load_experiments, load_simulations,
        format_decisions, format_experiments, format_simulations,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if decisions or (not experiments and not simulations):
        data = load_decisions(root)
        if json_output:
            click.echo(_json.dumps(data, indent=2))
        else:
            click.echo(format_decisions(data))

    if experiments:
        data = load_experiments(root)
        if json_output:
            click.echo(_json.dumps(data, indent=2))
        else:
            click.echo(format_experiments(data))

    if simulations:
        data = load_simulations(root)
        if json_output:
            click.echo(_json.dumps(data, indent=2))
        else:
            click.echo(format_simulations(data))


# ── Workflow Intent Enrichment ────────────────────────────────────────
@click.command("enrich")
@click.pass_context
def enrich_cmd(ctx: click.Context) -> None:
    """Enrich workflow edges with intent annotations from graph1."""
    from codegraph.annotator import load_graph1
    from codegraph.architecture_advisor import save_enriched_workflow
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    workflow = load_workflow(root)
    graph1 = load_graph1(root)
    path = save_enriched_workflow(workflow, graph1, root)
    click.echo(f"Enriched workflow saved: {path}")


# ── Multi-Candidate Architecture Search ───────────────────────────────
@click.command("arch-search")
@click.option("--max-candidates", type=int, default=5,
              help="Maximum number of candidates to generate (default: 5).")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save results to .codegraph/planning/arch_search.json.")
@click.pass_context
def arch_search_cmd(ctx: click.Context, max_candidates: int,
                    json_output: bool, save: bool) -> None:
    """Run multi-candidate architecture search."""
    import json as _json
    from codegraph.arch_search import run_arch_search

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    result = run_arch_search(
        root, max_candidates=max_candidates, save_results=save,
    )

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format())


# ── Architecture Simulator ────────────────────────────────────────────
@click.command("arch-simulate")
@click.argument("subsystem_name")
@click.option("--depends-on", "deps", multiple=True,
              help="Dependencies for the new subsystem (repeatable).")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save simulation result.")
@click.pass_context
def arch_simulate_cmd(ctx: click.Context, subsystem_name: str,
                      deps: tuple, json_output: bool, save: bool) -> None:
    """Simulate adding a subsystem and predict impact."""
    import json as _json
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_simulator import simulate_subsystem_addition

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    result = simulate_subsystem_addition(
        subsystem_name, list(deps), arch,
    )
    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format())

    if save:
        planning_dir = root / ".codegraph" / "planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        out_path = planning_dir / "simulation_result.json"
        out_path.write_text(
            _json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        click.echo(f"Simulation saved to {out_path}")


# ── Architecture Versioning ───────────────────────────────────────────
@click.command("arch-version")
@click.option("--save", "do_save", is_flag=True,
              help="Save current architecture as a new version.")
@click.option("--list", "do_list", is_flag=True,
              help="List all architecture versions.")
@click.option("--diff", "diff_versions_opt", nargs=2, type=int, default=None,
              help="Diff two versions: --diff FROM TO")
@click.option("--rollback", type=int, default=None,
              help="Rollback architecture to a specific version.")
@click.option("--description", "-d", default="",
              help="Version description (for --save).")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def arch_version_cmd(ctx: click.Context, do_save: bool, do_list: bool,
                     diff_versions_opt: tuple | None, rollback: int | None,
                     description: str, json_output: bool) -> None:
    """Architecture version management."""
    import json as _json
    from codegraph.arch_versioning import (
        save_version, list_versions, diff_versions,
        rollback_version, format_version_history,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if do_save:
        version = save_version(root, description=description)
        click.echo(f"Saved architecture version v{version.version}")
        return

    if do_list:
        versions = list_versions(root)
        if json_output:
            click.echo(_json.dumps([v.to_dict() for v in versions], indent=2))
        else:
            click.echo(format_version_history(versions))
        return

    if diff_versions_opt:
        from_v, to_v = diff_versions_opt
        result = diff_versions(root, from_v, to_v)
        if result is None:
            click.echo("One or both versions not found.", err=True)
            sys.exit(EXIT_ERROR)
        if json_output:
            click.echo(_json.dumps(result.to_dict(), indent=2))
        else:
            click.echo(result.format())
        return

    if rollback is not None:
        if rollback_version(root, rollback):
            click.echo(f"Rolled back architecture to v{rollback}")
        else:
            click.echo(f"Version v{rollback} not found.", err=True)
            sys.exit(EXIT_ERROR)
        return

    versions = list_versions(root)
    if json_output:
        click.echo(_json.dumps([v.to_dict() for v in versions], indent=2))
    else:
        click.echo(format_version_history(versions))


# ── Graph Partitions ──────────────────────────────────────────────────
@click.command("partitions")
@click.option("--list", "do_list", is_flag=True, help="List known partition files.")
@click.option("--rebuild", is_flag=True, help="Rebuild partitions from current ArchitectureGraph.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def partitions_cmd(ctx: click.Context, do_list: bool, rebuild: bool, json_output: bool) -> None:
    """Inspect or rebuild graph partitions used for large-scale acceleration."""
    import json as _json
    from codegraph.architecture_graph import ArchitectureGraph
    from codegraph.graph_partitioning import (
        build_partitions,
        list_partition_files,
        load_partitions,
        save_partitions,
    )

    root = _resolve_root(ctx)

    if rebuild:
        graph = ArchitectureGraph.load(root)
        partitions = build_partitions(graph)
        save_partitions(root, partitions)
        if json_output:
            click.echo(_json.dumps(partitions.to_dict(), indent=2))
        else:
            click.echo(f"Rebuilt {len(partitions.partitions)} partitions.")
        return

    if do_list:
        files = list_partition_files(root)
        if json_output:
            click.echo(_json.dumps({"files": files, "count": len(files)}, indent=2))
        else:
            click.echo(f"Partition files: {len(files)}")
            for name in files:
                click.echo(f"  - {name}")
        return

    partitions = load_partitions(root)
    if partitions is None:
        click.echo("No partitions found. Run: codegraph partitions --rebuild")
        return

    if json_output:
        click.echo(_json.dumps(partitions.to_dict(), indent=2))
    else:
        click.echo(f"Partitions: {len(partitions.partitions)}")
        for pid, part in sorted(partitions.partitions.items()):
            click.echo(
                f"  {pid}: nodes={len(part.nodes)} "
                f"boundary={len(part.boundary_nodes)} edges={len(part.internal_edges)}"
            )


# ── Subsystem Cache ───────────────────────────────────────────────────
@click.command("subsystem-cache")
@click.option("--clear", "do_clear", is_flag=True, help="Clear persisted subsystem cache.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def subsystem_cache_cmd(ctx: click.Context, do_clear: bool, json_output: bool) -> None:
    """Inspect or clear subsystem cache entries."""
    import json as _json
    from codegraph.subsystem_cache import SubsystemCache, cache_status

    root = _resolve_root(ctx)
    cache = SubsystemCache(root)

    if do_clear:
        removed = cache.clear()
        if json_output:
            click.echo(_json.dumps({"cleared": removed}, indent=2))
        else:
            click.echo(f"Cleared {removed} subsystem cache entries.")
        return

    status = cache_status(root)
    if json_output:
        click.echo(_json.dumps(status, indent=2))
    else:
        click.echo(f"Cache entries: {status['entries']}")
        click.echo(f"Cache dir: {status['cache_dir']}")
        for name in status.get("files", [])[:20]:
            click.echo(f"  - {name}")


# ── Rebuild Partitions Task ───────────────────────────────────────────
@click.command("rebuild-partitions")
@click.pass_context
def rebuild_partitions_cmd(ctx: click.Context) -> None:
    """Recalculate graph partitions after major structural changes."""
    from codegraph.architecture_graph import ArchitectureGraph
    from codegraph.graph_partitioning import build_partitions, save_partitions

    root = _resolve_root(ctx)
    graph = ArchitectureGraph.load(root)
    partitions = build_partitions(graph)
    save_partitions(root, partitions)
    click.echo(f"Rebuilt {len(partitions.partitions)} partitions in .codegraph/partitions/")


# ── Registration ──────────────────────────────────────────────────────

COMMANDS = [
    architect_cmd,
    arch_health_cmd,
    architecture_cmd,
    arch_plan_cmd,
    viewer_cmd,
    compile_cmd,
    code_plan_cmd,
    arch_diff_cmd,
    arch_memory_cmd,
    enrich_cmd,
    arch_search_cmd,
    arch_simulate_cmd,
    arch_version_cmd,
    partitions_cmd,
    subsystem_cache_cmd,
    rebuild_partitions_cmd,
]
