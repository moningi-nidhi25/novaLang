"""A small virtual machine that executes Three Address Code.

Why it exists: TAC is only trustworthy if it *means the same thing* as the
program it came from. This runner executes TAC directly, so tests can run a
program both ways (AST interpreter vs. TAC) and demand identical output. The
same check will later prove that every optimization preserves behaviour.

Execution model
---------------
* One flat variable table per function call; the main program uses the global
  table. A function may touch a name outside its own table only if the
  program declares it in ``TACProgram.globals``; every other name (notably
  main's temporaries t1, t2, ...) is private to the frame that created it.
* ``param x`` pushes a value on an argument stack; ``call f, n`` pops the last
  *n* values, runs *f* in a fresh frame and stores its result.
* Operators are the very same functions the AST interpreter uses
  (``binary_op``, ``unary_op``, ``check_index``), so both executors agree on
  every detail such as integer division or error messages.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from compiler.errors.errors import NovaLangError, NovaRuntimeError
from compiler.interpreter.interpreter import (
    DEFAULT_MAX_CALL_DEPTH,
    DEFAULT_MAX_STEPS,
    MAX_STRING_LENGTH,
    RunResult,
    RuntimeFault,
    binary_op,
    check_index,
    format_value,
    type_name,
    unary_op,
)
from compiler.ir import tac as T
from compiler.ir.tac import TACFunction, TACInstruction, TACProgram, parse_operand


class TACMachine:
    def __init__(
        self,
        program: TACProgram,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_call_depth: int = DEFAULT_MAX_CALL_DEPTH,
    ) -> None:
        self.program = program
        self.max_steps = max_steps
        self.max_call_depth = max_call_depth
        self.functions: Dict[str, TACFunction] = {fn.name: fn for fn in program.functions}
        self.global_set = set(program.globals)
        # label -> instruction index, per function
        self.labels: Dict[str, Dict[str, int]] = {
            fn.name: {
                ins.result: i for i, ins in enumerate(fn.instructions) if ins.op == T.OP_LABEL
            }
            for fn in program.all_functions()
        }

    # ==================================================================
    def run(self) -> RunResult:
        self.globals: Dict[str, Any] = {}
        self.output: List[str] = []
        self.steps = 0
        self.arg_stack: List[Any] = []
        self.call_stack: List[str] = []
        errors: List[NovaLangError] = []
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 40_000))
        try:
            self._execute(self.program.main, self.globals)
        except NovaLangError as err:
            errors.append(err)
        except RecursionError:
            errors.append(NovaRuntimeError("Stack overflow: the program recursed too deeply.", 0, 0))
        finally:
            sys.setrecursionlimit(old_limit)
        variables = {k: format_value(v) for k, v in self.globals.items()}
        return RunResult("".join(self.output), errors, self.steps, variables)

    # ==================================================================
    def _fail(self, ins: TACInstruction, message: str, hint: Optional[str] = None) -> NovaRuntimeError:
        if self.call_stack:
            stack = "Call stack: " + " -> ".join(["main"] + self.call_stack)
            hint = f"{hint} {stack}" if hint else stack
        return NovaRuntimeError(f"{message} at line {ins.line}.", ins.line, ins.column, hint)

    def _get(self, operand: str, frame: Dict[str, Any], ins: TACInstruction) -> Any:
        is_const, value = parse_operand(operand)
        if is_const:
            return value
        if value in frame:
            return frame[value]
        if value in self.global_set and value in self.globals:
            return self.globals[value]
        raise self._fail(ins, f"Variable '{value}' is not defined")

    def _set(self, name: str, value: Any, frame: Dict[str, Any]) -> None:
        if frame is not self.globals and name in self.global_set:
            self.globals[name] = value      # a function assigning to a global
        else:
            frame[name] = value

    # ==================================================================
    def _execute(self, fn: TACFunction, frame: Dict[str, Any]) -> Any:
        code = fn.instructions
        labels = self.labels[fn.name]
        pc = 0
        while pc < len(code):
            ins = code[pc]
            pc += 1
            self.steps += 1
            if self.steps > self.max_steps:
                raise self._fail(
                    ins, "Execution step limit exceeded",
                    f"The program ran more than {self.max_steps:,} steps. "
                    "This usually means an infinite loop.",
                )
            op = ins.op
            try:
                if op in T.BINARY_OPS:
                    self._set(ins.result, binary_op(
                        op, self._get(ins.arg1, frame, ins), self._get(ins.arg2, frame, ins)), frame)
                elif op == T.OP_COPY:
                    self._set(ins.result, self._get(ins.arg1, frame, ins), frame)
                elif op == T.OP_LABEL:
                    pass
                elif op == T.OP_GOTO:
                    pc = labels[ins.result]
                elif op in (T.OP_IF_FALSE, T.OP_IF_TRUE):
                    cond = self._get(ins.arg1, frame, ins)
                    if not isinstance(cond, bool):
                        raise RuntimeFault(
                            f"Condition must be bool, found {type_name(cond)}",
                            "NovaLang has no truthiness; compare explicitly (e.g. x != 0).")
                    if cond == (op == T.OP_IF_TRUE):
                        pc = labels[ins.result]
                elif op == T.OP_NEG:
                    self._set(ins.result, unary_op("-", self._get(ins.arg1, frame, ins)), frame)
                elif op == T.OP_NOT:
                    self._set(ins.result, unary_op("!", self._get(ins.arg1, frame, ins)), frame)
                elif op == T.OP_PARAM:
                    self.arg_stack.append(self._get(ins.arg1, frame, ins))
                elif op == T.OP_CALL:
                    argc = int(ins.arg2)
                    args = self.arg_stack[len(self.arg_stack) - argc:]
                    del self.arg_stack[len(self.arg_stack) - argc:]
                    value = self._call(ins, args)
                    if ins.result is not None:
                        self._set(ins.result, value, frame)
                elif op == T.OP_RETURN:
                    return self._get(ins.arg1, frame, ins) if ins.arg1 is not None else None
                elif op == T.OP_PRINT:
                    self.output.append(format_value(self._get(ins.arg1, frame, ins)) + "\n")
                elif op == T.OP_ARRAY_NEW:
                    self._set(ins.result, [None] * int(ins.arg1), frame)
                elif op == T.OP_INDEX:
                    container = self._get(ins.arg1, frame, ins)
                    index = self._get(ins.arg2, frame, ins)
                    check_index(container, index)
                    self._set(ins.result, container[index], frame)
                elif op == T.OP_INDEX_SET:
                    container = self._get(ins.arg1, frame, ins)
                    index = self._get(ins.arg2, frame, ins)
                    if isinstance(container, str):
                        raise RuntimeFault("Strings are immutable; cannot assign to a string index")
                    check_index(container, index)
                    container[index] = self._get(ins.result, frame, ins)
                else:  # pragma: no cover
                    raise RuntimeFault(f"Unknown TAC instruction '{op}'")
            except RuntimeFault as fault:
                raise self._fail(ins, fault.message, fault.hint)
        return None

    def _call(self, ins: TACInstruction, args: List[Any]) -> Any:
        name = ins.arg1
        if name == "len":
            if len(args) != 1 or not isinstance(args[0], (list, str)):
                found = type_name(args[0]) if args else "nothing"
                raise self._fail(ins, f"len() expects an array or string, found {found}")
            return len(args[0])
        fn = self.functions.get(name)
        if fn is None:
            raise self._fail(ins, f"Function '{name}' is not defined")
        if len(args) != len(fn.params):
            raise self._fail(
                ins, f"Function '{name}' expects {len(fn.params)} arguments but got {len(args)}")
        if len(self.call_stack) >= self.max_call_depth:
            raise self._fail(
                ins, "Stack overflow",
                f"More than {self.max_call_depth} nested calls: the recursion probably "
                "has no base case.",
            )
        self.call_stack.append(name)
        try:
            return self._execute(fn, dict(zip(fn.params, args)))
        finally:
            self.call_stack.pop()


def run_tac(program: TACProgram, **limits: int) -> RunResult:
    """Execute a TAC program and return its output (same shape as the interpreter)."""
    return TACMachine(program, **limits).run()
