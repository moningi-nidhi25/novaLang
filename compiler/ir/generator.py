"""AST -> Three Address Code generator.

Compiler concept: *intermediate code generation*. The generator walks the
(semantically valid) AST and flattens it into TAC. Two ideas do all the work:

1. Every expression returns the *operand* (a variable, constant or fresh
   temporary) that holds its value, after emitting the instructions that
   compute it:

       (a + b) * c   ->   t1 = a + b      (returns "t1")
                          t2 = t1 * c     (returns "t2")

2. Control flow becomes labels and jumps:

       if (c) { A } else { B }          while (c) { A }
       -----------------------          -----------------
           ifFalse c goto L1            L1:
           A                                ifFalse c goto L2
           goto L2                          A
       L1:                                  goto L1
           B                            L2:
       L2:

   ``break`` jumps to the loop's end label, ``continue`` to its start (or, in
   a ``for`` loop, to the update step).

Details worth knowing
---------------------
* Shadowing: TAC has one flat namespace per function, so a variable declared
  in an inner scope that reuses a name gets a fresh name (``x`` -> ``x_1``).
  Likewise a function's own variables never share a name with a global.
* Temporaries are named t1, t2, ... (restarting in every function) and skip
  any name the program already uses, so a user variable called ``t1`` is safe.
* ``&&`` and ``||`` short-circuit, so they compile to jumps, not an operator.
* Evaluation order matches the interpreter. If a later operand contains a call
  (which could modify a global), an earlier operand that is a global variable
  is first copied into a temporary so it is read at the right moment.

Input must already have passed semantic analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from compiler.errors.errors import NovaLangError
from compiler.ir import tac as T
from compiler.ir.tac import TACFunction, TACInstruction, TACProgram, format_constant
from compiler.parser import ast as A
from compiler.semantic.analyzer import analyze_source


class _Frame:
    """Per-function generation state."""

    def __init__(self, is_main: bool) -> None:
        self.is_main = is_main
        self.code: List[TACInstruction] = []
        self.scopes: List[Dict[str, str]] = [{}]    # source name -> TAC name
        self.used: Set[str] = set()                 # TAC variable names in this frame
        self.temp_counter = 0


@dataclass
class _Loop:
    break_label: str
    continue_label: Optional[str] = None            # allocated lazily for `for` loops


def _has_call(node: A.Node) -> bool:
    if isinstance(node, A.FunctionCall):
        return True
    return any(_has_call(child) for child in node.children())


class TACGenerator(A.NodeVisitor):
    def __init__(self, program: A.Program) -> None:
        self.program = program
        self.reserved: Set[str] = set()
        self._collect_names(program)
        self.global_names: Set[str] = {
            n.name for n in program.body if isinstance(n, A.VariableDeclaration)
        }
        self.label_counter = 0
        self.frame: _Frame = _Frame(True)
        self.loops: List[_Loop] = []

    # ==================================================================
    # Entry point
    # ==================================================================
    def generate(self) -> TACProgram:
        main = TACFunction("main")
        self.frame = _Frame(is_main=True)
        for node in self.program.body:
            if not isinstance(node, A.FunctionDeclaration):
                node.accept(self)
        main.instructions = self.frame.code

        functions = [
            self._function(node)
            for node in self.program.body
            if isinstance(node, A.FunctionDeclaration)
        ]
        globals_ = [n.name for n in self.program.body if isinstance(n, A.VariableDeclaration)]
        return TACProgram(main, functions, globals_)

    def _function(self, node: A.FunctionDeclaration) -> TACFunction:
        self.frame = _Frame(is_main=False)
        self.loops = []
        params = [self._declare(p) for p in node.params]
        for stmt in node.body.statements:      # params and body share one scope
            stmt.accept(self)
        code = self.frame.code
        if not code or code[-1].op != T.OP_RETURN:
            self._emit(T.OP_RETURN, "nil", node=node)    # falling off the end returns nil
        return TACFunction(node.name, params, code)

    # ==================================================================
    # Naming
    # ==================================================================
    def _collect_names(self, node: A.Node) -> None:
        if isinstance(node, A.Identifier):
            self.reserved.add(node.name)
        elif isinstance(node, A.VariableDeclaration):
            self.reserved.add(node.name)
        elif isinstance(node, A.FunctionDeclaration):
            self.reserved.add(node.name)
            self.reserved.update(node.params)
        for child in node.children():
            self._collect_names(child)

    def _fresh(self, base: str) -> str:
        n = 1
        while f"{base}_{n}" in self.reserved:
            n += 1
        name = f"{base}_{n}"
        self.reserved.add(name)
        return name

    def _declare(self, name: str) -> str:
        """Bind *name* in the current scope and return its TAC name."""
        f = self.frame
        if f.is_main and len(f.scopes) == 1:
            tac_name = name                       # a true global keeps its name
        elif name in self.global_names or name in f.used:
            tac_name = self._fresh(name)          # would clash: rename
        else:
            tac_name = name
        f.used.add(tac_name)
        f.scopes[-1][name] = tac_name
        return tac_name

    def _lookup(self, name: str) -> str:
        for scope in reversed(self.frame.scopes):
            if name in scope:
                return scope[name]
        return name                                # a global seen from inside a function

    def _temp(self) -> str:
        f = self.frame
        while True:
            f.temp_counter += 1
            name = f"t{f.temp_counter}"
            if name not in self.reserved:
                return name

    def _label(self) -> str:
        self.label_counter += 1
        return f"L{self.label_counter}"

    # ==================================================================
    # Emission helpers
    # ==================================================================
    def _emit(
        self, op: str, arg1: Optional[str] = None, arg2: Optional[str] = None,
        result: Optional[str] = None, node: Optional[A.Node] = None,
    ) -> TACInstruction:
        ins = TACInstruction(
            op, arg1, arg2, result,
            node.line if node is not None else 0,
            node.column if node is not None else 0,
        )
        self.frame.code.append(ins)
        return ins

    def _emit_label(self, label: str) -> None:
        self._emit(T.OP_LABEL, result=label)

    def _expr(self, node: A.Node) -> str:
        """Generate code for an expression; return the operand holding its value."""
        return node.accept(self)

    def _operands(self, nodes: List[A.Node]) -> List[str]:
        """Evaluate expressions left to right, protecting global reads.

        Without protection, ``g + f()`` would read ``g`` AFTER ``f`` ran (the
        operand is just the name ``g``), but the interpreter reads it before.
        """
        out: List[str] = []
        for i, n in enumerate(nodes):
            operand = self._expr(n)
            if operand in self.global_names and any(_has_call(m) for m in nodes[i + 1:]):
                tmp = self._temp()
                self._emit(T.OP_COPY, operand, None, tmp, n)
                operand = tmp
            out.append(operand)
        return out

    # ==================================================================
    # Statements
    # ==================================================================
    def visit_VariableDeclaration(self, node: A.VariableDeclaration) -> None:
        value = self._expr(node.initializer)       # BEFORE declaring: `let x = x;` may mean an outer x
        target = self._declare(node.name)
        self._emit(T.OP_COPY, value, None, target, node)

    def visit_Assignment(self, node: A.Assignment) -> None:
        target = node.target
        if isinstance(target, A.Identifier):
            value = self._expr(node.value)
            self._emit(T.OP_COPY, value, None, self._lookup(target.name), node)
        else:                                      # a[i] = value (value is evaluated first)
            value, array, index = self._operands([node.value, target.object, target.index])
            self._emit(T.OP_INDEX_SET, array, index, value, node)

    def visit_ExpressionStatement(self, node: A.ExpressionStatement) -> None:
        if isinstance(node.expression, A.FunctionCall):
            self._call(node.expression, want_result=False)
        else:
            self._expr(node.expression)

    def visit_PrintStatement(self, node: A.PrintStatement) -> None:
        self._emit(T.OP_PRINT, self._expr(node.expression), node=node)

    def visit_Block(self, node: A.Block) -> None:
        self.frame.scopes.append({})
        for stmt in node.statements:
            stmt.accept(self)
        self.frame.scopes.pop()

    def visit_IfStatement(self, node: A.IfStatement) -> None:
        cond = self._expr(node.condition)
        first = self._label()
        self._emit(T.OP_IF_FALSE, cond, None, first, node)
        node.then_branch.accept(self)
        if node.else_branch is None:
            self._emit_label(first)
            return
        end = self._label()
        self._emit(T.OP_GOTO, result=end, node=node)
        self._emit_label(first)
        node.else_branch.accept(self)
        self._emit_label(end)

    def visit_WhileStatement(self, node: A.WhileStatement) -> None:
        start, end = self._label(), self._label()
        self._emit_label(start)
        cond = self._expr(node.condition)
        self._emit(T.OP_IF_FALSE, cond, None, end, node)
        self.loops.append(_Loop(break_label=end, continue_label=start))
        node.body.accept(self)
        self.loops.pop()
        self._emit(T.OP_GOTO, result=start, node=node)
        self._emit_label(end)

    def visit_ForStatement(self, node: A.ForStatement) -> None:
        self.frame.scopes.append({})               # scope of the loop variable
        node.init.accept(self)
        start, end = self._label(), self._label()
        self._emit_label(start)
        cond = self._expr(node.condition)
        self._emit(T.OP_IF_FALSE, cond, None, end, node)
        loop = _Loop(break_label=end)
        self.loops.append(loop)
        node.body.accept(self)
        self.loops.pop()
        if loop.continue_label is not None:        # `continue` must still run the update
            self._emit_label(loop.continue_label)
        node.update.accept(self)
        self._emit(T.OP_GOTO, result=start, node=node)
        self._emit_label(end)
        self.frame.scopes.pop()

    def visit_ReturnStatement(self, node: A.ReturnStatement) -> None:
        if node.value is None:
            self._emit(T.OP_RETURN, "nil", node=node)
        else:
            self._emit(T.OP_RETURN, self._expr(node.value), node=node)

    def visit_BreakStatement(self, node: A.BreakStatement) -> None:
        self._emit(T.OP_GOTO, result=self._current_loop(node).break_label, node=node)

    def visit_ContinueStatement(self, node: A.ContinueStatement) -> None:
        loop = self._current_loop(node)
        if loop.continue_label is None:
            loop.continue_label = self._label()
        self._emit(T.OP_GOTO, result=loop.continue_label, node=node)

    def visit_FunctionDeclaration(self, node: A.FunctionDeclaration) -> None:
        raise NovaLangError("Nested function declarations are not supported.", node.line, node.column)

    def _current_loop(self, node: A.Node) -> _Loop:
        if not self.loops:
            raise NovaLangError(
                "'break' or 'continue' outside of a loop (run semantic analysis first).",
                node.line, node.column,
            )
        return self.loops[-1]

    # ==================================================================
    # Expressions: each returns the operand that holds the value
    # ==================================================================
    def visit_Literal(self, node: A.Literal) -> str:
        return format_constant(node.value)

    def visit_Identifier(self, node: A.Identifier) -> str:
        return self._lookup(node.name)

    def visit_UnaryExpression(self, node: A.UnaryExpression) -> str:
        operand = self._expr(node.operand)
        tmp = self._temp()
        self._emit(T.OP_NEG if node.operator == "-" else T.OP_NOT, operand, None, tmp, node)
        return tmp

    def visit_BinaryExpression(self, node: A.BinaryExpression) -> str:
        if node.operator in ("&&", "||"):
            return self._short_circuit(node)
        left, right = self._operands([node.left, node.right])
        tmp = self._temp()
        self._emit(node.operator, left, right, tmp, node)
        return tmp

    def visit_TernaryExpression(self, node: A.TernaryExpression) -> str:
        result = self._temp()
        false_label = self._label()
        end_label = self._label()

        condition = self._expr(node.condition)

        self._emit(T.OP_IF_FALSE, condition, None, false_label, node)

        true_value = self._expr(node.true_expr)
        self._emit(T.OP_COPY, true_value, None, result, node.true_expr)
        self._emit(T.OP_GOTO, result=end_label, node=node)

        self._emit_label(false_label)

        false_value = self._expr(node.false_expr)
        self._emit(T.OP_COPY, false_value, None, result, node.false_expr)

        self._emit_label(end_label)

        return result

    def _short_circuit(self, node: A.BinaryExpression) -> str:
        """``a && b``:  t = a; ifFalse t goto End; t = b; End:
        ``a || b``:  t = a; if t goto End;      t = b; End:"""
        tmp = self._temp()
        end = self._label()
        self._emit(T.OP_COPY, self._expr(node.left), None, tmp, node)
        self._emit(T.OP_IF_FALSE if node.operator == "&&" else T.OP_IF_TRUE, tmp, None, end, node)
        self._emit(T.OP_COPY, self._expr(node.right), None, tmp, node)
        self._emit_label(end)
        return tmp

    def visit_ArrayLiteral(self, node: A.ArrayLiteral) -> str:
        elements = self._operands(node.elements)   # evaluate every element first ...
        tmp = self._temp()
        self._emit(T.OP_ARRAY_NEW, str(len(elements)), None, tmp, node)
        for i, element in enumerate(elements):     # ... then fill the new array
            self._emit(T.OP_INDEX_SET, tmp, str(i), element, node)
        return tmp

    def visit_IndexExpression(self, node: A.IndexExpression) -> str:
        array, index = self._operands([node.object, node.index])
        tmp = self._temp()
        self._emit(T.OP_INDEX, array, index, tmp, node)
        return tmp

    def visit_FunctionCall(self, node: A.FunctionCall) -> str:
        return self._call(node, want_result=True)

    def _call(self, node: A.FunctionCall, want_result: bool) -> Optional[str]:
        """Evaluate all arguments first, then push them and call. This keeps the
        parameters of nested calls (f(g(1), 2)) from interleaving."""
        name = node.callee.name
        args = self._operands(node.arguments)
        for arg in args:
            self._emit(T.OP_PARAM, arg, node=node)
        if not want_result:
            self._emit(T.OP_CALL, name, str(len(args)), None, node)
            return None
        tmp = self._temp()
        self._emit(T.OP_CALL, name, str(len(args)), tmp, node)
        return tmp


# ======================================================================
# Convenience wrappers
# ======================================================================
def generate_tac(program: A.Program) -> TACProgram:
    """Generate TAC for an already-analyzed program."""
    return TACGenerator(program).generate()


@dataclass
class TACResult:
    program: Optional[TACProgram] = None
    errors: List[NovaLangError] = field(default_factory=list)
    warnings: List[NovaLangError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tac": self.program.to_dict() if self.program else None,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


def compile_to_tac(source: str) -> TACResult:
    """Lex, parse, analyze and generate TAC. Any front-end error stops the
    pipeline: TAC is only generated for programs that passed every check."""
    sem = analyze_source(source)
    if sem.errors or sem.program is None:
        return TACResult(errors=list(sem.errors), warnings=list(sem.warnings))
    return TACResult(generate_tac(sem.program), [], list(sem.warnings))
