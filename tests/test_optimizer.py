import glob
import json
import os
import random

import pytest

from compiler.interpreter.interpreter import interpret
from compiler.ir import tac as T
from compiler.ir.basic_blocks import build_cfg, compile_to_cfg
from compiler.ir.generator import compile_to_tac, generate_tac
from compiler.ir.tac import TACFunction, TACInstruction, TACProgram
from compiler.ir.tac_runner import run_tac
from compiler.optimizer.dataflow import (
    NAC, analyze_constants, fold, live_out_sets, meet, transfer,
)
from compiler.optimizer.optimizer import compile_and_optimize, optimize
from compiler.optimizer.type_inference import (
    ANY, ARRAY, BOOL, FLOAT, INT, NIL, NUM, STRING, TypeInfo, constant_type, join,
    result_type,
)
from compiler.semantic.analyzer import analyze_source

from test_tac import EXAMPLES, PROGRAMS, _bool_expr, _int_expr, _normalize

HERE = os.path.dirname(__file__)


# ------------------------------------------------------------------ helpers
def opt(src):
    r = compile_and_optimize(src)
    assert r.ok, [e.message for e in r.errors]
    return r.result


def lines(instructions):
    return [i.text() for i in instructions]


def main_after(src):
    return lines(opt(src).optimized.main.instructions)


def fn_after(src, name):
    return lines(opt(src).optimized.function(name).instructions)


def has_instruction(after, op, constant):
    """True if some instruction is exactly `<dest> = <something> <op> <constant>`."""
    return any(l.endswith(f" {op} {constant}") for l in after)


def assert_well_formed(prog):
    for fn in prog.all_functions():
        labels = [i.result for i in fn.instructions if i.is_label]
        assert len(labels) == len(set(labels))
        for i in fn.instructions:
            if i.is_jump:
                assert i.jump_target in labels
        if not fn.is_main and fn.instructions:
            assert fn.instructions[-1].is_terminator       # ends in return or goto
        build_cfg(fn)                                       # must build without error


def check_equivalent(src):
    """The optimizer's contract: optimized TAC behaves exactly like the original
    TAC and like the AST interpreter -- same output, same error, same final globals."""
    sem = analyze_source(src)
    assert sem.ok, [e.message for e in sem.errors]
    expected = interpret(sem.program)
    prog = generate_tac(sem.program)
    original = run_tac(prog)
    result = optimize(prog)
    optimized = run_tac(result.optimized)
    assert_well_formed(result.optimized)

    for run in (original, optimized):
        assert run.output == expected.output
        assert [_normalize(e.message) for e in run.errors] == \
            [_normalize(e.message) for e in expected.errors]
    for name in prog.globals:
        assert optimized.variables.get(name) == original.variables.get(name), name
    assert optimize(result.optimized).changes == [], "optimizing twice must change nothing more"
    return result, expected


# ============================================================ brief examples
def test_brief_example_constant_folding():
    assert lines(opt("let x = 10 + 20;").original.main.instructions) == ["t1 = 10 + 20", "x = t1"]
    assert main_after("let x = 10 + 20;") == ["x = 30"]


def test_brief_example_constant_propagation():
    assert main_after("let x = 10; let y = x + 5;") == ["x = 10", "y = 15"]


def test_brief_example_algebraic_simplification():
    src = "let n = 3; while (n > 0) { n = n - 1; print(n + 0); print(n * 1); print(n * 0); }"
    after = main_after(src)
    for pattern in (" + 0", " * 1", " * 0"):
        assert not any(pattern in l for l in after), after
    check_equivalent(src)


def test_brief_example_dead_code():
    assert main_after("function f() { return 1; print(2); }") == []     # main is empty
    assert fn_after("function f() { return 1; print(2); }", "f") == ["return 1"]


def test_brief_before_after_listing():
    text = opt("let x = 10 + 20;").format()
    assert text == ("BEFORE OPTIMIZATION\n\nmain:\n    t1 = 10 + 20\n    x = t1\n\n"
                    "AFTER OPTIMIZATION\n\nmain:\n    x = 30")


def test_demo_factorial_optimization():
    src = open(os.path.join(HERE, "..", "examples", "demo_factorial.nova")).read()
    result = opt(src)
    assert lines(result.optimized.main.instructions) == [
        "param 5", "result = call factorial, 1", "print result"]
    check_equivalent(src)


# ================================================================== folding
@pytest.mark.parametrize("src,expected", [
    ("print(2 + 3 * 4);", "print 14"),
    ("print((2 + 3) * 4);", "print 20"),
    ("print(10 - 3 - 2);", "print 5"),
    ("print(7 / 2);", "print 3"),
    ("print(-7 / 2);", "print -3"),
    ("print(7 % -3);", "print 1"),
    ("print(7 / 2.0);", "print 3.5"),
    ("print(1 + 2.5);", "print 3.5"),
    ('print("a" + "b");', 'print "ab"'),
    ('print("a" < "b");', "print true"),
    ("print(1 < 2);", "print true"),
    ("print(1 == 1.0);", "print true"),
    ("print(true == 1);", "print false"),
    ("print(!true);", "print false"),
    ("print(!!true);", "print true"),
    ("print(-(-5));", "print 5"),
    ("print(nil == nil);", "print true"),
    ("print(true && false || true);", "print true"),
])
def test_constant_folding(src, expected):
    assert main_after(src) == [expected]
    check_equivalent(src)


def test_operations_that_would_fail_are_not_folded():
    for src in ("print(1 / 0);", "print(5 % 0);", "print(1.5 / 0);"):
        after = main_after(src)
        assert any("/" in l or "%" in l for l in after), (src, after)
        result, expected = check_equivalent(src)
        assert expected.errors                      # the run-time error still happens


def test_expression_statement_that_fails_is_kept():
    assert main_after("1 / 0;") == ["t1 = 1 / 0"]


def test_huge_integers_are_not_folded_forever():
    src = "print(" + " * ".join(["100000000000000000000"] * 20) + ");"
    after = main_after(src)
    assert any("*" in l for l in after)             # stopped folding at the size limit
    check_equivalent(src)


def test_infinity_is_never_written_as_a_constant():
    big = "1" + "0" * 308 + ".0"
    src = f"let big = {big}; print(big * 10.0);"
    after = main_after(src)
    assert any("*" in l for l in after)
    result, expected = check_equivalent(src)
    assert expected.output == "inf\n"


def test_negative_zero_is_folded_faithfully():
    src = "let z = 0.0; let nz = -z; print(nz); print(nz + 0);"
    assert check_equivalent(src)[1].output == "-0.0\n0.0\n"


def test_fold_unit():
    assert fold("+", ["1", "2"]) == "3"
    assert fold("+", ["1", "2.5"]) == "3.5"
    assert fold("neg", ["5"]) == "-5"
    assert fold("not", ["true"]) == "false"
    assert fold("==", ["1", "1.0"]) == "true"
    assert fold("/", ["1", "0"]) is None
    assert fold("+", ['"a"', "1"]) is None          # type error stays for run time
    assert fold("neg", ['"a"']) is None
    assert fold("copy", ["1"]) is None
    assert fold("+", ['"' + "x" * 600 + '"', '"' + "y" * 600 + '"']) is None   # too long


# =============================================================== propagation
def test_straight_line_copies_and_arithmetic():
    assert main_after("let a = 5; let b = a; let c = b + 1;") == ["a = 5", "b = 5", "c = 6"]


def test_string_constants_propagate():
    assert main_after('let s = "hi"; print(s);') == ['s = "hi"', 'print "hi"']


def test_known_constant_joins_when_both_branches_agree():
    src = "function f(c) { let x = 0; if (c) { x = 5; } else { x = 5; } return x + 1; }"
    assert "return 6" in fn_after(src, "f")
    check_equivalent(src + "print(f(true)); print(f(false));")


def test_different_constants_at_a_join_are_not_propagated():
    src = "function f(c) { let x = 0; if (c) { x = 5; } else { x = 6; } return x + 1; }"
    assert any(" + 1" in l for l in fn_after(src, "f"))
    check_equivalent(src + "print(f(true)); print(f(false));")


def test_loop_variable_is_not_a_constant():
    src = "let i = 0; while (i < 3) { i = i + 1; } print(i);"
    after = main_after(src)
    assert "t1 = i < 3" in after and "print i" in after
    assert check_equivalent(src)[1].output == "3\n"


def test_value_set_before_a_loop_and_unchanged_in_it_is_propagated():
    src = "let k = 10; let i = 0; while (i < 3) { print(k + i); i = i + 1; }"
    assert "t2 = 10 + i" in main_after(src)
    check_equivalent(src)


def test_call_invalidates_global_constants():
    src = "let g = 1; function bump() { g = g + 10; } print(g); bump(); print(g);"
    assert main_after(src) == ["g = 1", "print 1", "call bump, 0", "print g"]
    assert check_equivalent(src)[1].output == "1\n11\n"


def test_function_does_not_assume_globals_are_constant():
    src = "let g = 5; function f() { return g + 1; } print(f());"
    assert fn_after(src, "f") == ["t1 = g + 1", "return t1"]


def test_global_state_at_function_entry_is_unknown():
    # g is 1 when f starts, and 5 after the first iteration: the read at the top of the
    # loop must NOT be replaced by 5 (a missing entry would wrongly meet to "always 5")
    src = ("let g = 1; function f(n) { let i = 0; while (i < n) { print(g); g = 5; i = i + 1; } } f(2);")
    after = fn_after(src, "f")
    assert "print g" in after
    assert check_equivalent(src)[1].output == "1\n5\n"


def test_locals_survive_calls():
    src = "function id(x) { return x; } function f() { let a = 5; id(1); return a + 1; }"
    assert "return 6" in fn_after(src, "f")
    check_equivalent(src + "print(f());")


def test_parameters_are_not_constants():
    assert fn_after("function f(a) { return a + 1; }", "f") == ["t1 = a + 1", "return t1"]


def test_len_does_not_invalidate_globals():
    src = "let g = 1; let a = [1, 2]; let n = len(a); print(g);"
    assert main_after(src)[-1] == "print 1"


def test_arrays_are_never_constants():
    src = "let a = [1]; let b = a; b[0] = 9; print(a[0]);"
    assert check_equivalent(src)[1].output == "9\n"


def test_shadowed_variables_keep_separate_constants():
    src = "let x = 1; { let x = 2; print(x); } print(x);"
    assert main_after(src) == ["x = 1", "print 2", "print 1"]
    check_equivalent(src)


# ================================================================== algebra
def test_int_identities_for_known_ints():
    src = ("let n = 3; while (n > 0) { n = n - 1; print(n + 0); print(0 + n); print(n - 0); "
           "print(n * 1); print(1 * n); print(n / 1); print(n * 0); print(0 * n); }")
    after = main_after(src)
    for pattern in (" + 0", "0 + ", " - 0", " * 1", "1 * ", " / 1", " * 0", "0 * "):
        assert not any(pattern in l for l in after), (pattern, after)
    check_equivalent(src)


def test_float_identities_are_applied_only_where_exact():
    src = ("let f = 2.5; let i = 0; while (i < 2) { f = f + 0.5; i = i + 1; } "
           "print(f - 0); print(f * 1); print(f + 0); print(f * 0);")
    after = main_after(src)
    assert not has_instruction(after, "-", "0") and not has_instruction(after, "*", "1")
    assert has_instruction(after, "+", "0")         # x + 0 is NOT exact for floats (-0.0)
    assert has_instruction(after, "*", "0")         # nor is x * 0 (-0.0, and sign of the result)
    assert check_equivalent(src)[1].output == "3.5\n3.5\n3.5\n0.0\n"


def test_unknown_types_are_never_simplified():
    src = "function f(a) { return a + 0; }"
    assert has_instruction(fn_after(src, "f"), "+", "0")
    result, expected = check_equivalent(src + 'print(f("x"));')
    assert "cannot be applied to types string and int" in expected.errors[0].message


def test_string_times_zero_error_is_preserved():
    src = 'function f(a) { return a * 0; } print(f("x"));'
    assert has_instruction(fn_after(src, "f"), "*", "0")
    assert check_equivalent(src)[1].errors


def test_call_result_type_is_unknown_so_not_simplified():
    src = "function f() { return 1; } let x = f(); let y = 1; while (y < 3) { y = y + 1; print(x + 0); }"
    assert has_instruction(main_after(src), "+", "0")
    check_equivalent(src)


# ======================================================= branches / dead code
def test_true_condition_keeps_only_the_then_branch():
    assert main_after("if (true) { print(1); } else { print(2); }") == ["print 1"]


def test_false_condition_keeps_only_the_else_branch():
    assert main_after("if (1 > 2) { print(1); } else { print(2); }") == ["print 2"]


def test_condition_known_through_a_variable():
    assert main_after("let debug = false; if (debug) { print(1); } print(2);") == [
        "debug = false", "print 2"]


def test_while_false_disappears():
    assert main_after("while (false) { print(1); } print(2);") == ["print 2"]


def test_break_leaves_clean_code():
    assert main_after("while (true) { break; } print(3);") == ["print 3"]


def test_for_loop_with_constant_false_condition():
    assert main_after("for (let i = 0; 1 > 2; i = i + 1) { print(i); } print(9);") == ["print 9"]


def test_if_else_that_returns_on_both_paths_loses_its_dead_blocks():
    src = "function f(x) { if (x) { return 1; } else { return 2; } }"
    assert fn_after(src, "f") == ["ifFalse x goto L1", "return 1", "L1:", "return 2"]


def test_optimized_examples_have_no_unreachable_blocks():
    for path in EXAMPLES:
        result = opt(open(path).read())
        for fn in result.optimized.all_functions():
            assert all(b.reachable for b in build_cfg(fn).blocks), (path, fn.name)


def test_non_boolean_constant_condition_is_left_for_run_time():
    code = [TACInstruction(T.OP_IF_FALSE, "5", None, "L1", 1), TACInstruction(T.OP_PRINT, "1", None, None, 2),
            TACInstruction(T.OP_LABEL, None, None, "L1")]
    result = optimize(TACProgram(TACFunction("main", [], code)))
    assert lines(result.optimized.main.instructions) == lines(code)
    assert run_tac(result.optimized).errors[0].message.startswith("Condition must be bool")


def test_if_true_instruction_is_folded_too():
    code = [TACInstruction(T.OP_IF_TRUE, "true", None, "L1"), TACInstruction(T.OP_PRINT, "1"),
            TACInstruction(T.OP_LABEL, None, None, "L1"), TACInstruction(T.OP_PRINT, "2")]
    out = optimize(TACProgram(TACFunction("main", [], code))).optimized
    assert lines(out.main.instructions) == ["print 2"]


# ================================================================ dead stores
def test_unused_block_variable_is_removed():
    assert main_after("{ let u = 5; }") == []


def test_global_variables_are_always_kept():
    assert main_after("let u = 5;") == ["u = 5"]


def test_dead_chain_of_locals_is_removed():
    assert fn_after("function f(a) { let x = a; let y = x; return 1; }", "f") == ["return 1"]


def test_failing_computation_is_kept_even_if_unused():
    result, expected = check_equivalent("let a = 1; let b = 0; { let c = a / b; }")
    # `c` is never read, but `1 / 0` can fail, so the division itself must stay
    assert lines(result.optimized.main.instructions) == ["a = 1", "b = 0", "c = 1 / 0"]
    assert expected.errors


def test_unused_call_result_is_dropped_but_the_call_stays():
    src = "function f() { print(7); return 1; } function g() { let u = f(); return 2; } print(g());"
    assert fn_after(src, "g") == ["call f, 0", "return 2"]
    assert check_equivalent(src)[1].output == "7\n2\n"


def test_array_writes_are_never_dead():
    src = "let a = [0, 0]; a[0] = 5; print(a[0]);"
    assert check_equivalent(src)[1].output == "5\n"
    assert any("[" in l and "=" in l for l in main_after(src))


# ============================================================== coalescing
def test_temporary_is_merged_into_its_destination():
    src = "function f(a, b, c) { let r = (a + b) * c; return r; }"
    assert fn_after(src, "f") == ["t1 = a + b", "r = t1 * c", "return r"]


def test_temporary_read_twice_is_not_merged():
    src = "function f(a, b) { let c = a && b; return c; }"
    after = fn_after(src, "f")
    assert after.count("t1 = a") == 1 and "c = t1" in after
    check_equivalent(src + "print(f(true, false)); print(f(false, true)); print(f(true, true));")


def test_merging_into_a_global_is_allowed():
    src = "function f(a) { return a; } let g = f(1) + 2;"
    assert main_after(src) == ["param 1", "t1 = call f, 1", "g = t1 + 2"]


def test_self_referencing_update_is_merged():
    after = fn_after("function f(n) { n = n - 1; return n; }", "f")
    assert after == ["n = n - 1", "return n"]


# ============================================================ jump cleanup
def test_jump_to_next_and_unused_labels_are_removed():
    src = "function f(x) { if (x) { print(1); } }"
    assert fn_after(src, "f") == ["ifFalse x goto L1", "print 1", "L1:", "return nil"]
    code = [TACInstruction(T.OP_GOTO, None, None, "L1"), TACInstruction(T.OP_LABEL, None, None, "L1"),
            TACInstruction(T.OP_LABEL, None, None, "L2"), TACInstruction(T.OP_PRINT, "1")]
    assert lines(optimize(TACProgram(TACFunction("main", [], code))).optimized.main.instructions) == ["print 1"]


def test_goto_over_consecutive_labels():
    code = [TACInstruction(T.OP_GOTO, None, None, "L2"), TACInstruction(T.OP_LABEL, None, None, "L1"),
            TACInstruction(T.OP_LABEL, None, None, "L2"), TACInstruction(T.OP_PRINT, "1")]
    # L1 is unreachable (nothing jumps to it) so everything collapses
    assert lines(optimize(TACProgram(TACFunction("main", [], code))).optimized.main.instructions) == ["print 1"]


def test_conditional_whose_branches_meet_is_kept():
    # `ifFalse t goto L; L:` still checks that t is a bool, so it must stay
    code = [TACInstruction(T.OP_IF_FALSE, "x", None, "L1"), TACInstruction(T.OP_LABEL, None, None, "L1")]
    out = optimize(TACProgram(TACFunction("main", [], code), [], ["x"])).optimized
    assert lines(out.main.instructions) == ["ifFalse x goto L1", "L1:"]


# ================================================================== change log
def test_change_log_for_the_basic_example():
    result = opt("let x = 10 + 20;")
    assert [(c.pass_name, c.before, c.after) for c in result.changes] == [
        ("constant folding", "t1 = 10 + 20", "t1 = 30"),
        ("constant propagation", "x = t1", "x = 30"),
        ("dead store removal", "t1 = 30", None),
    ]
    assert result.stats == {"constant folding": 1, "constant propagation": 1, "dead store removal": 1}
    assert result.instruction_counts == {"before": 2, "after": 1}
    assert all(c.function == "main" and c.line == 1 and c.description for c in result.changes)


def test_change_log_text_and_json():
    result = opt("let x = 10 + 20;")
    text = result.format_changes()
    assert "[constant folding] main, line 1: t1 = 10 + 20  =>  t1 = 30" in text
    assert "t1 = 30  =>  (deleted)" in text
    d = json.loads(json.dumps(result.to_dict()))
    assert d["changes"][0] == {
        "pass": "constant folding", "function": "main", "line": 1, "before": "t1 = 10 + 20",
        "after": "t1 = 30", "description": d["changes"][0]["description"]}
    assert d["original"]["functions"][0]["name"] == "main" and d["optimized"]["globals"] == ["x"]
    assert d["stats"]["constant folding"] == 1 and d["instruction_counts"]["after"] == 1


def test_every_pass_is_reported_by_name():
    src = """
    function f(c) { if (c) { return 1; } else { return 2; } }
    let n = 2;
    while (n > 0) { n = n - 1; print(n * 1); }
    let x = 10 + 20;
    if (false) { print(0); }
    { let u = 1; }
    let r = f(true) + 1;
    """
    stats = opt(src).stats
    assert set(stats) == {
        "constant folding", "constant propagation", "algebraic simplification", "branch folding",
        "unreachable code", "temporary coalescing", "dead store removal", "jump cleanup"}


def test_compile_and_optimize_reports_front_end_errors():
    r = compile_and_optimize("print(y);")
    assert not r.ok and r.result is None and r.errors[0].phase == "Semantic Error"
    d = r.to_dict()
    assert d["ok"] is False and d["optimized"] is None and d["changes"] == []
    r = compile_and_optimize("let x = 1 / 0;")
    assert r.ok and len(r.warnings) == 1
    assert json.loads(json.dumps(r.to_dict()))["ok"] is True


# ================================================================== safety
def test_input_program_is_never_modified():
    prog = compile_to_tac(open(os.path.join(HERE, "..", "examples", "functions.nova")).read()).program
    before = prog.format()
    result = optimize(prog)
    assert prog.format() == before and result.original is prog
    assert result.optimized is not prog and result.optimized.format() != before


def test_globals_list_is_preserved():
    prog = compile_to_tac("let a = 1; { let b = 2; } let c = 3;").program
    assert optimize(prog).optimized.globals == ["a", "c"]


def test_optimizer_handles_empty_programs_and_functions():
    assert main_after("") == []
    assert fn_after("function f() { }", "f") == ["return nil"]


def test_optimizing_never_increases_instruction_count():
    for path in EXAMPLES:
        counts = opt(open(path).read()).instruction_counts
        assert counts["after"] <= counts["before"], path


def test_examples_actually_get_smaller():
    src = open(os.path.join(HERE, "..", "examples", "calculator.nova")).read()
    counts = opt(src).instruction_counts
    assert counts["after"] < counts["before"]


# ================================================================ unit: types
def test_type_join_lattice():
    assert join(None, INT) == INT and join(INT, None) == INT
    assert join(INT, INT) == INT and join(INT, FLOAT) == NUM and join(NUM, INT) == NUM
    assert join(INT, STRING) == ANY and join(BOOL, NIL) == ANY and join(ANY, INT) == ANY


def test_result_types():
    assert result_type("+", INT, INT) == INT and result_type("+", INT, FLOAT) == FLOAT
    assert result_type("/", INT, INT) == INT and result_type("*", NUM, INT) == NUM
    assert result_type("+", STRING, STRING) == STRING and result_type("+", STRING, INT) == ANY
    assert result_type("<", INT, INT) == BOOL and result_type("==", STRING, INT) == BOOL
    assert result_type("+", ANY, INT) == ANY and result_type("+", None, INT) is None


def test_constant_types():
    assert [constant_type(c) for c in ("1", "2.5", '"s"', "true", "nil")] == [INT, FLOAT, STRING, BOOL, NIL]


def test_type_inference_over_a_program():
    src = """
    let n = 10; let f = 1.5; f = 2; let s = "a"; let a = [1];
    function g(p) { let local = p + 1; return local; }
    while (n > 0) { n = n - 1; }
    let k = g(1);
    """
    ti = TypeInfo(compile_to_tac(src).program)
    assert [ti.type_of("main", v) for v in ("n", "f", "s", "a", "k")] == [INT, NUM, STRING, ARRAY, ANY]
    assert ti.type_of("g", "p") == ANY and ti.type_of("g", "local") == ANY
    assert ti.type_of("main", "7") == INT and ti.type_of("main", None) == ANY


def test_global_types_are_joined_across_functions():
    src = "let g = 1.5; function f() { g = 2; } f();"       # int widens to float: legal
    assert TypeInfo(compile_to_tac(src).program).type_of("main", "g") == NUM


# ============================================================ unit: dataflow
def test_meet():
    assert meet([{"x": "1"}, {"x": "1"}]) == {"x": "1"}
    assert meet([{"x": "1"}, {"x": "2"}]) == {"x": NAC}
    assert meet([{"x": "1"}, {"x": NAC}]) == {"x": NAC}
    assert meet([{"x": "1"}, {}]) == {"x": "1"}          # a missing entry means "no information yet"
    assert meet([]) == {}


def test_transfer_function():
    state = {}
    transfer(state, TACInstruction(T.OP_COPY, "5", None, "x"), {"g"})
    transfer(state, TACInstruction("+", "x", "1", "y"), {"g"})
    transfer(state, TACInstruction("+", "x", "unknown", "z"), {"g"})
    transfer(state, TACInstruction(T.OP_COPY, "7", None, "g"), {"g"})
    assert state == {"x": "5", "y": "6", "z": NAC, "g": "7"}
    transfer(state, TACInstruction(T.OP_CALL, "f", "0", None), {"g"})
    assert state["g"] == NAC and state["x"] == "5"        # the call clobbers globals only
    transfer(state, TACInstruction(T.OP_CALL, "len", "1", "t"), {"x"})
    assert state["x"] == "5" and state["t"] == NAC        # len cannot change globals


def test_constant_analysis_on_a_diamond_and_a_loop():
    prog = compile_to_tac("function f(c) { let x = 1; if (c) { x = 2; } return x; } let i = 0; while (i < 2) { i = i + 1; }").program
    cfg = build_cfg(prog.function("f"))
    states = analyze_constants(cfg, False, ["c"], set())
    join_block = cfg.blocks[-1].name
    assert states[cfg.entry]["c"] == NAC
    assert states[join_block]["x"] == NAC                  # 1 on one path, 2 on the other
    loop = build_cfg(prog.main)
    loop_states = analyze_constants(loop, True, [], {"i"})
    assert loop_states["B2"]["i"] == NAC                   # 0 on entry, 1 after an iteration


def test_liveness():
    prog = compile_to_tac("function f(a) { let x = a + 1; let y = 5; if (a) { return x; } return 0; }").program
    cfg = build_cfg(prog.function("f"))
    live = live_out_sets(cfg)
    assert "x" in live[cfg.entry] and "y" not in live[cfg.entry]


# ================================================= differential: fixed programs
@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_optimized_program_behaves_identically(name):
    check_equivalent(PROGRAMS[name])


@pytest.mark.parametrize("path", EXAMPLES, ids=[os.path.basename(p) for p in EXAMPLES])
def test_optimized_example_behaves_identically(path):
    assert check_equivalent(open(path).read())[0]


EXTRA = {
    "globals_everywhere": """
        let g = 1; let h = 2;
        function bump() { g = g + h; return g; }
        function readh() { return h * 10; }
        print(g + bump()); print(bump() + g); print(readh() + h); h = 5; print(readh());""",
    "shadow_and_loops": """
        let x = 1;
        for (let i = 0; i < 3; i = i + 1) { let x = i * 2; if (x == 2) { continue; } print(x); }
        print(x);""",
    "constant_loop_bounds": "let n = 4; let s = 0; for (let i = 0; i < n; i = i + 1) { s = s + i * 2; } print(s);",
    "dead_after_return": "function f(n) { if (n > 0) { return 1; } return 2; print(99); } print(f(1)); print(f(0));",
    "nested_functions_and_params": """
        function sq(x) { return x * x; }
        function cube(x) { return x * sq(x); }
        print(cube(3) + sq(2)); print(cube(sq(2)));""",
    "string_building": 'let s = "a"; for (let i = 0; i < 3; i = i + 1) { s = s + "b"; } print(s); print(len(s));',
    "boolean_logic": """
        let a = true; let b = false;
        print(a && b); print(a || b); print(!a || b); print(a && !b);
        function t() { print("t"); return true; } print(b && t()); print(a || t());""",
    "float_mix": "let f = 0.1; let i = 0; while (i < 3) { f = f + 0.1; i = i + 1; } print(f); print(f * 1); print(f - 0);",
    "int_float_assignment": "let x = 1.5; x = 2; print(x + 0); print(x * 1); print(x * 0);",
    "array_in_loops": "let a = [1, 2, 3]; for (let i = 0; i < len(a); i = i + 1) { a[i] = a[i] * 2 + 0; } print(a);",
    "division_by_zero_after_output": "print(1); let z = 0; print(10 / z); print(2);",
    "type_error_after_folding": 'function f(a) { return a + 1; } print(2 + 3); print(f("s"));',
    "unused_everything": "{ let a = 1; let b = a + 2; let c = b * 3; } function f() { let z = 4; } f(); print(1);",
}


@pytest.mark.parametrize("name", sorted(EXTRA))
def test_optimizer_specific_programs(name):
    check_equivalent(EXTRA[name])


def test_random_expressions_survive_optimization():
    rng = random.Random(777)
    header = "let a = 7; let b = -3; let c = 0; let flag = true;\n"
    for _ in range(250):
        expr = _int_expr(rng, 4) if rng.random() < 0.5 else _bool_expr(rng, 4)
        check_equivalent(header + f"print({expr});")


# ======================================================= random whole programs
class ProgramGenerator:
    """Writes random, semantically valid NovaLang programs with loops, branches,
    shadowing, globals modified by functions, calls, arrays and the occasional
    run-time error -- the kind of code where a wrong optimization would show."""

    def __init__(self, rng):
        self.rng = rng
        self.counter = 0
        self.scopes = []              # list of {name: "var" | "ro" (read-only counter) | "array"}
        self.funcs = [("bump", 0), ("side", 0), ("twice", 1)]
        self.loop_depth = 0

    # -- names --------------------------------------------------------
    def fresh(self, prefix="v"):
        self.counter += 1
        return f"{prefix}{self.counter}"

    def _visible_kinds(self):
        seen = {}
        for scope in self.scopes:
            seen.update(scope)
        return seen

    def visible(self, assignable_only=False):
        wanted = ("var",) if assignable_only else ("var", "ro")
        return [n for n, kind in self._visible_kinds().items() if kind in wanted]

    def visible_arrays(self):
        return [n for n, kind in self._visible_kinds().items() if kind == "array"]

    # -- expressions ----------------------------------------------------
    def expr(self, depth):
        r = self.rng.random()
        if depth <= 0 or r < 0.3:
            if self.rng.random() < 0.5 or not self.visible():
                n = self.rng.randint(0, 9)
                return str(n) if self.rng.random() < 0.85 else f"-{n}"
            return self.rng.choice(self.visible())
        if r < 0.42:
            name, arity = self.rng.choice(self.funcs)
            return f"{name}({', '.join(self.expr(depth - 1) for _ in range(arity))})"
        if r < 0.5:
            return f"-({self.expr(depth - 1)})"
        if r < 0.56 and self.visible_arrays():
            return f"{self.rng.choice(self.visible_arrays())}[{self.rng.choice([0, 0, 1, 1, 1, 2])}]"
        op = self.rng.choices(["+", "-", "*", "/", "%"], [30, 30, 25, 5, 5])[0]
        return f"({self.expr(depth - 1)} {op} {self.expr(depth - 1)})"

    def cond(self, depth):
        r = self.rng.random()
        if depth <= 0 or r < 0.5:
            op = self.rng.choice(["<", ">", "<=", ">=", "==", "!="])
            return f"({self.expr(1)} {op} {self.expr(1)})"
        if r < 0.6:
            return self.rng.choice(["true", "false"])
        if r < 0.7:
            return f"!({self.cond(depth - 1)})"
        return f"({self.cond(depth - 1)} {self.rng.choice(['&&', '||'])} {self.cond(depth - 1)})"

    # -- statements -------------------------------------------------------
    def block(self, depth, count, extra=None):
        self.scopes.append(dict(extra or {}))
        out = []
        for _ in range(count):
            out.extend(self.statement(depth))
        self.scopes.pop()
        return out

    def statement(self, depth):
        rng = self.rng
        kinds = ["let", "let", "assign", "assign", "print", "print", "call"]
        if depth > 0:
            kinds += ["if", "if", "for", "while"]
        if self.loop_depth:
            kinds += ["jump"]
        if rng.random() < 0.15:
            kinds = ["array"] + kinds
        kind = rng.choice(kinds)

        if kind == "let":
            outer = [n for n in self.visible() if n not in self.scopes[-1]]
            reuse = depth > 0 and outer and rng.random() < 0.2          # shadow an outer variable
            name = rng.choice(outer) if reuse else self.fresh()
            init = self.expr(2)                                         # evaluated before the name exists
            self.scopes[-1][name] = "var"
            return [f"let {name} = {init};"]
        if kind == "assign":
            targets = self.visible(assignable_only=True)
            if not targets:
                return ["print(1);"]
            if rng.random() < 0.35:                                     # lots of traffic on the globals
                targets = ["g", "h"]
            return [f"{rng.choice(targets)} = {self.expr(2)};"]
        if kind == "print":
            return [f"print({self.expr(3)});"]
        if kind == "call":
            name = rng.choice(["bump", "side"])
            return [f"{name}();"]
        if kind == "array":
            name = self.fresh("arr")
            first = f"let {name} = [{self.expr(1)}, {self.expr(1)}];"
            self.scopes[-1][name] = "array"
            return [first, f"{name}[{rng.choice([0, 1])}] = {self.expr(2)};", f"print({name}[{rng.choice([0, 1])}]);"]
        if kind == "jump":
            word = rng.choice(["break", "continue"])
            return [f"if ({self.cond(1)}) {{ {word}; }}"]
        if kind == "if":
            out = [f"if ({self.cond(2)}) {{"] + self.block(depth - 1, rng.randint(1, 3)) + ["}"]
            if rng.random() < 0.5:
                out[-1] = "} else {"
                out += self.block(depth - 1, rng.randint(1, 3)) + ["}"]
            return out
        if kind == "for":
            k, bound = self.fresh("k"), rng.randint(0, 3)
            self.loop_depth += 1
            body = self.block(depth - 1, rng.randint(1, 3), {k: "ro"})
            self.loop_depth -= 1
            return [f"for (let {k} = 0; {k} < {bound}; {k} = {k} + 1) {{"] + body + ["}"]
        # while with a counter that is incremented first, so `continue` can never loop forever
        c, bound = self.fresh("c"), rng.randint(0, 3)
        self.scopes[-1][c] = "ro"
        self.loop_depth += 1
        body = self.block(depth - 1, rng.randint(1, 3))
        self.loop_depth -= 1
        return [f"let {c} = 0;", f"while ({c} < {bound}) {{", f"{c} = {c} + 1;"] + body + ["}"]

    def function(self, name, arity):
        params = [self.fresh("p") for _ in range(arity)]
        self.scopes = [{"g": "var", "h": "var"}]
        saved = self.funcs
        self.funcs = [f for f in saved if f[0] in ("bump", "side", "twice") and f[0] != name]
        body = self.block(2, self.rng.randint(2, 4), {p: "var" for p in params})
        self.scopes = [{"g": "var", "h": "var"}, {p: "var" for p in params}]
        if self.rng.random() < 0.4:
            body.append(f"if ({self.cond(1)}) {{ return {self.expr(2)}; }}")
        body.append(f"return {self.expr(2)};")
        self.funcs = saved
        self.scopes = []
        return f"function {name}({', '.join(params)}) {{\n" + "\n".join(body) + "\n}"

    def program(self):
        header = [
            "let g = 3;", "let h = -2;",
            "function bump() { g = g + 1; return g; }",
            "function side() { print(\"s\"); h = h * 2; return h; }",
            "function twice(x) { return x * 2; }",
        ]
        extra = []
        for i in range(self.rng.randint(0, 3)):
            name = f"fn{i}"
            extra.append(self.function(name, self.rng.randint(0, 2)))
            self.funcs.append((name, int(extra[-1].split("(")[1].split(")")[0].count("p"))))
        self.scopes = [{"g": "var", "h": "var"}]
        body = []
        for _ in range(self.rng.randint(5, 10)):
            body.extend(self.statement(2))
        return "\n".join(header + extra + body)


def test_random_programs_survive_optimization():
    rng = random.Random(20260713)
    changed = errors = 0
    total = 400
    for _ in range(total):
        src = ProgramGenerator(rng).program()
        try:
            result, expected = check_equivalent(src)
        except AssertionError:
            print("FAILING PROGRAM:\n" + src)
            raise
        changed += bool(result.changes)
        errors += bool(expected.errors)
    # the generator must really exercise the optimizer and the error paths
    assert changed > total * 0.9
    assert 0.03 * total < errors < 0.6 * total
