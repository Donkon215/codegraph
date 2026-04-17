"""codegraph.copilot_briefing — Quick edit briefing card for Copilot.

Generates a compact 8-12 line markdown card for a file that Copilot
reads before making any edits. Covers: layer, subsystem, fan-in/out,
violations, smells, verdict, and recommended next action.

Extracted from copilot_context_builder.py for single-responsibility.
Re-exported from copilot_context_builder for backward compatibility.

CLI command: codegraph arch-context <file> [--save] [--json]
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from codegraph.logging_config import get_logger

logger = get_logger("copilot_briefing")


def quick_edit_briefing(
    project_root: Path,
    file_path: str,
    *,
    include_decision: bool = True,
) -> str:
    """Generate a compact markdown briefing card for a file.

    Designed to be the FIRST thing Copilot reads before editing a file.
    8-12 lines covering everything needed to make safe decisions.

    Args:
        project_root: Project root path.
        file_path: Relative file path to brief on.
        include_decision: Whether to include a recommended action.

    Returns:
        Markdown string suitable for embedding in .codegraph/feedback.md
        or printing inline in a Copilot chat.
    """
    from codegraph.copilot_focus import focus_context
    from codegraph.copilot_hotspots import hotspot_context

    focus = focus_context(project_root, file_path, depth=1)
    hotspots = hotspot_context(project_root)

    # Determine verdict
    if not focus.nodes:
        verdict = "UNKNOWN -- run `codegraph build` first"
        verdict_tag = "?"
    elif focus.violations:
        verdict = "CAUTION -- violations exist"
        verdict_tag = "CAUTION"
    elif focus.fan_out > 15 or focus.fan_in > 20:
        verdict = "CAUTION -- high coupling"
        verdict_tag = "CAUTION"
    elif focus.smells:
        verdict = "REVIEW -- smells detected"
        verdict_tag = "REVIEW"
    else:
        verdict = "SAFE -- proceed"
        verdict_tag = "SAFE"

    lines: List[str] = [
        f"## Architecture Briefing: `{file_path}`",
        f"",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Layer** | {focus.layer or 'unknown'} |",
        f"| **Subsystem** | {focus.subsystem or 'unknown'} |",
        f"| **Fan-in** | {focus.fan_in} callers |",
        f"| **Fan-out** | {focus.fan_out} callees |",
        f"| **Violations** | {len(focus.violations)} |",
        f"| **Smells** | {len(focus.smells)} |",
        f"| **System Score** | {hotspots.score:.2f} {hotspots.grade} |",
        f"| **Verdict** | [{verdict_tag}] {verdict} |",
        f"",
    ]

    if focus.violations:
        lines.append("**Violations (must fix first):**")
        for v in focus.violations[:5]:
            lines.append(f"- {v}")
        lines.append("")

    if focus.smells:
        lines.append("**Smells:**")
        for s in focus.smells[:3]:
            stype = s.get("smell_type", "?")
            desc = s.get("description", "")
            lines.append(f"- `{stype}`: {desc}")
        lines.append("")

    if focus.constraints:
        lines.append("**Active Constraints:**")
        for c in focus.constraints[:3]:
            lines.append(f"- {c}")
        lines.append("")

    if include_decision:
        if focus.violations:
            action = f"Fix {len(focus.violations)} violation(s) before editing"
            command = f"codegraph decide {file_path} --json"
        elif focus.fan_out > 15:
            action = f"High fan-out ({focus.fan_out}): extract helpers before adding more deps"
            command = f"codegraph scenario --components {file_path} --json"
        elif focus.fan_in > 20:
            action = (
                f"High fan-in ({focus.fan_in}): changes here blast {focus.fan_in} callers"
                f" -- simulate first"
            )
            command = f"codegraph copilot-loop {file_path} --simulate --json"
        else:
            action = "Safe to edit"
            command = f"codegraph focus {file_path} --json"

        lines.append(f"**Recommended Action:** {action}")
        lines.append(f"**Next Command:** `{command}`")
        lines.append("")

    lines.append("**Post-edit:** `codegraph build && codegraph analyze && codegraph score`")

    return "\n".join(lines)


def save_quick_briefing_to_feedback(
    project_root: Path,
    file_path: str,
    *,
    append: bool = False,
) -> Path:
    """Generate a quick briefing and write it to .codegraph/feedback.md.

    By default overwrites the file so it stays small and Copilot always
    reads fresh context. Pass ``append=True`` to keep prior server prompts
    below the new briefing (useful when the reactive server is running).
    """
    briefing = quick_edit_briefing(project_root, file_path)

    feedback_dir = project_root / ".codegraph"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / "feedback.md"

    if append and feedback_path.exists():
        try:
            existing = feedback_path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        content = briefing + "\n\n---\n\n" + existing if existing else briefing
    else:
        content = briefing

    feedback_path.write_text(content, encoding="utf-8")
    return feedback_path
