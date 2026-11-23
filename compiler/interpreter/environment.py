"""Runtime environments (variable storage) for the NovaLang interpreter.

Compiler concept: at run time every active scope owns an *environment*, a
table mapping names to current values. Environments form a chain through
``parent``; looking a name up walks outward, exactly like the compile-time
symbol table -- but here the table holds real values instead of types.

    global env      {result: 120}
    └── function env {n: 5}           <- created per call
        └── block env {tmp: 4}        <- created per { } block

Note: a function call's environment is parented to the *global* environment,
not to the caller's. That is static (lexical) scoping: a function sees the
globals and its own locals, never the locals of whoever called it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class UndefinedName(KeyError):
    """Raised when a name is not found in any enclosing environment."""


class Environment:
    def __init__(self, parent: Optional["Environment"] = None) -> None:
        self.values: Dict[str, Any] = {}
        self.parent = parent

    def define(self, name: str, value: Any) -> None:
        """Create (or overwrite) *name* in THIS environment (used by `let`)."""
        self.values[name] = value

    def get(self, name: str) -> Any:
        env: Optional[Environment] = self
        while env is not None:
            if name in env.values:
                return env.values[name]
            env = env.parent
        raise UndefinedName(name)

    def assign(self, name: str, value: Any) -> None:
        """Update the nearest existing binding of *name* (used by `x = ...`)."""
        env: Optional[Environment] = self
        while env is not None:
            if name in env.values:
                env.values[name] = value
                return
            env = env.parent
        raise UndefinedName(name)

    def depth(self) -> int:
        d, env = 0, self.parent
        while env is not None:
            d += 1
            env = env.parent
        return d
