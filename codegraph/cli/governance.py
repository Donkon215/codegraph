"""codegraph.cli.governance — Governance CLI commands.

Commands: analyze, tasks, suggest (group), apply, policy, lock, drift,
repair, repair-plan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from codegraph.config import find_project_root, load_config
from codegraph.cli.core import handle_error, timed_command, EXIT_ERROR, EXIT_VALIDATION_FAIL


# ── suggest group ──────────────────────────────────────────────────────
@click.group("suggest")
def suggest_group() -> None:
    """Manage architecture policy rules (suggested_workflow)."""
    pass


@suggest_group.command("add")
@click.option("--type", "rule_type", required=True,
              type=click.Choice(["required_call", "forbidden_call",
                                 "forbidden_path", "layer_boundary",
                                 "dependency_limit"]))
@click.option("--source", default=None, help="Source scope pattern.")
@click.option("--target", default=None, help="Target scope pattern.")
@click.option("--source-layer", type=int, default=None, help="Source layer number.")
@click.option("--target-layer", type=int, default=None, help="Target layer number.")
@click.option("--source-arch-layer", default=None, help="Source arch layer.")
@click.option("--target-arch-layer", default=None, help="Target arch layer.")
@click.option("--max-fan-in", type=int, default=None, help="Max fan-in (dependency_limit).")
@click.option("--max-fan-out", type=int, default=None, help="Max fan-out (dependency_limit).")
@click.option("--reason", required=True, help="Reason for the rule.")
@click.option("--author", default="human", help="Author of the rule.")
@click.pass_context
def suggest_add(ctx: click.Context, rule_type: str, source: str | None,
                target: str | None, source_layer: int | None,
                target_layer: int | None, source_arch_layer: str | None,
                target_arch_layer: str | None, max_fan_in: int | None,
                max_fan_out: int | None, reason: str, author: str) -> None:
    """Add a new architecture policy rule."""
    from codegraph.suggest import add_rule
    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    rule_id = add_rule(
        root, rule_type, reason=reason, author=author,
        source=source, target=target,
        source_layer=source_layer, target_layer=target_layer,
        source_arch_layer=source_arch_layer, target_arch_layer=target_arch_layer,
        max_fan_in=max_fan_in, max_fan_out=max_fan_out,
    )
    click.echo(f"Added rule {rule_id}")


@suggest_group.command("remove")
@click.argument("rule_id")
@click.pass_context
def suggest_remove(ctx: click.Context, rule_id: str) -> None:
    """Remove a policy rule by ID."""
    from codegraph.suggest import remove_rule
    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    if remove_rule(root, rule_id):
        click.echo(f"Removed rule {rule_id}")
    else:
        click.echo(f"Rule {rule_id} not found", err=True)
        sys.exit(1)


@suggest_group.command("list")
@click.option("--type", "filter_type", default=None, help="Filter by rule type.")
@click.pass_context
def suggest_list(ctx: click.Context, filter_type: str | None) -> None:
    """List all policy rules."""
    from codegraph.suggest import list_rules, format_rules_table
    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    rules = list_rules(root, filter_type=filter_type)
    if rules:
        click.echo(format_rules_table(rules))
    else:
        click.echo("No rules defined.")


@suggest_group.command("validate")
@click.pass_context
def suggest_validate(ctx: click.Context) -> None:
    """Validate the suggested_workflow rules."""
    from codegraph.suggest import (
        load_suggested_workflow, validate_suggested_workflow,
        find_dangling_rules,
    )
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    sw = load_suggested_workflow(root)
    graph0 = load_graph0(root)
    graph1 = load_graph1(root)

    issues = validate_suggested_workflow(sw, graph0, graph1)
    dangling = find_dangling_rules(sw, graph0, graph1)

    if issues:
        for issue in issues:
            click.echo(f"  [{issue.severity}] {issue.message}")
    if dangling:
        for d in dangling:
            click.echo(f"  [warning] Dangling rule {d.rule_id}: {d.side} matches 0 nodes")
    if not issues and not dangling:
        click.echo("Suggested workflow validation passed.")


@suggest_group.command("diff")
@click.pass_context
def suggest_diff(ctx: click.Context) -> None:
    """Show policy compliance diff."""
    from codegraph.suggest import load_suggested_workflow, policy_diff
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    sw = load_suggested_workflow(root)
    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    wf = load_workflow(root)

    diff = policy_diff(sw, wf, graph0, graph1)
    click.echo(diff.format())


@suggest_group.command("stats")
@click.pass_context
def suggest_stats(ctx: click.Context) -> None:
    """Show rule statistics dashboard."""
    from codegraph.suggest import load_suggested_workflow, rule_statistics
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    sw = load_suggested_workflow(root)
    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    wf = load_workflow(root)

    stats = rule_statistics(sw, wf, graph0, graph1)
    click.echo(stats.format())


@suggest_group.command("import-template")
@click.argument("template_name")
@click.pass_context
def suggest_import_template(ctx: click.Context, template_name: str) -> None:
    """Import rules from a built-in template."""
    from codegraph.suggest import import_rules_template, available_templates

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    available = available_templates()
    if template_name not in available:
        click.echo(f"Unknown template '{template_name}'. Available: {', '.join(available)}", err=True)
        sys.exit(1)

    count = import_rules_template(template_name, root)
    click.echo(f"Imported {count} rules from template '{template_name}'")


# ── analyze ────────────────────────────────────────────────────────────
@click.command("analyze")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def analyze_cmd(ctx: click.Context, as_json: bool) -> None:
    """Run full codebase analysis (orphans, stale intents, coverage gaps, policy)."""
    from codegraph.analyzer import run_analyze, format_analysis_report

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    result = run_analyze(root, as_json=as_json)
    report = format_analysis_report(result, as_json=as_json)
    click.echo(report)


def _tasks_load_data(root):
    """Load all data needed for task generation."""
    from codegraph.analyzer import run_analyze
    from codegraph.storage import get_graph_version
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    analysis = run_analyze(root)
    gv = get_graph_version(root)
    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    workflow = load_workflow(root)

    index = None
    try:
        from codegraph.index import IndexStore
        index = IndexStore(root)
    except FileNotFoundError:
        pass

    return analysis, gv, graph0, graph1, workflow, index


# ── tasks ──────────────────────────────────────────────────────────────
@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--filter-type", default=None, help="Filter tasks by task_id type.")
@click.option("--max-priority", type=int, default=None, help="Max priority level to show.")
@click.pass_context
def tasks(ctx: click.Context, as_json: bool, filter_type: str | None, max_priority: int | None) -> None:
    """Generate the agent work queue."""
    from codegraph.tasks import (
        generate_tasks, write_tasks, task_statistics, filter_tasks,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    analysis, gv, graph0, graph1, workflow, index = _tasks_load_data(root)

    batch = generate_tasks(
        analysis, graph0, graph1, workflow,
        index=index, graph_version=gv,
        project_root=root,
    )

    if index is not None:
        index.close()

    write_tasks(batch, root)

    display_tasks = batch.tasks
    if filter_type or max_priority:
        display_tasks = filter_tasks(
            batch, task_type=filter_type, max_priority=max_priority,
        )

    if as_json:
        click.echo(batch.to_json())
    else:
        stats = task_statistics(batch)
        click.echo(stats.format())
        if display_tasks:
            click.echo(f"\nTasks ({len(display_tasks)}):")
            for t in display_tasks:
                node_count = len(t.nodes) if t.nodes else 0
                click.echo(f"  [{t.task_id}] P{t.priority} — {node_count} node(s)")

    click.echo(f"\nTasks written to .codegraph/tasks/tasks.json")


# ── apply ──────────────────────────────────────────────────────────────
@click.command()
@click.argument("response_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying files.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--skip-plan-check", is_flag=True, help="Bypass planning gate (not recommended).")
@click.pass_context
def apply(ctx: click.Context, response_file: str, dry_run: bool, json_output: bool, skip_plan_check: bool) -> None:
    """Apply agent response to the codebase."""
    from codegraph.apply import run_apply, format_apply_result

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    result = run_apply(
        Path(response_file).resolve(), root,
        dry_run=dry_run, skip_plan_check=skip_plan_check,
    )
    output = format_apply_result(result, as_json=json_output)
    click.echo(output)

    if result.failed:
        sys.exit(1)


# ── policy ─────────────────────────────────────────────────────────────
@click.command("policy")
@click.option("--init", "do_init", is_flag=True,
              help="Initialize default architecture policies.")
@click.option("--check", "do_check", is_flag=True,
              help="Evaluate all policies against current architecture.")
@click.option("--add", "add_name", default=None,
              help="Add a new policy by name.")
@click.option("--type", "policy_type", default="custom",
              help="Policy type (no_large_modules, score_gate, etc.).")
@click.option("--rule", default="", help="Rule description.")
@click.option("--action", default="warn", help="Action: warn, block, suggest.")
@click.option("--threshold", type=float, default=0.0, help="Numeric threshold.")
@click.option("--remove", "remove_id", default=None,
              help="Remove a policy by ID.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def policy_cmd(ctx: click.Context, do_init: bool, do_check: bool,
               add_name: str | None, policy_type: str, rule: str,
               action: str, threshold: float, remove_id: str | None,
               json_output: bool) -> None:
    """Manage and evaluate architecture policies."""
    import json as _json
    from codegraph.arch_policy import (
        add_policy, evaluate_policies, init_default_policies,
        load_policies, remove_policy,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if do_init:
        policies = init_default_policies(root)
        click.echo(f"Initialized {len(policies)} default policies.")
        return

    if add_name:
        p = add_policy(root, add_name, policy_type, rule, action, threshold)
        click.echo(f"Added policy {p.policy_id}: {p.name}")
        return

    if remove_id:
        if remove_policy(root, remove_id):
            click.echo(f"Removed policy {remove_id}")
        else:
            click.echo(f"Policy {remove_id} not found", err=True)
            sys.exit(EXIT_ERROR)
        return

    if do_check:
        report = evaluate_policies(root)
        if json_output:
            click.echo(_json.dumps(report.to_dict(), indent=2))
        else:
            click.echo(report.format())
        if not report.passed:
            sys.exit(EXIT_VALIDATION_FAIL)
        return

    policies = load_policies(root)
    if not policies:
        click.echo("No policies defined. Use --init to create defaults.")
        return

    if json_output:
        click.echo(_json.dumps(
            {"policies": [p.to_dict() for p in policies]}, indent=2,
        ))
    else:
        click.echo(f"Architecture Policies ({len(policies)}):")
        for p in policies:
            status = "✓" if p.enabled else "○"
            click.echo(f"  {status} [{p.policy_id}] {p.name} "
                        f"({p.policy_type}, {p.action})")
            click.echo(f"    {p.rule}")


# ── lock ───────────────────────────────────────────────────────────────
@click.command("lock")
@click.option("--strict", is_flag=True,
              help="Treat undeclared modules as errors.")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def lock_cmd(ctx: click.Context, strict: bool, json_output: bool) -> None:
    """Check architecture lock — verify code obeys architecture rules."""
    import json as _json
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.architecture_lock import check_lock
    from codegraph.models.graph0 import Graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    graph0_path = root / ".codegraph" / "graphs" / "graph0.json"
    if not graph0_path.exists():
        click.echo("No graph0 found. Run: codegraph build", err=True)
        sys.exit(EXIT_ERROR)

    graph0 = Graph0.from_json(graph0_path.read_text(encoding="utf-8"))
    actual_modules = list({n.file for n in graph0.nodes if n.file})

    workflow_path = root / ".codegraph" / "workflow" / "workflow.json"
    actual_edges: list[tuple[str, str]] = []
    if workflow_path.exists():
        wf_data = _json.loads(workflow_path.read_text(encoding="utf-8"))
        for e in wf_data.get("edges", []):
            src = e.get("source", "")
            tgt = e.get("target", "")
            if "::" in src:
                src = src.split("::")[0] + ".py"
            if "::" in tgt:
                tgt = tgt.split("::")[0] + ".py"
            actual_edges.append((src, tgt))

    report = check_lock(arch, actual_modules, actual_edges, strict=strict)
    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if not report.is_locked:
        sys.exit(EXIT_ERROR)


# ── drift ──────────────────────────────────────────────────────────────
@click.command("drift")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.option("--save", is_flag=True, help="Save drift report.")
@click.pass_context
def drift_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Detect drift between declared architecture and actual code."""
    import json as _json
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.drift_detector import detect_drift
    from codegraph.models.graph0 import Graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if not arch:
        click.echo("No architecture defined.", err=True)
        sys.exit(EXIT_ERROR)

    graph0_path = root / ".codegraph" / "graphs" / "graph0.json"
    if not graph0_path.exists():
        click.echo("No graph0 found. Run: codegraph build", err=True)
        sys.exit(EXIT_ERROR)

    graph0 = Graph0.from_json(graph0_path.read_text(encoding="utf-8"))

    workflow_path = root / ".codegraph" / "workflow" / "workflow.json"
    actual_edges: list[tuple[str, str]] = []
    if workflow_path.exists():
        wf_data = _json.loads(workflow_path.read_text(encoding="utf-8"))
        for e in wf_data.get("edges", []):
            src = e.get("source", "").split("::")[0]
            tgt = e.get("target", "").split("::")[0]
            if src and tgt:
                if not src.endswith(".py"):
                    src += ".py"
                if not tgt.endswith(".py"):
                    tgt += ".py"
                actual_edges.append((src, tgt))

    report = detect_drift(arch, graph0, actual_edges, project_root=root)
    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if save:
        report.save(root)
        click.echo(f"\nDrift report saved.")


# ── repair ─────────────────────────────────────────────────────────────
@click.command("repair")
@click.option("--max-cycles", type=int, default=3,
              help="Maximum repair cycles.")
@click.option("--dry-run", is_flag=True, help="Show without modifying files.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def repair_cmd(ctx: click.Context, max_cycles: int, dry_run: bool,
               json_output: bool) -> None:
    """Run automated repair cycles."""
    import json as _json
    from codegraph.analyzer import run_analyze
    from codegraph.tasks import generate_tasks
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow
    from codegraph.storage import get_graph_version

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    for cycle in range(1, max_cycles + 1):
        click.echo(f"\n=== Repair Cycle {cycle}/{max_cycles} ===")

        analysis = run_analyze(root)
        graph0 = load_graph0(root)
        graph1 = load_graph1(root)
        workflow = load_workflow(root)
        gv = get_graph_version(root)

        index = None
        try:
            from codegraph.index import IndexStore
            index = IndexStore(root)
        except FileNotFoundError:
            pass

        batch = generate_tasks(
            analysis, graph0, graph1, workflow,
            index=index, graph_version=gv,
            project_root=root,
        )

        if index is not None:
            index.close()

        if not batch.tasks:
            click.echo("No tasks remaining. Converged.")
            break

        click.echo(f"Tasks: {len(batch.tasks)}")
        for t in batch.tasks[:5]:
            click.echo(f"  [{t.task_id}] P{t.priority}")

        if dry_run:
            click.echo("[dry-run] Not applying.")
            break


# ── repair-plan ────────────────────────────────────────────────────────
@click.command("repair-plan")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", is_flag=True, help="Save repair plan.")
@click.pass_context
def repair_plan_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Generate a repair plan from current analysis."""
    import json as _json
    from codegraph.tasks import generate_tasks

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    analysis, gv, graph0, graph1, workflow, index = _tasks_load_data(root)

    batch = generate_tasks(
        analysis, graph0, graph1, workflow,
        index=index, graph_version=gv,
        project_root=root,
    )

    if index is not None:
        index.close()

    if json_output:
        click.echo(batch.to_json())
    else:
        click.echo(f"Repair Plan: {len(batch.tasks)} tasks")
        for t in batch.tasks:
            node_count = len(t.nodes) if t.nodes else 0
            click.echo(f"  [{t.task_id}] P{t.priority} — {node_count} node(s)")

    if save:
        from codegraph.tasks import write_tasks
        write_tasks(batch, root)
        click.echo("Repair plan saved.")


# ── Architecture Delta ────────────────────────────────────────────────
@click.command("arch-delta")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", is_flag=True,
              help="Save delta to .codegraph/architecture_delta.json.")
@click.pass_context
@timed_command
def delta_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Generate architecture delta between current state and proposed plan."""
    import json as _json
    from codegraph.architecture_delta import generate_architecture_delta

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    delta = generate_architecture_delta(root)

    if json_output:
        click.echo(_json.dumps(delta.to_dict(), indent=2))
    else:
        click.echo(delta.format())

    if save:
        delta.save(root)
        click.echo("\nDelta saved.")


# ── Architecture Score ────────────────────────────────────────────────
@click.command("score")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save-baseline", is_flag=True,
              help="Save current score as baseline.")
@click.option("--compare", is_flag=True,
              help="Compare current score against saved baseline.")
@click.pass_context
@timed_command
def score_cmd(ctx: click.Context, json_output: bool, save_baseline: bool,
              compare: bool) -> None:
    """Compute and display the architecture quality score."""
    import json as _json
    from codegraph.architecture_score import (
        ArchitectureScore, compare_scores, compute_score,
    )

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    current = compute_score(root)

    if compare:
        baseline = ArchitectureScore.load(root)
        if baseline is None:
            click.echo("No baseline score found. Use --save-baseline first.",
                       err=True)
            sys.exit(EXIT_ERROR)
        result = compare_scores(baseline, current)
        if json_output:
            click.echo(_json.dumps(result, indent=2))
        else:
            delta = result["delta"]
            icon = "+" if delta >= 0 else ""
            click.echo(f"Baseline: {result['baseline_score']:.3f} "
                       f"({result['baseline_grade']})")
            click.echo(f"Current:  {result['current_score']:.3f} "
                       f"({result['current_grade']})")
            click.echo(f"Delta:    {icon}{delta:.3f}")
            click.echo(f"Merge allowed: {result['merge_allowed']}")
        if not result["merge_allowed"]:
            sys.exit(EXIT_VALIDATION_FAIL)
        return

    if json_output:
        click.echo(_json.dumps(current.to_dict(), indent=2))
    else:
        click.echo(current.format())

    if save_baseline:
        current.save(root)
        click.echo("\nBaseline score saved.")


# ── Architecture Proof ────────────────────────────────────────────────
@click.command("prove")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--proposal-id", default="",
              help="Custom proposal ID for the proof.")
@click.pass_context
@timed_command
def prove_cmd(ctx: click.Context, json_output: bool, proposal_id: str) -> None:
    """Validate architecture changes via simulation proof gate.

    Runs cycle detection, layer violations, subsystem constraints,
    coupling analysis, blast radius, and budget checks.
    Rejects changes with HIGH_RISK or BLOCKED risk.
    """
    import json as _json
    from codegraph.architecture_proof import REJECTED, generate_proof

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    proof = generate_proof(root, proposal_id=proposal_id)

    if json_output:
        click.echo(_json.dumps(proof.to_dict(), indent=2))
    else:
        click.echo(proof.format())

    proof.save(root)

    if proof.status == REJECTED:
        click.echo("\nProof REJECTED — implementation blocked.", err=True)
        sys.exit(EXIT_VALIDATION_FAIL)
    else:
        click.echo(f"\nProof: {proof.status}")


# ── Context Builder ───────────────────────────────────────────────────
@click.command("arch-context")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", is_flag=True,
              help="Save context to .codegraph/context/copilot_context.json.")
@click.pass_context
@timed_command
def context_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Generate enriched architecture context for Copilot."""
    import json as _json
    from codegraph.copilot_context_builder import build_enriched_context

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    enriched = build_enriched_context(root)

    if json_output:
        click.echo(_json.dumps(enriched.to_dict(), indent=2))
    else:
        click.echo(enriched.format())

    if save:
        enriched.save(root)
        click.echo("\nContext saved.")


# ── Pipeline Orchestrator ─────────────────────────────────────────────
@click.command("pipeline")
@click.option("--dry-run", is_flag=True,
              help="Show what would be done without executing.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", is_flag=True,
              help="Save pipeline report.")
@click.pass_context
@timed_command
def pipeline_cmd(ctx: click.Context, dry_run: bool, json_output: bool,
                 save: bool) -> None:
    """Execute the full architecture evolution pipeline.

    Enforced pipeline:
      build → analyze → advisor → delta → context → simulate → prove
      → implement → test → score_compare → merge_decision

    Uses state-machine transitions. Blocks on HIGH_RISK or BLOCKED.
    """
    import json as _json
    from codegraph.pipeline_orchestrator import run_pipeline

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    report = run_pipeline(root, dry_run=dry_run)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())

    if save:
        report.save(root)
        click.echo("\nPipeline report saved.")

    if not report.success:
        sys.exit(EXIT_VALIDATION_FAIL)


# ── Registration ──────────────────────────────────────────────────────

COMMANDS = [
    analyze_cmd,
    tasks,
    apply,
    policy_cmd,
    lock_cmd,
    drift_cmd,
    repair_cmd,
    repair_plan_cmd,
    delta_cmd,
    score_cmd,
    prove_cmd,
    context_cmd,
    pipeline_cmd,
]

GROUPS = [
    suggest_group,
]
