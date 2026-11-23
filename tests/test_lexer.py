import pytest

from compiler.lexer.lexer import Lexer, lex
from compiler.lexer.tokens import TokenType as T


def types(source):
    return [t.type for t in Lexer(source).tokenize()]


def tokens(source):
    return Lexer(source).tokenize()


# ---------------------------------------------------------------- basics
def test_empty_source_gives_only_eof():
    assert types("") == [T.EOF]


def test_spec_example_let_statement():
    toks = tokens("let x = 10 + 20;")
    assert [str(t) for t in toks] == [
        "LET", "IDENTIFIER(x)", "ASSIGN", "INTEGER(10)", "PLUS",
        "INTEGER(20)", "SEMICOLON", "EOF",
    ]


# -------------------------------------------------------------- keywords
@pytest.mark.parametrize("word,expected", [
    ("let", T.LET), ("function", T.FUNCTION), ("return", T.RETURN),
    ("if", T.IF), ("else", T.ELSE), ("while", T.WHILE), ("for", T.FOR),
    ("break", T.BREAK), ("continue", T.CONTINUE), ("print", T.PRINT),
    ("true", T.TRUE), ("false", T.FALSE), ("nil", T.NIL),
])
def test_keywords(word, expected):
    assert types(word) == [expected, T.EOF]


def test_boolean_and_nil_values():
    t, f, n, _ = tokens("true false nil")
    assert t.value is True and f.value is False and n.value is None


def test_keyword_prefix_is_identifier():
    assert types("letter iffy") == [T.IDENTIFIER, T.IDENTIFIER, T.EOF]


def test_keywords_are_case_sensitive():
    assert types("Let IF") == [T.IDENTIFIER, T.IDENTIFIER, T.EOF]


# ----------------------------------------------------------- identifiers
@pytest.mark.parametrize("name", ["x", "_tmp", "myVar2", "snake_case_9", "__"])
def test_identifiers(name):
    toks = tokens(name)
    assert toks[0].type is T.IDENTIFIER and toks[0].lexeme == name


# --------------------------------------------------------------- numbers
def test_integer_and_float():
    a, b, _ = tokens("42 9.65")
    assert (a.type, a.value) == (T.INTEGER, 42)
    assert (b.type, b.value) == (T.FLOAT, 9.65)


def test_trailing_dot_is_not_part_of_number():
    lexer = Lexer("3.")
    toks = lexer.tokenize()
    assert toks[0].type is T.INTEGER and toks[0].lexeme == "3"
    assert len(lexer.errors) == 1  # the stray '.'


def test_number_glued_to_letters_is_error():
    r = lex("12abc")
    assert not r.ok
    assert "Invalid number literal '12abc'" in r.errors[0].message
    assert [t.type for t in r.tokens] == [T.EOF]


def test_minus_is_separate_from_number():
    assert types("-5") == [T.MINUS, T.INTEGER, T.EOF]


# --------------------------------------------------------------- strings
def test_simple_string():
    t = tokens('"hello world"')[0]
    assert t.type is T.STRING and t.value == "hello world"
    assert t.lexeme == '"hello world"'


def test_string_escapes():
    t = tokens(r'"a\nb\t\"c\\"')[0]
    assert t.value == 'a\nb\t"c\\'


def test_empty_string():
    assert tokens('""')[0].value == ""


def test_unterminated_string():
    r = lex('let s = "abc')
    assert len(r.errors) == 1
    assert "Unterminated string" in r.errors[0].message
    assert (r.errors[0].line, r.errors[0].column) == (1, 9)


def test_string_cannot_span_lines():
    r = lex('"abc\ndef"')
    assert any("Unterminated string" in e.message for e in r.errors)


def test_invalid_escape():
    r = lex(r'"bad \q escape"')
    assert "Invalid escape sequence" in r.errors[0].message
    assert all(t.type is not T.STRING for t in r.tokens)


def test_comment_markers_inside_string_are_text():
    t = tokens('"// not a comment"')[0]
    assert t.value == "// not a comment"


# ------------------------------------------------------------- operators
@pytest.mark.parametrize("src,expected", [
    ("+", T.PLUS), ("-", T.MINUS), ("*", T.STAR), ("/", T.SLASH), ("%", T.PERCENT),
    ("==", T.EQ), ("!=", T.NEQ), ("<", T.LT), (">", T.GT), ("<=", T.LTE), (">=", T.GTE),
    ("&&", T.AND), ("||", T.OR), ("!", T.NOT), ("=", T.ASSIGN),
    ("(", T.LPAREN), (")", T.RPAREN), ("{", T.LBRACE), ("}", T.RBRACE),
    ("[", T.LBRACKET), ("]", T.RBRACKET), (",", T.COMMA), (";", T.SEMICOLON),
])
def test_operators_and_punctuation(src, expected):
    assert types(src) == [expected, T.EOF]


def test_maximal_munch():
    assert types("a<=b") == [T.IDENTIFIER, T.LTE, T.IDENTIFIER, T.EOF]
    assert types("a==b") == [T.IDENTIFIER, T.EQ, T.IDENTIFIER, T.EOF]
    assert types("a=!b") == [T.IDENTIFIER, T.ASSIGN, T.NOT, T.IDENTIFIER, T.EOF]
    assert types("===") == [T.EQ, T.ASSIGN, T.EOF]


def test_single_ampersand_and_pipe_have_hints():
    for src, op in (("a & b", "&&"), ("a | b", "||")):
        r = lex(src)
        assert len(r.errors) == 1
        assert op in r.errors[0].hint


# -------------------------------------------------------------- comments
def test_line_comment_is_skipped():
    assert types("let // comment here\nx") == [T.LET, T.IDENTIFIER, T.EOF]


def test_comment_at_eof_without_newline():
    assert types("x // done") == [T.IDENTIFIER, T.EOF]


def test_block_comment_is_skipped_and_lines_counted():
    toks = tokens("a /* one\ntwo\nthree */ b")
    assert [t.type for t in toks] == [T.IDENTIFIER, T.IDENTIFIER, T.EOF]
    assert toks[1].line == 3


def test_unterminated_block_comment():
    r = lex("x /* never closed")
    assert "Unterminated block comment" in r.errors[0].message
    assert (r.errors[0].line, r.errors[0].column) == (1, 3)


def test_division_is_not_comment():
    assert types("a / b") == [T.IDENTIFIER, T.SLASH, T.IDENTIFIER, T.EOF]


# ------------------------------------------------------ invalid characters
def test_unexpected_character_message_and_position():
    r = lex("let a = 1;\nlet $x = 5;")
    assert len(r.errors) == 1
    e = r.errors[0]
    assert e.message == "Unexpected character '$' at line 2, column 5."
    assert (e.line, e.column) == (2, 5)


def test_lexer_recovers_and_reports_all_errors():
    r = lex("let a = @;\nlet b = #;")
    assert [(e.line, e.column) for e in r.errors] == [(1, 9), (2, 9)]
    # valid tokens around the errors are still produced
    assert T.SEMICOLON in [t.type for t in r.tokens]


def test_non_ascii_character_is_error():
    assert not lex("let é = 1;").ok


def test_single_quote_has_hint():
    r = lex("'hi'")
    assert "double quotes" in r.errors[0].hint


# -------------------------------------------------------------- positions
def test_line_and_column_tracking():
    toks = tokens("let x = 10;\n  print(x);")
    pos = [(t.type, t.line, t.column) for t in toks]
    assert pos[0] == (T.LET, 1, 1)
    assert pos[1] == (T.IDENTIFIER, 1, 5)
    assert pos[2] == (T.ASSIGN, 1, 7)
    assert pos[3] == (T.INTEGER, 1, 9)
    assert pos[5] == (T.PRINT, 2, 3)
    assert pos[6] == (T.LPAREN, 2, 8)


def test_eof_position():
    toks = tokens("a\nb")
    assert (toks[-1].type, toks[-1].line, toks[-1].column) == (T.EOF, 2, 2)


def test_windows_line_endings():
    toks = tokens("a\r\nb")
    assert toks[1].line == 2 and toks[1].column == 1


# --------------------------------------------------------- whole programs
def test_factorial_program_lexes_cleanly():
    src = """
    function factorial(n) {
        if (n <= 1) { return 1; }
        return n * factorial(n - 1);
    }
    let result = factorial(5);
    print(result);
    """
    r = lex(src)
    assert r.ok
    assert r.tokens[0].type is T.FUNCTION
    assert r.tokens[-1].type is T.EOF


def test_array_program():
    assert types("let a = [1, 2.5, \"x\"]; print(a[0]);")[:8] == [
        T.LET, T.IDENTIFIER, T.ASSIGN, T.LBRACKET, T.INTEGER, T.COMMA,
        T.FLOAT, T.COMMA,
    ]


def test_lexer_is_reusable():
    lexer = Lexer("let $ = 1;")
    lexer.tokenize()
    assert len(lexer.errors) == 1
    lexer.tokenize()
    assert len(lexer.errors) == 1  # state reset, errors not doubled


# ----------------------------------------------------- error presentation
def test_error_format_shows_source_line_and_caret():
    src = "let a = 1;\nlet $x = 5;"
    err = lex(src).errors[0]
    text = err.format(src)
    assert text.startswith("Lexical Error: Unexpected character '$'")
    assert "2 | let $x = 5;" in text
    lines = text.splitlines()
    code_line = next(l for l in lines if "let $x" in l)
    caret_line = lines[lines.index(code_line) + 1]
    assert caret_line.index("^") == code_line.index("$")


def test_to_dict_is_json_friendly():
    import json
    d = lex("let x = 1; $").to_dict()
    json.dumps(d)
    assert d["tokens"][0] == {
        "type": "LET", "lexeme": "let", "value": None, "line": 1, "column": 1,
    }
    assert d["errors"][0]["phase"] == "Lexical Error"
