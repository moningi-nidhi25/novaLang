import json

import pytest

from compiler.parser import ast as A
from compiler.parser.parser import parse


# ------------------------------------------------------------------ helpers
def ok(source):
    r = parse(source)
    assert r.ok, [e.message for e in r.errors]
    return r.program


def stmt(source):
    """Parse a single statement and return it."""
    body = ok(source).body
    assert len(body) == 1
    return body[0]


def expr(source):
    """Parse `<source>;` as an expression statement and return the expression."""
    s = stmt(source + ";")
    assert isinstance(s, A.ExpressionStatement)
    return s.expression


def shape(n):
    """Compact S-expression form of an expression, for readable assertions."""
    if isinstance(n, A.BinaryExpression):
        return (n.operator, shape(n.left), shape(n.right))
    if isinstance(n, A.UnaryExpression):
        return (n.operator, shape(n.operand))
    if isinstance(n, A.Literal):
        return n.value
    if isinstance(n, A.Identifier):
        return n.name
    if isinstance(n, A.FunctionCall):
        return ("call", shape(n.callee), *[shape(a) for a in n.arguments])
    if isinstance(n, A.IndexExpression):
        return ("index", shape(n.object), shape(n.index))
    if isinstance(n, A.ArrayLiteral):
        return ("array", *[shape(e) for e in n.elements])
    raise AssertionError(type(n))


def errors(source):
    return parse(source).errors


# ---------------------------------------------------------------- empty
def test_empty_program():
    assert ok("").body == []


def test_comments_only_program():
    assert ok("// nothing\n/* here */").body == []


# ------------------------------------------------------------ expressions
def test_literals():
    assert (expr("10").value, expr("10").literal_type) == (10, "int")
    assert (expr("2.5").value, expr("2.5").literal_type) == (2.5, "float")
    assert (expr('"hi"').value, expr('"hi"').literal_type) == ("hi", "string")
    assert (expr("true").value, expr("true").literal_type) == (True, "bool")
    assert (expr("false").value, expr("false").literal_type) == (False, "bool")
    assert (expr("nil").value, expr("nil").literal_type) == (None, "nil")


def test_precedence_mul_before_add():
    assert shape(expr("2 + 3 * 4")) == ("+", 2, ("*", 3, 4))


def test_parentheses_override_precedence():
    assert shape(expr("(2 + 3) * 4")) == ("*", ("+", 2, 3), 4)


def test_left_associativity():
    assert shape(expr("10 - 3 - 2")) == ("-", ("-", 10, 3), 2)
    assert shape(expr("100 / 10 / 2")) == ("/", ("/", 100, 10), 2)
    assert shape(expr("1 + 2 + 3")) == ("+", ("+", 1, 2), 3)


def test_modulo_same_level_as_multiply():
    assert shape(expr("a * b % c")) == ("%", ("*", "a", "b"), "c")


def test_unary_binds_tighter_than_binary():
    assert shape(expr("-a * b")) == ("*", ("-", "a"), "b")
    assert shape(expr("2 - -3")) == ("-", 2, ("-", 3))


def test_unary_is_right_associative():
    assert shape(expr("!!x")) == ("!", ("!", "x"))
    assert shape(expr("- -5")) == ("-", ("-", 5))


def test_comparison_lower_than_arithmetic():
    assert shape(expr("a + 1 < b * 2")) == ("<", ("+", "a", 1), ("*", "b", 2))


def test_equality_lower_than_comparison():
    assert shape(expr("a < b == c < d")) == ("==", ("<", "a", "b"), ("<", "c", "d"))


def test_and_binds_tighter_than_or():
    assert shape(expr("a || b && c")) == ("||", "a", ("&&", "b", "c"))
    assert shape(expr("a && b || c")) == ("||", ("&&", "a", "b"), "c")


def test_not_with_logical_ops():
    assert shape(expr("!a && b")) == ("&&", ("!", "a"), "b")


def test_all_comparison_operators():
    for op in ("<", ">", "<=", ">=", "==", "!="):
        assert shape(expr(f"a {op} b")) == (op, "a", "b")


def test_binary_node_position_is_operator():
    e = expr("a   +  b")
    assert (e.line, e.column) == (1, 5)


def test_call_with_arguments():
    assert shape(expr("add(1, x + 2)")) == ("call", "add", 1, ("+", "x", 2))


def test_call_without_arguments():
    assert shape(expr("f()")) == ("call", "f")


def test_nested_calls():
    assert shape(expr("f(g(1), h())")) == ("call", "f", ("call", "g", 1), ("call", "h"))


def test_call_in_expression_binds_tight():
    assert shape(expr("n * factorial(n - 1)")) == (
        "*", "n", ("call", "factorial", ("-", "n", 1)))


def test_array_literal_and_empty_array():
    assert shape(expr("[1, 2, 3]")) == ("array", 1, 2, 3)
    assert shape(expr("[]")) == ("array",)
    assert shape(expr('[1, "a", [2]]')) == ("array", 1, "a", ("array", 2))


def test_index_and_chained_index():
    assert shape(expr("a[0]")) == ("index", "a", 0)
    assert shape(expr("m[i][j + 1]")) == ("index", ("index", "m", "i"), ("+", "j", 1))


def test_call_then_index():
    assert shape(expr("f(1)[2]")) == ("index", ("call", "f", 1), 2)


# ---------------------------------------------------------- declarations
def test_variable_declaration():
    s = stmt("let x = 10 + 20;")
    assert isinstance(s, A.VariableDeclaration)
    assert s.name == "x"
    assert shape(s.initializer) == ("+", 10, 20)
    assert (s.line, s.column) == (1, 1)


def test_assignment_statement():
    s = stmt("x = x + 1;")
    assert isinstance(s, A.Assignment)
    assert isinstance(s.target, A.Identifier) and s.target.name == "x"
    assert shape(s.value) == ("+", "x", 1)


def test_index_assignment():
    s = stmt("a[i + 1] = 5;")
    assert isinstance(s, A.Assignment)
    assert shape(s.target) == ("index", "a", ("+", "i", 1))


def test_print_statement():
    s = stmt("print(x + 1);")
    assert isinstance(s, A.PrintStatement)
    assert shape(s.expression) == ("+", "x", 1)


def test_expression_statement_call():
    s = stmt("greet();")
    assert isinstance(s, A.ExpressionStatement)
    assert isinstance(s.expression, A.FunctionCall)


def test_standalone_block():
    s = stmt("{ let a = 1; print(a); }")
    assert isinstance(s, A.Block) and len(s.statements) == 2


# ----------------------------------------------------------- control flow
def test_if_without_else():
    s = stmt("if (x < y) { print(1); }")
    assert isinstance(s, A.IfStatement)
    assert shape(s.condition) == ("<", "x", "y")
    assert len(s.then_branch.statements) == 1
    assert s.else_branch is None


def test_if_else():
    s = stmt('if (x) { print(1); } else { print(2); }')
    assert isinstance(s.else_branch, A.Block)


def test_else_if_chain():
    s = stmt("if (a) { } else if (b) { } else { }")
    assert isinstance(s.else_branch, A.IfStatement)
    assert isinstance(s.else_branch.else_branch, A.Block)


def test_while_loop():
    s = stmt("while (i < 5) { print(i); i = i + 1; }")
    assert isinstance(s, A.WhileStatement)
    assert shape(s.condition) == ("<", "i", 5)
    assert len(s.body.statements) == 2


def test_for_loop_with_let():
    s = stmt("for (let i = 0; i < 5; i = i + 1) { print(i); }")
    assert isinstance(s, A.ForStatement)
    assert isinstance(s.init, A.VariableDeclaration) and s.init.name == "i"
    assert shape(s.condition) == ("<", "i", 5)
    assert isinstance(s.update, A.Assignment)


def test_for_loop_with_assignment_init():
    s = stmt("for (i = 0; i < 3; i = i + 1) { }")
    assert isinstance(s.init, A.Assignment)


def test_break_and_continue():
    s = stmt("while (true) { if (a) { break; } continue; }")
    inner = s.body.statements
    assert isinstance(inner[0].then_branch.statements[0], A.BreakStatement)
    assert isinstance(inner[1], A.ContinueStatement)


# -------------------------------------------------------------- functions
def test_function_declaration():
    s = stmt("function add(a, b) { return a + b; }")
    assert isinstance(s, A.FunctionDeclaration)
    assert s.name == "add" and s.params == ["a", "b"]
    ret = s.body.statements[0]
    assert isinstance(ret, A.ReturnStatement)
    assert shape(ret.value) == ("+", "a", "b")


def test_function_without_params():
    s = stmt("function hi() { print(1); }")
    assert s.params == []


def test_return_without_value():
    s = stmt("function f() { return; }")
    assert s.body.statements[0].value is None


def test_factorial_program_structure():
    prog = ok("""
    function factorial(n) {
        if (n <= 1) { return 1; }
        return n * factorial(n - 1);
    }
    let result = factorial(5);
    print(result);
    """)
    kinds = [type(n).__name__ for n in prog.body]
    assert kinds == ["FunctionDeclaration", "VariableDeclaration", "PrintStatement"]
    fn = prog.body[0]
    assert [type(n).__name__ for n in fn.body.statements] == ["IfStatement", "ReturnStatement"]


# ------------------------------------------------------------- AST output
def test_to_dict_is_json_serialisable_and_structured():
    prog = ok("let x = 10 + 20;")
    d = json.loads(json.dumps(prog.to_dict()))
    decl = d["body"][0]
    assert d["type"] == "Program"
    assert decl["type"] == "VariableDeclaration" and decl["label"] == "x"
    init = decl["initializer"]
    assert init["type"] == "BinaryExpression" and init["label"] == "+"
    assert [init["left"]["label"], init["right"]["label"]] == ["10", "20"]
    assert init["line"] == 1 and init["column"] == 12


def test_format_tree():
    tree = A.format_tree(ok("let x = 10 + 20;"))
    assert tree.splitlines() == [
        "Program",
        "└── VariableDeclaration x",
        "    └── BinaryExpression +",
        "        ├── Literal 10",
        "        └── Literal 20",
    ]


def test_children_order_is_source_order():
    e = expr("a - b")
    assert [c.name for c in e.children()] == ["a", "b"]


def test_visitor_dispatch():
    class Counter(A.NodeVisitor):
        def __init__(self):
            self.n = 0

        def visit_Literal(self, node):
            self.n += 1

        def generic_visit(self, node):
            for c in node.children():
                c.accept(self)

    c = Counter()
    ok("let a = [1, 2, 3 + 4];").accept(c)
    assert c.n == 4


def test_parse_result_to_dict():
    d = parse("let x = 1;").to_dict()
    assert d["errors"] == [] and d["ast"]["type"] == "Program"
    assert d["tokens"][0]["type"] == "LET"


# ------------------------------------------------------------ syntax errors
def test_missing_close_paren_in_if_matches_brief_example():
    src = "if (x > 10 {\n    print(x);\n}"
    errs = errors(src)
    assert errs[0].message == "Expected ')' after condition."
    # caret just after '10', where ')' belongs
    assert (errs[0].line, errs[0].column) == (1, 11)
    text = errs[0].format(src)
    assert "1 | if (x > 10 {" in text
    assert "Found '{' instead." in text


def test_missing_semicolon_points_at_end_of_previous_token():
    src = "let x = 5\nlet y = 6;"
    errs = errors(src)
    assert errs[0].message == "Expected ';' after variable declaration."
    assert (errs[0].line, errs[0].column) == (1, 10)


def test_missing_variable_name():
    assert errors("let = 5;")[0].message == "Expected variable name after 'let'."


def test_missing_assign_in_let():
    assert errors("let x 5;")[0].message == "Expected '=' after variable name."


def test_missing_expression():
    errs = errors("let x = ;")
    assert errs[0].message == "Expected expression."
    assert (errs[0].line, errs[0].column) == (1, 9)


def test_operator_without_operand():
    assert errors("let x = 1 + ;")[0].message == "Expected expression."


def test_unclosed_grouping_paren():
    assert errors("let x = (1 + 2;")[0].message == "Expected ')' after expression."


def test_unclosed_call():
    assert errors("f(1, 2;")[0].message == "Expected ')' after arguments."


def test_unclosed_index_and_array():
    assert errors("a[1;")[0].message == "Expected ']' after index."
    assert errors("let a = [1, 2;")[0].message == "Expected ']' after array elements."


def test_unclosed_block_reports_open_location():
    errs = errors("while (true) {\n  print(1);\n")
    assert errs[0].message == "Expected '}' to close the block."
    assert "line 1" in errs[0].hint


def test_missing_brace_before_body():
    errs = errors("if (x) print(1);")
    assert errs[0].message == "Expected '{' before if body."


def test_function_errors():
    assert errors("function (a) { }")[0].message == "Expected function name after 'function'."
    assert errors("function f a) { }")[0].message == "Expected '(' after function name."
    assert errors("function f(a b) { }")[0].message == "Expected ')' after parameters."
    assert errors("function f(1) { }")[0].message == "Expected parameter name."
    assert errors("function f() return 1;")[0].message == "Expected '{' before function body."


def test_for_loop_errors():
    assert errors("for (let i = 0 i < 3; i = i + 1) { }")[0].message == \
        "Expected ';' after for-loop initializer."
    assert errors("for (let i = 0; i < 3 i = i + 1) { }")[0].message == \
        "Expected ';' after for-loop condition."
    assert errors("for (let i = 0; i < 3; i = i + 1 { }")[0].message == \
        "Expected ')' after for-loop clauses."


def test_invalid_assignment_target():
    errs = errors("1 + 2 = 3;")
    assert errs[0].message == "Invalid assignment target."
    assert errors("f(x) = 3;")[0].message == "Invalid assignment target."


def test_print_without_parens():
    assert errors("print x;")[0].message == "Expected '(' after 'print'."


def test_function_inside_block_is_error_without_cascade():
    errs = errors("if (a) { function f() { return 1; } print(2); }")
    assert [e.message for e in errs] == ["Functions can only be declared at the top level."]


def test_stray_closing_brace():
    errs = errors("let a = 1;\n}\nlet b = 2;")
    assert len(errs) == 1 and errs[0].message == "Expected expression."


def test_error_recovery_reports_multiple_errors():
    src = "let a = ;\nlet b = 2;\nlet c = ;\nprint(b);"
    errs = errors(src)
    assert [(e.line) for e in errs] == [1, 3]


def test_recovery_still_builds_valid_statements():
    r = parse("let a = ;\nlet b = 2;\nprint(b);")
    assert len(r.errors) == 1
    kinds = [type(n).__name__ for n in r.program.body]
    assert kinds == ["VariableDeclaration", "PrintStatement"]


def test_error_at_eof_message():
    errs = errors("let x = 1 +")
    assert errs[0].message == "Expected expression."
    assert "end of file" in errs[0].hint


def test_parser_always_terminates_on_garbage():
    for src in ["}}}", "))) ((", "let let let", "function function", "else else",
                "[[[", "1 2 3 4", "; ; ;", "if if if", "for (;;)"]:
        parse(src)  # must not hang or raise


def test_lexical_errors_stop_parsing():
    r = parse("let x = $;")
    assert r.program is None
    assert r.errors[0].phase == "Lexical Error"


def test_broken_header_does_not_cascade_into_body():
    src = "if (x > 10 {\n    print(x);\n}\nlet y = 1;"
    errs = errors(src)
    assert [e.message for e in errs] == ["Expected ')' after condition."]


def test_broken_function_header_skips_body_once():
    src = "function f(a b) { return a; }\nprint(1);"
    r = parse(src)
    assert [e.message for e in r.errors] == ["Expected ')' after parameters."]
    assert [type(n).__name__ for n in r.program.body] == ["PrintStatement"]


# ======================================================================
# Nesting limits (found by the Phase 11 stress tests: 150 nested parentheses used to
# crash the parser with RecursionError, which the API would have turned into an HTTP 500)
# ======================================================================
from compiler.parser.ast import tree_depth  # noqa: E402
from compiler.parser.parser import MAX_AST_DEPTH, MAX_NESTING  # noqa: E402


class TestNestingLimits:
    def deep_parens(self, n):
        return "print(" + "(" * n + "1" + ")" * n + ");"

    def test_reasonable_nesting_is_fine(self):
        assert parse(self.deep_parens(20)).ok
        assert parse("{" * 20 + "}" * 20).ok

    def test_too_many_parentheses_is_a_syntax_error_not_a_crash(self):
        result = parse(self.deep_parens(MAX_NESTING + 10))
        assert not result.ok
        assert len(result.errors) == 1                       # one error, no cascade
        assert "nested too deeply" in result.errors[0].message
        assert result.errors[0].hint

    def test_the_error_points_at_the_spot_where_the_limit_was_passed(self):
        err = parse(self.deep_parens(60)).errors[0]
        assert err.line == 1 and err.column > MAX_NESTING

    @pytest.mark.parametrize("make", [
        lambda n: "{" * n + "}" * n,
        lambda n: "if (true) {" * n + "}" * n,
        lambda n: "while (false) {" * n + "}" * n,
        lambda n: "let a = " + "[" * n + "1" + "]" * n + ";",
    ])
    def test_every_nesting_construct_is_limited(self, make):
        assert parse(make(10)).ok
        result = parse(make(MAX_NESTING + 10))
        assert not result.ok and "nested too deeply" in result.errors[0].message

    def test_long_operator_chain_is_limited_by_tree_depth(self):
        ok = "print(" + " + ".join(["1"] * 50) + ");"
        too_long = "print(" + " + ".join(["1"] * (MAX_AST_DEPTH + 20)) + ");"
        assert parse(ok).ok
        result = parse(too_long)
        assert not result.ok and result.program is None      # no tree: later stages would recurse over it
        assert "nested too deeply" in result.errors[0].message

    def test_chain_error_points_into_the_expression(self):
        err = parse("print(" + " + ".join(["1"] * 200) + ");").errors[0]
        assert err.line == 1 and err.column >= 1

    @pytest.mark.parametrize("make", [
        lambda n: "print(" + "-" * n + "1);",
        lambda n: "print(" + "!" * n + "true);",
        lambda n: "let x = 1;\nif (x == 0) { print(0); }" + "".join(
            f" else if (x == {i}) {{ print({i}); }}" for i in range(1, n)),
    ])
    def test_extreme_depth_never_raises(self, make):
        result = parse(make(1500))                           # far past Python's recursion limit
        assert not result.ok
        assert "nested too deeply" in result.errors[0].message

    def test_a_long_else_if_ladder_still_works(self):
        ladder = "let x = 1;\nif (x == 0) { print(0); }" + "".join(
            f" else if (x == {i}) {{ print({i}); }}" for i in range(1, 60))
        assert parse(ladder).ok

    def test_limits_apply_to_the_finished_tree_not_just_the_parser(self):
        # Grouping parentheses add no tree node, so nest array literals, which do.
        program = parse("let a = " + "[" * 10 + "1" + "]" * 10 + ";").program
        depth, deepest = tree_depth(program)
        assert 10 < depth < MAX_AST_DEPTH and deepest.line == 1

    def test_grouping_parentheses_add_no_tree_depth(self):
        assert tree_depth(parse(self.deep_parens(10)).program)[0] == 3   # Program > Print > Literal

    def test_tree_depth_of_a_flat_program(self):
        depth, _ = tree_depth(parse("let a = 1;").program)
        assert depth == 3                                    # Program > VariableDeclaration > Literal
