from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class _Scope:
    kind: str
    name: str
    bindings: Dict[str, str] = field(default_factory=dict)


class ScopeTree:
    def __init__(self) -> None:
        self._stack: List[_Scope] = []

    def push(self, kind: str, name: str) -> None:
        self._stack.append(_Scope(kind=kind, name=name))

    def pop(self) -> None:
        if self._stack:
            self._stack.pop()

    def bind(self, local_name: str, node_id: str) -> None:
        if self._stack:
            self._stack[-1].bindings[local_name] = node_id

    def resolve(self, name: str) -> Optional[str]:
        for scope in reversed(self._stack):
            if name in scope.bindings:
                return scope.bindings[name]
        return None
