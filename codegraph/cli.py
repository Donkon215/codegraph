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
