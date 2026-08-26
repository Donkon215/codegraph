"""codegraph.cli.intelligence — Intelligence CLI commands.

Commands: evolution, evolve, memory-intel, metrics-snapshot,
copilot-context, health, multilevel, memory, subsystems, metrics, refactor,
path, visualize, context, focus, hotspots, scope, arch-context, copilot-loop,
scenario, decide, server, feedback, arch-diff.
Groups: semantic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from codegraph.config import find_project_root
from codegraph.cli.core import handle_error, timed_command, EXIT_ERROR, EXIT_VALIDATION_FAIL


# ── Evolution Engine ──────────────────────────────────────────────────
@click.command("evolution")
@click.option("--max-cycles", type=int, default=3,
              help="Maximum evolution cycles (default: 3).")
@click.option("--dry-run", is_flag=True,
              help="Simulate evolution without recording.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save report to .codegraph/planning/evolution_report.json.")
@click.pass_context
def evolution_cmd(ctx: click.Context, max_cycles: int, dry_run: bool,
                  json_output: bool, save: bool) -> None:
    """Run the architecture evolution engine.

    Closed-loop pipeline: detect → memory → mutate → policy →
    simulate → select → record.
    """
    import json as _json
    from codegraph.arch_evolution import (
        EvolutionReport, run_evolution, save_evolution_report,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    results = run_evolution(root, max_cycles=max_cycles, dry_run=dry_run)
    report = EvolutionReport.from_results(results)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if save:
        path = save_evolution_report(root, report)
        click.echo(f"Evolution report saved to {path}")


# ── Evolve (legacy advisor loop) ──────────────────────────────────────
@click.command("evolve")
@click.option("--max-cycles", type=int, default=3,
              help="Maximum repair cycles before stopping.")
@click.option("--dry-run", is_flag=True,
              help="Show what would be done without modifying files.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
@timed_command
def evolve_cmd(ctx: click.Context, max_cycles: int, dry_run: bool,
               json_output: bool) -> None:
    """Run the full architecture evolution loop.

    Sequence: advisor → target delta → tasks → (optional apply).
    """
    import json as _json

    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_advisor import advise_architecture
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore
    from codegraph.target_architecture import (
        TargetWorkflow,
        compute_architecture_delta,
        delta_to_tasks,
        generate_target_from_architecture,
    )
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    workflow = load_workflow(root)
    arch = SystemArchitecture.load(root)

    if not arch:
        click.echo("No architecture defined. Use 'codegraph architecture --init'.",
                    err=True)
        sys.exit(EXIT_ERROR)

    with IndexStore(root) as index:
        advice = advise_architecture(graph0, index, project_root=root)

    click.echo(f"=== Architecture Evolution ===")
    click.echo(f"Advisor findings: {len(advice.smells)} smells")
    for smell in advice.smells[:5]:
        click.echo(f"  - [{smell.severity}] {smell.smell_type}: {smell.entity}")

    target = generate_target_from_architecture(arch, workflow)
    click.echo(f"\nTarget workflow: {len(target.edges)} edges, {len(target.nodes)} nodes")

    current_nodes = list(graph0.nodes.keys()) if hasattr(graph0, 'nodes') else []
    delta = compute_architecture_delta(target, workflow, current_nodes)

    if not delta.has_changes:
        click.echo("\nArchitecture is converged. No changes needed.")
        return

    click.echo(f"\nDelta: {delta.total_changes} changes")
    click.echo(delta.format())

    if dry_run:
        click.echo("\n[dry-run] No changes applied.")
        return

    gv_path = root / ".codegraph" / "graphs" / "graph0.json"
    if gv_path.exists():
        gv_data = _json.loads(gv_path.read_text(encoding="utf-8"))
        gv = gv_data.get("graph_version", 0)
    else:
        gv = 0

    response = delta_to_tasks(delta, gv)
    delta.save(root)

    if json_output:
        click.echo(_json.dumps(response, indent=2))
    else:
        n_repairs = len(response.get("repairs", []))
        click.echo(f"\nGenerated {n_repairs} repair tasks.")
        click.echo("Use 'codegraph apply agent_response.json' to execute.")

    resp_path = root / "agent_response.json"
    resp_path.write_text(
        _json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    click.echo(f"Agent response saved: {resp_path}")


# ── Memory Intelligence ──────────────────────────────────────────────
@click.command("memory-intel")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True,
              help="Save strategy scores to .codegraph/memory/.")
@click.pass_context
def memory_intel_cmd(ctx: click.Context, json_output: bool,
                     save: bool) -> None:
    """Analyze architecture memory for patterns and strategy effectiveness."""
    import json as _json
    from codegraph.arch_memory_intelligence import (
        analyze_memory, save_strategy_scores,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    report = analyze_memory(root)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if save:
        path = save_strategy_scores(root, report.strategy_scores)
        click.echo(f"Strategy scores saved to {path}")


# ── Metrics Snapshot ──────────────────────────────────────────────────
@click.command("metrics-snapshot")
@click.option("--trigger", default="manual",
              help="What triggered this snapshot (build, refactor, evolution).")
@click.pass_context
def metrics_snapshot_cmd(ctx: click.Context, trigger: str) -> None:
    """Record a metrics snapshot from current architecture state."""
    from codegraph.arch_memory_intelligence import record_metrics_snapshot
    from codegraph.architecture_advisor import advise_architecture
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        advice = advise_architecture(graph0, index)

    snap = record_metrics_snapshot(
        root,
        score=advice.score,
        grade=advice.grade,
        modularity=getattr(advice, "modularity", 0.0),
        coupling=getattr(advice, "coupling", 0.0),
        cycles=len([s for s in advice.smells
                    if s.smell_type == "cycle"]),
        god_modules=len([s for s in advice.smells
                         if s.smell_type == "god_module"]),
        trigger=trigger,
    )
    click.echo(f"Recorded: {snap.grade} {snap.score:.3f} ({trigger})")


# ── Copilot Context ──────────────────────────────────────────────────
@click.command("copilot-context")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True, help="Save context to disk.")
@click.pass_context
def copilot_context_cmd(ctx: click.Context, json_output: bool,
                        save: bool) -> None:
    """Generate comprehensive context for Copilot decision-making."""
    import json as _json
    from codegraph.copilot_context import build_copilot_context

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    context = build_copilot_context(root)
    if json_output:
        click.echo(_json.dumps(context.to_dict(), indent=2))
    else:
        click.echo(context.format())

    if save:
        context.save(root)
        click.echo(f"\nCopilot context saved.")


# ── Multilevel Analysis ──────────────────────────────────────────────
@click.command("multilevel")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", is_flag=True,
              help="Save report to .codegraph/analysis/multilevel.json.")
@click.pass_context
@timed_command
def multilevel_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Run multi-level architecture analysis (function → module → subsystem)."""
    import json as _json

    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore
    from codegraph.multilevel import analyze_multilevel

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        report = analyze_multilevel(graph0, index)

    if save:
        out_dir = root / ".codegraph" / "analysis"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "multilevel.json"
        out_path.write_text(
            _json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        click.echo(f"Report saved: {out_path}")

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Memory ────────────────────────────────────────────────────────────
@click.command("memory")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--note", default=None, help="Add a note to architecture memory.")
@click.pass_context
def memory_cmd(ctx: click.Context, json_output: bool, note: str | None) -> None:
    """View or add architecture memory notes."""
    import json as _json
    from codegraph.agent_memory import load_memory, add_note, format_memory

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if note:
        add_note(root, note)
        click.echo("Note added to architecture memory.")
        return

    mem = load_memory(root)
    if json_output:
        click.echo(_json.dumps(mem, indent=2))
    else:
        click.echo(format_memory(mem))


# ── Subsystems ────────────────────────────────────────────────────────
@click.command("subsystems")
@click.option("--resolution", type=float, default=1.0,
              help="Louvain resolution parameter.")
@click.option("--min-size", type=int, default=3,
              help="Minimum subsystem size to display.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
@timed_command
def subsystems_cmd(ctx: click.Context, resolution: float, min_size: int,
                   json_output: bool) -> None:
    """Detect subsystems using community detection."""
    import json as _json
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore
    from codegraph.subsystem import detect_subsystems

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        report = detect_subsystems(
            graph0, index, resolution=resolution, min_size=min_size,
        )

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Metrics ───────────────────────────────────────────────────────────
@click.command("metrics")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--node", default=None, help="Show metrics for a specific node.")
@click.option("--top", type=int, default=10, help="Top N nodes to show.")
@click.pass_context
@timed_command
def metrics_cmd(ctx: click.Context, json_output: bool, node: str | None,
                top: int) -> None:
    """Show graph metrics (fan-in, fan-out, centrality)."""
    import json as _json
    from codegraph.metrics import compute_metrics, format_metrics

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    report = compute_metrics(root, node_id=node, top_n=top)
    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(format_metrics(report))


# ── Refactor ──────────────────────────────────────────────────────────
@click.command("refactor")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--cycles", "show_cycles", is_flag=True,
              help="Detect dependency cycles.")
@click.option("--god-modules", "show_god", is_flag=True,
              help="Detect god modules.")
@click.pass_context
@timed_command
def refactor_cmd(ctx: click.Context, json_output: bool,
                 show_cycles: bool, show_god: bool) -> None:
    """Detect refactoring opportunities."""
    import json as _json
    from codegraph.refactor import (
        detect_cycles, find_god_modules, compute_coupling,
    )
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        if show_cycles or (not show_cycles and not show_god):
            cycles = detect_cycles(graph0, index)
            if json_output:
                click.echo(_json.dumps({"cycles": cycles}, indent=2))
            else:
                if cycles:
                    click.echo(f"Dependency Cycles ({len(cycles)}):")
                    for c in cycles:
                        click.echo(f"  → {' → '.join(c)}")
                else:
                    click.echo("No dependency cycles found.")

        if show_god or (not show_cycles and not show_god):
            gods = find_god_modules(graph0)
            if json_output:
                click.echo(_json.dumps({"god_modules": gods}, indent=2))
            else:
                if gods:
                    click.echo(f"\nGod Modules ({len(gods)}):")
                    for g in gods:
                        click.echo(f"  {g['module']}: {g['node_count']} nodes")
                else:
                    click.echo("No god modules found.")


# ── Semantic commands ────────────────────────────────────────────────

@click.group("semantic")
def semantic_group() -> None:
    """Manage the Graph_2 semantic behavior layer."""


@semantic_group.command("build")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def semantic_build(ctx: click.Context, json_output: bool) -> None:
    """Extract semantic behaviors from all project code."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.extractor import load_graph0
    from codegraph.semantics import build_graph2, save_graph2

    graph0 = load_graph0(root)
    graph2 = build_graph2(graph0, root)
    save_graph2(graph2, root)

    if json_output:
        summary = graph2.get_behavior_summary()
        click.echo(_json.dumps(summary, indent=2))
    else:
        click.echo(f"Extracted semantics for {len(graph2.nodes)} nodes.")
        summary = graph2.get_behavior_summary()
        if summary.get("action_types"):
            click.echo("  Actions: " + ", ".join(
                f"{k}={v}" for k, v in sorted(summary["action_types"].items())
            ))
        if summary.get("side_effect_types"):
            click.echo("  Side effects: " + ", ".join(
                f"{k}={v}" for k, v in sorted(summary["side_effect_types"].items())
            ))


@semantic_group.command("show")
@click.argument("node_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def semantic_show(ctx: click.Context, node_id: str, json_output: bool) -> None:
    """Show semantic behavior for a specific node."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.semantics import load_graph2

    graph2 = load_graph2(root)
    node = graph2.get_node(node_id)

    if node is None:
        click.echo(f"No semantic data for node: {node_id}", err=True)
        sys.exit(EXIT_ERROR)

    if json_output:
        click.echo(_json.dumps(node.to_dict(), indent=2))
    else:
        click.echo(f"Node: {node.id}")
        if node.actions:
            click.echo("  Actions:")
            for a in node.actions:
                click.echo(f"    - {a.verb} {a.object} ({a.action_type.value})")
        if node.guards:
            click.echo("  Guards:")
            for g in node.guards:
                click.echo(f"    - {g.condition}" + (f" → raises {g.raises}" if g.raises else ""))
        if node.side_effects:
            click.echo("  Side effects:")
            for se in node.side_effects:
                click.echo(f"    - {se.effect_type.value}: {se.target or se.description}")
        if node.data_flow:
            click.echo(f"  Inputs:  {', '.join(node.data_flow.inputs)}")
            click.echo(f"  Outputs: {', '.join(node.data_flow.outputs)}")
        if node.domain_tags:
            click.echo(f"  Domain tags: {', '.join(node.domain_tags)}")
        click.echo(f"  Confidence: {node.confidence:.0%}")


@semantic_group.command("summary")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def semantic_summary(ctx: click.Context, json_output: bool) -> None:
    """Show behavior summary statistics."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.semantics import load_graph2

    graph2 = load_graph2(root)
    summary = graph2.get_behavior_summary()

    if json_output:
        click.echo(_json.dumps(summary, indent=2))
    else:
        click.echo(f"Semantic nodes: {summary['total_nodes']}")
        if summary.get("action_types"):
            click.echo("\nAction types:")
            for k, v in sorted(summary["action_types"].items(), key=lambda x: -x[1]):
                click.echo(f"  {k}: {v}")
        if summary.get("side_effect_types"):
            click.echo("\nSide effect types:")
            for k, v in sorted(summary["side_effect_types"].items(), key=lambda x: -x[1]):
                click.echo(f"  {k}: {v}")
        if summary.get("domain_tags"):
            click.echo("\nDomain tags:")
            for k, v in sorted(summary["domain_tags"].items(), key=lambda x: -x[1]):
                click.echo(f"  {k}: {v}")


@semantic_group.command("check")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def semantic_check(ctx: click.Context, json_output: bool) -> None:
    """Run semantic policy checks (DB writes without guards, etc.)."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    from codegraph.extractor import load_graph0
    from codegraph.workflow import load_workflow
    from codegraph.semantics import load_graph2, evaluate_semantic_rules_impl

    graph0 = load_graph0(root)
    workflow = load_workflow(root)
    graph2 = load_graph2(root)

    violations = evaluate_semantic_rules_impl(graph2, graph0, workflow)

    if json_output:
        click.echo(_json.dumps(violations, indent=2))
    elif not violations:
        click.echo("No semantic policy violations found.")
    else:
        click.echo(f"{len(violations)} semantic violation(s):")
        for v in violations:
            sev = v.get("severity", "info")
            click.echo(f"  [{sev}] {v.get('rule', '?')}: {v.get('message', '')}")


# ── Path query ────────────────────────────────────────────────────────

@click.command("path")
@click.argument("expression")
@click.option("--max-depth", type=int, default=20, help="Maximum path depth.")
@click.option("--max-paths", type=int, default=10, help="Maximum paths to find.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--forbidden", is_flag=True, help="Check as forbidden path (violation if path exists).")
@click.pass_context
def path_cmd(ctx: click.Context, expression: str, max_depth: int,
             max_paths: int, json_output: bool, forbidden: bool) -> None:
    """Query paths between node patterns (e.g. 'api/* -> database/*')."""
    import json as _json
    from codegraph.path_query import find_pattern_paths, check_forbidden_path
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    if " -> " not in expression:
        click.echo("Error: Expression must be 'source_pattern -> target_pattern'", err=True)
        sys.exit(EXIT_ERROR)

    parts = expression.split(" -> ", 1)
    source_pat = parts[0].strip()
    target_pat = parts[1].strip()

    with IndexStore(root) as index:
        if forbidden:
            result = check_forbidden_path(source_pat, target_pat, index, max_depth=max_depth)
        else:
            result = find_pattern_paths(source_pat, target_pat, index,
                                        max_depth=max_depth, max_paths=max_paths)

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format())
        if forbidden and result.violation:
            click.echo(click.style("VIOLATION: Forbidden path exists!", fg="red"))
            sys.exit(EXIT_VALIDATION_FAIL)


# ── Visualize ─────────────────────────────────────────────────────────

@click.command("visualize")
@click.option("--format", "fmt", default="html",
              type=click.Choice(["json", "mermaid", "html"]),
              help="Output format.")
@click.option("--output", "-o", default=None, type=click.Path(),
              help="Output file path.")
@click.option("--filter", "filter_file", default=None,
              help="Filter to nodes from matching files (glob).")
@click.option("--max-nodes", type=int, default=300,
              help="Maximum number of nodes to include.")
@click.pass_context
def visualize_cmd(ctx: click.Context, fmt: str, output: str | None,
                  filter_file: str | None, max_nodes: int) -> None:
    """Export the graph for visualization."""
    from codegraph.visualization import save_visualization, export_mermaid, export_html_report, build_vis_graph
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    workflow = load_workflow(root)

    if output:
        out_path = Path(output).resolve()
        save_visualization(graph0, graph1, workflow, out_path,
                           fmt=fmt, filter_file=filter_file, max_nodes=max_nodes)
        click.echo(f"Visualization saved to {out_path}")
    else:
        if fmt == "json":
            vis = build_vis_graph(graph0, graph1, workflow,
                                  filter_file=filter_file, max_nodes=max_nodes)
            click.echo(vis.to_json())
        elif fmt == "mermaid":
            content = export_mermaid(graph0, graph1, workflow,
                                    filter_file=filter_file, max_nodes=max_nodes)
            click.echo(content)
        elif fmt == "html":
            content = export_html_report(graph0, graph1, workflow,
                                         filter_file=filter_file, max_nodes=max_nodes)
            click.echo(content)


# ── LLM Context Builder ───────────────────────────────────────────────

@click.command("context")
@click.argument("node_ids", nargs=-1, required=True)
@click.option("--depth", type=int, default=2,
              help="BFS depth for expanding context.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def context_cmd(ctx: click.Context, node_ids: tuple[str, ...], depth: int,
                json_output: bool) -> None:
    """Build LLM prompt context for given node IDs."""
    import json as _json

    from codegraph.annotator import load_graph1
    from codegraph.context_builder import build_context
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    workflow = load_workflow(root)
    with IndexStore(root) as index:
        prompt_ctx = build_context(list(node_ids), graph0, graph1, workflow,
                                   index, depth=depth)

    if json_output:
        click.echo(_json.dumps(prompt_ctx.to_dict(), indent=2))
    else:
        click.echo(prompt_ctx.to_prompt())
        click.echo(f"\n--- ~{prompt_ctx.token_estimate()} tokens ---")


# ── Focus — Precision Context for a File/Node ────────────────────────

@click.command("focus")
@click.argument("target")
@click.option("--depth", type=int, default=1,
              help="BFS expansion depth (default: 1).")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def focus_cmd(ctx: click.Context, target: str, depth: int,
              json_output: bool) -> None:
    """Get precise architecture context for a file or node.

    Fast, minimal context for Copilot's in-loop use. Answers:
    "What do I need to know about THIS area before making a change?"

    TARGET can be a file path, node ID, or subsystem name.

    Examples:
      codegraph focus codegraph/analyzer.py
      codegraph focus codegraph/index.py::build_index
      codegraph focus payment
    """
    import json as _json

    from codegraph.copilot_context_builder import focus_context

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    result = focus_context(root, target, depth=depth)

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format())


# ── Hotspots — What Needs Attention ──────────────────────────────────

@click.command("hotspots")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def hotspots_cmd(ctx: click.Context, json_output: bool) -> None:
    """Show architecture hotspots — areas that need attention most.

    Fast summary of what's changing, broken, and risky.
    Copilot uses this to prioritize actions.
    """
    import json as _json

    from codegraph.copilot_context_builder import hotspot_context

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    report = hotspot_context(root)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Scope — Subsystem-Scoped Architecture ────────────────────────────

@click.command("scope")
@click.argument("subsystem")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def scope_cmd(ctx: click.Context, subsystem: str, json_output: bool) -> None:
    """Get scoped architecture context for a subsystem.

    Returns the full architectural boundary for one subsystem:
    modules, edges, constraints, violations. Use when working within
    a subsystem to understand its boundaries.

    Example:
      codegraph scope extraction
      codegraph scope governance
    """
    import json as _json

    from codegraph.copilot_context_builder import scope_context

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    result = scope_context(root, subsystem)

    if json_output:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format())


# ── Copilot Loop — Full Cognition Cycle ──────────────────────────────

@click.command("copilot-loop")
@click.argument("target")
@click.option("--simulate", is_flag=True,
              help="Run architecture simulation step.")
@click.option("--save", is_flag=True,
              help="Persist decision to .codegraph/decisions/.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def copilot_loop_cmd(ctx: click.Context, target: str, simulate: bool,
                     save: bool, json_output: bool) -> None:
    """Run the full Copilot cognition loop for a target.

    Single entry point that replaces manual hotspots → focus → decide →
    simulate → score. The system chooses the tools — Copilot just calls this.

    TARGET can be a file path, node ID, or subsystem name.

    Examples:
      codegraph copilot-loop codegraph/analyzer.py
      codegraph copilot-loop codegraph/index.py --simulate
      codegraph copilot-loop extraction --save
    """
    import json as _json

    from codegraph.copilot_intelligence import copilot_loop

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    report = copilot_loop(root, target, simulate=simulate, save=save)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Scenario — Component Scenario Explosion ──────────────────────────

@click.command("scenario")
@click.option("--components", multiple=True,
              help="Specific components to analyze (repeatable).")
@click.option("--max-combinations", type=int, default=200,
              help="Cap on cross-product expansion (default: 200).")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def scenario_cmd(ctx: click.Context, components: tuple, max_combinations: int,
                 json_output: bool) -> None:
    """Generate component interaction scenarios.

    Explodes component-level changes into system-level scenarios via
    cross-product expansion. Shows interaction risk and failure propagation.

    Examples:
      codegraph scenario
      codegraph scenario --components codegraph/index.py
      codegraph scenario --components codegraph/index.py --components codegraph/analyzer.py
    """
    import json as _json

    from codegraph.copilot_intelligence import scenario_context

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    target_components = list(components) if components else None
    report = scenario_context(
        root,
        target_components=target_components,
        max_combinations=max_combinations,
    )

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Decide — Structured Architecture Decision ────────────────────────

@click.command("decide")
@click.argument("target")
@click.option("--action", "action_hint", default="",
              help="Hint about the planned action type.")
@click.option("--save", is_flag=True,
              help="Persist decision to .codegraph/decisions/.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def decide_cmd(ctx: click.Context, target: str, action_hint: str,
               save: bool, json_output: bool) -> None:
    """Get a structured architecture decision for a target.

    Analyzes the target, considers alternatives, and produces a decision
    with full reasoning trace. Explains WHY a fix is the right approach.

    Examples:
      codegraph decide codegraph/analyzer.py
      codegraph decide codegraph/index.py::build_index --save
      codegraph decide extraction --action split
    """
    import json as _json

    from codegraph.copilot_intelligence import decide

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    decision = decide(root, target, action_hint=action_hint)

    if save:
        path = decision.save(root)
        click.echo(f"Decision saved to {path}")

    if json_output:
        click.echo(_json.dumps(decision.to_dict(), indent=2))
    else:
        click.echo(decision.format())


# ── Reactive Server ───────────────────────────────────────────────────
@click.command("server")
@click.option("--interval", type=float, default=2.0,
              help="Polling interval in seconds (default: 2).")
@click.option("--simulate", is_flag=True,
              help="Run simulation on each change cycle.")
@click.option("--max-cycles", type=int, default=0,
              help="Stop after N cycles (0 = run forever).")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--quiet", is_flag=True, help="Suppress terminal output.")
@click.pass_context
def server_cmd(ctx: click.Context, interval: float, simulate: bool,
               max_cycles: int, json_output: bool, quiet: bool) -> None:
    """Start the reactive intelligence server.

    Watches for file changes and automatically runs architecture analysis,
    generates prompts, and writes feedback to .codegraph/feedback.md.

    Copilot reads feedback.md for architecture-aware editing.

    Examples:
      codegraph server
      codegraph server --interval 5 --simulate
      codegraph server --json --quiet
      codegraph server --max-cycles 10
    """
    from codegraph.reactive_server import ReactiveServer, ServerConfig

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    config = ServerConfig(
        interval=interval,
        json_mode=json_output,
        quiet=quiet,
        simulate=simulate,
    )
    server = ReactiveServer(root, config)
    server.run_loop(max_cycles=max_cycles)


@click.command("arch-context")
@click.argument("file_path")
@click.option("--save", is_flag=True,
              help="Write briefing to .codegraph/feedback.md.")
@click.option("--json", "json_output", is_flag=True, help="JSON output (includes full decision).")
@click.pass_context
def arch_context_cmd(ctx: click.Context, file_path: str, save: bool,
                     json_output: bool) -> None:
    """Compact architecture briefing for a file — read before editing.

    Outputs a 6-12 line card covering: layer, subsystem, fan-in/out,
    violations, smells, verdict, and the recommended next action.

    Use --save to write the briefing to .codegraph/feedback.md so
    Copilot picks it up automatically on the next read.

    Examples:
      codegraph arch-context codegraph/analyzer.py
      codegraph arch-context codegraph/index.py --save
      codegraph arch-context codegraph/extractor.py --json
    """
    import json as _json

    from codegraph.copilot_context_builder import (
        focus_context,
        hotspot_context,
        quick_edit_briefing,
        save_quick_briefing_to_feedback,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if json_output:
        from codegraph.copilot_intelligence import decide
        focus = focus_context(root, file_path, depth=1)
        hotspots = hotspot_context(root)
        decision = decide(root, file_path)
        output = {
            "file": file_path,
            "focus": focus.to_dict(),
            "system_status": hotspots.status_line,
            "decision": decision.to_dict(),
            "briefing": quick_edit_briefing(root, file_path),
        }
        click.echo(_json.dumps(output, indent=2))
        return

    briefing = quick_edit_briefing(root, file_path)
    click.echo(briefing)

    if save:
        path = save_quick_briefing_to_feedback(root, file_path)
        click.echo(f"\nBriefing written to {path}")


@click.command("feedback")
@click.argument("targets", nargs=-1)
@click.option("--simulate", is_flag=True,
              help="Include simulation in analysis.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def feedback_cmd(ctx: click.Context, targets: tuple, simulate: bool,
                 json_output: bool) -> None:
    """One-shot reactive feedback for specific files.

    Runs the intelligence loop on the given targets and generates prompts.
    If no targets given, auto-detects changed files via git.

    Examples:
      codegraph feedback codegraph/analyzer.py
      codegraph feedback codegraph/index.py codegraph/query.py --simulate
      codegraph feedback --json
    """
    import json as _json

    from codegraph.reactive_server import ReactiveServer, ServerConfig

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    config = ServerConfig(
        json_mode=json_output,
        quiet=False,
        simulate=simulate,
    )
    server = ReactiveServer(root, config)

    if targets:
        files = list(targets)
    else:
        # Auto-detect changed files via git
        try:
            from codegraph.incremental_graph_update import detect_changed_files
            files = detect_changed_files(root)
        except Exception:
            click.echo("No targets specified and git detection failed.", err=True)
            sys.exit(EXIT_ERROR)

    if not files:
        click.echo("No changed files detected.")
        return

    event = server.run_once(changed_files=files)

    if json_output:
        click.echo(_json.dumps(event.to_dict(), indent=2))
    elif not event.prompts:
        click.echo("No architecture issues found.")


@click.command("arch-diff")
@click.option("--ref", default=None,
              help="Compare against a named history snapshot label (default: previous entry).")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def arch_diff_cmd(ctx: click.Context, ref: str, json_output: bool) -> None:
    """Compare current architecture score against a saved snapshot.

    Loads current metrics from architecture_advice.json and violations.json,
    then diffs them against the previous (or named) entry in
    .codegraph/architecture/architecture_history.json.

    Examples:
      codegraph arch-diff
      codegraph arch-diff --ref pre-refactor
      codegraph arch-diff --json
    """
    import json as _json

    from codegraph.utils.json_cache import load_json_cached

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    # ── Load current state ────────────────────────────────────────────
    advice_path = root / ".codegraph" / "architecture" / "architecture_advice.json"
    violations_path = root / ".codegraph" / "analysis" / "violations.json"

    advice = load_json_cached(advice_path, {})
    violations = load_json_cached(violations_path, {})

    current = {
        "score": advice.get("score", 0.0),
        "grade": advice.get("grade", "?"),
        "violations": len(violations.get("violations", [])),
        "smells": len(advice.get("smells", [])),
        "cycles": sum(
            1 for s in advice.get("smells", []) if s.get("smell_type") == "cycle"
        ),
        "god_modules": sum(
            1 for s in advice.get("smells", []) if s.get("smell_type") == "god_module"
        ),
    }

    # ── Load baseline from history ────────────────────────────────────
    history_path = root / ".codegraph" / "architecture" / "architecture_history.json"
    history = load_json_cached(history_path, {})
    entries = history.get("entries", [])

    baseline_entry: dict = {}
    baseline_label = "previous"

    if ref:
        # Named lookup: check "label" key first, then fall back to index
        for entry in entries:
            if entry.get("label") == ref:
                baseline_entry = entry
                baseline_label = ref
                break
        if not baseline_entry:
            click.echo(
                f"No history snapshot found with label '{ref}'. "
                "Available: " + ", ".join(e.get("label", "?") for e in entries if e.get("label")),
                err=True,
            )
            sys.exit(EXIT_VALIDATION_FAIL)
    elif len(entries) >= 2:
        baseline_entry = entries[-2]
        baseline_label = baseline_entry.get("label", f"entry[{len(entries)-2}]")
    elif len(entries) == 1:
        baseline_entry = entries[0]
        baseline_label = baseline_entry.get("label", "entry[0]")
    else:
        click.echo("No history snapshots found. Run `codegraph analyze` first.", err=True)
        sys.exit(EXIT_VALIDATION_FAIL)

    baseline = {
        "score": baseline_entry.get("score", baseline_entry.get("coupling_index", 0.0)),
        "grade": baseline_entry.get("grade", "?"),
        "violations": baseline_entry.get("layer_violations", 0),
        "smells": baseline_entry.get("smells", 0),
        "cycles": baseline_entry.get("cycles_count", 0),
        "god_modules": baseline_entry.get("god_modules", 0),
    }

    # ── Compute delta ─────────────────────────────────────────────────
    def _delta(key: str) -> float:
        return current[key] - baseline[key]  # type: ignore[operator]

    def _sign(v: float) -> str:
        return "+" if v > 0 else ""

    score_delta = _delta("score")
    violations_delta = int(_delta("violations"))
    smells_delta = int(_delta("smells"))
    cycles_delta = int(_delta("cycles"))

    # ── Output ────────────────────────────────────────────────────────
    if json_output:
        click.echo(_json.dumps({
            "current": current,
            "baseline": {"label": baseline_label, **baseline},
            "delta": {
                "score": round(score_delta, 4),
                "violations": violations_delta,
                "smells": smells_delta,
                "cycles": cycles_delta,
                "god_modules": int(_delta("god_modules")),
            },
            "verdict": (
                "improved" if score_delta > 0.01
                else "regressed" if score_delta < -0.01
                else "unchanged"
            ),
        }, indent=2))
        return

    # Human-readable table
    def _row(label: str, cur: object, base: object, delta: float) -> str:
        d_str = f"{_sign(delta)}{delta:.2g}" if isinstance(delta, float) else f"{_sign(float(delta))}{int(delta)}"
        arrow = " (^)" if delta > 0 else " (v)" if delta < 0 else ""
        return f"  {label:<18} {str(cur):<10} {str(base):<10} {d_str}{arrow}"

    lines = [
        f"## Architecture Diff: current vs {baseline_label}",
        "",
        f"  {'Metric':<18} {'Current':<10} {'Baseline':<10} Delta",
        f"  {'-'*18} {'-'*10} {'-'*10} -----",
        _row("Score", f"{current['score']:.2f}", f"{baseline['score']:.2f}", score_delta),
        _row("Grade", current["grade"], baseline["grade"], 0.0),
        _row("Violations", current["violations"], baseline["violations"], float(violations_delta)),
        _row("Smells", current["smells"], baseline["smells"], float(smells_delta)),
        _row("Cycles", current["cycles"], baseline["cycles"], float(cycles_delta)),
        _row("God modules", current["god_modules"], baseline["god_modules"], float(_delta("god_modules"))),
        "",
    ]

    if score_delta > 0.01:
        lines.append("  [IMPROVED] Architecture improved since baseline.")
    elif score_delta < -0.01:
        lines.append("  [REGRESSED] Architecture regressed since baseline.")
        lines.append("  Run `codegraph hotspots --json` to find the problem areas.")
    else:
        lines.append("  [UNCHANGED] No significant score change.")

    click.echo("\n".join(lines))


# ── Registration ──────────────────────────────────────────────────────

COMMANDS = [
    evolution_cmd,
    evolve_cmd,
    memory_intel_cmd,
    metrics_snapshot_cmd,
    copilot_context_cmd,
    multilevel_cmd,
    memory_cmd,
    subsystems_cmd,
    metrics_cmd,
    refactor_cmd,
    path_cmd,
    visualize_cmd,
    context_cmd,
    focus_cmd,
    hotspots_cmd,
    scope_cmd,
    arch_context_cmd,
    copilot_loop_cmd,
    scenario_cmd,
    decide_cmd,
    server_cmd,
    feedback_cmd,
    arch_diff_cmd,
]

GROUPS = [
    semantic_group,
]
