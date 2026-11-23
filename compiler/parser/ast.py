"""Abstract Syntax Tree (AST) for NovaLang.

Compiler concept: the parser turns a flat list of tokens into a *tree* that
captures the grammatical structure of the program. Parentheses, semicolons and
braces disappear -- the shape of the tree already says what groups with what.

    let x = 10 + 20;

        VariableDeclaration x
        └── BinaryExpression +
            ├── Literal 10
            └── Literal 20

Conventions
-----------
* Every node stores ``line`` and ``column`` (1-based) of the token that best
  represents it: the operator for binary/unary expressions, the first token
  for everything else. Later phases use this for error messages.
* ``to_dict()`` gives a JSON-friendly structure for the frontend graph view.
* Visitors: later phases (semantic analysis, interpreter, TAC generator)
  subclass ``NodeVisitor`` and implement ``visit_<NodeClassName>`` methods.
  ``node.accept(visitor)`` dispatches to the right one (the Visitor pattern).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, List, Optional


@dataclass(kw_only=True)
class Node:
    line: int = 0
    column: int = 0
    # Filled in by the semantic analyzer ("decorated AST"); None until then.
    inferred_type: Optional[str] = field(default=None, compare=False, repr=False)

    # -- Visitor pattern ---------------------------------------------------
    def accept(self, visitor: "NodeVisitor") -> Any:
        method = getattr(visitor, "visit_" + type(self).__name__, None)
        if method is None:
            return visitor.generic_visit(self)
        return method(self)

    # -- Presentation ------------------------------------------------------
    def label(self) -> str:
        """Short text shown next to the node name in trees and graphs."""
        return ""

    def children(self) -> List["Node"]:
        """Child nodes in source order (flattening list fields)."""
        out: List[Node] = []
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Node):
                out.append(value)
            elif isinstance(value, list):
                out.extend(v for v in value if isinstance(v, Node))
        return out

    def to_dict(self) -> dict:
        d: dict = {
            "type": type(self).__name__,
            "label": self.label(),
            "line": self.line,
            "column": self.column,
        }
        for f in fields(self):
            if f.name in ("line", "column"):
                continue
            value = getattr(self, f.name)
            if f.name == "inferred_type" and value is None:
                continue
            if isinstance(value, Node):
                d[f.name] = value.to_dict()
            elif isinstance(value, list):
                d[f.name] = [v.to_dict() if isinstance(v, Node) else v for v in value]
            else:
                d[f.name] = value
        return d


def tree_depth(root: Node) -> "tuple[int, Node]":
    """(depth of the deepest node, that node). The root has depth 1.

    Written with an explicit stack rather than recursion so it can measure a tree that
    is far too deep for the recursive passes (analyzer, interpreter) to handle.
    """
    deepest = (1, root)
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > deepest[0]:
            deepest = (depth, node)
        for f in fields(node):
            value = getattr(node, f.name)
            kids = value if isinstance(value, list) else [value]
            stack.extend((k, depth + 1) for k in kids if isinstance(k, Node))
    return deepest


class NodeVisitor:
    """Base class for tree walkers. Override ``visit_<NodeName>`` methods."""

    def visit(self, node: Node) -> Any:
        return node.accept(self)

    def generic_visit(self, node: Node) -> Any:
        raise NotImplementedError(f"{type(self).__name__} has no visit_{type(node).__name__}")


# ---------------------------------------------------------------- program
@dataclass
class Program(Node):
    body: List[Node] = field(default_factory=list)


# ------------------------------------------------------------- statements
@dataclass
class Block(Node):
    statements: List[Node] = field(default_factory=list)


@dataclass
class VariableDeclaration(Node):
    name: str = ""
    initializer: Optional[Node] = None

    def label(self) -> str:
        return self.name


@dataclass
class Assignment(Node):
    target: Optional[Node] = None   # Identifier or IndexExpression
    value: Optional[Node] = None

    def label(self) -> str:
        return "="


@dataclass
class ExpressionStatement(Node):
    expression: Optional[Node] = None


@dataclass
class PrintStatement(Node):
    expression: Optional[Node] = None


@dataclass
class IfStatement(Node):
    condition: Optional[Node] = None
    then_branch: Optional[Block] = None
    else_branch: Optional[Node] = None   # Block, IfStatement (else-if) or None


@dataclass
class WhileStatement(Node):
    condition: Optional[Node] = None
    body: Optional[Block] = None


@dataclass
class ForStatement(Node):
    init: Optional[Node] = None          # VariableDeclaration or Assignment
    condition: Optional[Node] = None
    update: Optional[Assignment] = None
    body: Optional[Block] = None


@dataclass
class FunctionDeclaration(Node):
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: Optional[Block] = None

    def label(self) -> str:
        return f"{self.name}({', '.join(self.params)})"


@dataclass
class ReturnStatement(Node):
    value: Optional[Node] = None


@dataclass
class BreakStatement(Node):
    pass


@dataclass
class ContinueStatement(Node):
    pass


# ------------------------------------------------------------ expressions
@dataclass
class BinaryExpression(Node):
    operator: str = ""
    left: Optional[Node] = None
    right: Optional[Node] = None

    def label(self) -> str:
        return self.operator

@dataclass
class TernaryExpression(Node):
    condition: Optional[Node] = None
    true_expr: Optional[Node] = None
    false_expr: Optional[Node] = None

    def label(self) -> str:
        return "?:"

@dataclass
class UnaryExpression(Node):
    operator: str = ""
    operand: Optional[Node] = None

    def label(self) -> str:
        return self.operator


@dataclass
class Literal(Node):
    value: Any = None
    literal_type: str = "nil"   # "int" | "float" | "string" | "bool" | "nil"

    def label(self) -> str:
        if self.literal_type == "string":
            return repr(self.value)
        if self.literal_type == "bool":
            return "true" if self.value else "false"
        if self.literal_type == "nil":
            return "nil"
        return str(self.value)


@dataclass
class Identifier(Node):
    name: str = ""

    def label(self) -> str:
        return self.name


@dataclass
class ArrayLiteral(Node):
    elements: List[Node] = field(default_factory=list)


@dataclass
class IndexExpression(Node):
    object: Optional[Node] = None
    index: Optional[Node] = None


@dataclass
class FunctionCall(Node):
    callee: Optional[Node] = None
    arguments: List[Node] = field(default_factory=list)


# ---------------------------------------------------------- tree printing
def format_tree(node: Node) -> str:
    """Render the tree as indented text with box-drawing characters."""
    lines: List[str] = []

    def title(n: Node) -> str:
        lab = n.label()
        return f"{type(n).__name__} {lab}" if lab else type(n).__name__

    def walk(n: Node, prefix: str, is_last: bool, is_root: bool) -> None:
        if is_root:
            lines.append(title(n))
            child_prefix = ""
        else:
            lines.append(prefix + ("└── " if is_last else "├── ") + title(n))
            child_prefix = prefix + ("    " if is_last else "│   ")
        kids = n.children()
        for i, kid in enumerate(kids):
            walk(kid, child_prefix, i == len(kids) - 1, False)

    walk(node, "", True, True)
    return "\n".join(lines)
