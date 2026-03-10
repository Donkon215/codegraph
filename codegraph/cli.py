"""codegraph.cli — Command-line interface for codegraph.

All CLI commands are defined here using Click. Entry point: ``main()``.

Tasks N-001 through N-032.
"""

from __future__ import annotations

import functools
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import click

from codegraph import __version__
from codegraph.config import find_project_root, load_config
from codegraph.exceptions import CodegraphError
from codegraph.logging_config import configure_logging, get_logger
from codegraph.storage import ensure_codegraph_dir, generate_gitignore

logger = get_logger("cli")

# ── N-028 — Exit code convention ───────────────────────────────────────
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_VALIDATION_FAIL = 2
EXIT_VERSION_MISMATCH = 3
EXIT_CONFIG_ERROR = 4


# ── N-021 — Unified error display ─────────────────────────────────────
def handle_error(error: Exception, verbose: bool = False) -> None:
    """Display a user-friendly error message with recovery guidance."""
    from codegraph.exceptions import (
        ASTParseError, VersionMismatchError, IndexInconsistencyError,
        ProjectNotFoundError, LayerViolationError, DanglingRuleError,
        RepairConflictError, GraphDriftError,
    )

    guidance: dict[type, str] = {
        ASTParseError: "Fix the syntax error in the source file, then re-run build.",
        VersionMismatchError: "Re-run 'codegraph tasks' to get a fresh task batch.",
        IndexInconsistencyError: "Run 'codegraph index rebuild' to repair.",
        ProjectNotFoundError: "Run 'codegraph init' to initialize the project.",
        LayerViolationError: "Only layers 3 (project) and 4 (test) are modifiable.",
        DanglingRuleError: "Run 'codegraph suggest validate' to find stale rules.",
        RepairConflictError: "Review the agent response for overlapping edits.",
        GraphDriftError: "Run 'codegraph build' to refresh the graph.",
    }

    click.echo(click.style(f"Error: {error}", fg="red"), err=True)

    hint = guidance.get(type(error))
    if hint:
        click.echo(click.style(f"  Hint: {hint}", fg="yellow"), err=True)

    if verbose:
        click.echo(traceback.format_exc(), err=True)


# ── N-024 — Command timing decorator ──────────────────────────────────
def timed_command(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that prints elapsed time in verbose mode."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.monotonic() - start
            ctx = click.get_current_context(silent=True)
            if ctx and ctx.obj and ctx.obj.get("verbose"):
                click.echo(f"  [{fn.__name__}] completed in {elapsed:.2f}s", err=True)

    return wrapper


@click.group()
@click.version_option(version=__version__, prog_name="codegraph")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress informational output.")
@click.option("--json-log", is_flag=True, help="Emit logs as JSON for agent consumption.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool, json_log: bool) -> None:
    """codegraph — A CLI-driven graph system for AI agents."""
    ctx.ensure_object(dict)
    level = "DEBUG" if verbose else ("WARNING" if quiet else "INFO")
    configure_logging(level=level, json_format=json_log)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


# ── init ───────────────────────────────────────────────────────────────
@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
def init(path: str) -> None:
    """Initialize a project for codegraph analysis."""
    project_root = Path(path).resolve()
    ensure_codegraph_dir(project_root)
    generate_gitignore(project_root)
    click.echo(f"Initialized .codegraph/ in {project_root}")


# ── status ─────────────────────────────────────────────────────────────
@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current codegraph project status."""
    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    config = load_config(root)
    click.echo(f"Project root: {root}")
    click.echo(f"Config: {config}")

    # D-014 — Layer statistics if graph1 exists
    from codegraph.storage import resolve_path
    g1_path = resolve_path(root, "graphs", "graph1.json")
    if g1_path.exists():
        from codegraph.models.graph1 import Graph1
        from codegraph.layers import layer_statistics, format_layer_stats
        g1 = Graph1.from_json(g1_path.read_text(encoding="utf-8"))
        stats = layer_statistics(g1)
        click.echo(format_layer_stats(stats))

        # E-024 — Annotation statistics
        g0_path = resolve_path(root, "graphs", "graph0.json")
        if g0_path.exists():
            from codegraph.annotator import graph1_statistics
            from codegraph.models.graph0 import Graph0
            g0 = Graph0.from_json(g0_path.read_text(encoding="utf-8"))
            astats = graph1_statistics(g0, g1)
            click.echo(astats.format())

    # D-018 — Config change detection
    from codegraph.config import compute_config_hash, config_changed_since_build
    from codegraph.storage import get_stored_config_hash
    stored = get_stored_config_hash(root)
    if stored and config_changed_since_build(root, stored):
        click.echo("⚠  config.yaml has changed since last build — run 'codegraph build'.")

    # F — Workflow statistics
    from codegraph.storage import resolve_path as _rp
    from codegraph.constants import WORKFLOW_DIR, WORKFLOW_FILE
    wf_path = _rp(root, WORKFLOW_DIR, WORKFLOW_FILE)
    if wf_path.exists():
        from codegraph.workflow import load_workflow, edge_statistics
        wf = load_workflow(root)
        if wf.edges:
            es = edge_statistics(wf)
            click.echo(f"Workflow:  {es.total} edges  "
                        f"({', '.join(f'{k}={v}' for k,v in sorted(es.by_type.items()))})")

    # G — Index statistics
    from codegraph.constants import INDEX_DIR
    idx_path = _rp(root, INDEX_DIR, "codegraph.db")
    if idx_path.exists():
        from codegraph.index import index_statistics
        istats = index_statistics(root)
        click.echo(istats.format())

    # H — Suggested workflow statistics
    from codegraph.constants import SUGGESTED_WORKFLOW_FILE
    sw_path = _rp(root, WORKFLOW_DIR, SUGGESTED_WORKFLOW_FILE)
    if sw_path.exists():
        from codegraph.suggest import load_suggested_workflow
        sw = load_suggested_workflow(root)
        click.echo(f"Policy rules: {len(sw.rules)}")

    # I — Task statistics
    from codegraph.constants import TASKS_DIR, TASKS_FILE
    tasks_path = _rp(root, TASKS_DIR, TASKS_FILE)
    if tasks_path.exists():
        from codegraph.tasks import load_tasks, task_statistics
        tb = load_tasks(root)
        if tb.tasks:
            tstats = task_statistics(tb)
            click.echo(tstats.format())


# ── build ──────────────────────────────────────────────────────────────
@main.command()
@click.option("--no-cache", is_flag=True, help="Ignore extraction cache.")
@click.option("--parallel", is_flag=True, help="Use parallel extraction for large projects.")
@click.option(
    "--layer-override", "layer_overrides", multiple=True,
    help="Override layer detection: path:layer_number (e.g. src/legacy/:2).",
)
@click.pass_context
def build(ctx: click.Context, no_cache: bool, parallel: bool, layer_overrides: tuple[str, ...]) -> None:
    """Extract structure and build all graphs."""
    from codegraph.extractor import extract_project, save_graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    ensure_codegraph_dir(root)
    config = load_config(root)
    quiet = ctx.obj.get("quiet", False)

    # D-013 — parse layer overrides
    overrides: dict[str, int] = {}
    if layer_overrides:
        from codegraph.layers import parse_layer_overrides
        try:
            overrides = parse_layer_overrides(layer_overrides)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

    click.echo(f"Building graphs for {root} …")
    graph0, report = extract_project(
        root,
        config,
        use_cache=not no_cache,
        parallel=parallel,
        progress=not quiet,
    )
    save_graph0(graph0, root)

    # D-007 — assign layers
    from codegraph.layers import assign_layers, layer_statistics, format_layer_stats
    layers = assign_layers(
        graph0.nodes, config,
        project_root=str(root),
        overrides=overrides or None,
    )

    # D-018 — store config hash
    from codegraph.config import compute_config_hash
    from codegraph.storage import store_config_hash
    store_config_hash(root, compute_config_hash(root))

    click.echo(report.summary())
    if not quiet:
        click.echo(f"Layer assignments: {len(layers)} nodes classified")

    # E-001/E-013 — initialize or merge Graph_1
    from codegraph.annotator import (
        load_graph1, save_graph1, initialize_graph1, merge_graph1,
        detect_stale_intents, format_stale_warnings,
    )
    existing_g1 = load_graph1(root)
    if not existing_g1.nodes:
        g1 = initialize_graph1(graph0, layers)
    else:
        g1 = merge_graph1(existing_g1, graph0, layers)

    # E-021 — stale intent warnings
    stale = detect_stale_intents(graph0, g1)
    g0_ids = frozenset(n.id for n in graph0.nodes)
    ghosts = g1.get_stale_nodes(g0_ids)
    warning_text = format_stale_warnings(stale, ghosts)
    if warning_text:
        click.echo(warning_text)

    save_graph1(g1, root)

    # F/G — Build workflow (static only) and indexes
    from codegraph.workflow import build_workflow, workflow_summary
    wf = build_workflow(root, config, trace=False, level="function")
    if not quiet:
        click.echo(workflow_summary(wf, graph0))

    from codegraph.index import build_all_indexes
    idx_result = build_all_indexes(graph0, g1, wf, root)
    if not quiet:
        total = sum(idx_result.values())
        click.echo(f"Index built: {total} rows across {len(idx_result)} tables")

    # Store build commit for delta tracking
    from codegraph.git_utils import get_current_commit
    from codegraph.delta import _store_build_commit
    commit = get_current_commit(root)
    if commit:
        _store_build_commit(root, commit)


# ── prune ──────────────────────────────────────────────────────────────
@main.command()
@click.pass_context
def prune(ctx: click.Context) -> None:
    """Remove stale Graph_1 entries that no longer exist in Graph_0."""
    from codegraph.annotator import load_graph1, save_graph1, prune_graph1
    from codegraph.extractor import load_graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    report = prune_graph1(graph0, graph1)
    if report.removed_count:
        save_graph1(graph1, root)
        click.echo(f"Pruned {report.removed_count} stale entries.")
    else:
        click.echo("No stale entries to prune.")


# ── intent-missing ─────────────────────────────────────────────────────
@main.command("intent-missing")
@click.pass_context
def intent_missing(ctx: click.Context) -> None:
    """List nodes missing intent annotations."""
    from codegraph.annotator import load_graph1, get_missing_intents
    from codegraph.extractor import load_graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    missing = get_missing_intents(graph0, graph1)
    if missing:
        click.echo(f"Nodes missing intent ({len(missing)}):")
        for nid in missing:
            click.echo(f"  {nid}")
    else:
        click.echo("All nodes have intent annotations.")


# ── intent-apply ───────────────────────────────────────────────────────
@main.command("intent-apply")
@click.argument("intent_file", type=click.Path(exists=True))
@click.option("--author", default="human", help="Author of the intents.")
@click.pass_context
def intent_apply(ctx: click.Context, intent_file: str, author: str) -> None:
    """Apply intent annotations from a JSON file."""
    from codegraph.annotator import (
        load_graph1, save_graph1, load_intent_file, apply_intents_batch,
    )
    from codegraph.extractor import load_graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    config = load_config(root)
    graph0 = load_graph0(root)
    graph1 = load_graph1(root)

    try:
        proposals = load_intent_file(Path(intent_file))
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    result = apply_intents_batch(
        graph1, proposals, author,
        graph0=graph0,
        track_history=config.track_intent_history,
    )
    save_graph1(graph1, root)
    click.echo(f"Applied: {result.applied}, Rejected: {result.rejected}")
    for w in result.warnings:
        click.echo(f"  Warning: {w}")
    for e in result.errors:
        click.echo(f"  Error: {e}", err=True)


# ── annotate ───────────────────────────────────────────────────────────
@main.command()
@click.option("--node", required=True, help="Node ID to annotate.")
@click.option("--intent", default=None, help="Intent description.")
@click.option("--arch-layer", default=None, help="Architectural layer label.")
@click.option("--tag", "tags", multiple=True, help="Tags (repeatable).")
@click.option("--author", default="human", help="Author of the annotation.")
@click.pass_context
def annotate(ctx: click.Context, node: str, intent: str | None, arch_layer: str | None, tags: tuple[str, ...], author: str) -> None:
    """Annotate a single node with intent, arch-layer, or tags."""
    from codegraph.annotator import load_graph1, save_graph1, apply_intent, set_arch_layer, add_tags

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    graph1 = load_graph1(root)

    if intent is not None:
        config = load_config(root)
        try:
            w = apply_intent(
                graph1, node, intent, author,
                arch_layer=arch_layer,
                tags=list(tags) if tags else None,
                track_history=config.track_intent_history,
            )
            for msg in w:
                click.echo(f"Warning: {msg}")
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
    else:
        if arch_layer is not None:
            try:
                set_arch_layer(graph1, node, arch_layer)
            except Exception as exc:
                click.echo(f"Error: {exc}", err=True)
                sys.exit(1)
        if tags:
            try:
                add_tags(graph1, node, list(tags))
            except Exception as exc:
                click.echo(f"Error: {exc}", err=True)
                sys.exit(1)

    save_graph1(graph1, root)
    click.echo(f"Annotated {node}.")


# ── Placeholder groups for future commands ─────────────────────────────
# ── suggest ─────────────────────────────────────────────────────────────
@main.group("suggest")
def suggest_group() -> None:
    """Manage architecture policy rules (suggested_workflow)."""
    pass


@suggest_group.command("add")
@click.option("--type", "rule_type", required=True,
              type=click.Choice(["required_call", "forbidden_call"]))
@click.option("--source", default=None, help="Source scope pattern.")
@click.option("--target", default=None, help="Target scope pattern.")
@click.option("--source-layer", type=int, default=None, help="Source layer number.")
@click.option("--target-layer", type=int, default=None, help="Target layer number.")
@click.option("--source-arch-layer", default=None, help="Source arch layer.")
@click.option("--target-arch-layer", default=None, help="Target arch layer.")
@click.option("--reason", required=True, help="Reason for the rule.")
@click.option("--author", default="human", help="Author of the rule.")
@click.pass_context
def suggest_add(ctx: click.Context, rule_type: str, source: str | None,
                target: str | None, source_layer: int | None,
                target_layer: int | None, source_arch_layer: str | None,
                target_arch_layer: str | None, reason: str, author: str) -> None:
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
@main.command("analyze")
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


# ── tasks ──────────────────────────────────────────────────────────────
@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--filter-type", default=None, help="Filter tasks by task_id type.")
@click.option("--max-priority", type=int, default=None, help="Max priority level to show.")
@click.pass_context
def tasks(ctx: click.Context, as_json: bool, filter_type: str | None, max_priority: int | None) -> None:
    """Generate the agent work queue."""
    from codegraph.analyzer import run_analyze
    from codegraph.tasks import (
        generate_tasks, write_tasks, task_statistics, filter_tasks,
    )
    from codegraph.storage import get_graph_version

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    # Run analysis first
    analysis = run_analyze(root)
    gv = get_graph_version(root)

    # Load graphs for task context
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    from codegraph.workflow import load_workflow

    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    workflow = load_workflow(root)

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

    # Write tasks file
    write_tasks(batch, root)

    # Apply filters for display
    display_tasks = batch.tasks
    if filter_type or max_priority:
        display_tasks = filter_tasks(
            batch, task_type=filter_type, max_priority=max_priority,
        )

    if as_json:
        import json as _json
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


@main.command()
@click.argument("response_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying files.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def apply(ctx: click.Context, response_file: str, dry_run: bool, json_output: bool) -> None:
    """Apply agent response to the codebase."""
    from codegraph.apply import run_apply, format_apply_result

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    config = load_config(root)
    result = run_apply(Path(response_file).resolve(), root, dry_run=dry_run)
    output = format_apply_result(result, as_json=json_output)
    click.echo(output)

    if result.failed:
        sys.exit(1)


@main.command()
@click.option("--dry-run", is_flag=True, help="Preview delta without modifying graphs.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--history", is_flag=True, help="Show delta history.")
@click.option("--verbose", "-v", "delta_verbose", is_flag=True, help="Verbose delta output.")
@click.pass_context
def delta(ctx: click.Context, dry_run: bool, json_output: bool, history: bool, delta_verbose: bool) -> None:
    """Compute incremental change log."""
    from codegraph.delta import run_delta, format_delta_result, format_delta_history

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    if history:
        click.echo(format_delta_history(root))
        return

    config = load_config(root)
    result = run_delta(root, config, dry_run=dry_run)
    output = format_delta_result(result, as_json=json_output, verbose=delta_verbose)
    click.echo(output)


@main.command()
@click.argument("expression", nargs=-1, required=True)
@click.option("--depth", type=int, default=None, help="Maximum traversal depth.")
@click.option("--limit", type=int, default=None, help="Maximum number of results.")
@click.option("--format", "output_format", default="text",
              type=click.Choice(["text", "json", "tree", "count"]),
              help="Output format.")
@click.option("--verbose", "-v", "query_verbose", is_flag=True, help="Show file/line details.")
@click.pass_context
def query(ctx: click.Context, expression: tuple, depth: int | None,
          limit: int | None, output_format: str, query_verbose: bool) -> None:
    """Query the graph index."""
    from codegraph.query import run_query

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    # L-020 — Batch: multiple expressions
    for expr in expression:
        try:
            output = run_query(
                expr, root,
                depth=depth, limit=limit,
                output_format=output_format, verbose=query_verbose,
            )
            click.echo(output)
            if len(expression) > 1:
                click.echo("")  # separator between queries
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)


@main.command("explain")
@click.argument("node_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def explain_cmd(ctx: click.Context, node_id: str, json_output: bool) -> None:
    """Show comprehensive information about a node."""
    from codegraph.query import run_query

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    fmt = "json" if json_output else "text"
    output = run_query(f'explain("{node_id}")', root, output_format=fmt)
    click.echo(output)


@main.command("archi-test")
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


@main.command("test-impact")
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


# ── workflow ───────────────────────────────────────────────────────────
@main.command()
@click.option("--trace", is_flag=True, help="Run tests with coverage.py for runtime tracing.")
@click.option("--archi", is_flag=True, help="Trace against .codegraph/test_archi/ instead of tests/.")
@click.option("--trace-all", is_flag=True, help="Trace both tests/ and test_archi/.")
@click.option("--include-imports", is_flag=True, help="Include import-level edges.")
@click.option(
    "--level", "level", default="function",
    type=click.Choice(["function", "class", "module"]),
    help="Graph compression level.",
)
@click.pass_context
def workflow(
    ctx: click.Context,
    trace: bool,
    archi: bool,
    trace_all: bool,
    include_imports: bool,
    level: str,
) -> None:
    """Build the workflow (execution) graph."""
    from codegraph.workflow import build_workflow, workflow_summary

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    config = load_config(root)
    quiet = ctx.obj.get("quiet", False)

    click.echo(f"Building workflow graph (level={level}) …")
    wf = build_workflow(
        root, config,
        trace=trace,
        archi=archi,
        trace_all=trace_all,
        include_imports=include_imports,
        level=level,
    )

    if not quiet:
        from codegraph.extractor import load_graph0
        graph0 = load_graph0(root)
        click.echo(workflow_summary(wf, graph0))

    # Build indexes after workflow
    from codegraph.index import build_all_indexes
    from codegraph.extractor import load_graph0
    from codegraph.annotator import load_graph1
    graph0 = load_graph0(root)
    graph1 = load_graph1(root)
    idx_result = build_all_indexes(graph0, graph1, wf, root)
    if not quiet:
        total = sum(idx_result.values())
        click.echo(f"Index built: {total} rows across {len(idx_result)} tables")


# ── validate ───────────────────────────────────────────────────────────
@main.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Validate workflow graph integrity."""
    from codegraph.workflow import load_workflow, validate_workflow
    from codegraph.extractor import load_graph0

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    graph0 = load_graph0(root)
    wf = load_workflow(root)

    if not wf.edges:
        click.echo("No workflow found — run 'codegraph workflow' first.")
        sys.exit(1)

    issues = validate_workflow(wf, graph0)
    if issues:
        for issue in issues:
            click.echo(f"  [{issue.severity}] {issue.message}")
        errors = sum(1 for i in issues if i.severity == "error")
        warnings = sum(1 for i in issues if i.severity == "warning")
        click.echo(f"\n{errors} errors, {warnings} warnings")
    else:
        click.echo("Workflow validation passed — no issues found.")


# ── index ──────────────────────────────────────────────────────────────
@main.group("index")
def index_group() -> None:
    """Manage graph indexes."""
    pass


@index_group.command("rebuild")
@click.pass_context
def index_rebuild(ctx: click.Context) -> None:
    """Rebuild index from committed graph files."""
    from codegraph.index import rebuild_index

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    click.echo("Rebuilding index …")
    result = rebuild_index(root)
    total = sum(result.values())
    click.echo(f"Index rebuilt: {total} rows across {len(result)} tables")
    for table, count in sorted(result.items()):
        click.echo(f"  {table}: {count}")


@index_group.command("dump")
@click.argument("table", required=False, default=None)
@click.pass_context
def index_dump(ctx: click.Context, table: str | None) -> None:
    """Export index contents as JSON for debugging."""
    from codegraph.index import export_index
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    data = export_index(root, table_name=table)
    click.echo(_json.dumps(data, indent=2))


@index_group.command("check")
@click.pass_context
def index_check(ctx: click.Context) -> None:
    """Check index consistency against graph files."""
    from codegraph.index import check_index_consistency

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    issues = check_index_consistency(root)
    if issues:
        for issue in issues:
            click.echo(f"  [{issue.table}] {issue.message}")
        click.echo(f"\n{len(issues)} issue(s) found")
    else:
        click.echo("Index is consistent with graph files.")


@main.command()
@click.argument("schema_type", type=click.Choice(
    ["graph0", "graph1", "graph2", "workflow", "suggested_workflow",
     "tasks", "agent_response", "delta"],
))
def schema(schema_type: str) -> None:
    """Print the JSON Schema for a data model."""
    import importlib.resources as _res
    import json as _json

    schema_file = f"{schema_type}.schema.json"
    try:
        text = (_res.files("codegraph.schemas") / schema_file).read_text(encoding="utf-8")
        click.echo(text)
    except FileNotFoundError:
        click.echo(f"Schema file not found: {schema_file}", err=True)
        sys.exit(1)


# ── N-013 — diff ───────────────────────────────────────────────────────
@main.command("diff")
@click.option("--target", default="all",
              type=click.Choice(["graph", "workflow", "all"]),
              help="What to diff.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def diff_cmd(ctx: click.Context, target: str, json_output: bool) -> None:
    """Show differences between current and previous graph state."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    delta_path = root / ".codegraph" / "delta" / "delta.json"
    if not delta_path.exists():
        click.echo("No delta found — run 'codegraph delta' first.", err=True)
        sys.exit(EXIT_ERROR)

    from codegraph.models.delta import DeltaResult
    delta_data = _json.loads(delta_path.read_text(encoding="utf-8"))
    delta_result = DeltaResult.from_json(_json.dumps(delta_data))

    changes: list[dict[str, Any]] = []
    for rec in delta_result.changes:
        if target == "graph" and rec.change_type not in ("added", "removed", "modified"):
            continue
        if target == "workflow" and rec.change_type not in ("edge_added", "edge_removed"):
            continue
        changes.append({
            "node_id": rec.node_id,
            "change_type": rec.change_type,
            "file": rec.file,
        })

    if json_output:
        click.echo(_json.dumps(changes, indent=2))
        return

    if not changes:
        click.echo("No differences found.")
        return

    added = [c for c in changes if "added" in c["change_type"]]
    removed = [c for c in changes if "removed" in c["change_type"]]
    modified = [c for c in changes if "modified" in c["change_type"]]

    if added:
        click.echo(click.style(f"\n+ Added ({len(added)}):", fg="green"))
        for c in added:
            click.echo(f"  + {c['node_id']}")
    if removed:
        click.echo(click.style(f"\n- Removed ({len(removed)}):", fg="red"))
        for c in removed:
            click.echo(f"  - {c['node_id']}")
    if modified:
        click.echo(click.style(f"\n~ Modified ({len(modified)}):", fg="yellow"))
        for c in modified:
            click.echo(f"  ~ {c['node_id']}")

    click.echo(f"\nTotal: {len(changes)} change(s)")


# ── N-032 — repair ────────────────────────────────────────────────────
@main.command("repair")
@click.option("--max-cycles", type=int, default=5, help="Maximum repair cycles.")
@click.option("--dry-run", is_flag=True, help="Preview without applying changes.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def repair_cmd(ctx: click.Context, max_cycles: int, dry_run: bool, json_output: bool) -> None:
    """Run the automated repair loop (build → analyze → apply → delta)."""
    import json as _json

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    config = load_config(root)
    results: list[dict[str, Any]] = []

    for cycle in range(1, max_cycles + 1):
        click.echo(f"\n═══ Repair cycle {cycle}/{max_cycles} ═══")

        # 1. Analyze
        from codegraph.analyzer import run_analyze
        analysis = run_analyze(root)

        task_count = (
            len(analysis.get("orphans", []))
            + len(analysis.get("stale_intents", []))
            + len(analysis.get("violations", []))
            if isinstance(analysis, dict)
            else 0
        )

        cycle_result = {"cycle": cycle, "issues_found": task_count}

        if task_count == 0:
            click.echo("  No issues found — repair complete.")
            cycle_result["status"] = "converged"
            results.append(cycle_result)
            break

        click.echo(f"  Found {task_count} issue(s)")

        if dry_run:
            cycle_result["status"] = "dry_run"
            results.append(cycle_result)
            click.echo("  (dry-run: skipping apply)")
            break

        # 2. Check for agent response
        response_path = root / ".codegraph" / "agent_response.json"
        if not response_path.exists():
            click.echo("  No agent_response.json found — waiting for agent.")
            cycle_result["status"] = "waiting_for_agent"
            results.append(cycle_result)
            break

        # 3. Apply
        from codegraph.apply import run_apply, format_apply_result
        apply_result = run_apply(response_path, root, dry_run=False)
        click.echo(format_apply_result(apply_result))
        cycle_result["applied"] = apply_result.applied
        cycle_result["failed"] = apply_result.failed

        # 4. Delta
        from codegraph.delta import run_delta
        delta_result = run_delta(root, config, dry_run=False)
        cycle_result["delta_changes"] = len(delta_result.files_changed)
        cycle_result["status"] = "completed"
        results.append(cycle_result)

    else:
        click.echo(f"\n  Max cycles ({max_cycles}) reached without convergence.")

    if json_output:
        click.echo(_json.dumps(results, indent=2))
    else:
        click.echo(f"\nRepair summary: {len(results)} cycle(s)")
        for r in results:
            click.echo(f"  Cycle {r['cycle']}: {r['status']} ({r['issues_found']} issues)")


# ── N-027 — version (detailed) ────────────────────────────────────────
@main.command("version")
@click.pass_context
def version_cmd(ctx: click.Context) -> None:
    """Display codegraph version and environment information."""
    click.echo(f"codegraph {__version__}")
    click.echo(f"Python {sys.version}")
    click.echo(f"Python path: {sys.executable}")

    if ctx.obj.get("verbose"):
        import importlib.metadata as meta
        click.echo("\nInstalled dependencies:")
        for dep in ("click", "pyyaml", "coverage"):
            try:
                ver = meta.version(dep)
                click.echo(f"  {dep}: {ver}")
            except meta.PackageNotFoundError:
                click.echo(f"  {dep}: not installed")


# ── N-025 — Shell completion support ──────────────────────────────────
@main.command("completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Generate shell completion script."""
    import os
    env_var = "_CODEGRAPH_COMPLETE"
    shell_map = {"bash": "bash_source", "zsh": "zsh_source", "fish": "fish_source"}
    os.environ[env_var] = shell_map[shell]
    try:
        main.main(standalone_mode=False)
    except SystemExit:
        pass
    finally:
        os.environ.pop(env_var, None)


# ── Q — CAS commands ──────────────────────────────────────────────────

@main.group("cas")
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
        click.echo(f"CAS integrity OK — {result.checked} nodes verified.")
    else:
        click.echo(f"CAS integrity FAILED — {len(result.mismatches)} mismatch(es)")
        for nid, (stored, computed) in list(result.mismatches.items())[:10]:
            click.echo(f"  {nid}: stored={stored[:12]}… computed={computed[:12]}…")
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
        click.echo(f"Body hash:       {info.body_hash[:16]}…" if info.body_hash else "Body hash: N/A")
        click.echo(f"Dependency hash: {info.dependency_hash[:16]}…" if info.dependency_hash else "Dependency hash: not computed")
        click.echo(f"Direct callees:  {len(info.direct_callees)}")
        click.echo(f"Direct callers:  {len(info.direct_callers)}")
        click.echo(f"Would invalidate: {info.transitive_dependents_count} node(s)")
        if info.would_invalidate:
            for dep in info.would_invalidate[:10]:
                click.echo(f"  → {dep}")


# ── R — Semantic commands ─────────────────────────────────────────────

@main.group("semantic")
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


# ── Path query ─────────────────────────────────────────────────────────
@main.command("path")
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


# ── Risk metrics ───────────────────────────────────────────────────────
@main.command("metrics")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--node", default=None, help="Show metrics for a specific node.")
@click.option("--top", type=int, default=10, help="Show top N riskiest nodes.")
@click.pass_context
def metrics_cmd(ctx: click.Context, json_output: bool, node: str | None, top: int) -> None:
    """Show dependency risk metrics (fan-in, fan-out, centrality, risk scores)."""
    import json as _json
    from codegraph.risk_metrics import compute_risk_metrics, get_node_risk
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    with IndexStore(root) as index:
        if node:
            m = get_node_risk(node, index)
            if m is None:
                click.echo(f"Node not found: {node}", err=True)
                sys.exit(EXIT_ERROR)
            if json_output:
                click.echo(_json.dumps(m.to_dict(), indent=2))
            else:
                click.echo(f"Node: {m.node_id}")
                click.echo(f"  Fan-in:  {m.fan_in}")
                click.echo(f"  Fan-out: {m.fan_out}")
                click.echo(f"  Degree:  {m.degree}")
                click.echo(f"  Betweenness: {m.betweenness:.4f}")
                click.echo(f"  Coupling: {m.coupling_score:.4f}")
                click.echo(f"  Risk: {m.risk_level.value} ({m.risk_score:.2f})")
        else:
            report = compute_risk_metrics(index)
            report.node_metrics = report.node_metrics[:top]
            if json_output:
                click.echo(_json.dumps(report.to_dict(), indent=2))
            else:
                click.echo(report.format())


# ── Refactor ───────────────────────────────────────────────────────────
@main.command("refactor")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--god-threshold", type=int, default=30,
              help="Node count threshold for god module detection.")
@click.option("--coupling-threshold", type=int, default=10,
              help="Edge count threshold for high coupling detection.")
@click.pass_context
def refactor_cmd(ctx: click.Context, json_output: bool,
                 god_threshold: int, coupling_threshold: int) -> None:
    """Analyze code structure and suggest refactorings."""
    import json as _json
    from codegraph.refactor import analyze_refactoring
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)

    with IndexStore(root) as index:
        report = analyze_refactoring(
            index, graph0,
            god_module_threshold=god_threshold,
            coupling_threshold=coupling_threshold,
        )

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Plan ───────────────────────────────────────────────────────────────
@main.command("plan")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", is_flag=True, help="Save the plan to .codegraph/plans/.")
@click.pass_context
def plan_cmd(ctx: click.Context, json_output: bool, save: bool) -> None:
    """Generate a repair plan from current tasks."""
    import json as _json
    from codegraph.planning import generate_plan, validate_plan, save_plan
    from codegraph.tasks import load_tasks
    from codegraph.storage import get_graph_version

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    tasks_batch = load_tasks(root)
    gv = get_graph_version(root)

    plan = generate_plan(tasks_batch.to_dict(), gv)
    issues = validate_plan(plan)

    if issues:
        for issue in issues:
            click.echo(f"  Warning: {issue}", err=True)

    if save:
        path = save_plan(plan, root)
        click.echo(f"Plan saved to {path}")

    if json_output:
        click.echo(plan.to_json())
    else:
        click.echo(plan.format())


# ── Memory ─────────────────────────────────────────────────────────────
@main.command("memory")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--note", default=None, help="Add a free-form note.")
@click.pass_context
def memory_cmd(ctx: click.Context, json_output: bool, note: str | None) -> None:
    """View or manage the agent memory."""
    import json as _json
    from codegraph.agent_memory import load_memory, save_memory

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(EXIT_ERROR)

    memory = load_memory(root)

    if note:
        memory.add_note(note)
        save_memory(memory, root)
        click.echo("Note added.")
        return

    if json_output:
        click.echo(memory.to_json())
    else:
        click.echo(memory.format())


# ── Visualize ──────────────────────────────────────────────────────────
@main.command("visualize")
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


# ── Subsystem Detection ───────────────────────────────────────────────
@main.command("subsystems")
@click.option("--resolution", type=float, default=1.0,
              help="Louvain resolution parameter (higher = more clusters).")
@click.option("--min-size", type=int, default=2,
              help="Minimum nodes for a subsystem.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def subsystems_cmd(ctx: click.Context, resolution: float, min_size: int,
                   json_output: bool) -> None:
    """Detect sub-architecture clusters in the dependency graph."""
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
        report = detect_subsystems(graph0, index, resolution=resolution,
                                   min_size=min_size)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(f"Detected {len(report.subsystems)} subsystems "
                   f"(modularity={report.modularity_score:.3f})")
        for ss in report.subsystems:
            click.echo(f"  {ss.name} — {len(ss.nodes)} nodes, "
                       f"{len(ss.files)} files, cohesion={ss.cohesion:.2f}")
        if report.couplings:
            click.echo("\nCross-subsystem coupling:")
            for c in report.couplings[:10]:
                click.echo(f"  {c.subsystem_a} <-> {c.subsystem_b}: "
                           f"{c.edge_count} edges (strength={c.coupling_strength:.3f})")


# ── Architecture Health ───────────────────────────────────────────────
@main.command("health")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.option("--save", "save_history", is_flag=True,
              help="Append result to health history.")
@click.pass_context
def health_cmd(ctx: click.Context, json_output: bool, save_history: bool) -> None:
    """Compute architecture health score and grade."""
    import json as _json

    from codegraph.arch_health import compute_health, save_health_report, append_health_history
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        report = compute_health(graph0, index)

    if save_history:
        save_health_report(report, root)
        append_health_history(report, root)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(f"Architecture Health: {report.to_dict()['grade']} ({report.overall_score:.1%})")
        click.echo(f"  Cycles: {report.cycle_count}")
        click.echo(f"  Critical risk nodes: {report.critical_nodes}")
        click.echo(f"  High risk nodes: {report.high_risk_nodes}")
        click.echo(f"  Avg cohesion: {report.avg_cohesion:.2f}")
        if report.architecture_smells:
            click.echo("\nArchitecture smells:")
            for smell in report.architecture_smells[:10]:
                click.echo(f"  - {smell}")
        if report.recommendations:
            click.echo("\nRecommendations:")
            for rec in report.recommendations[:5]:
                click.echo(f"  - {rec}")


# ── LLM Context Builder ──────────────────────────────────────────────
@main.command("context")
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


# ── Simulate ──────────────────────────────────────────────────────────
@main.command("simulate")
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


# ── Architecture Diff ─────────────────────────────────────────────────
@main.command("arch-diff")
@click.option("--snapshot", "old_label", default=None,
              help="Compare current graph against a named snapshot.")
@click.option("--save-snapshot", "save_label", default=None,
              help="Save current graph as a named snapshot.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def arch_diff_cmd(ctx: click.Context, old_label: str | None,
                  save_label: str | None, json_output: bool) -> None:
    """Compare architecture across graph versions."""
    import json as _json

    from codegraph.arch_diff import diff_snapshots, save_snapshot

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if save_label:
        snap_dir = save_snapshot(root, save_label)
        click.echo(f"Snapshot saved to {snap_dir}")
        return

    if not old_label:
        click.echo("Provide --snapshot <label> to diff or --save-snapshot <label> to save.",
                    err=True)
        sys.exit(EXIT_ERROR)

    report = diff_snapshots(root, old_label)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.format())


# ── Architecture Definition ───────────────────────────────────────────
@main.command("architecture")
@click.option("--init", "do_init", is_flag=True,
              help="Create a template architecture definition.")
@click.option("--validate", "do_validate", is_flag=True,
              help="Validate architecture against actual code.")
@click.option("--name", default="", help="Project name (for --init).")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def architecture_cmd(ctx: click.Context, do_init: bool, do_validate: bool,
                     name: str, json_output: bool) -> None:
    """Manage architecture definitions."""
    import json as _json

    from codegraph.arch_schema import SystemArchitecture, init_architecture
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore
    from codegraph.workflow import load_workflow

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    if do_init:
        arch = init_architecture(root, name=name)
        path = root / ".codegraph" / "architecture" / "system.json"
        click.echo(f"Architecture template created: {path}")
        if json_output:
            click.echo(_json.dumps(arch.to_dict(), indent=2))
        return

    arch = SystemArchitecture.load(root)
    if arch is None:
        click.echo("No architecture defined. Use --init to create one.", err=True)
        sys.exit(EXIT_ERROR)

    if do_validate:
        graph0 = load_graph0(root)
        workflow = load_workflow(root)
        with IndexStore(root) as index:
            from codegraph.arch_planner import plan_architecture

            plan = plan_architecture(arch, graph0, index)
        click.echo(f"Architecture: {arch.name}")
        click.echo(f"  Coverage: {plan.coverage.overall_coverage:.1%}")
        click.echo(f"  Missing modules: {len(plan.missing_modules)}")
        click.echo(f"  Missing functions: {len(plan.missing_functions)}")
        click.echo(f"  Missing connections: {len(plan.missing_connections)}")
        click.echo(f"  Constraint violations: {len(plan.constraint_violations)}")
        if json_output:
            click.echo(_json.dumps(plan.to_dict(), indent=2))
        return

    # Default: show architecture
    if json_output:
        click.echo(_json.dumps(arch.to_dict(), indent=2))
    else:
        click.echo(f"Architecture: {arch.name}")
        if arch.description:
            click.echo(f"  {arch.description}")
        click.echo(f"  Subsystems: {len(arch.subsystems)}")
        for s in arch.subsystems:
            click.echo(f"    - {s.name} ({len(s.components)} components)")
        click.echo(f"  Edges: {len(arch.edges)}")
        click.echo(f"  Constraints: {len(arch.constraints)}")


# ── Architecture Planner ──────────────────────────────────────────────
@main.command("plan")
@click.option("--output", "output_file", default=None,
              help="Save generated tasks to a file.")
@click.option("--agent-response", "agent_response", is_flag=True,
              help="Output as agent_response.json format.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def plan_cmd(ctx: click.Context, output_file: str | None,
             agent_response: bool, json_output: bool) -> None:
    """Generate tasks from architecture definition."""
    import json as _json

    from codegraph.arch_planner import plan_architecture, plan_to_agent_response
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    arch = SystemArchitecture.load(root)
    if arch is None:
        click.echo("No architecture defined. Use 'codegraph architecture --init' first.",
                    err=True)
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        plan = plan_architecture(arch, graph0, index)

    if agent_response:
        # Read graph version
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
@main.command("viewer")
@click.option("--output", "output_file", default=None,
              help="Custom output path for HTML file.")
@click.pass_context
def viewer_cmd(ctx: click.Context, output_file: str | None) -> None:
    """Generate interactive HTML architecture dashboard."""
    from codegraph.annotator import load_graph1
    from codegraph.arch_schema import SystemArchitecture
    from codegraph.arch_viewer import generate_viewer
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
    architecture = SystemArchitecture.load(root)

    out_path = Path(output_file) if output_file else None
    with IndexStore(root) as index:
        result_path = generate_viewer(
            root, graph0, graph1, workflow, index,
            architecture=architecture, output_path=out_path,
        )
    click.echo(f"Dashboard generated: {result_path}")


# ── Architecture Advisor ──────────────────────────────────────────────
@main.command("architect")
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
    from codegraph.extractor import load_graph0
    from codegraph.index import IndexStore

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    graph0 = load_graph0(root)
    with IndexStore(root) as index:
        advice = advise_architecture(
            graph0, index,
            god_module_threshold=god_module_threshold,
            fan_in_threshold=fan_in_threshold,
            fan_out_threshold=fan_out_threshold,
        )

    if save:
        path = advice.save(root)
        click.echo(f"Advice saved: {path}")

    if json_output:
        import json as _json
        click.echo(_json.dumps(advice.to_dict(), indent=2))
    else:
        click.echo(advice.format())


# ── Workflow Intent Enrichment ────────────────────────────────────────
@main.command("enrich")
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


# ── Architecture Evolution ────────────────────────────────────────────
@main.command("evolve")
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
    Shows what the architecture engine would do to converge the codebase.
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

    # 1. Load current state
    graph0 = load_graph0(root)
    workflow = load_workflow(root)
    arch = SystemArchitecture.load(root)

    if not arch:
        click.echo("No architecture defined. Use 'codegraph architecture --init'.",
                    err=True)
        sys.exit(EXIT_ERROR)

    # 2. Run advisor
    with IndexStore(root) as index:
        advice = advise_architecture(graph0, index)

    click.echo(f"=== Architecture Evolution ===")
    click.echo(f"Advisor findings: {len(advice.smells)} smells")
    for smell in advice.smells[:5]:
        click.echo(f"  - [{smell.severity}] {smell.smell_type}: {smell.entity}")

    # 3. Generate target from architecture
    target = generate_target_from_architecture(arch, workflow)
    click.echo(f"\nTarget workflow: {len(target.edges)} edges, {len(target.nodes)} nodes")

    # 4. Compute delta (target vs current)
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

    # 5. Generate tasks from delta
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

    # Save as agent_response.json
    resp_path = root / "agent_response.json"
    resp_path.write_text(
        _json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    click.echo(f"Agent response saved: {resp_path}")


# ── Multi-level Analysis ─────────────────────────────────────────────
@main.command("multilevel")
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


# ── Branch Management ─────────────────────────────────────────────────
@main.group("branch")
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


# ── Architecture Memory ──────────────────────────────────────────────
@main.command("arch-memory")
@click.option("--decisions", is_flag=True, help="Show recent decisions.")
@click.option("--experiments", is_flag=True, help="Show experiment results.")
@click.option("--tag", default=None, help="Filter by tag.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON output.")
@click.pass_context
def arch_memory_cmd(ctx: click.Context, decisions: bool, experiments: bool,
                    tag: str, json_output: bool) -> None:
    """View architecture decision memory."""
    import json as _json

    from codegraph.arch_memory import load_memory

    try:
        root = find_project_root()
    except FileNotFoundError as exc:
        handle_error(exc, ctx.obj.get("verbose", False))
        sys.exit(EXIT_ERROR)

    mem = load_memory(root)

    if json_output:
        click.echo(_json.dumps(mem.to_dict(), indent=2))
        return

    if decisions or (not decisions and not experiments):
        matched = mem.decisions
        if tag:
            matched = [d for d in matched if tag in d.tags]
        click.echo(f"Decisions ({len(matched)}):")
        for d in matched[-10:]:
            result_color = "green" if d.result == "success" else "red"
            click.echo(f"  [{d.decision_id}] {d.decision}")
            click.echo(f"    Result: " + click.style(d.result, fg=result_color))
            if d.reason:
                click.echo(f"    Reason: {d.reason}")

    if experiments:
        click.echo(f"\nExperiments ({len(mem.experiments)}):")
        for e in mem.experiments[-10:]:
            outcome_color = "green" if e.outcome == "success" else "red"
            click.echo(f"  [{e.experiment_id}] {e.branch_name}")
            click.echo(f"    Outcome: " + click.style(e.outcome, fg=outcome_color))
            if e.lesson:
                click.echo(f"    Lesson: {e.lesson}")
        rate = mem.get_experiment_success_rate()
        click.echo(f"  Success rate: {rate:.0%}")


# ── Subsystem Lifecycle ──────────────────────────────────────────────
@main.group("lifecycle")
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


# ── Compiler Commands ──────────────────────────────────────────────────


@main.command("compile")
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


@main.command("code-plan")
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


# ── Lock Commands ──────────────────────────────────────────────────────


@main.command("lock")
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


# ── Drift Commands ─────────────────────────────────────────────────────


@main.command("drift")
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


# ── Context Commands ───────────────────────────────────────────────────


@main.command("copilot-context")
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


# ── Architecture Simulator Commands ────────────────────────────────────


@main.command("arch-simulate")
@click.argument("subsystem_name")
@click.option("--depends-on", "deps", multiple=True,
              help="Dependencies for the new subsystem (repeatable).")
@click.option("--json", "json_output", is_flag=True, help="JSON output.")
@click.pass_context
def arch_simulate_cmd(ctx: click.Context, subsystem_name: str,
                      deps: tuple, json_output: bool) -> None:
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
