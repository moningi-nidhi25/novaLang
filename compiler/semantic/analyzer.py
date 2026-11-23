"""Semantic analyzer for NovaLang.

Compiler concept: the parser only proves the program is *grammatical*. Semantic
analysis checks that it *makes sense*:

* every name is declared before it is used (scope rules),
* operators get operands of suitable types (type checking),
* calls match their function's parameters (arity),
* ``return`` / ``break`` / ``continue`` appear only where they are allowed.

It walks the AST once using the Visitor pattern, consulting and filling the
symbol table. Expression visitors return the expression's *static type*
("int", "float", "string", "bool", "array", "nil" or "any"), and the type is
also stored on the node (``node.inferred_type``): a "decorated AST".

"any" means "not known until run time" (function parameters and call results);
checks involving "any" are postponed to the interpreter. The analyzer never
stops at the first error: a failed expression is given type "any" so that one
mistake does not trigger a cascade of follow-up errors.

This module is independent of the interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from compiler.errors.errors import NovaLangError, SemanticError, SemanticWarning
from compiler.parser import ast as A
from compiler.parser.parser import parse
from compiler.semantic.symbol_table import (
    ANY, ARRAY, BOOL, FLOAT, INT, NIL, STRING, Symbol, SymbolTable,
)

NUMERIC = {INT, FLOAT}
ARITHMETIC_OPS = {"+", "-", "*", "/", "%"}
ORDERING_OPS = {"<", ">", "<=", ">="}
EQUALITY_OPS = {"==", "!="}
LOGICAL_OPS = {"&&", "||"}

ARITH_HINT = (
    "Arithmetic operators work on int and float values ('+' also joins two "
    "strings). NovaLang never converts types behind your back."
)


def binary_result_type(op: str, lt: str, rt: str) -> Optional[str]:
    """Static result type of ``lt op rt``, or None if the combination is illegal."""
    if op in EQUALITY_OPS:
        return BOOL
    if op in LOGICAL_OPS:
        return BOOL if lt in (BOOL, ANY) and rt in (BOOL, ANY) else None
    if op in ORDERING_OPS:
        if lt in NUMERIC | {ANY} and rt in NUMERIC | {ANY}:
            return BOOL
        if lt in (STRING, ANY) and rt in (STRING, ANY):
            return BOOL
        return None
    # arithmetic
    if lt == ANY and rt == ANY:
        return ANY
    if op == "+" and STRING in (lt, rt):
        return STRING if lt in (STRING, ANY) and rt in (STRING, ANY) else None
    if lt in NUMERIC | {ANY} and rt in NUMERIC | {ANY}:
        if FLOAT in (lt, rt):
            return FLOAT
        if lt == INT and rt == INT:
            return INT
        return ANY            # int combined with an unknown value
    return None


def assignable(target: str, value: str) -> bool:
    """May a value of static type *value* be stored in a variable of type *target*?"""
    if target == ANY or value == ANY or target == value:
        return True
    return target == FLOAT and value == INT      # widening int -> float is allowed


# ----------------------------------------------------------------------
@dataclass
class SemanticResult:
    errors: List[NovaLangError] = field(default_factory=list)
    warnings: List[SemanticWarning] = field(default_factory=list)
    info: List[dict] = field(default_factory=list)       # "x declared successfully" log
    symbol_table: Optional[SymbolTable] = None
    program: Optional[A.Program] = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "info": list(self.info),
            "symbol_table": self.symbol_table.to_dict() if self.symbol_table else None,
        }


class SemanticAnalyzer(A.NodeVisitor):
    def __init__(self) -> None:
        self.table = SymbolTable()
        self.errors: List[NovaLangError] = []
        self.warnings: List[SemanticWarning] = []
        self.info: List[dict] = []
        self.loop_depth = 0
        self.function_depth = 0

    # ==================================================================
    # Entry point
    # ==================================================================
    def analyze(self, program: A.Program) -> SemanticResult:
        # Pass 1: declare every function so calls may appear before the
        # declaration and recursion / mutual recursion work ("hoisting").
        for node in program.body:
            if isinstance(node, A.FunctionDeclaration):
                self._declare_function(node)
        # Pass 2: check everything in source order.
        self._statements(program.body, check_unreachable=False)
        return SemanticResult(
            self.errors, self.warnings, self.info, self.table, program
        )

    # ==================================================================
    # Reporting helpers
    # ==================================================================
    def _error(self, node: A.Node, message: str, hint: Optional[str] = None) -> None:
        self.errors.append(SemanticError(message, node.line, node.column, hint))

    def _warn(self, node: A.Node, message: str, hint: Optional[str] = None) -> None:
        self.warnings.append(SemanticWarning(message, node.line, node.column, hint))

    def _note(self, node: A.Node, message: str) -> None:
        self.info.append({"line": node.line, "column": node.column, "message": message})

    # ==================================================================
    # Generic expression / statement dispatch
    # ==================================================================
    def _expr(self, node: A.Node) -> str:
        t = node.accept(self)
        node.inferred_type = t
        return t

    def _statements(self, stmts: List[A.Node], check_unreachable: bool = True) -> None:
        terminator: Optional[str] = None
        warned = False
        for s in stmts:
            if terminator and not warned and check_unreachable:
                self._warn(
                    s, f"Unreachable code after '{terminator}'.",
                    "Statements after return/break/continue in the same block can "
                    "never run.",
                )
                warned = True
            s.accept(self)
            if isinstance(s, A.ReturnStatement):
                terminator = "return"
            elif isinstance(s, A.BreakStatement):
                terminator = "break"
            elif isinstance(s, A.ContinueStatement):
                terminator = "continue"

    def _condition(self, node: A.Node, what: str) -> None:
        t = self._expr(node)
        if t not in (BOOL, ANY):
            self._error(
                node, f"Condition of '{what}' must be bool, found {t}.",
                "NovaLang has no truthiness: use a comparison such as x != 0 "
                "to produce a bool.",
            )

    # ==================================================================
    # Declarations
    # ==================================================================
    def _declare_function(self, node: A.FunctionDeclaration) -> None:
        sym = Symbol(node.name, "function", ANY, node.line, node.column, params=list(node.params))
        existing = self.table.declare(sym)
        if existing is None:
            n = len(node.params)
            self._note(node, f"Function '{node.name}' declared with {n} parameter{'s' if n != 1 else ''}.")
        elif existing.kind == "builtin":
            self._error(node, f"'{node.name}' is a built-in function and cannot be redeclared.")
        else:
            self._error(
                node, f"Function '{node.name}' is already declared (line {existing.line}).",
                "Each name may be declared only once per scope.",
            )

    def visit_FunctionDeclaration(self, node: A.FunctionDeclaration) -> None:
        self.table.enter_scope(f"function {node.name}", "function")
        self.function_depth += 1
        saved_loops, self.loop_depth = self.loop_depth, 0
        for pname in node.params:
            existing = self.table.declare(Symbol(pname, "parameter", ANY, node.line, node.column))
            if existing is not None:
                self._error(node, f"Duplicate parameter '{pname}' in function '{node.name}'.")
        # Parameters and the body's top-level statements share one scope, so
        # `function f(a) { let a = 1; }` is a duplicate declaration.
        self._statements(node.body.statements)
        self.loop_depth = saved_loops
        self.function_depth -= 1
        self.table.exit_scope()

    def visit_VariableDeclaration(self, node: A.VariableDeclaration) -> None:
        # Analyse the initializer BEFORE declaring the name, so the new variable
        # is not visible inside its own initializer.
        t = self._expr(node.initializer)
        var_type = ANY if t == NIL else t        # `let x = nil;` may hold anything later
        existing = self.table.declare(Symbol(node.name, "variable", var_type, node.line, node.column))
        if existing is None:
            self._note(node, f"Variable '{node.name}' declared successfully (type: {var_type}).")
        elif existing.kind == "builtin":
            self._error(node, f"'{node.name}' is a built-in function and cannot be redeclared.")
        elif existing.kind == "function":
            self._error(
                node, f"'{node.name}' is already declared as a function (line {existing.line}).",
                "Functions and variables share one namespace.",
            )
        else:
            self._error(
                node, f"Variable '{node.name}' is already declared in this scope (line {existing.line}).",
                "Declare a variable once with 'let'; to change it later use plain "
                f"assignment: {node.name} = ...;",
            )

    # ==================================================================
    # Statements
    # ==================================================================
    def visit_Program(self, node: A.Program) -> None:  # pragma: no cover - analyze() drives this
        self._statements(node.body, check_unreachable=False)

    def visit_Block(self, node: A.Block) -> None:
        self.table.enter_scope("block", "block")
        self._statements(node.statements)
        self.table.exit_scope()

    def visit_ExpressionStatement(self, node: A.ExpressionStatement) -> None:
        self._expr(node.expression)

    def visit_PrintStatement(self, node: A.PrintStatement) -> None:
        self._expr(node.expression)

    def visit_Assignment(self, node: A.Assignment) -> None:
        value_type = self._expr(node.value)
        target = node.target
        if isinstance(target, A.Identifier):
            sym = self.table.lookup(target.name)
            target.inferred_type = ANY
            if sym is None:
                self._error(
                    target, f"Variable '{target.name}' is not defined.",
                    f"Declare it first with: let {target.name} = ...;",
                )
                return
            if sym.kind in ("function", "builtin"):
                self._error(target, f"Cannot assign to function '{target.name}'.")
                return
            target.inferred_type = sym.type
            if not assignable(sym.type, value_type):
                self._error(
                    node,
                    f"Cannot assign {value_type} to variable '{target.name}' of type {sym.type}.",
                    "A variable keeps the type of its initial value (int may widen to "
                    "float). Declare a new variable if you need a different type.",
                )
            else:
                self._note(node, f"Assignment to '{target.name}' is valid ({value_type} -> {sym.type}).")
        else:  # IndexExpression: a[i] = value
            obj_type = self._expr(target)
            if isinstance(target, A.IndexExpression) and target.object.inferred_type == STRING:
                self._error(
                    target, "Strings are immutable; cannot assign to a string index.",
                    "Build a new string instead of changing characters in place.",
                )

    def visit_IfStatement(self, node: A.IfStatement) -> None:
        self._condition(node.condition, "if")
        node.then_branch.accept(self)
        if node.else_branch is not None:
            node.else_branch.accept(self)

    def visit_WhileStatement(self, node: A.WhileStatement) -> None:
        self._condition(node.condition, "while")
        self.loop_depth += 1
        node.body.accept(self)
        self.loop_depth -= 1

    def visit_ForStatement(self, node: A.ForStatement) -> None:
        # The loop variable lives in its own scope that wraps the whole loop.
        self.table.enter_scope("for", "for")
        node.init.accept(self)
        self._condition(node.condition, "for")
        node.update.accept(self)
        self.loop_depth += 1
        node.body.accept(self)
        self.loop_depth -= 1
        self.table.exit_scope()

    def visit_ReturnStatement(self, node: A.ReturnStatement) -> None:
        if self.function_depth == 0:
            self._error(
                node, "'return' outside of a function.",
                "return only makes sense inside a function body.",
            )
        if node.value is not None:
            self._expr(node.value)

    def visit_BreakStatement(self, node: A.BreakStatement) -> None:
        if self.loop_depth == 0:
            self._error(node, "'break' outside of a loop.",
                        "break may only appear inside a while or for loop.")

    def visit_ContinueStatement(self, node: A.ContinueStatement) -> None:
        if self.loop_depth == 0:
            self._error(node, "'continue' outside of a loop.",
                        "continue may only appear inside a while or for loop.")

    # ==================================================================
    # Expressions (each returns the static type)
    # ==================================================================
    def visit_Literal(self, node: A.Literal) -> str:
        return node.literal_type

    def visit_Identifier(self, node: A.Identifier) -> str:
        sym = self.table.lookup(node.name)
        if sym is None:
            self._error(
                node, f"Variable '{node.name}' is not defined.",
                f"Declare it before use with: let {node.name} = ...; "
                "(and check the spelling and the scope it was declared in).",
            )
            return ANY
        if sym.kind in ("function", "builtin"):
            self._error(
                node, f"'{node.name}' is a function and must be called with parentheses.",
                f"Write {node.name}(...) to call it; functions are not values in NovaLang.",
            )
            return ANY
        return sym.type

    def visit_ArrayLiteral(self, node: A.ArrayLiteral) -> str:
        for e in node.elements:
            self._expr(e)
        return ARRAY

    def visit_IndexExpression(self, node: A.IndexExpression) -> str:
        obj_t = self._expr(node.object)
        idx_t = self._expr(node.index)
        result = ANY
        if obj_t == STRING:
            result = STRING
        elif obj_t not in (ARRAY, ANY):
            self._error(
                node, f"Cannot index a value of type {obj_t}.",
                "Only arrays and strings can be indexed with [ ].",
            )
        if idx_t not in (INT, ANY):
            self._error(
                node.index, f"Index must be an int, found {idx_t}.",
                "Array positions are whole numbers starting at 0.",
            )
        elif self._is_negative_constant(node.index):
            self._error(
                node.index, "Index cannot be negative.",
                "Valid positions run from 0 to length-1.",
            )
        return result

    @staticmethod
    def _is_negative_constant(n: A.Node) -> bool:
        return (
            isinstance(n, A.UnaryExpression) and n.operator == "-"
            and isinstance(n.operand, A.Literal) and n.operand.literal_type == "int"
            and n.operand.value > 0
        )

    def visit_UnaryExpression(self, node: A.UnaryExpression) -> str:
        t = self._expr(node.operand)
        if node.operator == "-":
            if t in NUMERIC or t == ANY:
                return t
            self._error(
                node, f"Operator '-' cannot be applied to type {t}.",
                "Unary minus works on int and float values.",
            )
            return ANY
        # '!'
        if t in (BOOL, ANY):
            return BOOL
        self._error(
            node, f"Operator '!' cannot be applied to type {t}.",
            "'!' works on bool values only; compare first, e.g. !(x == 0).",
        )
        return BOOL

    def visit_BinaryExpression(self, node: A.BinaryExpression) -> str:
        lt = self._expr(node.left)
        rt = self._expr(node.right)
        result = binary_result_type(node.operator, lt, rt)
        if node.operator in ("/", "%") and self._is_zero(node.right):
            self._warn(
                node, "Division by zero: the right operand is the constant 0.",
                "The program is still valid, but it will fail at run time when this runs.",
            )
        if result is None:
            if node.operator in LOGICAL_OPS:
                hint = "Logical operators need bool operands; there is no truthiness in NovaLang."
            elif node.operator in ORDERING_OPS:
                hint = "Ordering comparisons work on two numbers or two strings."
            else:
                hint = ARITH_HINT
            self._error(
                node,
                f"Operator '{node.operator}' cannot be applied to types {lt} and {rt}.",
                hint,
            )
            return BOOL if node.operator in ORDERING_OPS | LOGICAL_OPS else ANY
        return result

    def visit_TernaryExpression(self, node: A.TernaryExpression) -> str:
        condition_type = self._expr(node.condition)
        true_type = self._expr(node.true_expr)
        false_type = self._expr(node.false_expr)

        if condition_type not in (BOOL, ANY):
            self._error(
                node.condition,
                f"Ternary condition must be bool, found {condition_type}.",
                "Use a comparison such as x > 0 before '?'.",
            )

        if true_type == false_type:
            return true_type

        if true_type in NUMERIC and false_type in NUMERIC:
            return FLOAT if FLOAT in (true_type, false_type) else INT

        if ANY in (true_type, false_type):
            return ANY

        self._error(
            node,
            f"Ternary alternatives have incompatible types "
            f"{true_type} and {false_type}.",
            "Use compatible types on both sides of ':'.",
        )

        return ANY

    @staticmethod
    def _is_zero(n: A.Node) -> bool:
        return isinstance(n, A.Literal) and n.literal_type in ("int", "float") and n.value == 0

    def visit_FunctionCall(self, node: A.FunctionCall) -> str:
        for a in node.arguments:
            self._expr(a)
        callee = node.callee
        if not isinstance(callee, A.Identifier):
            self._error(
                node, "Only named functions can be called.",
                "NovaLang functions are not values; call them by name: name(args).",
            )
            return ANY
        sym = self.table.lookup(callee.name)
        if sym is None:
            self._error(
                callee, f"Function '{callee.name}' is not defined.",
                "Declare it with: function name(params) { ... }",
            )
            return ANY
        if sym.kind not in ("function", "builtin"):
            self._error(
                callee, f"'{callee.name}' is a variable, not a function.",
                "Only functions can be called with ( ).",
            )
            return ANY
        expected = len(sym.params or [])
        got = len(node.arguments)
        if expected != got:
            self._error(
                callee,
                f"Function '{callee.name}' expects {expected} argument"
                f"{'s' if expected != 1 else ''} but got {got}.",
                f"Declared at line {sym.line} as {callee.name}({', '.join(sym.params or [])})."
                if sym.kind == "function" else
                f"Built-in signature: {callee.name}({', '.join(sym.params or [])}).",
            )
        if sym.kind == "builtin" and callee.name == "len" and expected == got:
            at = node.arguments[0].inferred_type
            if at not in (ARRAY, STRING, ANY):
                self._error(
                    node.arguments[0], f"len() expects an array or string, found {at}.",
                    "len(x) gives the number of elements of an array or characters of a string.",
                )
        callee.inferred_type = "function"
        return sym.type


# ======================================================================
# Convenience wrappers
# ======================================================================
def analyze(program: A.Program) -> SemanticResult:
    """Run semantic analysis on an already-parsed program."""
    return SemanticAnalyzer().analyze(program)


def analyze_source(source: str) -> SemanticResult:
    """Lex, parse and analyze *source*.

    Lexical or syntax errors are returned in ``errors`` and analysis is skipped:
    semantic checks on a broken tree would only be misleading.
    """
    parsed = parse(source)
    if parsed.errors or parsed.program is None:
        return SemanticResult(errors=list(parsed.errors), program=parsed.program)
    return analyze(parsed.program)
