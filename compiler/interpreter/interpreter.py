"""Tree-walking interpreter for NovaLang.

Compiler concept: an *interpreter* executes the program directly by walking
the AST -- each node type has a method that knows how to run it (Visitor
pattern). Statements are executed for their effect; expressions are
evaluated and return a Python value:

    NovaLang   int    float    string   bool    nil    array
    Python     int    float    str      bool    None   list

It is independent of the semantic analyzer. It re-checks the things that can
only be known at run time (operand types of values that were "any" statically,
division by zero, array bounds, ...), so it is also safe to run on programs
that skipped semantic analysis.

Safety limits (important for a web playground):
* ``max_steps``       -- aborts runaway loops ("possible infinite loop").
* ``max_call_depth``  -- aborts runaway recursion ("stack overflow").
* strings are capped at ``MAX_STRING_LENGTH`` characters.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from compiler.errors.errors import NovaLangError, NovaRuntimeError
from compiler.interpreter.environment import Environment, UndefinedName
from compiler.parser import ast as A
from compiler.parser.parser import parse

MAX_STRING_LENGTH = 1_000_000
DEFAULT_MAX_STEPS = 1_000_000
DEFAULT_MAX_CALL_DEPTH = 500


# ----------------------------------------------------------------------
# Control-flow signals: not errors, just a way to unwind the Python stack
# ----------------------------------------------------------------------
class _Signal(Exception):
    pass


class ReturnSignal(_Signal):
    def __init__(self, value: Any) -> None:
        self.value = value


class BreakSignal(_Signal):
    pass


class ContinueSignal(_Signal):
    pass


# ----------------------------------------------------------------------
# Value helpers
# ----------------------------------------------------------------------
def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def type_name(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if v is None:
        return "nil"
    if isinstance(v, list):
        return "array"
    return "unknown"


def values_equal(a: Any, b: Any) -> bool:
    """NovaLang `==`: numbers compare numerically, everything else needs the
    same type (so `true == 1` is false); arrays compare element by element."""
    if _is_num(a) and _is_num(b):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    return False


def format_value(v: Any, _top: bool = True, _seen: Optional[set] = None) -> str:
    """Text shown by print(). Top-level strings print raw; strings nested in
    arrays are quoted so `[1, "a"]` stays readable."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "nil"
    if isinstance(v, str):
        return v if _top else '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(v, list):
        seen = _seen if _seen is not None else set()
        if id(v) in seen:
            return "[...]"
        seen.add(id(v))
        text = "[" + ", ".join(format_value(x, False, seen) for x in v) + "]"
        seen.discard(id(v))
        return text
    return str(v)


def _trunc_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


# ----------------------------------------------------------------------
class RuntimeFault(Exception):
    """A run-time problem found while evaluating ONE operation.

    It carries no line number: whoever evaluates the operation (the AST
    interpreter or the TAC runner) knows the source position and converts it
    into a NovaRuntimeError. This keeps one definition of every operator.
    """

    def __init__(self, message: str, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


def _type_fault(op: str, left: Any, right: Any) -> RuntimeFault:
    return RuntimeFault(
        f"Operator '{op}' cannot be applied to types {type_name(left)} and {type_name(right)}"
    )


def binary_op(op: str, left: Any, right: Any) -> Any:
    """Apply a non-short-circuit binary operator to two runtime values."""
    if op == "==":
        return values_equal(left, right)
    if op == "!=":
        return not values_equal(left, right)
    try:
        return _arith(op, left, right)
    except OverflowError:
        raise RuntimeFault("Numeric overflow")


def _arith(op: str, left: Any, right: Any) -> Any:
    both_num = _is_num(left) and _is_num(right)

    if op in ("<", ">", "<=", ">="):
        both_str = isinstance(left, str) and isinstance(right, str)
        if not (both_num or both_str):
            raise _type_fault(op, left, right)
        return {"<": left < right, ">": left > right,
                "<=": left <= right, ">=": left >= right}[op]

    if op == "+" and isinstance(left, str) and isinstance(right, str):
        if len(left) + len(right) > MAX_STRING_LENGTH:
            raise RuntimeFault("String too long")
        return left + right
    if not both_num:
        raise _type_fault(op, left, right)

    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    both_int = isinstance(left, int) and isinstance(right, int)
    if op == "/":
        if right == 0:
            raise RuntimeFault(
                "Division by zero",
                "The right-hand operand evaluated to 0; check it before dividing.")
        return _trunc_div(left, right) if both_int else left / right
    if op == "%":
        if right == 0:
            raise RuntimeFault(
                "Modulo by zero",
                "The right-hand operand evaluated to 0; check it before using %.")
        if both_int:
            return left - right * _trunc_div(left, right)
        return math.fmod(left, right)
    raise RuntimeFault(f"Unknown operator '{op}'")


def unary_op(op: str, value: Any) -> Any:
    """Apply unary '-' or '!' to a runtime value."""
    if op == "-":
        if not _is_num(value):
            raise RuntimeFault(f"Operator '-' cannot be applied to type {type_name(value)}")
        return -value
    if not isinstance(value, bool):
        raise RuntimeFault(f"Operator '!' cannot be applied to type {type_name(value)}")
    return not value


def check_index(container: Any, index: Any) -> None:
    """Validate ``container[index]`` (type of container, type of index, bounds)."""
    if not isinstance(container, (list, str)):
        raise RuntimeFault(f"Cannot index a value of type {type_name(container)}")
    if not isinstance(index, int) or isinstance(index, bool):
        raise RuntimeFault(f"Index must be an int, found {type_name(index)}")
    if not 0 <= index < len(container):
        kind = "array" if isinstance(container, list) else "string"
        raise RuntimeFault(
            f"Index {index} out of range for {kind} of length {len(container)}",
            "Valid positions run from 0 to length-1.",
        )


# ----------------------------------------------------------------------
@dataclass
class RunResult:
    output: str = ""
    errors: List[NovaLangError] = field(default_factory=list)
    steps: int = 0
    variables: Dict[str, str] = field(default_factory=dict)   # final globals, formatted

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "output": self.output,
            "errors": [e.to_dict() for e in self.errors],
            "steps": self.steps,
            "variables": dict(self.variables),
        }


class Interpreter(A.NodeVisitor):
    def __init__(
        self,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_call_depth: int = DEFAULT_MAX_CALL_DEPTH,
    ) -> None:
        self.max_steps = max_steps
        self.max_call_depth = max_call_depth
        self._reset()

    def _reset(self) -> None:
        self.globals = Environment()
        self.env = self.globals
        self.functions: Dict[str, A.FunctionDeclaration] = {}
        self.output: List[str] = []
        self.steps = 0
        self.call_stack: List[str] = []

    # ==================================================================
    # Entry point
    # ==================================================================
    def run(self, program: A.Program) -> RunResult:
        self._reset()
        errors: List[NovaLangError] = []
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 40_000))
        try:
            # Hoist function declarations so calls may precede them in the file.
            for node in program.body:
                if isinstance(node, A.FunctionDeclaration):
                    self.functions[node.name] = node
            for node in program.body:
                self._exec(node)
        except NovaLangError as err:
            errors.append(err)
        except ReturnSignal:
            errors.append(NovaRuntimeError("'return' outside of a function.", 0, 0))
        except (BreakSignal, ContinueSignal):
            errors.append(NovaRuntimeError("'break' or 'continue' outside of a loop.", 0, 0))
        except RecursionError:
            errors.append(NovaRuntimeError(
                "Stack overflow: the program recursed too deeply.", 0, 0,
                self._stack_hint(),
            ))
        finally:
            sys.setrecursionlimit(old_limit)
        variables = {
            k: format_value(v) for k, v in self.globals.values.items()
        }
        return RunResult("".join(self.output), errors, self.steps, variables)

    # ==================================================================
    # Helpers
    # ==================================================================
    def _stack_hint(self, extra: Optional[str] = None) -> Optional[str]:
        parts = []
        if extra:
            parts.append(extra)
        if self.call_stack:
            parts.append("Call stack: " + " -> ".join(["main"] + self.call_stack))
        return " ".join(parts) or None

    def _error(self, node: A.Node, message: str, hint: Optional[str] = None) -> NovaRuntimeError:
        return NovaRuntimeError(
            f"{message} at line {node.line}.", node.line, node.column, self._stack_hint(hint)
        )

    def _exec(self, node: A.Node) -> Any:
        """Execute one statement (counts toward the step limit)."""
        self.steps += 1
        if self.steps > self.max_steps:
            raise self._error(
                node, "Execution step limit exceeded",
                f"The program ran more than {self.max_steps:,} steps. "
                "This usually means an infinite loop.",
            )
        return node.accept(self)

    def _eval(self, node: A.Node) -> Any:
        return node.accept(self)

    def _condition(self, node: A.Node, what: str) -> bool:
        value = self._eval(node)
        if not isinstance(value, bool):
            raise self._error(
                node, f"Condition of '{what}' must be bool, found {type_name(value)}",
                "NovaLang has no truthiness; compare explicitly (e.g. x != 0).",
            )
        return value

    # ==================================================================
    # Statements
    # ==================================================================
    def visit_FunctionDeclaration(self, node: A.FunctionDeclaration) -> None:
        pass  # already registered by the hoisting pass in run()

    def visit_VariableDeclaration(self, node: A.VariableDeclaration) -> None:
        self.env.define(node.name, self._eval(node.initializer))

    def visit_Assignment(self, node: A.Assignment) -> None:
        value = self._eval(node.value)
        target = node.target
        if isinstance(target, A.Identifier):
            try:
                self.env.assign(target.name, value)
            except UndefinedName:
                raise self._error(target, f"Variable '{target.name}' is not defined")
            return
        # a[i] = value
        container = self._eval(target.object)
        index = self._eval(target.index)
        if isinstance(container, str):
            raise self._error(target, "Strings are immutable; cannot assign to a string index")
        self._check_index(container, index, target)
        container[index] = value

    def visit_ExpressionStatement(self, node: A.ExpressionStatement) -> None:
        self._eval(node.expression)

    def visit_PrintStatement(self, node: A.PrintStatement) -> None:
        self.output.append(format_value(self._eval(node.expression)) + "\n")

    def visit_Block(self, node: A.Block) -> None:
        saved = self.env
        self.env = Environment(saved)
        try:
            for stmt in node.statements:
                self._exec(stmt)
        finally:
            self.env = saved

    def visit_IfStatement(self, node: A.IfStatement) -> None:
        if self._condition(node.condition, "if"):
            self._exec(node.then_branch)
        elif node.else_branch is not None:
            self._exec(node.else_branch)

    def visit_WhileStatement(self, node: A.WhileStatement) -> None:
        while self._condition(node.condition, "while"):
            try:
                self._exec(node.body)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def visit_ForStatement(self, node: A.ForStatement) -> None:
        saved = self.env
        self.env = Environment(saved)       # scope for the loop variable
        try:
            self._exec(node.init)
            while self._condition(node.condition, "for"):
                try:
                    self._exec(node.body)
                except BreakSignal:
                    break
                except ContinueSignal:
                    pass                    # `continue` still runs the update step
                self._exec(node.update)
        finally:
            self.env = saved

    def visit_ReturnStatement(self, node: A.ReturnStatement) -> None:
        value = self._eval(node.value) if node.value is not None else None
        raise ReturnSignal(value)

    def visit_BreakStatement(self, node: A.BreakStatement) -> None:
        raise BreakSignal()

    def visit_ContinueStatement(self, node: A.ContinueStatement) -> None:
        raise ContinueSignal()

    # ==================================================================
    # Expressions
    # ==================================================================
    def visit_Literal(self, node: A.Literal) -> Any:
        return node.value

    def visit_Identifier(self, node: A.Identifier) -> Any:
        try:
            return self.env.get(node.name)
        except UndefinedName:
            if node.name in self.functions or node.name == "len":
                raise self._error(
                    node, f"'{node.name}' is a function and must be called with parentheses")
            raise self._error(node, f"Variable '{node.name}' is not defined")

    def visit_ArrayLiteral(self, node: A.ArrayLiteral) -> list:
        return [self._eval(e) for e in node.elements]

    def _check_index(self, container: Any, index: Any, node: A.Node) -> None:
        try:
            check_index(container, index)
        except RuntimeFault as fault:
            raise self._error(node, fault.message, fault.hint)

    def visit_IndexExpression(self, node: A.IndexExpression) -> Any:
        container = self._eval(node.object)
        index = self._eval(node.index)
        self._check_index(container, index, node)
        return container[index]

    def visit_UnaryExpression(self, node: A.UnaryExpression) -> Any:
        value = self._eval(node.operand)
        try:
            return unary_op(node.operator, value)
        except RuntimeFault as fault:
            raise self._error(node, fault.message, fault.hint)

    def visit_BinaryExpression(self, node: A.BinaryExpression) -> Any:
        op = node.operator

        # Short-circuit operators evaluate the right side only when needed.
        if op in ("&&", "||"):
            left = self._eval(node.left)
            self._require_bool(op, left, node)
            if (op == "&&" and not left) or (op == "||" and left):
                return left
            right = self._eval(node.right)
            self._require_bool(op, right, node)
            return right

        left = self._eval(node.left)
        right = self._eval(node.right)
        try:
            return binary_op(op, left, right)
        except RuntimeFault as fault:
            raise self._error(node, fault.message, fault.hint)
    
    def visit_TernaryExpression(self, node: A.TernaryExpression):
        condition = self._eval(node.condition)

        if not isinstance(condition, bool):
            raise self._error(
                node.condition,
                f"Ternary condition must be bool, found {type_name(condition)}",
                "Use a comparison such as x > 0 before '?'.",
            )

        if condition:
            return self._eval(node.true_expr)
        return self._eval(node.false_expr)

    def _require_bool(self, op: str, value: Any, node: A.Node) -> None:
        if not isinstance(value, bool):
            raise self._error(
                node, f"Operator '{op}' needs bool operands, found {type_name(value)}",
                "NovaLang has no truthiness; compare explicitly.",
            )

    # ------------------------------------------------------------ calls
    def visit_FunctionCall(self, node: A.FunctionCall) -> Any:
        callee = node.callee
        if not isinstance(callee, A.Identifier):
            raise self._error(node, "Only named functions can be called")
        name = callee.name
        args = [self._eval(a) for a in node.arguments]

        if name == "len" and name not in self.functions:
            if len(args) != 1:
                raise self._error(
                    callee, f"Function 'len' expects 1 argument but got {len(args)}")
            if not isinstance(args[0], (list, str)):
                raise self._error(
                    callee, f"len() expects an array or string, found {type_name(args[0])}")
            return len(args[0])

        fn = self.functions.get(name)
        if fn is None:
            try:
                self.env.get(name)
            except UndefinedName:
                raise self._error(callee, f"Function '{name}' is not defined")
            raise self._error(callee, f"'{name}' is a variable, not a function")

        if len(args) != len(fn.params):
            n = len(fn.params)
            raise self._error(
                callee,
                f"Function '{name}' expects {n} argument{'s' if n != 1 else ''} but got {len(args)}",
            )
        if len(self.call_stack) >= self.max_call_depth:
            raise self._error(
                callee, "Stack overflow",
                f"More than {self.max_call_depth} nested calls: the recursion probably "
                "has no base case.",
            )
        self.steps += 1
        if self.steps > self.max_steps:
            raise self._error(callee, "Execution step limit exceeded")

        saved = self.env
        self.env = Environment(self.globals)        # lexical scope: globals only
        for pname, value in zip(fn.params, args):
            self.env.define(pname, value)
        self.call_stack.append(name)
        try:
            for stmt in fn.body.statements:
                self._exec(stmt)
            return None
        except ReturnSignal as ret:
            return ret.value
        except (BreakSignal, ContinueSignal):
            raise self._error(node, "'break' or 'continue' outside of a loop")
        finally:
            self.call_stack.pop()
            self.env = saved


# ======================================================================
# Convenience wrappers
# ======================================================================
def interpret(
    program: A.Program,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_call_depth: int = DEFAULT_MAX_CALL_DEPTH,
) -> RunResult:
    """Execute an already-parsed program."""
    return Interpreter(max_steps, max_call_depth).run(program)


def run_source(source: str, **limits: int) -> RunResult:
    """Lex, parse and run *source*. NOTE: this does not run semantic analysis;
    the full pipeline (added with the API) does lex -> parse -> analyze -> run."""
    parsed = parse(source)
    if parsed.errors or parsed.program is None:
        return RunResult(errors=list(parsed.errors))
    return interpret(parsed.program, **limits)
