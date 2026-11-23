"""Data-flow analyses used by the optimizer.

Compiler concept: a *data-flow analysis* computes facts about the program at
every point by pushing information along the control-flow graph until nothing
changes (a *fixpoint*). Two classic analyses live here:

1. **Constant propagation** (forward). For every point: which variables are
   certainly holding one known constant? Each variable has one of three states:

       (missing) = "no information yet"   (TOP, optimistic start)
       "10"      = "always this constant"
       NAC       = "not a constant" (different values on different paths)

   At a join point of the CFG the states of all predecessors are *met*: equal
   constants stay, anything else becomes NAC. Loops need several rounds
   because a loop variable's state depends on itself.

2. **Liveness** (backward). A variable is *live* at a point if its current
   value may still be read later. An assignment to a variable that is not live
   afterwards is a *dead store*.

Safety rules baked into the analyses:

* A call may change any global variable, so every global becomes NAC after a
  call (and at the start of every function). Locals are private to their
  function, so calls cannot touch them.
* Only immutable values (int, float, string, bool, nil) are ever constants;
  arrays are shared and mutable, so they are never constants.
* Folding uses the very same operator code as the interpreter, and refuses to
  fold anything that would fail at run time (division by zero, type errors) or
  that cannot be written back as a constant (infinity, enormous numbers). Those
  operations stay in the program, so the run-time error still happens.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from compiler.interpreter.interpreter import RuntimeFault, binary_op, unary_op
from compiler.ir import tac as T
from compiler.ir.basic_blocks import CFG
from compiler.ir.tac import (
    TACInstruction, constant_value, format_constant, is_constant,
)

NAC = "<not-a-constant>"
State = Dict[str, str]

MAX_FOLDED_STRING = 1000          # never bloat the listing with huge folded strings
MAX_FOLDED_INT_BITS = 1000        # nor with enormous integers


# ----------------------------------------------------------------------
# Safe constant folding
# ----------------------------------------------------------------------
def fold(op: str, operands: List[str]) -> Optional[str]:
    """Evaluate ``op`` on constant operands. Returns the result as a constant
    operand, or ``None`` if the operation must be left for run time."""
    try:
        values = [constant_value(o) for o in operands]
        if op in T.BINARY_OPS:
            result = binary_op(op, values[0], values[1])
        elif op == T.OP_NEG:
            result = unary_op("-", values[0])
        elif op == T.OP_NOT:
            result = unary_op("!", values[0])
        else:
            return None
    except RuntimeFault:
        return None                       # it would fail at run time: keep it, so it still does

    if isinstance(result, bool) or result is None:
        pass
    elif isinstance(result, float):
        if not math.isfinite(result):
            return None                   # 'inf' / 'nan' cannot be written as constants
    elif isinstance(result, int):
        if result.bit_length() > MAX_FOLDED_INT_BITS:
            return None
    elif isinstance(result, str):
        if len(result) > MAX_FOLDED_STRING:
            return None
    return format_constant(result)


def foldable_operands(ins: TACInstruction) -> Optional[List[str]]:
    """The operands of *ins* if it is an operation whose operands are all constants."""
    if ins.op in T.BINARY_OPS:
        operands = [ins.arg1, ins.arg2]
    elif ins.op in T.UNARY_OPS:
        operands = [ins.arg1]
    else:
        return None
    return operands if all(is_constant(o) for o in operands) else None


# ----------------------------------------------------------------------
# Constant propagation
# ----------------------------------------------------------------------
def operand_value(state: State, operand: str) -> str:
    """The constant an operand certainly holds, else NAC."""
    if is_constant(operand):
        return operand
    return state.get(operand, NAC)


def transfer(state: State, ins: TACInstruction, globals_: Set[str]) -> None:
    """Update *state* in place to describe the program just AFTER *ins*."""
    op = ins.op
    if op == T.OP_COPY:
        state[ins.result] = operand_value(state, ins.arg1)
    elif op in T.BINARY_OPS or op in T.UNARY_OPS:
        operands = [operand_value(state, a) for a in (ins.arg1, ins.arg2) if a is not None]
        result = None if NAC in operands else fold(op, operands)
        state[ins.result] = result if result is not None else NAC
    elif op == T.OP_CALL:
        if ins.arg1 != "len":                       # a user function may change any global
            for g in globals_:
                state[g] = NAC
        if ins.result is not None:
            state[ins.result] = NAC
    elif op in (T.OP_INDEX, T.OP_ARRAY_NEW):
        state[ins.result] = NAC


def meet(states: List[State]) -> State:
    """Combine the states flowing into a join point."""
    merged: State = {}
    keys: Set[str] = set()
    for s in states:
        keys.update(s)
    for key in keys:
        values = [s[key] for s in states if key in s]
        merged[key] = values[0] if all(v == values[0] for v in values) else NAC
    return merged


def entry_state(function_is_main: bool, params: List[str], globals_: Set[str]) -> State:
    """What is known when a function starts."""
    if function_is_main:
        return {}                                   # nothing is assigned yet
    state: State = {g: NAC for g in globals_}       # callers may have changed any global
    state.update({p: NAC for p in params})          # arguments are unknown
    return state


def analyze_constants(
    cfg: CFG, function_is_main: bool, params: List[str], globals_: Set[str],
) -> Dict[str, State]:
    """Return the constant state at the START of every reachable block."""
    start = entry_state(function_is_main, params, globals_)
    reachable = [b for b in cfg.blocks if b.reachable]
    in_states: Dict[str, State] = {}
    out_states: Dict[str, State] = {}

    changed = True
    while changed:
        changed = False
        for block in reachable:
            incoming = [out_states[p] for p in block.predecessors if p in out_states]
            if block.name == cfg.entry:
                incoming.append(start)
            new_in = meet(incoming)
            if block.name in in_states and in_states[block.name] == new_in:
                continue
            in_states[block.name] = new_in
            state = dict(new_in)
            for ins in block.instructions:
                transfer(state, ins, globals_)
            out_states[block.name] = state
            changed = True
    return in_states


# ----------------------------------------------------------------------
# Liveness
# ----------------------------------------------------------------------
def live_out_sets(cfg: CFG) -> Dict[str, Set[str]]:
    """Variables that may still be read after the END of each block."""
    live_in: Dict[str, Set[str]] = {b.name: set() for b in cfg.blocks}

    def block_out(block) -> Set[str]:
        out: Set[str] = set()
        for succ in block.successors:
            out |= live_in[succ]
        return out

    changed = True
    while changed:
        changed = False
        for block in reversed(cfg.blocks):
            live = block_out(block)
            for ins in reversed(block.instructions):
                live -= set(ins.defs())
                live |= set(ins.uses())
            if live != live_in[block.name]:
                live_in[block.name] = live
                changed = True
    return {b.name: block_out(b) for b in cfg.blocks}
