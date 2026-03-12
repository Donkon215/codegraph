"""codegraph.cli.intelligence — Intelligence CLI commands.

Commands: evolution, evolve, memory-intel, metrics-snapshot,
copilot-context, health, multilevel, memory, subsystems, metrics, refactor.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from codegraph.config import find_project_root
from codegraph.cli.core import handle_error, timed_command, EXIT_ERROR


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


# ── Health ────────────────────────────────────────────────────────────
@click.command("health")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", "save_history", is_flag=True,
              help="Save health entry to history.")
@click.pass_context
def health_cmd(ctx: click.Context, json_output: bool, save_history: bool) -> None:
    """Show per-module architecture health grades."""
    import json as _json
    from codegraph.arch_health import compute_health
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        report = compute_health(graph0, index, project_root=root)

    if save_history:
        from codegraph.arch_health import save_health_history
        save_health_history(report, root)
        click.echo("Health entry saved to history.")

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


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


# ── Registration ──────────────────────────────────────────────────────

COMMANDS = [
    evolution_cmd,
    evolve_cmd,
    memory_intel_cmd,
    metrics_snapshot_cmd,
    copilot_context_cmd,
    health_cmd,
    multilevel_cmd,
    memory_cmd,
    subsystems_cmd,
    metrics_cmd,
    refactor_cmd,
]
