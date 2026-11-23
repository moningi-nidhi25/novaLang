import json

import pytest

from compiler.interpreter.environment import Environment, UndefinedName
from compiler.interpreter.interpreter import (
    format_value, run_source, type_name, values_equal,
)
from compiler.semantic.analyzer import analyze_source
from compiler.parser.parser import parse
from compiler.interpreter.interpreter import interpret


# ------------------------------------------------------------------ helpers
def out(src, **limits):
    r = run_source(src, **limits)
    assert r.ok, [e.message for e in r.errors]
    return r.output


def lines(src, **limits):
    return out(src, **limits).splitlines()


def err(src, **limits):
    r = run_source(src, **limits)
    assert not r.ok, "expected a runtime error"
    return r.errors[0]


def value(expr_src):
    """Evaluate one expression by printing it."""
    return lines(f"print({expr_src});")[0]


# ============================================================ environment
def test_environment_define_get_assign():
    g = Environment()
    g.define("x", 1)
    inner = Environment(g)
    assert inner.get("x") == 1
    inner.assign("x", 5)                 # updates the OUTER binding
    assert g.get("x") == 5
    inner.define("x", 9)                 # shadows
    assert inner.get("x") == 9 and g.get("x") == 5
    assert inner.depth() == 1


def test_environment_undefined():
    e = Environment()
    with pytest.raises(UndefinedName):
        e.get("nope")
    with pytest.raises(UndefinedName):
        e.assign("nope", 1)


# ============================================================ value helpers
def test_type_name():
    assert [type_name(v) for v in (1, 1.5, "s", True, None, [])] == \
        ["int", "float", "string", "bool", "nil", "array"]


def test_values_equal_rules():
    assert values_equal(1, 1.0)
    assert not values_equal(True, 1)
    assert not values_equal(False, 0)
    assert values_equal(None, None) and not values_equal(None, 0)
    assert values_equal("a", "a") and not values_equal("a", "b")
    assert values_equal([1, [2]], [1, [2]]) and not values_equal([1], [1, 2])
    assert not values_equal("1", 1)


def test_format_value():
    assert format_value(True) == "true" and format_value(None) == "nil"
    assert format_value("hi") == "hi"
    assert format_value([1, "a", True, None, [2.5]]) == '[1, "a", true, nil, [2.5]]'
    cyc = [1]
    cyc.append(cyc)
    assert format_value(cyc) == "[1, [...]]"


# ============================================================ arithmetic
def test_hello_and_basic_print():
    assert out('print("Hello, NovaLang!");') == "Hello, NovaLang!\n"


def test_precedence_runs_correctly():
    assert value("2 + 3 * 4") == "14"
    assert value("(2 + 3) * 4") == "20"
    assert value("10 - 3 - 2") == "5"
    assert value("2 * 3 + 4 * 5") == "26"


def test_integer_division_truncates_toward_zero():
    assert value("7 / 2") == "3"
    assert value("-7 / 2") == "-3"
    assert value("7 / -2") == "-3"
    assert value("-7 / -2") == "3"


def test_float_division_and_mixed_arithmetic():
    assert value("7 / 2.0") == "3.5"
    assert value("1 + 2.5") == "3.5"
    assert value("4 / 2.0") == "2.0"
    assert value("0.5 * 4") == "2.0"


def test_modulo_sign_follows_dividend():
    assert value("7 % 3") == "1"
    assert value("-7 % 3") == "-1"
    assert value("7 % -3") == "1"
    assert value("5.5 % 2") == "1.5"


def test_division_identity():
    # a == (a / b) * b + a % b  for every sign combination
    for a in (7, -7):
        for b in (3, -3):
            assert value(f"({a} / {b}) * {b} + {a} % {b}") == str(a)


def test_unary_operators():
    assert value("-5") == "-5" and value("- -5") == "5"
    assert value("!true") == "false" and value("!!true") == "true"
    assert value("-2.5") == "-2.5"


def test_string_concatenation_and_comparison():
    assert value('"Nova" + "Lang"') == "NovaLang"
    assert value('"apple" < "banana"') == "true"
    assert value('"b" >= "a"') == "true"


def test_comparison_operators():
    for expr, expected in [("1 < 2", "true"), ("2 < 1", "false"), ("2 <= 2", "true"),
                           ("3 > 2.5", "true"), ("2 >= 3", "false"),
                           ("1 == 1.0", "true"), ("1 != 2", "true")]:
        assert value(expr) == expected


def test_equality_is_strict_about_types():
    assert value('1 == "1"') == "false"
    assert value("true == 1") == "false"
    assert value("nil == nil") == "true"
    assert value("[1, 2] == [1, 2]") == "true"
    assert value("[1, 2] != [1, 3]") == "true"


def test_big_integers_do_not_overflow():
    assert value("1000000 * 1000000 * 1000000 * 1000000") == "1" + "0" * 24


# ============================================================== variables
def test_variables_and_reassignment():
    assert lines("let x = 10; let y = 20; let r = x + y; print(r); x = 1; print(x);") == ["30", "1"]


def test_all_data_types_print():
    src = 'let age = 20; let cgpa = 9.65; let name = "Nidhi"; let ok = true; let n = nil;' \
          "print(age); print(cgpa); print(name); print(ok); print(n);"
    assert lines(src) == ["20", "9.65", "Nidhi", "true", "nil"]


def test_block_scoping_and_shadowing():
    src = "let x = 1; { let x = 2; print(x); } print(x);"
    assert lines(src) == ["2", "1"]


def test_assignment_in_block_updates_outer():
    assert lines("let x = 1; { x = 5; } print(x);") == ["5"]


def test_final_variables_snapshot():
    r = run_source('let a = 1; let s = "hi"; let arr = [1, 2];')
    assert r.variables == {"a": "1", "s": "hi", "arr": "[1, 2]"}


# =========================================================== control flow
def test_if_else():
    assert lines('let x = 1; let y = 2; if (x < y) { print("x is smaller"); } '
                 'else { print("x is larger"); }') == ["x is smaller"]
    assert lines('if (2 < 1) { print("a"); } else { print("b"); }') == ["b"]


def test_else_if_chain():
    src = """
    function grade(s) {
        if (s >= 90) { return "A"; } else if (s >= 80) { return "B"; } else { return "C"; }
    }
    print(grade(95)); print(grade(85)); print(grade(10));
    """
    assert lines(src) == ["A", "B", "C"]


def test_while_loop():
    assert lines("let i = 0; while (i < 3) { print(i); i = i + 1; }") == ["0", "1", "2"]


def test_for_loop():
    assert lines("for (let i = 0; i < 3; i = i + 1) { print(i * i); }") == ["0", "1", "4"]


def test_for_with_assignment_initializer():
    assert lines("let i = 10; for (i = 0; i < 2; i = i + 1) { print(i); } print(i);") == \
        ["0", "1", "2"]


def test_for_variable_not_visible_afterwards():
    assert "not defined" in err("for (let i = 0; i < 1; i = i + 1) { } print(i);").message


def test_break_and_continue_in_while():
    src = """
    let i = 0;
    while (true) {
        i = i + 1;
        if (i == 2) { continue; }
        if (i > 4) { break; }
        print(i);
    }
    """
    assert lines(src) == ["1", "3", "4"]


def test_continue_in_for_still_runs_update():
    src = "for (let i = 0; i < 5; i = i + 1) { if (i % 2 == 0) { continue; } print(i); }"
    assert lines(src) == ["1", "3"]


def test_break_only_exits_inner_loop():
    src = """
    for (let i = 0; i < 2; i = i + 1) {
        for (let j = 0; j < 5; j = j + 1) {
            if (j == 1) { break; }
            print(i * 10 + j);
        }
    }
    """
    assert lines(src) == ["0", "10"]


def test_short_circuit_and_or():
    assert value("false && (1 / 0 == 0)") == "false"      # right side never runs
    assert value("true || (1 / 0 == 0)") == "true"
    assert value("true && false") == "false"
    assert value("false || true") == "true"


def test_logical_operators_require_bool():
    assert "needs bool operands" in err("print(1 && true);").message
    assert "needs bool operands" in err("print(true && 1);").message
    assert "needs bool operands" in err("print(0 || true);").message


def test_conditions_must_be_bool_at_runtime():
    assert err("if (1) { }").message == "Condition of 'if' must be bool, found int at line 1."
    assert "Condition of 'while'" in err('while ("x") { }').message
    assert "Condition of 'for'" in err("for (let i = 0; 1; i = i + 1) { }").message


# =============================================================== functions
def test_function_call_and_return():
    assert lines("function add(a, b) { return a + b; } let r = add(10, 20); print(r);") == ["30"]


def test_factorial_recursion_demo():
    src = """
    function factorial(n) {
        if (n <= 1) { return 1; }
        return n * factorial(n - 1);
    }
    let result = factorial(5);
    print(result);
    """
    assert lines(src) == ["120"]


def test_fibonacci():
    src = """
    function fib(n) { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); }
    print(fib(10));
    """
    assert lines(src) == ["55"]


def test_large_factorial_uses_big_ints():
    src = "function f(n) { if (n <= 1) { return 1; } return n * f(n - 1); } print(f(25));"
    assert lines(src) == ["15511210043330985984000000"]


def test_deep_but_legal_recursion():
    src = "function sum(n) { if (n == 0) { return 0; } return n + sum(n - 1); } print(sum(400));"
    assert lines(src) == ["80200"]


def test_function_without_return_gives_nil():
    assert lines("function f() { let x = 1; } print(f());") == ["nil"]
    assert lines("function g() { return; } print(g());") == ["nil"]


def test_early_return_from_loop():
    src = """
    function find(a, target) {
        for (let i = 0; i < len(a); i = i + 1) {
            if (a[i] == target) { return i; }
        }
        return -1;
    }
    print(find([5, 6, 7], 7)); print(find([5, 6, 7], 9));
    """
    assert lines(src) == ["2", "-1"]


def test_call_before_declaration():
    assert lines("print(twice(4)); function twice(n) { return n * 2; }") == ["8"]


def test_mutual_recursion():
    src = """
    function even(n) { if (n == 0) { return true; } return odd(n - 1); }
    function odd(n) { if (n == 0) { return false; } return even(n - 1); }
    print(even(10)); print(odd(7)); print(even(7));
    """
    assert lines(src) == ["true", "true", "false"]


def test_parameters_are_local_and_do_not_change_caller():
    src = "function f(a) { a = a + 1; return a; } let x = 1; print(f(x)); print(x);"
    assert lines(src) == ["2", "1"]


def test_function_can_read_and_modify_globals():
    src = "let c = 0; function inc() { c = c + 1; } inc(); inc(); print(c);"
    assert lines(src) == ["2"]


def test_function_cannot_see_callers_locals():
    src = "function g() { return secret; } function f() { let secret = 1; return g(); } print(f());"
    assert err(src).message.startswith("Variable 'secret' is not defined")


def test_locals_do_not_leak_between_calls():
    src = "function f(n) { let t = n * 2; return t; } print(f(1)); print(f(5));"
    assert lines(src) == ["2", "10"]


def test_arguments_evaluated_left_to_right_with_calls():
    assert lines("function id(x) { print(x); return x; } print(id(1) + id(2));") == \
        ["1", "2", "3"]


# ================================================================== arrays
def test_array_indexing_and_assignment():
    src = "let a = [10, 20, 30, 40]; print(a[0]); a[1] = 99; print(a); print(a[2] + a[3]);"
    assert lines(src) == ["10", "[10, 99, 30, 40]", "70"]


def test_nested_arrays():
    assert lines("let m = [[1, 2], [3, 4]]; m[1][0] = 9; print(m); print(m[1][0]);") == \
        ["[[1, 2], [9, 4]]", "9"]


def test_len_builtin():
    assert lines('print(len([1, 2, 3])); print(len("hello")); print(len([]));') == ["3", "5", "0"]


def test_arrays_are_reference_values():
    src = "let a = [1]; let b = a; b[0] = 5; print(a[0]);"
    assert lines(src) == ["5"]


def test_array_modified_inside_function():
    src = "function setfirst(arr) { arr[0] = 42; } let a = [1, 2]; setfirst(a); print(a);"
    assert lines(src) == ["[42, 2]"]


def test_loop_over_array_sum():
    src = "let a = [1, 2, 3, 4]; let s = 0; for (let i = 0; i < len(a); i = i + 1) { s = s + a[i]; } print(s);"
    assert lines(src) == ["10"]


def test_array_literal_is_fresh_each_evaluation():
    src = "function mk() { return [0]; } let a = mk(); let b = mk(); a[0] = 1; print(b[0]);"
    assert lines(src) == ["0"]


def test_string_indexing():
    assert lines('let s = "abc"; print(s[1]);') == ["b"]


def test_index_errors():
    assert err("let a = [1, 2, 3]; print(a[5]);").message == \
        "Index 5 out of range for array of length 3 at line 1."
    assert "out of range" in err("let a = [1]; print(a[-1]);").message
    assert "out of range" in err('print("ab"[2]);').message
    assert err("let a = [1]; print(a[1.5]);").message.startswith("Index must be an int, found float")
    assert err("let a = [1]; print(a[true]);").message.startswith("Index must be an int, found bool")
    assert err("let x = 5; print(x[0]);").message.startswith("Cannot index a value of type int")
    assert "out of range" in err("let a = [1]; a[3] = 1;").message
    assert "immutable" in err('let s = "abc"; s[0] = "x";').message


# =============================================================== runtime errors
def test_division_by_zero_matches_brief_example():
    src = "let a = 10;\nlet b = 0;\n\nprint(1);\nprint(2);\nprint(3);\nprint(4);\nprint(a / b);"
    e = err(src)
    assert e.phase == "Runtime Error"
    assert e.message == "Division by zero at line 8."
    assert (e.line, e.column) == (8, 9)


def test_output_before_error_is_preserved():
    r = run_source("print(1); print(2); print(1 / 0); print(3);")
    assert r.output == "1\n2\n"
    assert len(r.errors) == 1


def test_modulo_and_float_division_by_zero():
    assert err("print(5 % 0);").message == "Modulo by zero at line 1."
    assert err("print(5.0 / 0);").message == "Division by zero at line 1."
    assert err("print(5 / 0.0);").message == "Division by zero at line 1."


def test_runtime_type_errors():
    assert err('print(1 + "a");').message == \
        "Operator '+' cannot be applied to types int and string at line 1."
    assert "types bool and int" in err("print(true + 1);").message
    assert "types array and int" in err("print([1] * 2);").message
    assert "types int and string" in err('print(1 < "a");').message
    assert "Operator '-' cannot be applied to type string" in err('print(-"a");').message
    assert "Operator '!' cannot be applied to type int" in err("print(!1);").message


def test_runtime_checks_when_types_were_unknown_statically():
    src = 'function add(a, b) { return a + b; } print(add(1, "x"));'
    assert "cannot be applied to types int and string" in err(src).message


def test_undefined_variable_and_function_at_runtime():
    assert err("print(y);").message == "Variable 'y' is not defined at line 1."
    assert err("y = 1;").message == "Variable 'y' is not defined at line 1."
    assert err("foo();").message == "Function 'foo' is not defined at line 1."
    assert err("let x = 1; x();").message == "'x' is a variable, not a function at line 1."
    assert "must be called with parentheses" in err("function f() { } let g = f;").message


def test_wrong_argument_count_at_runtime():
    src = "function add(a, b) { return a + b; }\nadd(1);"
    assert err(src).message == "Function 'add' expects 2 arguments but got 1 at line 2."
    assert "expects 1 argument but got 0" in err("len();").message
    assert "len() expects an array or string, found int" in err("len(5);").message


def test_call_stack_hint_in_function_errors():
    src = "function inner(x) { return 1 / x; }\nfunction outer() { return inner(0); }\nouter();"
    e = err(src)
    assert e.message == "Division by zero at line 1."
    assert "Call stack: main -> outer -> inner" in e.hint


def test_error_format_shows_source_and_caret():
    src = "let a = 1;\nprint(a / 0);"
    text = err(src).format(src)
    assert text.startswith("Runtime Error: Division by zero at line 2.")
    assert "2 | print(a / 0);" in text


def test_runaway_recursion_is_stack_overflow_not_crash():
    e = err("function f(n) { return f(n + 1); } f(0);")
    assert e.message.startswith("Stack overflow")
    assert "Call stack" in e.hint


def test_custom_call_depth_limit():
    src = "function f(n) { if (n == 0) { return 0; } return f(n - 1); } print(f(10));"
    assert out(src, max_call_depth=20) == "0\n"
    assert err(src, max_call_depth=5).message.startswith("Stack overflow")


def test_infinite_loop_hits_step_limit():
    e = err("while (true) { }", max_steps=10_000)
    assert e.message.startswith("Execution step limit exceeded")
    assert "infinite loop" in e.hint


def test_step_limit_counts_function_calls_and_for_loops():
    assert err("for (let i = 0; true; i = i + 1) { }", max_steps=5000).message.startswith(
        "Execution step limit")


def test_string_growth_is_capped():
    src = 'let s = "xxxxxxxxxx"; while (true) { s = s + s; }'
    assert err(src).message.startswith("String too long")


def test_top_level_return_and_break_without_analysis():
    assert "outside of a function" in err("return 1;").message
    assert "outside of a loop" in err("break;").message


def test_syntax_errors_are_reported_not_executed():
    r = run_source("print(1); let = ;")
    assert r.output == "" and r.errors[0].phase == "Syntax Error"


def test_lexical_errors_are_reported_not_executed():
    assert run_source("print($);").errors[0].phase == "Lexical Error"


# ============================================================ result / API
def test_run_result_to_dict_is_json_friendly():
    d = json.loads(json.dumps(run_source("let x = 2; print(x * 21);").to_dict()))
    assert d["ok"] is True and d["output"] == "42\n"
    assert d["variables"] == {"x": "2"} and d["steps"] >= 2


def test_interpreter_is_reusable_and_independent():
    prog = parse("let x = 1; print(x);").program
    assert interpret(prog).output == "1\n"
    assert interpret(prog).output == "1\n"      # no state leaks between runs


# ============================================ integration with earlier phases
def test_full_pipeline_factorial_demo_outputs_120():
    src = """
    function factorial(n) {
        if (n <= 1) {
            return 1;
        }

        return n * factorial(n - 1);
    }

    let result = factorial(5);

    print(result);
    """
    sem = analyze_source(src)
    assert sem.ok and not sem.warnings
    assert interpret(sem.program).output == "120\n"


def test_semantic_warning_program_fails_cleanly_at_runtime():
    src = "let x = 10 / 0;"
    sem = analyze_source(src)
    assert sem.ok and len(sem.warnings) == 1            # compile-time warning ...
    assert err(src).message == "Division by zero at line 1."   # ... runtime error
