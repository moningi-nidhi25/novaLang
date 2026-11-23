"""Basic blocks and the control-flow graph (CFG).

Compiler concept: a *basic block* is a maximal run of instructions with one
entry (its first instruction) and one exit (its last): control can only enter
at the top and leave at the bottom. Inside a block there are no jumps in and
no jumps out, which makes it easy to reason about, and it is the unit most
optimizations work on.

Finding the blocks uses the classic *leader* rules. An instruction is a leader
(the first instruction of a block) if it is

  1. the first instruction of the function,
  2. the target of a jump (a labelled instruction some goto/if jumps to), or
  3. the instruction immediately after a jump or a return.

Each leader starts a block that runs up to (but not including) the next leader.

Then the *control-flow graph* connects blocks with edges that say where
control can go next:

    ends with           edges
    ------------------  ------------------------------------------------
    goto L              one "jump" edge to the block of L
    ifFalse c goto L    "true" edge to the next block, "false" edge to L
    if c goto L         "true" edge to L, "false" edge to the next block
    return              none (the function exits here)
    anything else       one "next" edge (falls through to the next block)

If both outcomes of a conditional lead to the same block, a single "branch"
edge is used. Blocks that cannot be reached from the entry are flagged
``reachable = False``: that is dead code the optimizer can remove.

A CFG is built per function (``main`` is a function too).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from compiler.errors.errors import NovaLangError
from compiler.ir import tac as T
from compiler.ir.generator import compile_to_tac
from compiler.ir.tac import TACFunction, TACInstruction, TACProgram

REASON_FIRST = "first instruction"
REASON_TARGET = "target of a jump"
REASON_AFTER_JUMP = "follows a jump"
REASON_AFTER_RETURN = "follows a return"

EDGE_NEXT = "next"
EDGE_JUMP = "jump"
EDGE_TRUE = "true"
EDGE_FALSE = "false"
EDGE_BRANCH = "branch"


# ----------------------------------------------------------------------
# Step 1: leaders
# ----------------------------------------------------------------------
def find_leaders(instructions: List[TACInstruction]) -> Dict[int, List[str]]:
    """Return ``{index: [reasons]}`` for every leader, in increasing index order."""
    n = len(instructions)
    leaders: Dict[int, List[str]] = {}

    def add(index: int, reason: str) -> None:
        if 0 <= index < n:
            reasons = leaders.setdefault(index, [])
            if reason not in reasons:
                reasons.append(reason)

    add(0, REASON_FIRST)
    label_index = {ins.result: i for i, ins in enumerate(instructions) if ins.is_label}
    for i, ins in enumerate(instructions):
        if ins.is_jump:
            if ins.jump_target not in label_index:
                raise ValueError(f"jump to undefined label {ins.jump_target!r}: {ins.text()}")
            add(label_index[ins.jump_target], REASON_TARGET)
            add(i + 1, REASON_AFTER_JUMP)
        elif ins.op == T.OP_RETURN:
            add(i + 1, REASON_AFTER_RETURN)
    return dict(sorted(leaders.items()))


# ----------------------------------------------------------------------
# Step 2: blocks and edges
# ----------------------------------------------------------------------
@dataclass
class BasicBlock:
    id: int
    name: str
    function: str
    start: int                       # index of the first instruction (inclusive)
    end: int                         # index of the last instruction (inclusive)
    instructions: List[TACInstruction]
    leader_reasons: List[str] = field(default_factory=list)
    successors: List[str] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)
    reachable: bool = True

    @property
    def label(self) -> Optional[str]:
        """The label this block starts with, if any."""
        first = self.instructions[0]
        return first.result if first.is_label else None

    @property
    def is_exit(self) -> bool:
        return not self.successors

    def to_dict(self, is_entry: bool = False) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "function": self.function,
            "start": self.start,
            "end": self.end,
            "label": self.label,
            "leader_reasons": list(self.leader_reasons),
            "instructions": [
                ins.to_dict(self.start + i) for i, ins in enumerate(self.instructions)
            ],
            "successors": list(self.successors),
            "predecessors": list(self.predecessors),
            "reachable": self.reachable,
            "is_entry": is_entry,
            "is_exit": self.is_exit,
        }


@dataclass
class Edge:
    source: str
    target: str
    kind: str

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "kind": self.kind}


@dataclass
class CFG:
    function: str
    blocks: List[BasicBlock] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)

    @property
    def entry(self) -> Optional[str]:
        return self.blocks[0].name if self.blocks else None

    @property
    def exits(self) -> List[str]:
        return [b.name for b in self.blocks if b.is_exit]

    def block(self, name: str) -> BasicBlock:
        for b in self.blocks:
            if b.name == name:
                return b
        raise KeyError(name)

    def flatten(self) -> List[TACInstruction]:
        """The blocks' instructions back in their original linear order."""
        return [ins for b in self.blocks for ins in b.instructions]

    def format(self) -> str:
        lines: List[str] = []
        for b in self.blocks:
            tags = "; ".join(b.leader_reasons)
            flags = "" if b.reachable else "  [unreachable]"
            lines.append(f"{b.name}  (leader: {tags}){flags}")
            for ins in b.instructions:
                lines.append(("    " if not ins.is_label else "  ") + ins.text())
            kinds = {(e.target): e.kind for e in self.edges if e.source == b.name}
            if b.successors:
                lines.append("    -> " + ", ".join(f"{t} ({kinds[t]})" for t in b.successors))
            else:
                lines.append("    -> (exit)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "entry": self.entry,
            "exits": self.exits,
            "blocks": [b.to_dict(is_entry=(b.name == self.entry)) for b in self.blocks],
            "edges": [e.to_dict() for e in self.edges],
        }


def build_cfg(fn: TACFunction) -> CFG:
    """Split *fn* into basic blocks and connect them."""
    instructions = fn.instructions
    cfg = CFG(fn.name)
    if not instructions:
        return cfg

    leaders = find_leaders(instructions)
    starts = list(leaders)
    for k, start in enumerate(starts):
        end = starts[k + 1] - 1 if k + 1 < len(starts) else len(instructions) - 1
        cfg.blocks.append(BasicBlock(
            id=k + 1, name=f"B{k + 1}", function=fn.name, start=start, end=end,
            instructions=instructions[start:end + 1], leader_reasons=leaders[start],
        ))

    block_at_label: Dict[str, BasicBlock] = {
        b.label: b for b in cfg.blocks if b.label is not None
    }

    def connect(src: BasicBlock, dst: BasicBlock, kind: str) -> None:
        cfg.edges.append(Edge(src.name, dst.name, kind))
        if dst.name not in src.successors:
            src.successors.append(dst.name)
        if src.name not in dst.predecessors:
            dst.predecessors.append(src.name)

    for k, block in enumerate(cfg.blocks):
        last = block.instructions[-1]
        following = cfg.blocks[k + 1] if k + 1 < len(cfg.blocks) else None
        if last.op == T.OP_GOTO:
            connect(block, block_at_label[last.jump_target], EDGE_JUMP)
        elif last.is_conditional_jump:
            target = block_at_label[last.jump_target]
            if following is target:
                connect(block, target, EDGE_BRANCH)          # both outcomes land here
            else:
                taken = EDGE_TRUE if last.op == T.OP_IF_TRUE else EDGE_FALSE
                fallen = EDGE_FALSE if last.op == T.OP_IF_TRUE else EDGE_TRUE
                edges = [(target, taken)]
                if following is not None:
                    edges.append((following, fallen))
                for dst, kind in sorted(edges, key=lambda e: e[1] != EDGE_TRUE):   # "true" first
                    connect(block, dst, kind)
        elif last.op == T.OP_RETURN:
            pass                                             # leaves the function
        elif following is not None:
            connect(block, following, EDGE_NEXT)

    _mark_reachable(cfg)
    return cfg


def _mark_reachable(cfg: CFG) -> None:
    by_name = {b.name: b for b in cfg.blocks}
    for b in cfg.blocks:
        b.reachable = False
    stack = [cfg.blocks[0].name]
    while stack:
        block = by_name[stack.pop()]
        if block.reachable:
            continue
        block.reachable = True
        stack.extend(block.successors)


# ----------------------------------------------------------------------
# Whole program
# ----------------------------------------------------------------------
@dataclass
class ProgramCFG:
    graphs: List[CFG] = field(default_factory=list)

    def graph(self, function: str) -> CFG:
        for g in self.graphs:
            if g.function == function:
                return g
        raise KeyError(function)

    def format(self) -> str:
        parts = []
        for g in self.graphs:
            header = "main:" if g.function == "main" else f"function {g.function}:"
            parts.append(header + "\n" + (g.format() if g.blocks else "  (no instructions)"))
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {"functions": [g.to_dict() for g in self.graphs]}


def build_program_cfg(program: TACProgram) -> ProgramCFG:
    return ProgramCFG([build_cfg(fn) for fn in program.all_functions()])


@dataclass
class CFGResult:
    tac: Optional[TACProgram] = None
    cfg: Optional[ProgramCFG] = None
    errors: List[NovaLangError] = field(default_factory=list)
    warnings: List[NovaLangError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tac": self.tac.to_dict() if self.tac else None,
            "cfg": self.cfg.to_dict() if self.cfg else None,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


def compile_to_cfg(source: str) -> CFGResult:
    """Lex, parse, analyze, generate TAC and build the CFGs of *source*."""
    result = compile_to_tac(source)
    if not result.ok:
        return CFGResult(errors=result.errors, warnings=result.warnings)
    return CFGResult(result.program, build_program_cfg(result.program), [], result.warnings)
