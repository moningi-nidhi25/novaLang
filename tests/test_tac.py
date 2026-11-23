import glob
import json
import os
import random

import pytest

from compiler.interpreter.interpreter import interpret
from compiler.ir import tac as T
from compiler.ir.generator import compile_to_tac, generate_tac
from compiler.ir.tac import (
    TACFunction, TACInstruction, TACProgram, constant_value, format_constant,
    is_constant, is_variable, parse_operand,
)
from compiler.ir.tac_runner import run_tac
from compiler.semantic.analyzer import analyze_source

EXAMPLES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "examples", "*.nova")))


# ------------------------------------------------------------------ helpers
def program(src):
    r = compile_to_tac(src)
    assert r.ok, [e.message for e in r.errors]
    return r.program


def lines(instructions):
    return [i.text() for i in instructions]


def main_lines(src):
    return lines(program(src).main.instructions)


def fn_lines(src, name):
    return lines(program(src).function(name).instructions)


def assert_well_formed(prog):
    """Every label defined once, every jump has a target in its own function,
    every label name unique program-wide, every function ends in a return."""
    all_labels = []
    for fn in prog.all_functions():
        labels = [i.result for i in fn.instructions if i.is_label]
        assert len(labels) == len(set(labels)), f"duplicate label in {fn.name}"
        all_labels += labels
        for ins in fn.instructions:
            if ins.is_jump:
                assert ins.jump_target in labels, f"{ins.text()} has no target in {fn.name}"
        if not fn.is_main:
            assert fn.instructions[-1].op == T.OP_RETURN
    assert len(all_labels) == len(set(all_labels)), "labels must be unique across the program"


def _normalize(message):
    """A jump instruction does not know which statement it came from, so TAC says
    "Condition must be bool" where the interpreter says "Condition of 'if' ...".
    Everything else (type, value, line) must match exactly."""
    import re
    return re.sub(r"Condition of '\w+' must be bool", "Condition must be bool", message)


def both(src):
    """Run *src* through the AST interpreter and through TAC; demand identical behaviour."""
    sem = analyze_source(src)
    assert sem.ok, [e.message for e in sem.errors]
    expected = interpret(sem.program)
    prog = generate_tac(sem.program)
    assert_well_formed(prog)
    got = run_tac(prog)
    assert got.output == expected.output
    assert [_normalize(e.message) for e in got.errors] == [_normalize(e.message) for e in expected.errors]
    return expected


# ====================================================== operands / instructions
@pytest.mark.parametrize("value", [
    0, 7, -5, 123456789012345678901234567890, 2.5, -0.5, 0.0, 1e22, 1.5e-07,
    True, False, None, "hi", "", 'a"b\\c\nd\te', "é", "\0", "// not a comment", "x = 1",
])
def test_constant_roundtrip(value):
    text = format_constant(value)
    assert is_constant(text)
    back = constant_value(text)
    assert back == value and type(back) is type(value)


def test_variables_are_not_constants():
    for name in ("x", "t1", "x_1", "_tmp", "L1", "truthy", "nilly", "falsey"):
        assert is_variable(name) and not is_constant(name)
    assert not is_variable(None) and not is_constant(None)
    assert not is_variable("10") and not is_variable('"s"') and not is_variable("nil")


def test_constant_value_rejects_variable():
    with pytest.raises(ValueError):
        constant_value("x")


def test_format_constant_rejects_other_types():
    with pytest.raises(TypeError):
        format_constant([1])


def test_instruction_text_forms():
    cases = [
        (TACInstruction("+", "a", "b", "t1"), "t1 = a + b"),
        (TACInstruction("<=", "a", "10", "t1"), "t1 = a <= 10"),
        (TACInstruction(T.OP_NEG, "a", None, "t1"), "t1 = -a"),
        (TACInstruction(T.OP_NOT, "a", None, "t1"), "t1 = !a"),
        (TACInstruction(T.OP_COPY, "t1", None, "x"), "x = t1"),
        (TACInstruction(T.OP_LABEL, result="L1"), "L1:"),
        (TACInstruction(T.OP_GOTO, result="L1"), "goto L1"),
        (TACInstruction(T.OP_IF_FALSE, "t1", None, "L2"), "ifFalse t1 goto L2"),
        (TACInstruction(T.OP_IF_TRUE, "t1", None, "L2"), "if t1 goto L2"),
        (TACInstruction(T.OP_PARAM, "x"), "param x"),
        (TACInstruction(T.OP_CALL, "f", "2", "t3"), "t3 = call f, 2"),
        (TACInstruction(T.OP_CALL, "f", "0", None), "call f, 0"),
        (TACInstruction(T.OP_RETURN, "t1"), "return t1"),
        (TACInstruction(T.OP_RETURN), "return"),
        (TACInstruction(T.OP_PRINT, "x"), "print x"),
        (TACInstruction(T.OP_ARRAY_NEW, "3", None, "t1"), "t1 = newarray 3"),
        (TACInstruction(T.OP_INDEX, "a", "i", "t2"), "t2 = a[i]"),
        (TACInstruction(T.OP_INDEX_SET, "a", "i", "t2"), "a[i] = t2"),
    ]
    for ins, expected in cases:
        assert ins.text() == expected == str(ins)


def test_unknown_op_text_raises():
    with pytest.raises(ValueError):
        TACInstruction("bogus").text()


def test_instruction_json_matches_brief_format():
    d = TACInstruction("+", "a", "b", "t1", line=3, column=9).to_dict(index=4)
    assert d["op"] == "+" and d["arg1"] == "a" and d["arg2"] == "b" and d["result"] == "t1"
    assert d["text"] == "t1 = a + b" and d["line"] == 3 and d["index"] == 4


def test_uses_and_defs():
    assert TACInstruction("+", "a", "1", "t1").uses() == ["a"]
    assert TACInstruction("+", "a", "1", "t1").defs() == ["t1"]
    assert TACInstruction(T.OP_COPY, "5", None, "x").uses() == []
    assert TACInstruction(T.OP_INDEX_SET, "a", "i", "v").uses() == ["a", "i", "v"]
    assert TACInstruction(T.OP_INDEX_SET, "a", "i", "v").defs() == []
    assert TACInstruction(T.OP_INDEX, "a", "i", "t").defs() == ["t"]
    assert TACInstruction(T.OP_CALL, "f", "2", "t3").defs() == ["t3"]
    assert TACInstruction(T.OP_CALL, "f", "2", "t3").uses() == []       # f is a name, not a variable
    assert TACInstruction(T.OP_CALL, "f", "2", None).defs() == []
    assert TACInstruction(T.OP_PARAM, "x").uses() == ["x"]
    assert TACInstruction(T.OP_IF_FALSE, "t1", None, "L1").uses() == ["t1"]
    assert TACInstruction(T.OP_RETURN, "nil").uses() == []
    assert TACInstruction(T.OP_LABEL, result="L1").uses() == []
    assert TACInstruction(T.OP_ARRAY_NEW, "3", None, "t").uses() == []
    assert TACInstruction(T.OP_ARRAY_NEW, "3", None, "t").defs() == ["t"]


def test_classification_helpers():
    goto = TACInstruction(T.OP_GOTO, result="L1")
    cond = TACInstruction(T.OP_IF_FALSE, "t1", None, "L2")
    ret = TACInstruction(T.OP_RETURN)
    assert goto.is_jump and goto.is_terminator and goto.jump_target == "L1"
    assert cond.is_conditional_jump and not cond.is_terminator and cond.jump_target == "L2"
    assert ret.is_terminator and not ret.is_jump and ret.jump_target is None
    assert TACInstruction(T.OP_LABEL, result="L1").is_label


def test_purity_is_conservative():
    assert TACInstruction(T.OP_COPY, "a", None, "x").is_pure
    assert TACInstruction("==", "a", "b", "t").is_pure and TACInstruction("!=", "a", "b", "t").is_pure
    assert TACInstruction(T.OP_ARRAY_NEW, "2", None, "t").is_pure
    # these can raise run-time errors, so deleting them could hide a bug
    for op in ("+", "-", "*", "/", "%", "<", ">", "<=", ">="):
        assert not TACInstruction(op, "a", "b", "t").is_pure
    for op in (T.OP_NEG, T.OP_NOT, T.OP_INDEX, T.OP_CALL, T.OP_PRINT, T.OP_INDEX_SET):
        assert not TACInstruction(op, "a", "b", "t").is_pure


# ======================================================== expressions -> TAC
def test_brief_example_constant_expression():
    assert main_lines("let x = 10 + 20;") == ["t1 = 10 + 20", "x = t1"]


def test_brief_example_parenthesised_expression():
    assert main_lines("let a = 1; let b = 2; let c = 3; let result = (a + b) * c;") == [
        "a = 1", "b = 2", "c = 3", "t1 = a + b", "t2 = t1 * c", "result = t2"]


def test_precedence_shapes_the_code():
    assert main_lines("let x = 2 + 3 * 4;") == ["t1 = 3 * 4", "t2 = 2 + t1", "x = t2"]
    assert main_lines("let x = (2 + 3) * 4;") == ["t1 = 2 + 3", "t2 = t1 * 4", "x = t2"]


def test_left_associativity_shapes_the_code():
    assert main_lines("let x = 10 - 3 - 2;") == ["t1 = 10 - 3", "t2 = t1 - 2", "x = t2"]


def test_literals_are_used_directly():
    assert main_lines('let a = 1; let b = 2.5; let c = "hi\\n"; let d = true; let e = nil;') == [
        "a = 1", "b = 2.5", 'c = "hi\\n"', "d = true", "e = nil"]


def test_unary_operators():
    assert main_lines("let x = 5; let y = -x; let z = !true;") == [
        "x = 5", "t1 = -x", "y = t1", "t2 = !true", "z = t2"]


def test_all_binary_operators_use_their_own_op():
    for op in ("+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">="):
        assert main_lines(f"let a = 6; let b = 3; let r = a {op} b;")[2] == f"t1 = a {op} b"


def test_assignment_statement():
    assert main_lines("let x = 1; x = x + 1;") == ["x = 1", "t1 = x + 1", "x = t1"]


def test_print_statement():
    assert main_lines("let x = 2; print(x * 3);") == ["x = 2", "t1 = x * 3", "print t1"]


def test_expression_statement_is_evaluated_and_discarded():
    assert main_lines("1 / 0;") == ["t1 = 1 / 0"]      # still raises at run time


# ----------------------------------------------------------- short-circuit
def test_and_short_circuits_with_jump():
    assert main_lines("let a = true; let b = false; let c = a && b;") == [
        "a = true", "b = false", "t1 = a", "ifFalse t1 goto L1", "t1 = b", "L1:", "c = t1"]


def test_or_short_circuits_with_jump():
    assert main_lines("let a = true; let b = false; let c = a || b;") == [
        "a = true", "b = false", "t1 = a", "if t1 goto L1", "t1 = b", "L1:", "c = t1"]


def test_short_circuit_skips_side_effects():
    src = """
    function t() { print("t"); return true; }
    function f() { print("f"); return false; }
    print(f() && t()); print(t() || f()); print(t() && f()); print(f() || t());
    """
    assert both(src).output == "f\nfalse\nt\ntrue\nt\nf\nfalse\nf\nt\ntrue\n"


# --------------------------------------------------------------- control flow
def test_if_without_else():
    assert main_lines("let x = 1; if (x < 2) { print(1); }") == [
        "x = 1", "t1 = x < 2", "ifFalse t1 goto L1", "print 1", "L1:"]


def test_if_else():
    assert main_lines("let x = 1; if (x < 2) { print(1); } else { print(2); }") == [
        "x = 1", "t1 = x < 2", "ifFalse t1 goto L1", "print 1", "goto L2", "L1:", "print 2", "L2:"]


def test_else_if_chain():
    out = main_lines("let x = 1; if (x == 1) { print(1); } else if (x == 2) { print(2); } else { print(3); }")
    assert out == [
        "x = 1", "t1 = x == 1", "ifFalse t1 goto L1", "print 1", "goto L2",
        "L1:", "t2 = x == 2", "ifFalse t2 goto L3", "print 2", "goto L4",
        "L3:", "print 3", "L4:", "L2:"]


def test_while_loop():
    assert main_lines("let i = 0; while (i < 3) { i = i + 1; }") == [
        "i = 0", "L1:", "t1 = i < 3", "ifFalse t1 goto L2", "t2 = i + 1", "i = t2", "goto L1", "L2:"]


def test_for_loop():
    assert main_lines("for (let i = 0; i < 3; i = i + 1) { print(i); }") == [
        "i = 0", "L1:", "t1 = i < 3", "ifFalse t1 goto L2", "print i",
        "t2 = i + 1", "i = t2", "goto L1", "L2:"]


def test_break_jumps_to_loop_end():
    assert main_lines("while (true) { break; }") == [
        "L1:", "ifFalse true goto L2", "goto L2", "goto L1", "L2:"]


def test_continue_in_while_jumps_to_condition():
    out = main_lines("let i = 0; while (i < 3) { i = i + 1; continue; }")
    assert out.count("goto L1") == 2 and "goto L2" not in out


def test_continue_in_for_jumps_to_update_step():
    out = main_lines("for (let i = 0; i < 3; i = i + 1) { if (i == 1) { continue; } print(i); }")
    assert out == [
        "i = 0", "L1:", "t1 = i < 3", "ifFalse t1 goto L2", "t2 = i == 1", "ifFalse t2 goto L3",
        "goto L4", "L3:", "print i", "L4:", "t3 = i + 1", "i = t3", "goto L1", "L2:"]


def test_for_without_continue_has_no_update_label():
    out = main_lines("for (let i = 0; i < 3; i = i + 1) { print(i); }")
    assert sum(1 for x in out if x.endswith(":")) == 2


def test_break_in_inner_loop_targets_inner_end():
    src = "while (true) { while (true) { break; } break; }"
    out = main_lines(src)
    # inner break -> L4 (inner end), outer break -> L2 (outer end)
    assert "goto L4" in out and "goto L2" in out


# ------------------------------------------------------------------ functions
def test_function_call_with_result_and_as_statement():
    src = "function f(a, b) { return a + b; } f(1, 2); let r = f(3, 4);"
    assert main_lines(src) == [
        "param 1", "param 2", "call f, 2", "param 3", "param 4", "t1 = call f, 2", "r = t1"]
    assert fn_lines(src, "f") == ["t1 = a + b", "return t1"]


def test_nested_calls_do_not_interleave_params():
    src = "function f(a, b) { return a; } function g(x) { return x; } print(f(g(1), 2));"
    assert main_lines(src) == [
        "param 1", "t1 = call g, 1", "param t1", "param 2", "t2 = call f, 2", "print t2"]


def test_function_header_and_params():
    prog = program("function add(a, b) { return a + b; }")
    assert prog.function("add").params == ["a", "b"]
    assert prog.function("add").header() == "function add(a, b):"
    assert prog.main.header() == "main:"


def test_falling_off_the_end_returns_nil():
    assert fn_lines("function g() { print(1); }", "g") == ["print 1", "return nil"]
    assert fn_lines("function g() { return; }", "g") == ["return nil"]


def test_no_extra_return_when_already_returning():
    assert fn_lines("function g() { return 1; }", "g") == ["return 1"]


def test_factorial_demo_tac():
    src = open(os.path.join(os.path.dirname(__file__), "..", "examples", "demo_factorial.nova")).read()
    prog = program(src)
    assert lines(prog.main.instructions) == [
        "param 5", "t1 = call factorial, 1", "result = t1", "print result"]
    assert lines(prog.function("factorial").instructions) == [
        "t1 = n <= 1", "ifFalse t1 goto L1", "return 1", "L1:",
        "t2 = n - 1", "param t2", "t3 = call factorial, 1", "t4 = n * t3", "return t4"]


def test_program_records_its_globals():
    prog = program("let a = 1; { let b = 2; } let c = 3; function f() { let d = 4; }")
    assert prog.globals == ["a", "c"]          # not block-scoped b, not function-local d
    assert prog.to_dict()["globals"] == ["a", "c"]


def test_function_temporaries_do_not_clobber_main_temporaries():
    # regression: main's t1 and bump's t1 are different variables
    src = "let g = 1; function bump() { g = g + 10; return 0; } let r = g + bump(); print(r); print(g);"
    assert both(src).output == "1\n11\n"


def test_temporaries_restart_in_each_function():
    prog = program("function f(a) { return a + 1; } let x = f(1) + 2;")
    assert "t1" in lines(prog.function("f").instructions)[0]
    assert lines(prog.main.instructions)[1].startswith("t1 =")


def test_len_is_an_ordinary_call():
    assert main_lines("let a = [1]; let n = len(a);") == [
        "t1 = newarray 1", "t1[0] = 1", "a = t1", "param a", "t2 = call len, 1", "n = t2"]


# --------------------------------------------------------------------- arrays
def test_array_literal():
    assert main_lines("let a = [1, 2];") == ["t1 = newarray 2", "t1[0] = 1", "t1[1] = 2", "a = t1"]


def test_empty_array():
    assert main_lines("let a = [];") == ["t1 = newarray 0", "a = t1"]


def test_array_elements_are_evaluated_before_the_array_is_filled():
    assert main_lines("let x = 1; let a = [x + 1, 5];") == [
        "x = 1", "t1 = x + 1", "t2 = newarray 2", "t2[0] = t1", "t2[1] = 5", "a = t2"]


def test_index_read_and_write():
    assert main_lines("let a = [0, 0]; let i = 1; a[i] = 7; print(a[i]);")[-3:] == [
        "a[i] = 7", "t2 = a[i]", "print t2"]


def test_index_assignment_value_is_computed_first():
    out = main_lines("let a = [1, 2]; a[0] = a[1] + 1;")
    assert out[-3:] == ["t2 = a[1]", "t3 = t2 + 1", "a[0] = t3"]


def test_nested_index_assignment():
    out = main_lines("let m = [[1], [2]]; m[1][0] = 9;")
    assert out[-2:] == ["t4 = m[1]", "t4[0] = 9"]     # t1..t3 built the literal


# ---------------------------------------------------------------- naming rules
def test_shadowed_variable_gets_a_fresh_name():
    assert main_lines("let x = 1; { let x = 2; print(x); } print(x);") == [
        "x = 1", "x_1 = 2", "print x_1", "print x"]


def test_initializer_still_refers_to_outer_variable():
    assert main_lines("let x = 1; { let x = x + 1; print(x); } print(x);") == [
        "x = 1", "t1 = x + 1", "x_1 = t1", "print x_1", "print x"]


def test_sibling_blocks_reusing_a_name():
    assert main_lines("{ let y = 1; print(y); } { let y = 2; print(y); }") == [
        "y = 1", "print y", "y_1 = 2", "print y_1"]


def test_block_variable_clashing_with_later_global_is_renamed():
    out = main_lines("{ let x = 1; print(x); } let x = 2; print(x);")
    assert out == ["x_1 = 1", "print x_1", "x = 2", "print x"]


def test_user_variable_named_like_a_temporary():
    assert main_lines("let t1 = 1; let t2 = t1 + 2;") == ["t1 = 1", "t3 = t1 + 2", "t2 = t3"]


def test_renamed_variable_avoids_existing_names():
    out = main_lines("let x = 1; let x_1 = 5; { let x = 2; print(x); print(x_1); }")
    assert "x_2 = 2" in out and "print x_2" in out and "print x_1" in out


def test_function_parameter_clashing_with_global_is_renamed():
    src = "let n = 5; function f(n) { return n + 1; } print(f(n));"
    prog = program(src)
    assert prog.function("f").params == ["n_1"]
    assert lines(prog.function("f").instructions) == ["t1 = n_1 + 1", "return t1"]
    assert lines(prog.main.instructions) == ["n = 5", "param n", "t1 = call f, 1", "print t1"]
    assert both(src).output == "6\n"


def test_function_local_clashing_with_global_does_not_touch_the_global():
    src = "let v = 1; function f() { let v = 99; return v; } print(f()); print(v);"
    assert both(src).output == "99\n1\n"


def test_function_reads_a_global_by_its_own_name():
    assert fn_lines("let g = 1; function f() { return g; }", "f") == ["return g"]


def test_function_scopes_rename_inner_duplicates():
    src = "function f(a) { if (a) { let b = 1; print(b); } { let b = 3; print(b); } }"
    assert fn_lines(src, "f") == ["ifFalse a goto L1", "b = 1", "print b", "L1:", "b_1 = 3", "print b_1", "return nil"]


def test_labels_are_unique_across_functions():
    prog = program("function f(a) { if (a) { return 1; } return 2; } "
                   "function g(a) { while (a) { a = false; } } let x = f(true);")
    assert_well_formed(prog)


# ------------------------------------------------------------ evaluation order
def test_global_operand_is_protected_from_a_later_call():
    src = "let g = 1; function bump() { g = g + 10; return 0; } print(g + bump());"
    prog = program(src)
    assert lines(prog.main.instructions)[1:5] == [
        "t1 = g", "t2 = call bump, 0", "t3 = t1 + t2", "print t3"]
    assert both(src).output == "1\n"


def test_local_operand_needs_no_protection():
    src = "function h() { return 1; } function f(a) { return a + h(); }"
    assert fn_lines(src, "f") == ["t1 = call h, 0", "t2 = a + t1", "return t2"]


def test_global_array_element_and_argument_order():
    src = """
    let g = 1;
    function bump() { g = g + 1; return g; }
    function pair(a, b) { return a * 10 + b; }
    print(pair(g, bump()));
    print([g, bump()]);
    """
    assert both(src).output == "12\n[2, 3]\n"


# ------------------------------------------------------------ source positions
def test_instructions_carry_source_lines():
    prog = program("let a = 1;\nlet b = 2;\nprint(a + b);\n")
    assert [i.line for i in prog.main.instructions] == [1, 2, 3, 3]
    assert prog.main.instructions[2].column == 9      # the '+' operator


# ------------------------------------------------------------------- program
def test_program_format_and_json():
    prog = program("function f(a) { return a; } print(f(1));")
    text = prog.format()
    assert text.startswith("main:\n    param 1") and "function f(a):\n    return a" in text
    d = json.loads(json.dumps(prog.to_dict()))
    assert [f["name"] for f in d["functions"]] == ["main", "f"]
    assert d["functions"][0]["kind"] == "main" and d["functions"][1]["kind"] == "function"
    assert d["functions"][1]["params"] == ["a"]
    assert d["functions"][0]["instructions"][0]["index"] == 0
    assert d["listing"] == text


def test_empty_program_has_empty_main():
    prog = program("")
    assert prog.main.instructions == [] and prog.format() == "main:"


def test_compile_to_tac_reports_front_end_errors():
    r = compile_to_tac("print(y);")
    assert not r.ok and r.program is None and r.errors[0].phase == "Semantic Error"
    r = compile_to_tac("let x = ;")
    assert r.errors[0].phase == "Syntax Error"
    r = compile_to_tac("let x = $;")
    assert r.errors[0].phase == "Lexical Error"


def test_compile_to_tac_passes_warnings_through():
    r = compile_to_tac("let x = 1 / 0;")
    assert r.ok and len(r.warnings) == 1
    d = json.loads(json.dumps(r.to_dict()))
    assert d["ok"] and d["tac"]["functions"][0]["name"] == "main" and len(d["warnings"]) == 1


def test_result_dict_for_errors_has_no_tac():
    assert compile_to_tac("print(y);").to_dict()["tac"] is None


# ================================================= TAC runner vs the interpreter
PROGRAMS = {
    "arithmetic": "print(2 + 3 * 4); print((2 + 3) * 4); print(7 / 2); print(-7 / 2); print(7 % -3); print(7 / 2.0); print(1 + 2.5);",
    "strings": 'let a = "Nova"; print(a + "Lang"); print("a" < "b"); print(a == "Nova"); print("x"[0]);',
    "comparison": "print(1 < 2); print(2 <= 2); print(3 > 4); print(1 == 1.0); print(true == 1); print([1,2] == [1,2]);",
    "unary": "let x = 5; print(-x); print(!(x > 3)); print(- -x);",
    "while_complex": "let i = 0; let s = 0; while (i < 10 && s < 20) { s = s + i; i = i + 1; } print(s); print(i);",
    "nested_loops": """
        for (let i = 0; i < 3; i = i + 1) {
            for (let j = 0; j < 3; j = j + 1) {
                if (j == 1) { continue; }
                if (i == 2) { break; }
                print(i * 10 + j);
            }
        }""",
    "shadowing": "let x = 1; { let x = x + 1; print(x); { let x = x * 10; print(x); } print(x); } print(x);",
    "block_vars": "{ let y = 1; print(y); } { let y = 2; print(y); } let y = 3; print(y);",
    "recursion": "function fib(n) { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); } print(fib(15));",
    "mutual_recursion": """
        function even(n) { if (n == 0) { return true; } return odd(n - 1); }
        function odd(n) { if (n == 0) { return false; } return even(n - 1); }
        print(even(10)); print(odd(7));""",
    "deep_recursion": "function s(n) { if (n == 0) { return 0; } return n + s(n - 1); } print(s(400));",
    "early_return_in_loops": """
        function find(a, t) {
            for (let i = 0; i < len(a); i = i + 1) {
                for (let j = 0; j < 1; j = j + 1) { if (a[i] == t) { return i; } }
            }
            return -1;
        }
        print(find([5, 6, 7], 7)); print(find([5], 9));""",
    "globals_modified": "let c = 0; function inc() { c = c + 1; } inc(); inc(); inc(); print(c);",
    "param_isolation": "function f(a) { a = a + 1; return a; } let x = 1; print(f(x)); print(x);",
    "param_named_like_global": "let n = 5; function f(n) { n = n * 2; return n; } print(f(3)); print(n);",
    "no_return_value": "function f() { let x = 1; } print(f()); function g() { return; } print(g());",
    "discarded_call": "function noisy() { print(\"called\"); return 1; } noisy(); let x = noisy(); print(x);",
    "arrays": "let a = [1, 2, 3]; a[1] = 20; print(a); print(len(a)); print(a[0] + a[2]);",
    "nested_arrays": "let m = [[1, 2], [3, 4]]; m[1][0] = 9; print(m); print(m[1][0]);",
    "array_aliasing": "let a = [1]; let b = a; b[0] = 5; print(a); function s(x) { x[0] = 42; } s(a); print(b);",
    "array_with_calls": "function one() { return 1; } let a = [one(), one() + 1, 3]; print(a);",
    "sum_array": "let a = [1, 2, 3, 4]; let s = 0; for (let i = 0; i < len(a); i = i + 1) { s = s + a[i]; } print(s);",
    "break_continue_while": "let i = 0; while (true) { i = i + 1; if (i == 2) { continue; } if (i > 4) { break; } print(i); }",
    "else_if": """
        function g(s) { if (s >= 90) { return "A"; } else if (s >= 80) { return "B"; } else { return "C"; } }
        print(g(95)); print(g(85)); print(g(10));""",
    "big_ints": "function f(n) { if (n <= 1) { return 1; } return n * f(n - 1); } print(f(25));",
    # runtime errors must also match
    "error_div_zero": "let a = 10; let b = 0; print(1); print(a / b); print(2);",
    "error_nested_call": "function inner(x) { return 1 / x; } function outer() { return inner(0); } print(\"start\"); outer();",
    "error_index": "let a = [1, 2]; print(a[5]);",
    "error_type": 'function add(a, b) { return a + b; } print(add(1, "x"));',
    "error_modulo": "print(5 % (1 - 1));",
    "error_condition_type": "function f(x) { if (x) { return 1; } return 2; } print(f(1));",
    "error_string_assign": 'let s = "abc"; function f(x) { x[0] = "z"; } f(s);',
}


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_tac_matches_interpreter(name):
    both(PROGRAMS[name])


@pytest.mark.parametrize("path", EXAMPLES, ids=[os.path.basename(p) for p in EXAMPLES])
def test_examples_tac_matches_interpreter(path):
    result = both(open(path).read())
    assert result.ok


def test_known_program_outputs_through_tac():
    assert run_tac(program("print(2 + 3 * 4);")).output == "14\n"
    assert run_tac(program(open(EXAMPLES[0]).read())).ok


def test_runner_error_message_has_line_and_call_stack():
    src = "function inner(x) { return 100 / x; }\nfunction outer() { return inner(0); }\nouter();"
    r = run_tac(program(src))
    assert r.errors[0].message == "Division by zero at line 1."
    assert "Call stack: main -> outer -> inner" in r.errors[0].hint


def test_runner_output_before_error_is_kept():
    r = run_tac(program("print(1); print(1 / 0); print(2);"))
    assert r.output == "1\n" and len(r.errors) == 1


def test_runner_step_limit():
    r = run_tac(program("while (true) { }"), max_steps=5000)
    assert r.errors[0].message.startswith("Execution step limit exceeded")


def test_runner_call_depth_limit():
    r = run_tac(program("function f(n) { return f(n + 1); } f(0);"))
    assert r.errors[0].message.startswith("Stack overflow")
    r = run_tac(program("function f(n) { if (n == 0) { return 0; } return f(n - 1); } print(f(10));"),
                max_call_depth=5)
    assert r.errors[0].message.startswith("Stack overflow")


def test_runner_reports_variable_not_defined():
    prog = TACProgram(TACFunction("main", [], [TACInstruction(T.OP_PRINT, "ghost", line=4)]))
    r = run_tac(prog)
    assert r.errors[0].message == "Variable 'ghost' is not defined at line 4."


def test_runner_final_variables_snapshot():
    r = run_tac(program("let a = 1; let s = \"hi\"; let arr = [1, 2];"))
    assert r.variables["a"] == "1" and r.variables["s"] == "hi" and r.variables["arr"] == "[1, 2]"


def test_runner_is_reusable():
    prog = program("let x = 1; print(x);")
    assert run_tac(prog).output == run_tac(prog).output == "1\n"


# ------------------------------------------------ randomized differential test
def _int_expr(rng, depth):
    if depth == 0 or rng.random() < 0.25:
        return rng.choice(["a", "b", "c", str(rng.randint(0, 9)), str(rng.randint(-5, -1))])
    kind = rng.random()
    if kind < 0.12:
        return f"-({_int_expr(rng, depth - 1)})"
    op = rng.choice(["+", "-", "*", "/", "%"])
    return f"({_int_expr(rng, depth - 1)} {op} {_int_expr(rng, depth - 1)})"


def _bool_expr(rng, depth):
    if depth == 0 or rng.random() < 0.2:
        return rng.choice(["true", "false", "flag"])
    kind = rng.random()
    if kind < 0.45:
        op = rng.choice(["<", ">", "<=", ">=", "==", "!="])
        return f"({_int_expr(rng, depth - 1)} {op} {_int_expr(rng, depth - 1)})"
    if kind < 0.6:
        return f"!({_bool_expr(rng, depth - 1)})"
    op = rng.choice(["&&", "||"])
    return f"({_bool_expr(rng, depth - 1)} {op} {_bool_expr(rng, depth - 1)})"


def test_random_expressions_agree():
    rng = random.Random(20240613)
    header = "let a = 7; let b = -3; let c = 0; let flag = true;\n"
    errors_seen = 0
    for _ in range(300):
        expr = _int_expr(rng, 4) if rng.random() < 0.5 else _bool_expr(rng, 4)
        result = both(header + f"print({expr});")
        errors_seen += bool(result.errors)
    assert 0 < errors_seen < 300          # the generator exercises both success and failure paths
