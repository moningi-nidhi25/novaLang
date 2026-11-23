"""Type inference over Three Address Code.

Why the optimizer needs types: some textbook simplifications are only valid for
certain types. ``x + 0 -> x`` is fine when ``x`` is an int, but if ``x`` is a
string the ORIGINAL program raises a run-time error ("cannot add string and
int") and the simplified one silently succeeds. An optimization must never
change what a program does, so we only simplify when we can PROVE the type.

The semantic analyzer's static types are not enough: a variable of static type
int can still receive an unknown value (``x = f();`` is accepted because the
call's type is unknown until run time). So this module re-derives types from
the TAC itself, soundly:

* Every definition of a variable contributes the type of the value it stores.
* A variable's type is the JOIN of all its definitions anywhere in the program
  (globals are shared by all functions). If the definitions disagree, the
  variable is ``any``.
* Parameters and call results are ``any``.

The lattice (bottom = "no definition seen yet"):

                      any
        /    |     |     |     \\
      num  string bool array  nil
     /   \\
   int   float

``num`` means "an int or a float". The analysis is a fixpoint: start from
bottom and keep joining until nothing changes (loops make a variable's type
depend on itself, e.g. ``i = i + 1``).
"""

from __future__ import annotations

from typing import Dict, Optional

from compiler.ir import tac as T
from compiler.ir.tac import TACInstruction, TACProgram, constant_value, is_constant

INT, FLOAT, NUM, STRING, BOOL, ARRAY, NIL, ANY = (
    "int", "float", "num", "string", "bool", "array", "nil", "any",
)
NUMERIC = {INT, FLOAT, NUM}
COMPARISONS = ("==", "!=", "<", ">", "<=", ">=")


def constant_type(operand: str) -> str:
    value = constant_value(operand)
    if isinstance(value, bool):
        return BOOL
    if value is None:
        return NIL
    if isinstance(value, str):
        return STRING
    if isinstance(value, int):
        return INT
    return FLOAT


def join(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Least upper bound of two types (``None`` is bottom)."""
    if a is None:
        return b
    if b is None or a == b:
        return a
    if a in NUMERIC and b in NUMERIC:
        return NUM
    return ANY


def _arith(lt: str, rt: str) -> str:
    if lt == INT and rt == INT:
        return INT
    if FLOAT in (lt, rt):
        return FLOAT
    return NUM


def result_type(op: str, lt: Optional[str], rt: Optional[str]) -> Optional[str]:
    """Type of ``lt op rt`` assuming the operation succeeds (``None`` = unknown yet)."""
    if lt is None or rt is None:
        return None
    if op in COMPARISONS:
        return BOOL
    if lt in NUMERIC and rt in NUMERIC:
        return _arith(lt, rt)
    if op == "+" and lt == STRING and rt == STRING:
        return STRING
    return ANY


class TypeInfo:
    """Inferred type of every variable and temporary of a TAC program."""

    def __init__(self, program: TACProgram) -> None:
        self.globals = set(program.globals)
        self._local: Dict[str, Dict[str, Optional[str]]] = {
            fn.name: {} for fn in program.all_functions()
        }
        self._global: Dict[str, Optional[str]] = {}
        for fn in program.functions:
            for param in fn.params:
                self._local[fn.name][param] = ANY
        self._solve(program)

    # ------------------------------------------------------------ queries
    def type_of(self, function: str, operand: Optional[str]) -> str:
        """Type of an operand inside *function*; ``any`` when nothing is known."""
        if operand is None:
            return ANY
        if is_constant(operand):
            return constant_type(operand)
        return self._lookup(function, operand) or ANY

    # ----------------------------------------------------------- internals
    def _table(self, function: str, name: str) -> Dict[str, Optional[str]]:
        return self._global if name in self.globals else self._local[function]

    def _lookup(self, function: str, name: str) -> Optional[str]:
        return self._table(function, name).get(name)

    def _operand(self, function: str, operand: Optional[str]) -> Optional[str]:
        if operand is None:
            return None
        if is_constant(operand):
            return constant_type(operand)
        return self._lookup(function, operand)

    def _defined_type(self, function: str, ins: TACInstruction) -> Optional[str]:
        op = ins.op
        if op == T.OP_COPY:
            return self._operand(function, ins.arg1)
        if op in T.BINARY_OPS:
            return result_type(op, self._operand(function, ins.arg1),
                               self._operand(function, ins.arg2))
        if op == T.OP_NEG:
            t = self._operand(function, ins.arg1)
            return t if t is None or t in NUMERIC else ANY
        if op == T.OP_NOT:
            return BOOL
        if op == T.OP_ARRAY_NEW:
            return ARRAY
        return ANY                      # call results and array / string elements

    def _solve(self, program: TACProgram) -> None:
        changed = True
        while changed:
            changed = False
            for fn in program.all_functions():
                for ins in fn.instructions:
                    for name in ins.defs():
                        t = self._defined_type(fn.name, ins)
                        if t is None:
                            continue
                        table = self._table(fn.name, name)
                        merged = join(table.get(name), t)
                        if merged != table.get(name):
                            table[name] = merged
                            changed = True
