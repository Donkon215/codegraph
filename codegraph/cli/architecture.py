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


def _canonical_change_simulation_plan(payload: object) -> list[dict[str, str]]:
    """Translate edge-only canonical changes to the simulator's plan input."""
    from codegraph.architecture_change import ArchitectureChange, OpType

    if not isinstance(payload, dict):
        raise ValueError("canonical change must be a JSON object")
    change = ArchitectureChange.from_dict(payload)
    change.validate()
    plan: list[dict[str, str]] = []
    for operation in change.operations:
        if operation.op not in (OpType.ADD_EDGE, OpType.REMOVE_EDGE):
            continue
        plan.append({"change": "add_edge" if operation.op == OpType.ADD_EDGE else "remove_edge",
                     "node": operation.source, "target": operation.target})
    return plan


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
@click.option("--change", "canonical_change", is_flag=True,
              help="Output as canonical ArchitectureChange JSON.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def arch_plan_cmd(ctx: click.Context, output_file: str | None,
                  agent_response: bool, canonical_change: bool, json_output: bool) -> None:
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

    if canonical_change:
        from codegraph.architecture_change_adapters import from_arch_plan

        output = from_arch_plan(plan).to_json()
        if output_file:
            Path(output_file).write_text(output, encoding="utf-8")
            click.echo(f"ArchitectureChange written to {output_file}")
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
@click.option("--change", "canonical_change", is_flag=True,
              help="Emit a canonical ArchitectureChange plan.")
@click.option("--output", "output_file", default=None,
              help="Write the plan JSON to this file.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def compile_cmd(ctx: click.Context, intent: str, do_apply: bool,
                save: bool, canonical_change: bool, output_file: str | None,
                json_output: bool) -> None:
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
    if canonical_change:
        if do_apply:
            click.echo("--change cannot be combined with --apply.", err=True)
            sys.exit(EXIT_ERROR)
        from codegraph.architecture_change_adapters import from_compiled_plan

        change_json = from_compiled_plan(plan).to_json()
        if output_file:
            Path(output_file).write_text(change_json, encoding="utf-8")
            click.echo(f"ArchitectureChange written to {output_file}")
        else:
            click.echo(change_json)
        return
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
    from codegraph.architecture_delta import ArchitectureDelta
    from codegraph.code_planner import generate_plan, validate_plan

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
    delta = ArchitectureDelta.from_legacy_target_dict(delta_data)

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
@click.argument("subsystem_name", required=False)
@click.option("--depends-on", "deps", multiple=True,
              help="Dependencies for the new subsystem (repeatable).")
@click.option("--plan", "plan_path", type=click.Path(exists=True, dir_okay=False), default=None,
              help="JSON list of {change, node, target} to simulate together, with a verdict.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save simulation result.")
@click.option("--proof", "record_proof", is_flag=True,
              help="Run the architecture proof gate and record its proof artifact (plan mode).")
@click.option("--revise-rejected", is_flag=True,
              help="Use per-change simulation feedback to remove individually rejected changes; review the returned revised_plan before implementation.")
@click.option("--save-prediction", is_flag=True,
              help="Save the isolated predicted graph as .codegraph/predicted_graph.json.")
@click.pass_context
def arch_simulate_cmd(ctx: click.Context, subsystem_name: str, deps: tuple,
                      plan_path: str | None, json_output: bool, save: bool,
                      record_proof: bool, revise_rejected: bool,
                      save_prediction: bool) -> None:
    """Simulate adding a subsystem and predict impact, or simulate a --plan."""
    import json as _json
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_simulator import simulate_changes, simulate_subsystem_addition

    # Preserve the historical subsystem-name form while accepting the natural
    # `arch-simulate plan.json` spelling for JSON plan files.
    if plan_path is None and subsystem_name and Path(subsystem_name).suffix.lower() == ".json":
        plan_path, subsystem_name = subsystem_name, None

    if bool(subsystem_name) == bool(plan_path):
        click.echo("Give either a subsystem name or --plan, not both or neither.", err=True)
        sys.exit(EXIT_ERROR)
    if record_proof and not plan_path:
        click.echo("--proof is only supported with a JSON plan.", err=True)
        sys.exit(EXIT_ERROR)
    if save_prediction and not plan_path:
        click.echo("--save-prediction requires a JSON plan.", err=True)
        sys.exit(EXIT_ERROR)
    if revise_rejected and not plan_path:
        click.echo("--revise-rejected requires a JSON plan.", err=True)
        sys.exit(EXIT_ERROR)

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if plan_path:
        if save:
            # Plan mode writes no .codegraph state; print the JSON instead.
            click.echo("--save is not supported with --plan (plan mode writes no state). Use --json.", err=True)
            sys.exit(EXIT_ERROR)
        try:
            plan = _json.loads(Path(plan_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            click.echo(f"Could not read plan: {exc}", err=True)
            sys.exit(EXIT_ERROR)
        canonical_change = None
        unscored_operations: list[str] = []
        if isinstance(plan, dict):
            try:
                from codegraph.architecture_change import (
                    ArchitectureChange, ArchitectureChangeValidationError, OpType,
                )

                canonical_change = ArchitectureChange.from_dict(plan)
                canonical_change.validate()
                plan = _canonical_change_simulation_plan(plan)
                unscored_operations = [
                    operation.op.value for operation in canonical_change.operations
                    if operation.op not in (OpType.ADD_EDGE, OpType.REMOVE_EDGE)
                ]
            except (ArchitectureChangeValidationError, ValueError, TypeError, KeyError) as exc:
                click.echo(f"Invalid ArchitectureChange plan: {exc}", err=True)
                sys.exit(EXIT_ERROR)
        if not isinstance(plan, list) or not all(isinstance(item, dict) for item in plan):
            click.echo("Plan must be a JSON list of {change, node, target} objects or a canonical ArchitectureChange object.", err=True)
            sys.exit(EXIT_ERROR)

        if revise_rejected:
            if canonical_change is not None or unscored_operations:
                click.echo("--revise-rejected currently supports edge-operation plan lists only.", err=True)
                sys.exit(EXIT_ERROR)
            from codegraph.architecture_simulator import revise_rejected_changes

            original_result = simulate_changes(root, plan)
            revised_plan, dropped_changes, revised_result = revise_rejected_changes(root, plan)
            result = dict(revised_result)
            result["revision"] = {
                "original_verdict": original_result.get("verdict"),
                "original_reasons": original_result.get("reasons", []),
                "dropped_changes": dropped_changes,
                "remaining_count": len(revised_plan),
            }
            result["revised_plan"] = revised_plan
            plan = revised_plan
            if result.get("unattributed_reject"):
                result["reasons"] = list(result.get("reasons", [])) + [
                    "The rejection could not be attributed to an individual change; no changes were removed."
                ]
        else:
            result = simulate_changes(root, plan)
        if unscored_operations:
            result["canonical_operations"] = unscored_operations
            result["status"] = "partially_simulated"
            result["simulated"] = False
            result["function_checks_available"] = False
            if result.get("verdict") != "REJECT":
                result["verdict"] = "REVIEW"
            result["reasons"].append(
                "ArchitectureChange contains operations outside the edge sandbox: "
                + ", ".join(unscored_operations)
            )
        if save_prediction:
            from codegraph.architecture_change import ArchitectureChange, ArchitectureOperation, OpType
            from codegraph.architecture_graph import ArchitectureGraph

            current = ArchitectureGraph.load(root)
            if canonical_change is not None:
                change = canonical_change
            else:
                operations = []
                for item in plan:
                    action, source, target = item["change"], item["node"], item["target"]
                    if action == "remove_edge":
                        operations.append(ArchitectureOperation(OpType.REMOVE_EDGE, source=source,
                                                                target=target, edge_type="call"))
                    elif action == "add_edge":
                        operations.append(ArchitectureOperation(OpType.ADD_EDGE, source=source,
                                                                target=target, edge_type="call"))
                    elif action == "rewire_edge":
                        for edge in current.edges:
                            if edge.get("source") == source and edge.get("edge_type", "call") == "call":
                                operations.append(ArchitectureOperation(
                                    OpType.REMOVE_EDGE, source=source, target=edge.get("target", ""), edge_type="call"))
                        operations.append(ArchitectureOperation(OpType.ADD_EDGE, source=source,
                                                                target=target, edge_type="call"))
                change = ArchitectureChange(operations=operations)
            predicted = ArchitectureGraph.from_planned(current, change)
            artifact_path = predicted.save_predicted(root)
            result["predicted_graph"] = str(artifact_path)
            from codegraph.architecture_detection import detect_layered_architecture
            from codegraph.architecture_health import compute_architecture_health
            from codegraph.architecture_scoring import compute_architecture_index

            layer_report = detect_layered_architecture(
                predicted.structure_graph, architecture_graph=predicted,
            )
            health_report = compute_architecture_health(predicted)
            score_report = compute_architecture_index(root, architecture_graph=predicted)
            result["predicted_checks"] = {
                "layer": layer_report,
                "health": health_report.to_dict(),
                "score": score_report.to_dict(),
            }
            baseline_layer_report = detect_layered_architecture(
                current.structure_graph, architecture_graph=current,
            )
            baseline_violations = {
                (item.get("source"), item.get("target"))
                for item in baseline_layer_report.get("violations", [])
            }
            new_layer_violations = [
                item for item in layer_report.get("violations", [])
                if (item.get("source"), item.get("target")) not in baseline_violations
            ]
            result["predicted_checks"]["new_layer_violations"] = new_layer_violations
            if new_layer_violations:
                result["verdict"] = "REJECT"
                result["reasons"].append(
                    f"Predicted graph introduces {len(new_layer_violations)} layer violation(s)"
                )
        if record_proof:
            from codegraph.architecture_proof import generate_proof
            from codegraph.architecture_memory import proposal_feedback, record_proposal_outcome

            delta = {
                "added_edges": [
                    {"source": item["node"], "target": item["target"]}
                    for item in plan if item["change"] == "add_edge"
                ],
                "removed_edges": [
                    {"source": item["node"], "target": item["target"]}
                    for item in plan if item["change"] == "remove_edge"
                ],
                "removed_nodes": [],
                "constraint_violations": [],
                "risk_estimate": "LOW",
                "total_changes": len(plan) + len(unscored_operations),
            }
            proof = generate_proof(root, delta=delta)
            proof.save(root)
            result["proof"] = proof.to_dict()
            if result.get("verdict") == "REJECT":
                proof_outcome = "rejected"
            elif result.get("verdict") != "ACCEPT":
                proof_outcome = "review"
            else:
                proof_outcome = {
                    "PROVEN_SAFE": "accepted",
                    "PROVEN_WARNING": "review",
                    "REJECTED": "rejected",
                }.get(proof.status, "untested")
            task_types = {
                "connect_call" if item["change"] in {"add_edge", "rewire_edge"}
                else "flag_violation"
                for item in plan
            }
            if canonical_change is not None:
                from codegraph.architecture_change import OpType

                for operation in canonical_change.operations:
                    if operation.op in (OpType.ADD_COMPONENT, OpType.ADD_SUBSYSTEM):
                        task_types.add("create_module")
                    elif operation.op == OpType.ADD_CONSTRAINT:
                        task_types.add("add_constraint")
            task_types = sorted(task_types)
            record_proposal_outcome(
                root,
                proposal_id=proof.proposal_id,
                outcome=proof_outcome,
                violation_count=len(proof.violations),
                task_types=task_types,
            )
            result["proposal_feedback"] = proposal_feedback(root)
            if proof.status == "REJECTED":
                result["verdict"] = "REJECT"
                result["reasons"].append("Architecture proof gate rejected the plan")
            elif proof.status == "PROVEN_WARNING":
                if result["verdict"] != "REJECT":
                    result["verdict"] = "REVIEW"
                result["reasons"].append("Architecture proof gate returned PROVEN_WARNING")
            elif proof.status != "PROVEN_SAFE":
                result["verdict"] = "REVIEW"
                result["reasons"].append(f"Architecture proof gate status: {proof.status}")
        if json_output:
            click.echo(_json.dumps(result, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Verdict: {result['verdict']}")
            for reason in result["reasons"]:
                click.echo(f"  - {reason}")
            click.echo(f"Note: {result['graph_note']}")
        return

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


@click.command("arch-reconcile")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def arch_reconcile_cmd(ctx: click.Context, json_output: bool) -> None:
    """Compare .codegraph/predicted_graph.json with the current rebuilt graph."""
    import json as _json
    from codegraph.architecture_reconcile import reconcile_project

    root = _resolve_root(ctx)
    try:
        report = reconcile_project(root)
    except (OSError, ValueError, _json.JSONDecodeError) as exc:
        click.echo(f"Could not reconcile predicted graph: {exc}", err=True)
        sys.exit(EXIT_ERROR)
    if json_output:
        click.echo(_json.dumps(report, indent=2, ensure_ascii=False))
    else:
        status = "MATCH" if report["matches"] else "DRIFT"
        click.echo(f"Predicted vs actual: {status}")
        for key in ("predicted_only_nodes", "actual_only_nodes", "predicted_only_edges",
                    "actual_only_edges", "predicted_only_constraints", "actual_only_constraints"):
            if report[key]:
                click.echo(f"{key}: {len(report[key])}")


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
    arch_reconcile_cmd,
    arch_version_cmd,
    partitions_cmd,
    subsystem_cache_cmd,
    rebuild_partitions_cmd,
]
