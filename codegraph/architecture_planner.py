"""codegraph.architecture_planner — Planning layer API surface.

Compatibility module exposing architecture planning APIs via stable naming.
"""

from codegraph.arch_planner import plan_architecture, plan_to_agent_response

__all__ = ["plan_architecture", "plan_to_agent_response"]
