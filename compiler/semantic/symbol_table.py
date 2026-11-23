"""Symbol table for NovaLang.

Compiler concept: a *symbol table* records every name the program declares
(variables, parameters, functions) together with facts about it (kind, type,
where it was declared). Scopes are nested, and lookup walks outward from the
innermost scope to the global one -- this is *static (lexical) scoping*.

    global scope
    ├── function add          (params a, b live here)
    └── block                 (variables declared inside { } live here)

Scopes are kept after they are closed, so the whole tree can be shown to the
student afterwards (the "Symbol Table" tab).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Static types used by the semantic analyzer.
INT, FLOAT, STRING, BOOL, ARRAY, NIL, ANY = (
    "int", "float", "string", "bool", "array", "nil", "any",
)


@dataclass
class Symbol:
    name: str
    kind: str                    # "variable" | "parameter" | "function" | "builtin"
    type: str = ANY              # static type ("any" = not known until run time)
    line: int = 0
    column: int = 0
    params: Optional[List[str]] = None   # functions / builtins only
    scope: str = ""              # name of the scope that owns it (filled by declare)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "kind": self.kind,
            "type": self.type,
            "line": self.line,
            "column": self.column,
            "scope": self.scope,
        }
        if self.params is not None:
            d["params"] = list(self.params)
        return d


# Built-in functions live outside every scope; they can be called but not redeclared.
BUILTINS: Dict[str, Symbol] = {
    "len": Symbol("len", "builtin", INT, 0, 0, params=["value"], scope="builtin"),
}


@dataclass
class Scope:
    name: str
    kind: str                    # "global" | "function" | "block" | "for"
    level: int
    parent: Optional["Scope"] = None
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    children: List["Scope"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "level": self.level,
            "symbols": [s.to_dict() for s in self.symbols.values()],
            "children": [c.to_dict() for c in self.children],
        }


class SymbolTable:
    def __init__(self) -> None:
        self.global_scope = Scope("global", "global", 0)
        self.current = self.global_scope

    # ------------------------------------------------------------ scopes
    def enter_scope(self, name: str, kind: str = "block") -> Scope:
        scope = Scope(name, kind, self.current.level + 1, parent=self.current)
        self.current.children.append(scope)
        self.current = scope
        return scope

    def exit_scope(self) -> None:
        if self.current.parent is None:
            raise RuntimeError("cannot exit the global scope")
        self.current = self.current.parent

    @property
    def depth(self) -> int:
        return self.current.level

    # ----------------------------------------------------- declare / lookup
    def declare(self, symbol: Symbol) -> Optional[Symbol]:
        """Add *symbol* to the current scope.

        Returns None on success. If the name is already taken (in this very
        scope, or by a built-in) nothing is inserted and the *existing*
        symbol is returned so the caller can report a precise error.
        """
        if symbol.name in BUILTINS:
            return BUILTINS[symbol.name]
        existing = self.current.symbols.get(symbol.name)
        if existing is not None:
            return existing
        symbol.scope = self.current.name
        self.current.symbols[symbol.name] = symbol
        return None

    def lookup_local(self, name: str) -> Optional[Symbol]:
        return self.current.symbols.get(name)

    def lookup(self, name: str) -> Optional[Symbol]:
        """Search the current scope, then each enclosing scope, then built-ins."""
        scope: Optional[Scope] = self.current
        while scope is not None:
            sym = scope.symbols.get(name)
            if sym is not None:
                return sym
            scope = scope.parent
        return BUILTINS.get(name)

    # --------------------------------------------------------------- output
    def to_dict(self) -> dict:
        return self.global_scope.to_dict()

    def all_symbols(self) -> List[Symbol]:
        """Every symbol in every scope, in declaration-tree order."""
        out: List[Symbol] = []

        def walk(scope: Scope) -> None:
            out.extend(scope.symbols.values())
            for child in scope.children:
                walk(child)

        walk(self.global_scope)
        return out
