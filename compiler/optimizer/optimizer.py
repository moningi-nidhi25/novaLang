"""TAC optimizer.

Compiler concept: an *optimizer* rewrites the intermediate code into code that
does the same thing, only with less work. The golden rule is that **the
optimized program must behave exactly like the original**: same output, same
run-time errors, in the same order. Every transformation below is therefore
guarded by a safety condition, and the test-suite proves the rule by running
original and optimized TAC side by side on hundreds of programs.

Passes (repeated, with the types re-inferred each round, until nothing changes,
because each pass enables the others):

  constant propagation   replace a variable by its value when it certainly
                         holds one constant at that point (data-flow analysis)
  constant folding       10 + 20  ->  30    (never folds an operation that
                         would fail at run time, e.g. 1 / 0)
  algebraic              x + 0 -> x, x - 0 -> x, x * 1 -> x, x / 1 -> x,
  simplification         x * 0 -> 0 -- only when x is PROVEN to be a number
                         (see type_inference.py for why types matter)
  branch folding         ifFalse true goto L  ->  (nothing),
                         ifFalse false goto L ->  goto L
  unreachable code       delete blocks no path can reach (CFG reachability)
  temp coalescing        t1 = a + b; x = t1   ->   x = a + b
  dead store removal     delete assignments nobody reads (liveness analysis);
                         global variables are always kept
  jump cleanup           delete `goto L` right before `L:` and unused labels

Not optimized on purpose: anything that can raise a run-time error is never
deleted, even if its result is unused (``t = a / b`` stays), because deleting
it would hide an error the program is supposed to report.

Every rewrite is recorded as a ``Change`` so the UI can explain exactly what
the optimizer did and why.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

from compiler.errors.errors import NovaLangError
from compiler.ir import tac as T
from compiler.ir.basic_blocks import build_cfg
from compiler.ir.generator import compile_to_tac
from compiler.ir.tac import (
    TACFunction, TACInstruction, TACProgram, constant_value, is_constant, is_variable,
)
from compiler.optimizer.dataflow import (
    NAC, analyze_constants, fold, foldable_operands, live_out_sets, transfer,
)
from compiler.optimizer.type_inference import INT, NUMERIC, TypeInfo

PASS_PROPAGATION = "constant propagation"
PASS_FOLDING = "constant folding"
PASS_ALGEBRAIC = "algebraic simplification"
PASS_BRANCH = "branch folding"
PASS_UNREACHABLE = "unreachable code"
PASS_COALESCE = "temporary coalescing"
PASS_DEAD_STORE = "dead store removal"
PASS_JUMPS = "jump cleanup"

MAX_ROUNDS = 50

# instructions that define exactly one value and have no control-flow effect
_VALUE_OPS = set(T.BINARY_OPS) | {T.OP_NEG, T.OP_NOT, T.OP_COPY, T.OP_CALL, T.OP_INDEX, T.OP_ARRAY_NEW}


@dataclass
class Change:
    """One rewrite performed by the optimizer."""

    pass_name: str
    function: str
    line: int
    before: str
    after: Optional[str]          # None when the instruction was deleted
    description: str

    def to_dict(self) -> dict:
        return {
            "pass": self.pass_name,
            "function": self.function,
            "line": self.line,
            "before": self.before,
            "after": self.after,
            "description": self.description,
        }


@dataclass
class OptimizationResult:
    original: TACProgram
    optimized: TACProgram
    changes: List[Change] = field(default_factory=list)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(Counter(c.pass_name for c in self.changes))

    @property
    def instruction_counts(self) -> Dict[str, int]:
        def total(p: TACProgram) -> int:
            return sum(len(fn.instructions) for fn in p.all_functions())
        return {"before": total(self.original), "after": total(self.optimized)}

    def format(self) -> str:
        return (
            "BEFORE OPTIMIZATION\n\n" + self.original.format()
            + "\n\nAFTER OPTIMIZATION\n\n" + self.optimized.format()
        )

    def format_changes(self) -> str:
        lines = []
        for c in self.changes:
            where = f"line {c.line}" if c.line else "-"
            arrow = f"{c.before}  =>  {c.after}" if c.after is not None else f"{c.before}  =>  (deleted)"
            lines.append(f"[{c.pass_name}] {c.function}, {where}: {arrow}   ({c.description})")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "original": self.original.to_dict(),
            "optimized": self.optimized.to_dict(),
            "changes": [c.to_dict() for c in self.changes],
            "stats": self.stats,
            "instruction_counts": self.instruction_counts,
        }


# ----------------------------------------------------------------------
# Per-function optimizer
# ----------------------------------------------------------------------
class _FunctionOptimizer:
    def __init__(self, fn: TACFunction, program: TACProgram, types: TypeInfo,
                 changes: List[Change]) -> None:
        self.fn = fn
        self.globals = set(program.globals)
        self.types = types
        self.changes = changes

    def round(self) -> bool:
        """Run every pass once; True if any of them changed the function."""
        changed = self.propagate_and_fold()
        changed |= self.remove_unreachable()
        changed |= self.coalesce_temporaries()
        changed |= self.remove_dead_stores()
        changed |= self.cleanup_jumps()
        return changed

    def log(self, pass_name: str, before: TACInstruction, after: Optional[TACInstruction],
            description: str) -> None:
        self.changes.append(Change(
            pass_name, self.fn.name, before.line, before.text(),
            after.text() if after is not None else None, description,
        ))

    # ------------------------------------------------------------------
    # 1. propagation + folding + algebra + branch folding
    # ------------------------------------------------------------------
    def propagate_and_fold(self) -> bool:
        cfg = build_cfg(self.fn)
        if not cfg.blocks:
            return False
        in_states = analyze_constants(cfg, self.fn.is_main, self.fn.params, self.globals)

        new_code: List[TACInstruction] = []
        changed = False
        for block in cfg.blocks:
            if not block.reachable:
                new_code.extend(block.instructions)
                continue
            state = dict(in_states[block.name])
            for ins in block.instructions:
                rewritten = self._rewrite(ins, state)
                if rewritten is not ins:
                    changed = True
                if rewritten is not None:
                    transfer(state, rewritten, self.globals)
                    new_code.append(rewritten)
                else:
                    changed = True
        if changed:
            self.fn.instructions = new_code
        return changed

    def _rewrite(self, ins: TACInstruction, state: Dict[str, str]) -> Optional[TACInstruction]:
        """Rewrite one instruction given what is known before it.
        Returns the new instruction, or None if it should be deleted."""
        cur = ins

        # constant propagation: use a variable's known constant instead of the variable
        for field_name in cur.operand_fields():
            operand = getattr(cur, field_name)
            if is_variable(operand):
                value = state.get(operand)
                if value is not None and value != NAC:
                    new = replace(cur, **{field_name: value})
                    self.log(PASS_PROPAGATION, cur, new, f"'{operand}' is always {value} at this point")
                    cur = new

        # constant folding: evaluate an operation on constants now
        operands = foldable_operands(cur)
        if operands is not None:
            folded = fold(cur.op, operands)
            if folded is not None:
                new = TACInstruction(T.OP_COPY, folded, None, cur.result, cur.line, cur.column)
                self.log(PASS_FOLDING, cur, new, "both operands are constants, so it is computed at compile time")
                cur = new
        elif cur.op in T.BINARY_OPS:
            simplified = self._simplify(cur)
            if simplified is not None:
                new, why = simplified
                self.log(PASS_ALGEBRAIC, cur, new, why)
                cur = new

        # branch folding: a condition that is a known constant
        if cur.is_conditional_jump and is_constant(cur.arg1):
            value = constant_value(cur.arg1)
            if isinstance(value, bool):                 # non-bool stays: it is a run-time error
                taken = (value is False) if cur.op == T.OP_IF_FALSE else (value is True)
                if taken:
                    new = TACInstruction(T.OP_GOTO, None, None, cur.result, cur.line, cur.column)
                    self.log(PASS_BRANCH, cur, new, "the condition is always true for this jump, so it always jumps")
                    return new
                self.log(PASS_BRANCH, cur, None, "the jump is never taken, so it is removed")
                return None
        return cur

    def _simplify(self, ins: TACInstruction):
        """Algebraic identities, applied only when the types make them exact."""
        op, a, b = ins.op, ins.arg1, ins.arg2
        ta = self.types.type_of(self.fn.name, a)
        tb = self.types.type_of(self.fn.name, b)

        def copy_of(value: str) -> TACInstruction:
            return TACInstruction(T.OP_COPY, value, None, ins.result, ins.line, ins.column)

        # int + 0 and 0 + int. Not for floats: -0.0 + 0 is 0.0, not -0.0.
        if op == "+":
            if b == "0" and ta == INT:
                return copy_of(a), f"{a} + 0 is just {a} ({a} is an int)"
            if a == "0" and tb == INT:
                return copy_of(b), f"0 + {b} is just {b} ({b} is an int)"
        elif op == "-":
            if b == "0" and ta in NUMERIC:
                return copy_of(a), f"{a} - 0 is just {a} ({a} is a number)"
        elif op == "*":
            if b == "1" and ta in NUMERIC:
                return copy_of(a), f"{a} * 1 is just {a} ({a} is a number)"
            if a == "1" and tb in NUMERIC:
                return copy_of(b), f"1 * {b} is just {b} ({b} is a number)"
            # int * 0 only: for floats the result could be -0.0 and for non-numbers an error
            if b == "0" and ta == INT:
                return copy_of("0"), f"{a} * 0 is 0 ({a} is an int)"
            if a == "0" and tb == INT:
                return copy_of("0"), f"0 * {b} is 0 ({b} is an int)"
        elif op == "/":
            if b == "1" and ta in NUMERIC:
                return copy_of(a), f"{a} / 1 is just {a} ({a} is a number)"
        return None

    # ------------------------------------------------------------------
    # 2. unreachable code
    # ------------------------------------------------------------------
    def remove_unreachable(self) -> bool:
        cfg = build_cfg(self.fn)
        dead = [b for b in cfg.blocks if not b.reachable]
        if not dead:
            return False
        for block in dead:
            for ins in block.instructions:
                self.log(PASS_UNREACHABLE, ins, None, "no path from the start of the function reaches it")
        self.fn.instructions = [i for b in cfg.blocks if b.reachable for i in b.instructions]
        return True

    # ------------------------------------------------------------------
    # 3. temporary coalescing
    # ------------------------------------------------------------------
    def coalesce_temporaries(self) -> bool:
        code = self.fn.instructions
        reads = Counter(name for ins in code for name in ins.uses())
        new_code: List[TACInstruction] = []
        changed = False
        i = 0
        while i < len(code):
            first = code[i]
            second = code[i + 1] if i + 1 < len(code) else None
            if self._can_coalesce(first, second, reads):
                merged = replace(first, result=second.result)
                self.log(PASS_COALESCE, first, merged,
                         f"'{first.result}' was only a stepping stone to '{second.result}'")
                new_code.append(merged)
                changed = True
                i += 2
            else:
                new_code.append(first)
                i += 1
        if changed:
            self.fn.instructions = new_code
        return changed

    def _can_coalesce(self, first: TACInstruction, second: Optional[TACInstruction],
                      reads: Counter) -> bool:
        if second is None or first.op not in _VALUE_OPS or second.op != T.OP_COPY:
            return False
        defined = first.defs()
        if len(defined) != 1:
            return False
        name = defined[0]
        return (
            second.arg1 == name and second.result != name
            and name not in self.globals          # other functions may read a global
            and reads[name] == 1                  # the copy is its only reader
        )

    # ------------------------------------------------------------------
    # 4. dead stores
    # ------------------------------------------------------------------
    def remove_dead_stores(self) -> bool:
        cfg = build_cfg(self.fn)
        if not cfg.blocks:
            return False
        live_out = live_out_sets(cfg)
        new_code: List[TACInstruction] = []
        changed = False
        for block in cfg.blocks:
            kept: List[TACInstruction] = []
            live = set(live_out[block.name])
            for ins in reversed(block.instructions):
                defined = ins.defs()
                dead = (
                    block.reachable and len(defined) == 1
                    and defined[0] not in live and defined[0] not in self.globals
                )
                if dead and ins.is_pure:
                    self.log(PASS_DEAD_STORE, ins, None, f"'{defined[0]}' is never read afterwards")
                    changed = True
                    continue
                if dead and ins.op == T.OP_CALL:     # keep the call, drop the unused result
                    dropped = replace(ins, result=None)
                    self.log(PASS_DEAD_STORE, ins, dropped, f"the result '{defined[0]}' is never used; the call stays")
                    changed = True
                    ins = dropped
                live -= set(ins.defs())
                live |= set(ins.uses())
                kept.append(ins)
            new_code.extend(reversed(kept))
        if changed:
            self.fn.instructions = new_code
        return changed

    # ------------------------------------------------------------------
    # 5. jump cleanup
    # ------------------------------------------------------------------
    def cleanup_jumps(self) -> bool:
        code = self.fn.instructions
        changed = False

        # a `goto L` whose very next instruction (ignoring other labels) is `L:`
        kept: List[TACInstruction] = []
        for i, ins in enumerate(code):
            if ins.op == T.OP_GOTO and self._falls_into(code, i + 1, ins.result):
                self.log(PASS_JUMPS, ins, None, "it jumps to the instruction that follows anyway")
                changed = True
                continue
            kept.append(ins)

        # labels nobody jumps to
        targets = {i.jump_target for i in kept if i.is_jump}
        final: List[TACInstruction] = []
        for ins in kept:
            if ins.is_label and ins.result not in targets:
                self.log(PASS_JUMPS, ins, None, "no jump leads here")
                changed = True
                continue
            final.append(ins)
        if changed:
            self.fn.instructions = final
        return changed

    @staticmethod
    def _falls_into(code: List[TACInstruction], start: int, label: str) -> bool:
        j = start
        while j < len(code) and code[j].is_label:
            if code[j].result == label:
                return True
            j += 1
        return False


# ----------------------------------------------------------------------
# Driver and wrappers
# ----------------------------------------------------------------------
def _copy_program(program: TACProgram) -> TACProgram:
    def copy_fn(fn: TACFunction) -> TACFunction:
        return TACFunction(fn.name, list(fn.params), [replace(i) for i in fn.instructions])
    return TACProgram(copy_fn(program.main), [copy_fn(f) for f in program.functions],
                      list(program.globals))


def optimize(program: TACProgram) -> OptimizationResult:
    """Optimize *program*. The input is never modified."""
    working = _copy_program(program)
    changes: List[Change] = []
    for _ in range(MAX_ROUNDS):
        # Types are re-inferred every round: deleting a dead assignment can make
        # a variable's type more precise, which can enable a further simplification.
        types = TypeInfo(working)
        changed = False
        for fn in working.all_functions():
            changed |= _FunctionOptimizer(fn, working, types, changes).round()
        if not changed:
            break
    return OptimizationResult(program, working, changes)


@dataclass
class SourceOptimization:
    result: Optional[OptimizationResult] = None
    errors: List[NovaLangError] = field(default_factory=list)
    warnings: List[NovaLangError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        d = {
            "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }
        d.update(self.result.to_dict() if self.result else
                 {"original": None, "optimized": None, "changes": [], "stats": {},
                  "instruction_counts": None})
        return d


def compile_and_optimize(source: str) -> SourceOptimization:
    """Lex, parse, analyze, generate TAC and optimize it."""
    tac = compile_to_tac(source)
    if not tac.ok:
        return SourceOptimization(errors=tac.errors, warnings=tac.warnings)
    return SourceOptimization(optimize(tac.program), [], tac.warnings)
