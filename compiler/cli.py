"""Command-line view of the whole pipeline:  python -m compiler examples/demo_factorial.nova

Prints what the web playground shows, as plain text: every one of the ten stages. It is built
on ``run_pipeline`` (the same function the API calls), so the terminal and the browser can never
disagree about what the compiler did.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from compiler.pipeline import STAGE_IDS, STAGES, PipelineResult, run_pipeline

NAMES = dict(STAGES)
MARK = {"ok": "ok", "warning": "ok, with warnings", "error": "FAILED", "skipped": "skipped"}


# ----------------------------------------------------------------------
# One renderer per stage (each reads the plain-data form the API returns)
# ----------------------------------------------------------------------
def _tokens(data) -> str:
    return "\n".join(f"{t['line']:>4}:{t['column']:<4} {t['type']:<12} {t['lexeme']!r}" for t in data)


def _ast(node, depth=0) -> str:
    label = f" {node['label']}" if node.get("label") else ""
    kind = f"   : {node['inferred_type']}" if node.get("inferred_type") else ""
    lines = [f"{'  ' * depth}{node['type']}{label}{kind}"]
    for key, value in node.items():
        kids = value if isinstance(value, list) else [value]
        for kid in kids:
            if isinstance(kid, dict) and "type" in kid and "line" in kid:
                lines.append(_ast(kid, depth + 1))
    return "\n".join(lines)


def _symbols(scope, depth=0) -> str:
    pad = "  " * depth
    lines = [f"{pad}{scope['name']}  ({scope['kind']})"]
    for s in scope["symbols"]:
        params = f"({', '.join(s['params'])})" if s.get("params") is not None else ""
        lines.append(f"{pad}  {s['name']}{params}: {s['kind']}, type {s['type']}, line {s['line']}")
    for child in scope["children"]:
        if child["symbols"] or child["children"]:
            lines.append(_symbols(child, depth + 1))
    return "\n".join(lines)


def _cfg(data) -> str:
    lines: List[str] = []
    for fn in data["functions"]:
        lines.append("main:" if fn["function"] == "main" else f"function {fn['function']}:")
        for b in fn["blocks"]:
            flag = "" if b["reachable"] else "  [unreachable]"
            lines.append(f"  {b['name']}  ({'; '.join(b['leader_reasons'])}){flag}")
            lines.extend(f"      {i['text']}" for i in b["instructions"])
            out = [f"{e['target']} ({e['kind']})" for e in fn["edges"] if e["source"] == b["name"]]
            lines.append("      -> " + (", ".join(out) if out else "(exit)"))
    return "\n".join(lines)


def _optimized(data) -> str:
    lines = [f"{data['instruction_counts']['before']} -> {data['instruction_counts']['after']} instructions", ""]
    lines.append(data["optimized"]["listing"])
    if data["changes"]:
        lines += ["", "What changed:"]
        for c in data["changes"]:
            after = c["after"] if c["after"] is not None else "(deleted)"
            lines.append(f"  [{c['pass']}] {c['before']}  =>  {after}")
    return "\n".join(lines)


def _execution(data) -> str:
    lines = ["Output:"] + [f"  {row}" for row in data["output"].splitlines()]
    lines.append(f"{data['steps']} steps; optimized TAC output "
                 + ("is identical" if data["verified"] else "DIFFERS (compiler bug!)"))
    return "\n".join(lines)


def render_stage(stage_id: str, data) -> str:
    return {
        "source": lambda d: d["text"].rstrip("\n"),
        "tokens": _tokens,
        "ast": _ast,
        "semantic": lambda d: "\n".join(i["message"] for i in d["info"]) or "(nothing declared)",
        "symbol_table": _symbols,
        "tac": lambda d: d["listing"],
        "cfg": _cfg,
        "optimized_tac": _optimized,
        "optimized_cfg": _cfg,
        "execution": _execution,
    }[stage_id](data)


def render(result: PipelineResult, only: Optional[str] = None) -> str:
    """All stages (or just *only*) as text; errors are shown with the caret-under-source format."""
    parts: List[str] = []
    number = 0
    for stage in result.stages:
        number += 1
        if only and stage.id != only:
            continue
        head = f"[{number}/{len(STAGES)}] {NAMES[stage.id]}  -  {MARK[stage.status]}"
        if stage.summary:
            head += f"   ({stage.summary})"
        parts.append(head + "\n" + "=" * len(head))
        if stage.data is not None and stage.status != "skipped":
            parts.append(render_stage(stage.id, stage.data))
        for problem in [*stage.errors, *stage.warnings]:
            parts.append(problem.format(result.source))
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compiler", description="Run a NovaLang program through every compiler stage.")
    ap.add_argument("file", help="a .nova file, or - to read standard input")
    ap.add_argument("--stage", choices=STAGE_IDS, help="show only this stage")
    ap.add_argument("--json", action="store_true", help="print the API's JSON instead of text")
    args = ap.parse_args(argv)
    try:
        source = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    except OSError as exc:
        print(f"cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 2
    result = run_pipeline(source)
    if args.json:
        print(json.dumps(result.to_dict(only=[args.stage] if args.stage else None), indent=2))
    else:
        sys.stdout.write(render(result, args.stage))
    return 0 if result.ok else 1
