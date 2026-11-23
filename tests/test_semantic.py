import json

import pytest

from compiler.semantic.analyzer import analyze_source, assignable, binary_result_type
from compiler.semantic.symbol_table import BUILTINS, Symbol, SymbolTable


# ------------------------------------------------------------------ helpers
def run(src):
    return analyze_source(src)


def msgs(src):
    return [e.message for e in run(src).errors]


def warns(src):
    return [w.message for w in run(src).warnings]


def clean(src):
    r = run(src)
    assert r.ok, [e.message for e in r.errors]
    return r


# ============================================================ symbol table
def test_symbol_table_declare_and_lookup():
    t = SymbolTable()
    assert t.declare(Symbol("x", "variable", "int")) is None
    assert t.lookup("x").type == "int"
    assert t.lookup("nope") is None


def test_symbol_table_duplicate_returns_existing_and_keeps_original():
    t = SymbolTable()
    first = Symbol("x", "variable", "int", line=1)
    t.declare(first)
    existing = t.declare(Symbol("x", "variable", "string", line=2))
    assert existing is first
    assert t.lookup("x").type == "int"


def test_symbol_table_nested_scopes_and_shadowing():
    t = SymbolTable()
    t.declare(Symbol("x", "variable", "int"))
    t.enter_scope("block")
    assert t.lookup("x").type == "int"                 # visible from inner scope
    assert t.lookup_local("x") is None
    assert t.declare(Symbol("x", "variable", "string")) is None   # shadowing allowed
    assert t.lookup("x").type == "string"
    t.exit_scope()
    assert t.lookup("x").type == "int"                 # outer restored


def test_symbol_table_cannot_exit_global():
    with pytest.raises(RuntimeError):
        SymbolTable().exit_scope()


def test_builtins_resolve_but_cannot_be_declared():
    t = SymbolTable()
    assert t.lookup("len") is BUILTINS["len"]
    assert t.declare(Symbol("len", "variable")) is BUILTINS["len"]


def test_symbol_table_depth():
    t = SymbolTable()
    assert t.depth == 0
    t.enter_scope("a")
    t.enter_scope("b")
    assert t.depth == 2


# ============================================================ variables
def test_valid_program_has_no_errors():
    clean("let x = 10;\nlet y = x + 5;\nprint(y);")


def test_undefined_variable_matches_brief_example():
    r = run("let x = 10;\n\nprint(y);")
    assert [e.message for e in r.errors] == ["Variable 'y' is not defined."]
    assert (r.errors[0].line, r.errors[0].column) == (3, 7)
    assert r.errors[0].phase == "Semantic Error"


def test_error_format_shows_caret():
    src = "let x = 10;\nprint(y);"
    text = run(src).errors[0].format(src)
    assert "2 | print(y);" in text and "Why:" in text


def test_declaration_log_message():
    r = clean("let x = 10 + 20;")
    assert r.info[0]["message"] == "Variable 'x' declared successfully (type: int)."


def test_duplicate_declaration_same_scope():
    m = msgs("let x = 1;\nlet x = 2;")
    assert m == ["Variable 'x' is already declared in this scope (line 1)."]


def test_shadowing_in_inner_scope_is_allowed():
    clean("let x = 1; if (true) { let x = 2; print(x); } print(x);")


def test_variable_not_visible_after_block():
    assert msgs("if (true) { let a = 1; }\nprint(a);") == ["Variable 'a' is not defined."]


def test_inner_scope_sees_outer_variable():
    clean("let a = 1; while (a < 3) { a = a + 1; }")


def test_variable_not_visible_in_its_own_initializer():
    assert msgs("let x = x + 1;") == ["Variable 'x' is not defined."]


def test_use_before_declaration():
    assert msgs("print(x);\nlet x = 1;") == ["Variable 'x' is not defined."]


def test_for_loop_variable_is_scoped_to_loop():
    assert msgs("for (let i = 0; i < 3; i = i + 1) { }\nprint(i);") == \
        ["Variable 'i' is not defined."]


def test_assignment_to_undefined_variable():
    assert msgs("y = 5;") == ["Variable 'y' is not defined."]


def test_assignment_to_function_name():
    assert msgs("function f() { }\nf = 3;") == ["Cannot assign to function 'f'."]


def test_variable_conflicts_with_function_name():
    assert msgs("function f() { }\nlet f = 1;") == \
        ["'f' is already declared as a function (line 1)."]


def test_cannot_redeclare_builtin():
    assert msgs("let len = 1;") == ["'len' is a built-in function and cannot be redeclared."]
    assert msgs("function len(a) { }") == ["'len' is a built-in function and cannot be redeclared."]


# ================================================================== types
def test_assignment_type_mismatch():
    assert msgs('let x = 1;\nx = "hello";') == \
        ["Cannot assign string to variable 'x' of type int."]


def test_int_widens_to_float_but_not_back():
    clean("let f = 1.5; f = 2;")
    assert msgs("let i = 1; i = 2.5;") == ["Cannot assign float to variable 'i' of type int."]


def test_nil_initialised_variable_accepts_anything():
    clean('let n = nil; n = 5; n = "x";')


def test_assignment_from_unknown_type_is_allowed():
    clean("function f(a) { let x = 1; x = a; }")


def test_array_variable_type():
    assert msgs("let a = [1]; a = 5;") == ["Cannot assign int to variable 'a' of type array."]


def test_int_plus_string_error():
    assert msgs('let x = 1 + "a";') == ["Operator '+' cannot be applied to types int and string."]


def test_string_concatenation_ok():
    r = clean('let s = "a" + "b";')
    assert r.symbol_table.lookup("s") is None or True
    assert r.program.body[0].initializer.inferred_type == "string"


def test_other_operators_reject_strings_bools_arrays_nil():
    assert msgs('let x = "a" - "b";')
    assert msgs("let x = true + 1;")
    assert msgs("let x = [1] * 2;")
    assert msgs("let x = nil + 1;")


def test_ordering_comparisons():
    clean('let a = 1 < 2.5; let b = "a" < "b";')
    assert msgs('let a = 1 < "a";') == ["Operator '<' cannot be applied to types int and string."]
    assert msgs("let a = true > false;")


def test_equality_accepts_any_types():
    clean('let a = 1 == "x"; let b = nil != true;')


def test_logical_operators_need_bool():
    clean("let a = true && false || true;")
    assert msgs("let a = 1 && true;") == ["Operator '&&' cannot be applied to types int and bool."]


def test_unary_operators():
    clean("let a = -5; let b = !true; let c = -2.5;")
    assert msgs('let a = -"x";') == ["Operator '-' cannot be applied to type string."]
    assert msgs("let a = !5;") == ["Operator '!' cannot be applied to type int."]


def test_inferred_result_types():
    r = clean("let a = 1 + 2; let b = 1 + 2.5; let c = 1 < 2; let d = 7 / 2;")
    types = [n.initializer.inferred_type for n in r.program.body]
    assert types == ["int", "float", "bool", "int"]


def test_conditions_must_be_bool():
    assert msgs("if (1) { }") == ["Condition of 'if' must be bool, found int."]
    assert msgs('while ("x") { }') == ["Condition of 'while' must be bool, found string."]
    assert msgs("for (let i = 0; i; i = i + 1) { }") == \
        ["Condition of 'for' must be bool, found int."]
    clean("let x = 1; if (x > 0) { } while (x < 0) { }")


def test_unknown_types_checked_at_runtime_not_flagged():
    clean("function f(a, b) { if (a) { return a + b; } return a < b; }")


def test_any_with_string_concat_and_numbers():
    clean('function f(a) { let s = a + "x"; let n = a + 1; return n; }')


def test_binary_result_type_table():
    assert binary_result_type("+", "int", "int") == "int"
    assert binary_result_type("+", "int", "float") == "float"
    assert binary_result_type("+", "any", "int") == "any"
    assert binary_result_type("+", "any", "float") == "float"
    assert binary_result_type("+", "any", "string") == "string"
    assert binary_result_type("-", "string", "string") is None
    assert binary_result_type("==", "int", "string") == "bool"


def test_assignable_table():
    assert assignable("float", "int") and not assignable("int", "float")
    assert assignable("any", "string") and assignable("int", "any")


# ============================================================ arrays / index
def test_array_indexing_ok():
    r = clean("let a = [10, 20]; print(a[0]); a[1] = 5; let m = [[1],[2]]; print(m[0][0]);")
    assert r.ok


def test_index_non_indexable():
    assert msgs("let x = 5; print(x[0]);") == ["Cannot index a value of type int."]


def test_index_must_be_int():
    assert msgs("let a = [1]; print(a[1.5]);") == ["Index must be an int, found float."]
    assert msgs('let a = [1]; print(a["x"]);') == ["Index must be an int, found string."]


def test_negative_constant_index():
    assert msgs("let a = [1]; print(a[-1]);") == ["Index cannot be negative."]


def test_string_indexing_yields_string_and_is_immutable():
    r = clean('let s = "abc"; let c = s[0];')
    assert r.program.body[1].initializer.inferred_type == "string"
    assert msgs('let s = "abc"; s[0] = "x";') == \
        ["Strings are immutable; cannot assign to a string index."]


# ============================================================== functions
def test_factorial_demo_is_valid():
    r = clean("""
    function factorial(n) {
        if (n <= 1) { return 1; }
        return n * factorial(n - 1);
    }
    let result = factorial(5);
    print(result);
    """)
    d = r.symbol_table.to_dict()
    assert [s["name"] for s in d["symbols"]] == ["factorial", "result"]
    fn_scope = d["children"][0]
    assert fn_scope["name"] == "function factorial"
    assert [(s["name"], s["kind"]) for s in fn_scope["symbols"]] == [("n", "parameter")]


def test_call_undefined_function():
    assert msgs("foo(1);") == ["Function 'foo' is not defined."]


def test_wrong_argument_count():
    src = "function add(a, b) { return a + b; }\n"
    assert msgs(src + "add(1);") == ["Function 'add' expects 2 arguments but got 1."]
    assert msgs(src + "add(1, 2, 3);") == ["Function 'add' expects 2 arguments but got 3."]
    assert msgs("function one(a) { }\none();") == ["Function 'one' expects 1 argument but got 0."]


def test_call_before_declaration_is_allowed():
    clean("print(twice(4));\nfunction twice(n) { return n * 2; }")


def test_mutual_recursion():
    clean("""
    function even(n) { if (n == 0) { return true; } return odd(n - 1); }
    function odd(n) { if (n == 0) { return false; } return even(n - 1); }
    print(even(4));
    """)


def test_calling_a_variable():
    assert msgs("let x = 1;\nx(2);") == ["'x' is a variable, not a function."]


def test_function_used_as_value():
    assert msgs("function f() { }\nlet g = f;") == \
        ["'f' is a function and must be called with parentheses."]


def test_call_result_of_call_is_rejected():
    assert msgs("function f() { return 1; }\nf()(2);") == ["Only named functions can be called."]


def test_duplicate_function():
    assert msgs("function f() { }\nfunction f() { }") == \
        ["Function 'f' is already declared (line 1)."]


def test_duplicate_parameter():
    assert msgs("function f(a, a) { }") == ["Duplicate parameter 'a' in function 'f'."]


def test_local_redeclaring_parameter_is_duplicate():
    assert msgs("function f(a) { let a = 1; }") == \
        ["Variable 'a' is already declared in this scope (line 1)."]


def test_function_locals_do_not_leak():
    assert msgs("function f() { let hidden = 1; }\nprint(hidden);") == \
        ["Variable 'hidden' is not defined."]


def test_function_cannot_see_later_globals():
    assert msgs("function f() { return g; }\nlet g = 1;") == ["Variable 'g' is not defined."]


def test_function_sees_earlier_globals():
    clean("let g = 1;\nfunction f() { return g; }")


def test_len_builtin():
    r = clean('let a = [1,2]; let n = len(a); let m = len("abc");')
    assert r.program.body[1].initializer.inferred_type == "int"
    assert msgs("len();") == ["Function 'len' expects 1 argument but got 0."]
    assert msgs("len(1, 2);") == ["Function 'len' expects 1 argument but got 2."]
    assert msgs("len(5);") == ["len() expects an array or string, found int."]


# ============================================= return / break / continue
def test_return_outside_function():
    assert msgs("return 1;") == ["'return' outside of a function."]


def test_return_inside_function_and_nested_blocks():
    clean("function f(x) { if (x) { return 1; } while (true) { return 2; } return 3; }")


def test_break_and_continue_outside_loop():
    assert msgs("break;") == ["'break' outside of a loop."]
    assert msgs("continue;") == ["'continue' outside of a loop."]
    assert msgs("if (true) { break; }") == ["'break' outside of a loop."]


def test_break_and_continue_inside_loops():
    clean("while (true) { if (true) { break; } continue; }")
    clean("for (let i = 0; i < 3; i = i + 1) { if (i == 1) { continue; } break; }")


def test_break_in_function_inside_loop_is_not_allowed():
    # A function body starts with no enclosing loop even if called from one.
    assert msgs("function f() { break; }\nwhile (true) { f(); }") == \
        ["'break' outside of a loop."]


# ================================================================ warnings
def test_division_by_constant_zero_is_warning_not_error():
    r = run("let x = 10 / 0;")
    assert r.ok
    assert [w.message for w in r.warnings] == \
        ["Division by zero: the right operand is the constant 0."]
    assert r.warnings[0].phase == "Semantic Warning"


def test_modulo_by_zero_warning():
    assert len(warns("let x = 5 % 0;")) == 1
    assert warns("let x = 5 / 2;") == []


def test_unreachable_code_warning():
    assert warns("function f() { return 1; print(2); print(3); }") == \
        ["Unreachable code after 'return'."]
    assert warns("while (true) { break; print(1); }") == ["Unreachable code after 'break'."]
    assert warns("while (true) { continue; print(1); }") == ["Unreachable code after 'continue'."]


def test_no_warnings_for_normal_code():
    assert warns("function f(a) { if (a) { return 1; } return 2; }") == []


# ============================================== recovery / cascades / misc
def test_errors_do_not_cascade():
    assert msgs("let y = undefined_var + 1;\nprint(y);") == \
        ["Variable 'undefined_var' is not defined."]


def test_multiple_independent_errors_all_reported():
    m = msgs("print(a);\nlet x = 1 + \"s\";\nbreak;\nfoo();")
    assert m == [
        "Variable 'a' is not defined.",
        "Operator '+' cannot be applied to types int and string.",
        "'break' outside of a loop.",
        "Function 'foo' is not defined.",
    ]


def test_syntax_errors_skip_semantic_analysis():
    r = run("let x = ;\nprint(y);")
    assert [e.phase for e in r.errors] == ["Syntax Error"]


def test_lexical_errors_skip_semantic_analysis():
    assert run("let x = $;").errors[0].phase == "Lexical Error"


def test_decorated_ast_contains_types_in_json():
    r = clean("let x = 1 + 2.5;")
    d = r.program.to_dict()["body"][0]["initializer"]
    assert d["inferred_type"] == "float"
    assert d["left"]["inferred_type"] == "int"


def test_result_to_dict_is_json_serialisable():
    r = run("let x = 1;\nprint(y);\nfunction f(a) { return a; }")
    d = json.loads(json.dumps(r.to_dict()))
    assert d["ok"] is False
    assert d["errors"][0]["message"] == "Variable 'y' is not defined."
    assert d["symbol_table"]["name"] == "global"
    assert any(i["message"].startswith("Variable 'x' declared") for i in d["info"])


def test_scope_tree_contains_blocks_and_for():
    r = clean("let a = 1; if (a > 0) { let b = 2; } for (let i = 0; i < 1; i = i + 1) { }")
    d = r.symbol_table.to_dict()
    kinds = [c["kind"] for c in d["children"]]
    assert kinds == ["block", "for"]
    assert [s["name"] for s in d["children"][0]["symbols"]] == ["b"]
    assert [s["name"] for s in d["children"][1]["symbols"]] == ["i"]
