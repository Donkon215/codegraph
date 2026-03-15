from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional, Union


@dataclass
class CallSite:
    raw_name: str
    line: int
    is_method_call: bool = False
    object_name: Optional[str] = None
    is_dynamic: bool = False


@dataclass
class DynamicCall:
    pattern: str
    line: int
    scope: str = ""


def _unparse_safe(node: ast.AST) -> Optional[str]:
    try:
        return ast.unparse(node)
    except Exception:
        return None


def extract_call_sites(
    func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
) -> List[CallSite]:
    calls: List[CallSite] = []

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.append(CallSite(raw_name=func.id, line=node.lineno))
            elif isinstance(func, ast.Attribute):
                obj = _unparse_safe(func.value)
                calls.append(
                    CallSite(
                        raw_name=f"{obj}.{func.attr}" if obj else func.attr,
                        line=node.lineno,
                        is_method_call=True,
                        object_name=obj,
                    )
                )
            else:
                calls.append(
                    CallSite(
                        raw_name=_unparse_safe(func) or "<dynamic>",
                        line=node.lineno,
                        is_dynamic=True,
                    )
                )

    return calls


def detect_dynamic_calls(
    func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    scope: str = "",
) -> List[DynamicCall]:
    dynamics: List[DynamicCall] = []

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue

        func = node.func

        if (
            isinstance(func, ast.Call)
            and isinstance(func.func, ast.Name)
            and func.func.id == "getattr"
        ):
            dynamics.append(DynamicCall(pattern="getattr", line=node.lineno, scope=scope))
            continue

        if isinstance(func, ast.Subscript):
            dynamics.append(DynamicCall(pattern="dict_dispatch", line=node.lineno, scope=scope))
            continue

        if not isinstance(func, (ast.Name, ast.Attribute)):
            dynamics.append(DynamicCall(pattern="indirect_call", line=node.lineno, scope=scope))

    return dynamics
