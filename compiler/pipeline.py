"""The whole NovaLang pipeline behind ONE function.

Compiler concept: a compiler is a chain of stages, each consuming the previous
stage's output. The web API (and any future command-line tool) must not
re-implement that chain, otherwise the endpoints drift apart and disagree about
what the compiler does. So all of the orchestration lives here, and the API
layer is only a thin wrapper that calls ``run_pipeline``.

The ten stages, in order::

    source -> tokens -> ast -> semantic -> symbol_table
           -> tac -> cfg -> optimized_tac -> optimized_cfg -> execution

Every stage reports a ``status``:

    ok       the stage ran and produced its output
    warning  it ran, but produced warnings (e.g. unreachable code)
    error    it ran and found errors; later stages are skipped
    skipped  not run, because an earlier stage failed or ``upto`` stopped earlier

A stage never raises: failures are data, because the frontend needs to show
*which* stage broke and why.

Execution has one extra twist. The program is run by the tree-walking
interpreter (the reference semantics) AND the optimized TAC is run on the TAC
machine. If both succeed with the same output the response says
``verified: true``: a live proof, on the user's own program, that the
optimizer preserved behaviour. A run-time error is *not* a pipeline failure --
the error is the program's behaviour, and both engines must agree about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from compiler.errors.errors import LexicalError, NovaLangError
from compiler.interpreter.interpreter import RunResult, interpret
from compiler.ir.basic_blocks import build_program_cfg
from compiler.ir.generator import generate_tac
from compiler.ir.tac_runner import run_tac
from compiler.optimizer.optimizer import optimize
from compiler.parser.parser import parse
from compiler.semantic.analyzer import analyze

# ----------------------------------------------------------------------
# Stage catalogue
# ----------------------------------------------------------------------
STAGES = [
    ("source", "Source Code"),
    ("tokens", "Tokens"),
    ("ast", "Abstract Syntax Tree"),
    ("semantic", "Semantic Analysis"),
    ("symbol_table", "Symbol Table"),
    ("tac", "Three Address Code"),
    ("cfg", "Basic Blocks & CFG"),
    ("optimized_tac", "Optimized TAC"),
    ("optimized_cfg", "Optimized CFG"),
    ("execution", "Execution"),
]
STAGE_IDS = [s[0] for s in STAGES]

OK, WARNING, ERROR, SKIPPED = "ok", "warning", "error", "skipped"

# Which stages each API endpoint wants (it runs the pipeline up to the last one).
UPTO = {
    "lex": "tokens",
    "parse": "ast",
    "analyze": "symbol_table",
    "tac": "tac",
    "cfg": "cfg",
    "optimize": "optimized_cfg",
    "run": "execution",
    "compile": "execution",
}


@dataclass
class Stage:
    id: str
    name: str
    status: str = SKIPPED
    summary: str = ""
    data: Any = None
    errors: List[NovaLangError] = field(default_factory=list)
    warnings: List[NovaLangError] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "data": self.data,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


@dataclass
class PipelineResult:
    source: str
    stages: List[Stage]

    # ------------------------------------------------------------ queries
    def stage(self, stage_id: str) -> Stage:
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(stage_id)

    @property
    def errors(self) -> List[NovaLangError]:
        return [e for s in self.stages for e in s.errors]

    @property
    def warnings(self) -> List[NovaLangError]:
        return [w for s in self.stages for w in s.warnings]

    @property
    def ok(self) -> bool:
        """True when no stage reported an error (a stage left 'skipped' by ``upto`` is fine)."""
        return not self.errors

    @property
    def failed_stage(self) -> Optional[str]:
        for s in self.stages:
            if s.status == ERROR:
                return s.id
        return None

    def to_dict(self, only: Optional[List[str]] = None) -> dict:
        stages = [s for s in self.stages if only is None or s.id in only]
        return {
            "ok": self.ok,
            "failed_stage": self.failed_stage,
            "source": self.source,
            "stages": [s.to_dict() for s in stages],
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


# ----------------------------------------------------------------------
# The pipeline
# ----------------------------------------------------------------------
def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _finish(stage: Stage) -> None:
    """Derive the status from the errors / warnings a stage collected."""
    if stage.errors:
        stage.status = ERROR
    elif stage.warnings:
        stage.status = WARNING
    else:
        stage.status = OK


def run_pipeline(source: str, upto: str = "execution") -> PipelineResult:
    """Run the compiler on *source*, stopping after the stage named *upto*."""
    if upto not in STAGE_IDS:
        raise ValueError(f"unknown stage {upto!r}; choose from {STAGE_IDS}")
    last = STAGE_IDS.index(upto)
    stages = {sid: Stage(sid, name) for sid, name in STAGES}
    result = PipelineResult(source, [stages[sid] for sid in STAGE_IDS])

    def wanted(stage_id: str) -> bool:
        return STAGE_IDS.index(stage_id) <= last

    # 1. source ---------------------------------------------------------
    s = stages["source"]
    s.data = {"text": source, "lines": source.count("\n") + 1 if source else 0}
    s.summary = f"{_plural(s.data['lines'], 'line')}, {_plural(len(source), 'character')}"
    s.status = OK
    if not wanted("tokens"):
        return result

    # 2-3. tokens and AST (one call: the parser owns the lexer) -------------
    parsed = parse(source)
    lex_errors = [e for e in parsed.errors if isinstance(e, LexicalError)]
    syntax_errors = [e for e in parsed.errors if not isinstance(e, LexicalError)]

    s = stages["tokens"]
    s.data = [t.to_dict() for t in parsed.tokens]
    s.errors = lex_errors
    s.summary = _plural(len(parsed.tokens), "token") + (
        f", {_plural(len(lex_errors), 'lexical error')}" if lex_errors else "")
    _finish(s)
    if lex_errors or not wanted("ast"):
        return result

    s = stages["ast"]
    s.errors = syntax_errors
    if parsed.program is None or syntax_errors:
        s.summary = _plural(len(syntax_errors), "syntax error")
        _finish(s)
        return result

    # 4-5. semantic analysis (decorates the AST with inferred types) -------
    program = parsed.program
    sem = analyze(program)
    s.data = program.to_dict()            # serialized AFTER analysis: carries inferred_type
    s.summary = f"{_plural(len(program.body), 'top-level statement')}"
    _finish(s)
    if not wanted("semantic"):
        return result

    s = stages["semantic"]
    s.data = {"info": list(sem.info)}
    s.errors = list(sem.errors)
    s.warnings = list(sem.warnings)
    s.summary = (f"{_plural(len(sem.errors), 'error')}, {_plural(len(sem.warnings), 'warning')}")
    _finish(s)

    sym = stages["symbol_table"]
    if sem.symbol_table is not None and wanted("symbol_table"):
        sym.data = sem.symbol_table.to_dict()
        sym.summary = "scope tree built"
        sym.status = OK
    if sem.errors or not wanted("tac"):
        return result

    # 6. TAC ----------------------------------------------------------------
    tac = generate_tac(program)
    s = stages["tac"]
    s.data = tac.to_dict()
    n_before = sum(len(f.instructions) for f in tac.all_functions())
    s.summary = f"{_plural(n_before, 'instruction')} in {_plural(len(tac.all_functions()), 'function')}"
    s.status = OK
    if not wanted("cfg"):
        return result

    # 7. basic blocks and CFG --------------------------------------------------
    cfg = build_program_cfg(tac)
    s = stages["cfg"]
    s.data = cfg.to_dict()
    n_blocks = sum(len(g.blocks) for g in cfg.graphs)
    s.summary = _plural(n_blocks, "basic block")
    s.status = OK
    if not wanted("optimized_tac"):
        return result

    # 8-9. optimization ----------------------------------------------------------
    opt = optimize(tac)
    s = stages["optimized_tac"]
    s.data = opt.to_dict()
    counts = opt.instruction_counts
    s.summary = (f"{counts['before']} -> {counts['after']} instructions, "
                 f"{_plural(len(opt.changes), 'change')}")
    s.status = OK
    if not wanted("optimized_cfg"):
        return result

    s = stages["optimized_cfg"]
    opt_cfg = build_program_cfg(opt.optimized)
    s.data = opt_cfg.to_dict()
    s.summary = _plural(sum(len(g.blocks) for g in opt_cfg.graphs), "basic block")
    s.status = OK
    if not wanted("execution"):
        return result

    # 10. execution ------------------------------------------------------------------
    s = stages["execution"]
    ref = interpret(program)
    via_tac = run_tac(opt.optimized)
    verified = _same_behaviour(ref, via_tac)
    s.data = {
        "output": ref.output,
        "steps": ref.steps,
        "variables": dict(ref.variables),
        "optimized_output": via_tac.output,
        "verified": verified,
    }
    s.errors = list(ref.errors)           # a run-time error is the program's behaviour
    if ref.errors:
        s.summary = "stopped by a run-time error"
    else:
        s.summary = (f"{_plural(ref.steps, 'step')}; optimized TAC "
                     + ("gives identical output" if verified else "DIFFERS (compiler bug!)"))
    _finish(s)
    return result


def _same_behaviour(a: RunResult, b: RunResult) -> bool:
    """Same printed output and the same kind of failure (message wording may differ)."""
    return a.output == b.output and bool(a.errors) == bool(b.errors)
