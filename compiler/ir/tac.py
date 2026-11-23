"""Three Address Code (TAC): NovaLang's intermediate representation.

Compiler concept: an *intermediate representation* (IR) sits between the
front end (AST) and whatever comes next (optimizer, code generator). TAC is a
flat list of simple instructions, each with at most one operator and at most
three addresses (two operands and a result):

    let result = (a + b) * c;        t1 = a + b
                                     t2 = t1 * c
                                     result = t2

Nested expressions disappear: every intermediate value gets a *temporary*
(t1, t2, ...). Control flow (if / while / for) becomes labels and jumps, which
is exactly what makes basic blocks and control-flow graphs possible (Phase 6).

Instruction format (a "quadruple"): ``op, arg1, arg2, result``.

    op         meaning                      text form
    ---------  ---------------------------  ----------------------------
    + - * / %  arithmetic                   t1 = a + b
    == != < >  comparison                   t1 = a < b
    <= >=
    neg  not   unary minus / logical not    t1 = -a      t1 = !a
    copy       assignment                   x = t1
    label      jump target                  L1:
    goto       unconditional jump           goto L1
    if_false   jump if arg1 is false        ifFalse t1 goto L1
    if_true    jump if arg1 is true         if t1 goto L1
    param      push a call argument         param x
    call       call arg1 with arg2 args     t1 = call f, 2
    return     return (optional) arg1       return t1
    print      print arg1                   print t1
    array_new  create array of arg1 slots   t1 = newarray 3
    index      result = arg1[arg2]          t2 = a[i]
    index_set  arg1[arg2] = result          a[i] = t2

Operands are plain strings: a variable or temporary name (``x``, ``t1``) or a
constant written like its NovaLang literal (``10``, ``2.5``, ``"hi"``,
``true``, ``false``, ``nil``). Identifiers can never look like constants
because the keywords are reserved, so no extra tagging is needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, List, Optional, Tuple

# ----------------------------------------------------------------------
# Opcodes
# ----------------------------------------------------------------------
BINARY_OPS = ("+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=")
OP_NEG = "neg"
OP_NOT = "not"
OP_COPY = "copy"
OP_LABEL = "label"
OP_GOTO = "goto"
OP_IF_FALSE = "if_false"
OP_IF_TRUE = "if_true"
OP_PARAM = "param"
OP_CALL = "call"
OP_RETURN = "return"
OP_PRINT = "print"
OP_ARRAY_NEW = "array_new"
OP_INDEX = "index"
OP_INDEX_SET = "index_set"

UNARY_OPS = (OP_NEG, OP_NOT)


# ----------------------------------------------------------------------
# Operands
# ----------------------------------------------------------------------
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")


def format_constant(value: Any) -> str:
    """Render a Python value as a TAC constant operand (inverse of parse_operand)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    raise TypeError(f"cannot use {type(value).__name__} as a TAC constant")


@lru_cache(maxsize=None)
def parse_operand(text: str) -> Tuple[bool, Any]:
    """Return ``(True, value)`` if *text* is a constant, else ``(False, name)``."""
    if text == "true":
        return True, True
    if text == "false":
        return True, False
    if text == "nil":
        return True, None
    if text.startswith('"'):
        return True, json.loads(text)
    if _INT_RE.match(text):
        return True, int(text)
    if _FLOAT_RE.match(text):
        return True, float(text)
    return False, text


def is_constant(operand: Optional[str]) -> bool:
    return operand is not None and parse_operand(operand)[0]


def constant_value(operand: str) -> Any:
    is_const, value = parse_operand(operand)
    if not is_const:
        raise ValueError(f"{operand!r} is not a constant")
    return value


def is_variable(operand: Optional[str]) -> bool:
    """True for a variable or temporary name (anything that is not a constant)."""
    return operand is not None and not parse_operand(operand)[0]


# ----------------------------------------------------------------------
# Instructions
# ----------------------------------------------------------------------
@dataclass
class TACInstruction:
    op: str
    arg1: Optional[str] = None
    arg2: Optional[str] = None
    result: Optional[str] = None
    line: int = 0          # source line this instruction came from
    column: int = 0

    # ---------------------------------------------------------- display
    def text(self) -> str:
        op, a1, a2, r = self.op, self.arg1, self.arg2, self.result
        if op in BINARY_OPS:
            return f"{r} = {a1} {op} {a2}"
        if op == OP_NEG:
            return f"{r} = -{a1}"
        if op == OP_NOT:
            return f"{r} = !{a1}"
        if op == OP_COPY:
            return f"{r} = {a1}"
        if op == OP_LABEL:
            return f"{r}:"
        if op == OP_GOTO:
            return f"goto {r}"
        if op == OP_IF_FALSE:
            return f"ifFalse {a1} goto {r}"
        if op == OP_IF_TRUE:
            return f"if {a1} goto {r}"
        if op == OP_PARAM:
            return f"param {a1}"
        if op == OP_CALL:
            call = f"call {a1}, {a2}"
            return f"{r} = {call}" if r is not None else call
        if op == OP_RETURN:
            return f"return {a1}" if a1 is not None else "return"
        if op == OP_PRINT:
            return f"print {a1}"
        if op == OP_ARRAY_NEW:
            return f"{r} = newarray {a1}"
        if op == OP_INDEX:
            return f"{r} = {a1}[{a2}]"
        if op == OP_INDEX_SET:
            return f"{a1}[{a2}] = {r}"
        raise ValueError(f"unknown TAC op {op!r}")  # pragma: no cover

    def __str__(self) -> str:
        return self.text()

    def to_dict(self, index: Optional[int] = None) -> dict:
        d = {
            "op": self.op,
            "arg1": self.arg1,
            "arg2": self.arg2,
            "result": self.result,
            "text": self.text(),
            "line": self.line,
            "column": self.column,
        }
        if index is not None:
            d["index"] = index
        return d

    # ------------------------------------------- classification helpers
    @property
    def is_label(self) -> bool:
        return self.op == OP_LABEL

    @property
    def is_jump(self) -> bool:
        return self.op in (OP_GOTO, OP_IF_FALSE, OP_IF_TRUE)

    @property
    def is_conditional_jump(self) -> bool:
        return self.op in (OP_IF_FALSE, OP_IF_TRUE)

    @property
    def is_terminator(self) -> bool:
        """Instructions after which control never falls through to the next one."""
        return self.op in (OP_GOTO, OP_RETURN)

    @property
    def jump_target(self) -> Optional[str]:
        return self.result if self.is_jump else None

    @property
    def is_pure(self) -> bool:
        """Cannot fail and has no effect other than computing ``result``.

        Only such instructions may be deleted when their result is unused.
        Operand types are not tracked in TAC, so anything that *might* raise
        a run-time error is NOT pure: ``a + b`` (a string and an int),
        ``a / b`` (b is zero), ``-s`` (s is a string), ``a[i]`` (bad index).
        Deleting those would silently remove an error the program should
        report. Copies, array creation and ``==`` / ``!=`` can never fail.
        """
        return self.op in (OP_COPY, OP_ARRAY_NEW, "==", "!=")

    # ----------------------------------------------- data-flow helpers
    def operand_fields(self) -> Tuple[str, ...]:
        """Names of the fields (``arg1``, ``arg2``, ``result``) this instruction READS.

        ``call`` is empty: its ``arg1`` is a function name and ``arg2`` an
        argument count; the arguments themselves arrive via ``param``.
        ``index_set`` reads all three: ``a[i] = v`` reads a, i and v.
        """
        op = self.op
        if op in BINARY_OPS or op == OP_INDEX:
            return ("arg1", "arg2")
        if op in (OP_NEG, OP_NOT, OP_COPY, OP_IF_FALSE, OP_IF_TRUE,
                  OP_PARAM, OP_PRINT, OP_RETURN):
            return ("arg1",)
        if op == OP_INDEX_SET:
            return ("arg1", "arg2", "result")
        return ()                   # label, goto, call, array_new

    def uses(self) -> List[str]:
        """Variable / temporary names this instruction READS."""
        operands = [getattr(self, f) for f in self.operand_fields()]
        return [o for o in operands if is_variable(o)]

    def defs(self) -> List[str]:
        """Variable / temporary names this instruction WRITES."""
        if self.op in BINARY_OPS or self.op in (OP_NEG, OP_NOT, OP_COPY,
                                                OP_ARRAY_NEW, OP_INDEX):
            return [self.result]
        if self.op == OP_CALL and self.result is not None:
            return [self.result]
        return []


# ----------------------------------------------------------------------
# Functions and programs
# ----------------------------------------------------------------------
@dataclass
class TACFunction:
    name: str
    params: List[str] = field(default_factory=list)
    instructions: List[TACInstruction] = field(default_factory=list)

    @property
    def is_main(self) -> bool:
        return self.name == "main"

    def header(self) -> str:
        if self.is_main:
            return "main:"
        return f"function {self.name}({', '.join(self.params)}):"

    def format(self) -> str:
        lines = [self.header()]
        for ins in self.instructions:
            lines.append(ins.text() if ins.is_label else "    " + ins.text())
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "params": list(self.params),
            "kind": "main" if self.is_main else "function",
            "instructions": [ins.to_dict(i) for i, ins in enumerate(self.instructions)],
        }


@dataclass
class TACProgram:
    """A whole compiled program.

    ``globals`` lists the variables declared at the top level of the program.
    They are the only names a function may read or write besides its own, and
    a call may change any of them -- so later phases (the optimizer, the
    runner) must treat a call as a possible write to every global. Everything
    else in ``main`` (temporaries, block-scoped variables) is private to it.
    """

    main: TACFunction
    functions: List[TACFunction] = field(default_factory=list)
    globals: List[str] = field(default_factory=list)

    def all_functions(self) -> List[TACFunction]:
        return [self.main] + self.functions

    def function(self, name: str) -> Optional[TACFunction]:
        for fn in self.functions:
            if fn.name == name:
                return fn
        return None

    def format(self) -> str:
        return "\n\n".join(fn.format() for fn in self.all_functions() if fn.instructions or fn.is_main)

    def to_dict(self) -> dict:
        return {
            "functions": [fn.to_dict() for fn in self.all_functions()],
            "globals": list(self.globals),
            "listing": self.format(),
        }
