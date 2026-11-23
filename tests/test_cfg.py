import json
import os

import pytest

from compiler.ir import tac as T
from compiler.ir.basic_blocks import (
    REASON_AFTER_JUMP, REASON_AFTER_RETURN, REASON_FIRST, REASON_TARGET,
    build_cfg, build_program_cfg, compile_to_cfg, find_leaders,
)
from compiler.ir.generator import compile_to_tac
from compiler.ir.tac import TACFunction, TACInstruction

from test_tac import EXAMPLES, PROGRAMS


# ------------------------------------------------------------------ helpers
def cfgs(src):
    r = compile_to_cfg(src)
    assert r.ok, [e.message for e in r.errors]
    return r.cfg


def main_cfg(src):
    return cfgs(src).graph("main")


def edges(cfg):
    return [(e.source, e.target, e.kind) for e in cfg.edges]


def spans(cfg):
    return [(b.name, b.start, b.end) for b in cfg.blocks]


def ins(op, a1=None, a2=None, r=None):
    return TACInstruction(op, a1, a2, r)


def check_invariants(fn: TACFunction, cfg):
    """Structural properties every correct CFG must satisfy."""
    code = fn.instructions
    if not code:
        assert cfg.blocks == [] and cfg.entry is None
        return

    # the blocks partition the instructions, in order, with nothing lost or duplicated
    assert len(cfg.flatten()) == len(code) and all(a is b for a, b in zip(cfg.flatten(), code))
    assert cfg.blocks[0].start == 0 and cfg.blocks[-1].end == len(code) - 1
    for prev, cur in zip(cfg.blocks, cfg.blocks[1:]):
        assert cur.start == prev.end + 1
    for b in cfg.blocks:
        assert b.instructions == code[b.start:b.end + 1] and b.leader_reasons

    # one exit per block: jumps and returns appear only as the LAST instruction
    for b in cfg.blocks:
        for i in b.instructions[:-1]:
            assert not i.is_jump and i.op != T.OP_RETURN

    # one entry per block: every jump target is the first instruction of a block
    starts = {b.label: b for b in cfg.blocks if b.label}
    for i in code:
        if i.is_jump:
            assert i.jump_target in starts
    for b in cfg.blocks[1:]:             # a label can only sit at the top of a block
        assert all(not i.is_label for i in b.instructions[1:])
    assert all(not i.is_label for i in cfg.blocks[0].instructions[1:])

    # edges agree with successors/predecessors
    by_name = {b.name: b for b in cfg.blocks}
    for e in cfg.edges:
        assert e.target in by_name[e.source].successors
        assert e.source in by_name[e.target].predecessors
    for b in cfg.blocks:
        assert len(set(b.successors)) == len(b.successors)
        for s in b.successors:
            assert b.name in by_name[s].predecessors
        for p in b.predecessors:
            assert b.name in by_name[p].successors

    # edge shape follows the last instruction
    for k, b in enumerate(cfg.blocks):
        last = b.instructions[-1]
        out = [e for e in cfg.edges if e.source == b.name]
        if last.op == T.OP_RETURN:
            assert out == []
        elif last.op == T.OP_GOTO:
            assert [(e.target, e.kind) for e in out] == [(starts[last.jump_target].name, "jump")]
        elif last.is_conditional_jump:
            assert 1 <= len(out) <= 2
            if len(out) == 2:
                assert {e.kind for e in out} == {"true", "false"} and out[0].kind == "true"
            else:
                assert out[0].kind == "branch" or k == len(cfg.blocks) - 1
        elif k + 1 < len(cfg.blocks):
            assert [(e.target, e.kind) for e in out] == [(cfg.blocks[k + 1].name, "next")]
        else:
            assert out == []

    # exits are exactly the blocks without successors
    assert cfg.exits == [b.name for b in cfg.blocks if not b.successors]

    # reachability flag matches an independent traversal
    seen, stack = set(), [cfg.entry]
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack.extend(by_name[n].successors)
    assert {b.name for b in cfg.blocks if b.reachable} == seen


# ================================================================= leaders
def test_leaders_first_instruction_always():
    assert find_leaders([ins(T.OP_PRINT, "1")]) == {0: [REASON_FIRST]}


def test_leaders_empty():
    assert find_leaders([]) == {}


def test_leaders_follow_jumps_and_targets():
    code = [
        ins(T.OP_COPY, "1", None, "x"),               # 0  first
        ins(T.OP_IF_FALSE, "x", None, "L1"),          # 1
        ins(T.OP_PRINT, "1"),                         # 2  follows a jump
        ins(T.OP_LABEL, r="L1"),                      # 3  target
        ins(T.OP_PRINT, "2"),                         # 4
    ]
    assert find_leaders(code) == {
        0: [REASON_FIRST], 2: [REASON_AFTER_JUMP], 3: [REASON_TARGET],
    }


def test_leader_with_several_reasons():
    code = [ins(T.OP_GOTO, r="L1"), ins(T.OP_LABEL, r="L1")]
    assert find_leaders(code) == {0: [REASON_FIRST], 1: [REASON_TARGET, REASON_AFTER_JUMP]}


def test_leaders_after_return():
    code = [ins(T.OP_RETURN, "1"), ins(T.OP_PRINT, "2")]
    assert find_leaders(code) == {0: [REASON_FIRST], 1: [REASON_AFTER_RETURN]}


def test_jump_to_last_instruction_has_no_following_leader():
    code = [ins(T.OP_PRINT, "1"), ins(T.OP_GOTO, r="L1"), ins(T.OP_LABEL, r="L1")]
    assert list(find_leaders(code)) == [0, 2]


def test_jump_to_undefined_label_is_rejected():
    with pytest.raises(ValueError, match="undefined label 'L9'"):
        find_leaders([ins(T.OP_GOTO, r="L9")])
    with pytest.raises(ValueError):
        build_cfg(TACFunction("main", [], [ins(T.OP_IF_FALSE, "x", None, "L9")]))


# =========================================================== exact small graphs
def test_straight_line_code_is_one_block():
    g = main_cfg("let a = 1; let b = a + 2; print(b);")
    assert spans(g) == [("B1", 0, 3)] and g.edges == [] and g.exits == ["B1"]
    assert g.blocks[0].is_exit and g.blocks[0].leader_reasons == [REASON_FIRST]


def test_empty_program_has_no_blocks():
    g = main_cfg("")
    assert g.blocks == [] and g.entry is None and g.exits == [] and g.flatten() == []
    assert cfgs("").format() == "main:\n  (no instructions)"


def test_if_else_diamond():
    g = main_cfg("let x = 1; if (x < 2) { print(1); } else { print(2); } print(3);")
    assert spans(g) == [("B1", 0, 2), ("B2", 3, 4), ("B3", 5, 6), ("B4", 7, 8)]
    assert edges(g) == [
        ("B1", "B2", "true"), ("B1", "B3", "false"),
        ("B2", "B4", "jump"), ("B3", "B4", "next"),
    ]
    assert g.block("B4").predecessors == ["B2", "B3"]
    assert g.exits == ["B4"] and g.entry == "B1"
    assert g.block("B3").label == "L1" and g.block("B4").label == "L2"


def test_if_without_else():
    g = main_cfg("let x = 1; if (x < 2) { print(1); } print(2);")
    assert spans(g) == [("B1", 0, 2), ("B2", 3, 3), ("B3", 4, 5)]
    assert edges(g) == [("B1", "B2", "true"), ("B1", "B3", "false"), ("B2", "B3", "next")]


def test_while_loop_has_a_back_edge():
    g = main_cfg("let i = 0; while (i < 3) { i = i + 1; }")
    assert spans(g) == [("B1", 0, 0), ("B2", 1, 3), ("B3", 4, 6), ("B4", 7, 7)]
    assert edges(g) == [
        ("B1", "B2", "next"), ("B2", "B3", "true"), ("B2", "B4", "false"), ("B3", "B2", "jump"),
    ]
    assert g.block("B2").predecessors == ["B1", "B3"]


def test_for_loop_with_continue():
    g = main_cfg("for (let i = 0; i < 3; i = i + 1) { if (i == 1) { continue; } print(i); }")
    assert spans(g) == [
        ("B1", 0, 0), ("B2", 1, 3), ("B3", 4, 5), ("B4", 6, 6),
        ("B5", 7, 8), ("B6", 9, 12), ("B7", 13, 13),
    ]
    assert edges(g) == [
        ("B1", "B2", "next"),
        ("B2", "B3", "true"), ("B2", "B7", "false"),
        ("B3", "B4", "true"), ("B3", "B5", "false"),
        ("B4", "B6", "jump"), ("B5", "B6", "next"),
        ("B6", "B2", "jump"),
    ]
    assert all(b.reachable for b in g.blocks)


def test_short_circuit_creates_blocks():
    g = main_cfg("let a = true; let b = false; let c = a && b;")
    assert spans(g) == [("B1", 0, 3), ("B2", 4, 4), ("B3", 5, 6)]
    assert edges(g) == [("B1", "B2", "true"), ("B1", "B3", "false"), ("B2", "B3", "next")]


def test_or_conditional_uses_if_true_edges():
    # `if t1 goto L1` jumps when TRUE, so the jump edge is "true" and the fall-through is "false";
    # the "true" edge is always listed first.
    g = main_cfg("let a = true; let b = false; let c = a || b;")
    assert spans(g) == [("B1", 0, 3), ("B2", 4, 4), ("B3", 5, 6)]
    assert edges(g) == [("B1", "B3", "true"), ("B1", "B2", "false"), ("B2", "B3", "next")]
    assert g.block("B1").successors == ["B3", "B2"]


def test_function_graphs_have_their_own_numbering():
    src = open(os.path.join(os.path.dirname(__file__), "..", "examples", "demo_factorial.nova")).read()
    prog = cfgs(src)
    assert [g.function for g in prog.graphs] == ["main", "factorial"]
    assert [b.name for b in prog.graph("main").blocks] == ["B1"]
    f = prog.graph("factorial")
    assert spans(f) == [("B1", 0, 1), ("B2", 2, 2), ("B3", 3, 8)]
    assert edges(f) == [("B1", "B2", "true"), ("B1", "B3", "false")]
    assert f.exits == ["B2", "B3"]
    assert f.block("B3").leader_reasons == [REASON_TARGET, REASON_AFTER_RETURN]


def test_conditional_whose_branches_meet_gets_one_branch_edge():
    g = main_cfg("if (true) { }")
    assert spans(g) == [("B1", 0, 0), ("B2", 1, 1)]
    assert edges(g) == [("B1", "B2", "branch")]
    assert g.block("B1").successors == ["B2"]


def test_conditional_as_last_instruction_has_only_the_jump_edge():
    code = [ins(T.OP_IF_FALSE, "x", None, "L1"), ins(T.OP_RETURN, "1"), ins(T.OP_LABEL, r="L1")]
    g = build_cfg(TACFunction("f", [], code))
    assert edges(g) == [("B1", "B2", "true"), ("B1", "B3", "false")]
    last_only = [ins(T.OP_LABEL, r="L1"), ins(T.OP_IF_FALSE, "x", None, "L1")]
    g = build_cfg(TACFunction("f", [], last_only))
    assert edges(g) == [("B1", "B1", "false")]


# ================================================================ unreachable
def test_code_after_return_is_unreachable():
    g = cfgs("function f() { return 1; print(2); }").graph("f")
    assert spans(g) == [("B1", 0, 0), ("B2", 1, 2)]
    assert [b.reachable for b in g.blocks] == [True, False]
    assert g.block("B2").leader_reasons == [REASON_AFTER_RETURN]
    assert "[unreachable]" in g.format()


def test_code_after_break_is_unreachable():
    g = main_cfg("while (true) { break; }")
    assert spans(g) == [("B1", 0, 1), ("B2", 2, 2), ("B3", 3, 3), ("B4", 4, 4)]
    assert [b.reachable for b in g.blocks] == [True, True, False, True]
    assert g.block("B3").successors == ["B1"]          # edges out of dead code are still recorded
    assert "B3" in g.block("B1").predecessors


def test_if_else_that_returns_on_both_paths_leaves_dead_jumps():
    # The generator emits `goto end` after each then-branch and an implicit
    # `return nil` at the end. When every branch returns, those are dead code:
    # the CFG shows them (flagged unreachable) and the Phase 7 optimizer removes them.
    g = cfgs("function f(x) { if (x) { return 1; } else { return 2; } }").graph("f")
    assert spans(g) == [("B1", 0, 0), ("B2", 1, 1), ("B3", 2, 2), ("B4", 3, 4), ("B5", 5, 6)]
    assert [b.reachable for b in g.blocks] == [True, True, False, True, False]
    assert [i.text() for i in g.block("B3").instructions] == ["goto L2"]
    assert [i.text() for i in g.block("B5").instructions] == ["L2:", "return nil"]
    assert g.block("B3").predecessors == []                # nothing jumps to dead code


def test_dead_code_in_examples_is_only_dead_jumps_labels_and_the_implicit_return():
    for path in EXAMPLES:
        for g in build_program_cfg(compile_to_tac(open(path).read()).program).graphs:
            for b in g.blocks:
                if b.reachable:
                    continue
                assert g.function != "main", (path, b.name)
                assert all(i.op in (T.OP_GOTO, T.OP_LABEL, T.OP_RETURN) for i in b.instructions)
                assert all(not g.block(p).reachable for p in b.predecessors)


# ===================================================== invariants everywhere
@pytest.mark.parametrize("path", EXAMPLES, ids=[os.path.basename(p) for p in EXAMPLES])
def test_example_cfg_invariants(path):
    prog = compile_to_tac(open(path).read()).program
    for fn in prog.all_functions():
        check_invariants(fn, build_cfg(fn))


@pytest.mark.parametrize("name", sorted(n for n in PROGRAMS if not n.startswith("error_")))
def test_program_cfg_invariants(name):
    result = compile_to_tac(PROGRAMS[name])
    assert result.ok
    for fn in result.program.all_functions():
        check_invariants(fn, build_cfg(fn))


# ======================================================================= output
def test_flatten_restores_the_original_listing():
    prog = compile_to_tac("let i = 0; while (i < 3) { i = i + 1; } print(i);").program
    g = build_cfg(prog.main)
    assert [i.text() for i in g.flatten()] == [i.text() for i in prog.main.instructions]


def test_cfg_to_dict_is_json_friendly():
    result = compile_to_cfg("let x = 1; if (x < 2) { print(1); } else { print(2); }")
    d = json.loads(json.dumps(result.to_dict()))
    assert d["ok"] and d["tac"]["functions"][0]["name"] == "main"
    graph = d["cfg"]["functions"][0]
    assert graph["function"] == "main" and graph["entry"] == "B1" and graph["exits"] == ["B4"]
    b1, b2 = graph["blocks"][0], graph["blocks"][1]
    assert b1["is_entry"] and not b2["is_entry"]
    assert b1["name"] == "B1" and b1["id"] == 1 and b1["leader_reasons"] == ["first instruction"]
    assert b1["successors"] == ["B2", "B3"] and b2["predecessors"] == ["B1"]
    assert b2["instructions"][0]["index"] == b2["start"] == 3          # index within the function
    assert b2["instructions"][0]["text"] == "print 1"
    assert {"source": "B1", "target": "B2", "kind": "true"} in graph["edges"]
    assert graph["blocks"][2]["label"] == "L1" and b1["label"] is None


def test_cfg_format_text():
    text = cfgs("let x = 1; if (x < 2) { print(1); } else { print(2); }").format()
    assert text.startswith("main:\nB1  (leader: first instruction)\n    x = 1")
    assert "    -> B2 (true), B3 (false)" in text
    assert "  L1:\n    print 2" in text
    assert "    -> (exit)" in text


def test_lookup_errors():
    prog = cfgs("let x = 1;")
    with pytest.raises(KeyError):
        prog.graph("nope")
    with pytest.raises(KeyError):
        prog.graph("main").block("B9")


def test_compile_to_cfg_reports_front_end_errors_and_warnings():
    r = compile_to_cfg("print(y);")
    assert not r.ok and r.cfg is None and r.tac is None and r.errors[0].phase == "Semantic Error"
    assert r.to_dict()["cfg"] is None
    r = compile_to_cfg("let x = 1 / 0;")
    assert r.ok and len(r.warnings) == 1 and r.cfg is not None


def test_block_numbers_are_ids():
    g = main_cfg("let i = 0; while (i < 3) { i = i + 1; }")
    assert [b.id for b in g.blocks] == [1, 2, 3, 4]
