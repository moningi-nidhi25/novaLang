"""Phase 11: whole-system tests.

Unit tests (the other files) check one stage at a time. These check that the stages
agree with each other and with the layers built on top: the three execution engines,
the HTTP API, the demo programs, and the JSON the React frontend is tested against.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from compiler.interpreter.interpreter import interpret
from compiler.ir.generator import generate_tac
from compiler.ir.tac_runner import run_tac
from compiler.optimizer.optimizer import optimize
from compiler.parser.parser import parse
from compiler.pipeline import STAGE_IDS, run_pipeline
from compiler.semantic.analyzer import analyze

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.nova"))
ERROR_DEMOS = sorted((ROOT / "examples" / "errors").glob("*.nova"))
FIXTURES = sorted((ROOT / "frontend" / "src" / "test" / "fixtures").glob("*.json"))
client = TestClient(app)


def source(name: str) -> str:
    return (ROOT / "examples" / f"{name}.nova").read_text()


# What each example must print. Written by hand from reading the programs, so a bug
# that changes the output of the interpreter AND the TAC runner together still shows up.
EXPECTED_OUTPUT = {
    "hello": "Hello, NovaLang!\n",
    "demo_factorial": "120\n",
    "optimizer_showcase": "100\n86400\n",
    "loops": "0\n1\n2\n3\n4\n55\n1\n3\n5\n7\n",
    "functions": "30\n120\n55\n2\n",
}


# ======================================================================
# The headline demo
# ======================================================================
class TestFactorialDemo:
    """factorial(5) prints 120 and every one of the ten stages shows its work."""

    @pytest.fixture(scope="class")
    def body(self):
        return client.post("/api/compile", json={"source": source("demo_factorial")}).json()

    def stage(self, body, sid):
        return next(s for s in body["stages"] if s["id"] == sid)

    def test_ten_stages_all_ok(self, body):
        assert [s["id"] for s in body["stages"]] == STAGE_IDS
        assert body["ok"] and all(s["status"] == "ok" for s in body["stages"])

    def test_prints_120_and_optimizer_is_verified(self, body):
        ex = self.stage(body, "execution")["data"]
        assert ex["output"] == "120\n"
        assert ex["verified"] is True
        assert ex["variables"] == {"result": "120"}

    def test_tokens_stage_sees_every_token(self, body):
        toks = self.stage(body, "tokens")["data"]
        assert toks[0]["type"] == "FUNCTION" and toks[-1]["type"] == "EOF"
        assert [t["lexeme"] for t in toks if t["type"] == "INTEGER"] == ["1", "1", "1", "5"]

    def test_ast_has_the_three_top_level_pieces(self, body):
        kinds = [n["type"] for n in self.stage(body, "ast")["data"]["body"]]
        assert kinds == ["FunctionDeclaration", "VariableDeclaration", "PrintStatement"]

    def test_symbol_table_knows_the_function_and_its_parameter(self, body):
        table = self.stage(body, "symbol_table")["data"]
        names = {s["name"]: s for s in table["symbols"]}
        assert names["factorial"]["kind"] == "function" and names["factorial"]["params"] == ["n"]
        assert names["result"]["kind"] == "variable"
        inner = [s["name"] for c in table["children"] for s in c["symbols"]]
        assert "n" in inner

    def test_tac_listing_shows_the_recursion(self, body):
        listing = self.stage(body, "tac")["data"]["listing"]
        assert "function factorial(n):" in listing
        assert "call factorial, 1" in listing and "ifFalse" in listing

    def test_cfg_has_a_branching_block_and_two_exits_in_factorial(self, body):
        fn = next(f for f in self.stage(body, "cfg")["data"]["functions"] if f["function"] == "factorial")
        assert {e["kind"] for e in fn["edges"]} == {"true", "false"}
        assert len(fn["exits"]) == 2

    def test_optimizer_does_not_make_the_program_longer(self, body):
        counts = self.stage(body, "optimized_tac")["data"]["instruction_counts"]
        assert counts["after"] <= counts["before"]


# ======================================================================
# All engines agree
# ======================================================================
def three_ways(src: str):
    """Interpreter, TAC machine, optimized-TAC machine on the same checked program."""
    program = parse(src).program
    assert not analyze(program).errors
    ref = interpret(program)
    tac = generate_tac(program)
    return ref, run_tac(tac), run_tac(optimize(tac).optimized)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
class TestEveryExample:
    def test_three_engines_print_the_same(self, path):
        ref, plain, optimized = three_ways(path.read_text())
        assert not ref.errors
        assert ref.output == plain.output == optimized.output

    def test_pipeline_clean_and_verified(self, path):
        r = run_pipeline(path.read_text())
        assert r.ok and not r.warnings or r.ok   # warnings are allowed, errors are not
        assert r.stage("execution").data["verified"] is True

    def test_api_matches_pipeline_function(self, path):
        src = path.read_text()
        assert client.post("/api/compile", json={"source": src}).json() == run_pipeline(src).to_dict()

    def test_deterministic(self, path):
        src = path.read_text()
        a = client.post("/api/compile", json={"source": src}).content
        b = client.post("/api/compile", json={"source": src}).content
        assert a == b

    def test_optimizer_is_idempotent(self, path):
        tac = generate_tac(parse(path.read_text()).program)
        once = optimize(tac).optimized
        twice = optimize(once).optimized
        assert once.format() == twice.format()


@pytest.mark.parametrize("name,expected", sorted(EXPECTED_OUTPUT.items()))
def test_expected_output(name, expected):
    assert run_pipeline(source(name)).stage("execution").data["output"] == expected


def test_optimizer_showcase_really_shrinks():
    r = run_pipeline(source("optimizer_showcase"))
    counts = r.stage("optimized_tac").data["instruction_counts"]
    assert counts["after"] * 2 < counts["before"]
    passes = r.stage("optimized_tac").data["stats"]
    for needed in ("constant folding", "branch folding", "unreachable code", "dead store removal"):
        assert passes.get(needed, 0) > 0, needed
    listing = r.stage("optimized_tac").data["optimized"]["listing"]
    assert '"small"' not in listing and "86400" in listing


# ======================================================================
# Error demos: each failure is blamed on the right stage
# ======================================================================
ERROR_CASES = {
    "lexical_error": ("tokens", "Lexical Error", 3),
    "syntax_error": ("ast", "Syntax Error", 2),
    "semantic_error": ("semantic", "Semantic Error", 3),
    "runtime_error": ("execution", "Runtime Error", 6),
}


def test_every_error_demo_is_covered():
    assert {p.stem for p in ERROR_DEMOS} == set(ERROR_CASES)


@pytest.mark.parametrize("path", ERROR_DEMOS, ids=lambda p: p.stem)
class TestErrorDemos:
    def test_failed_stage_phase_and_line(self, path):
        stage, phase, line = ERROR_CASES[path.stem]
        body = client.post("/api/compile", json={"source": path.read_text()}).json()
        assert body["ok"] is False and body["failed_stage"] == stage
        first = body["errors"][0]
        assert first["phase"] == phase and first["line"] == line and first["message"]

    def test_stages_after_the_failure_are_skipped_and_before_it_are_not(self, path):
        stage, _, _ = ERROR_CASES[path.stem]
        body = client.post("/api/compile", json={"source": path.read_text()}).json()
        order = {s["id"]: s["status"] for s in body["stages"]}
        failed_at = STAGE_IDS.index(stage)
        for i, sid in enumerate(STAGE_IDS):
            if i < failed_at:
                assert order[sid] in ("ok", "warning"), sid
            if i > failed_at and stage != "execution":
                assert order[sid] in ("skipped", "ok"), sid   # symbol_table is built even for a bad program

    def test_error_text_can_be_rendered_with_a_caret_under_the_source(self, path):
        r = run_pipeline(path.read_text())
        text = r.errors[0].format(path.read_text())
        assert "^" in text and str(r.errors[0].line) in text


def test_runtime_error_demo_keeps_the_output_printed_before_the_error():
    r = run_pipeline((ROOT / "examples" / "errors" / "runtime_error.nova").read_text())
    ex = r.stage("execution").data
    assert ex["output"] == "90\n70\n"
    assert "never reached" not in ex["output"]
    assert ex["verified"] is True        # the optimized program fails in the same place


def test_semantic_demo_reports_both_mistakes_not_just_the_first():
    r = run_pipeline((ROOT / "examples" / "errors" / "semantic_error.nova").read_text())
    assert [e.line for e in r.errors] == [3, 4]


# ======================================================================
# The frontend's test fixtures are real backend responses
# ======================================================================
@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_frontend_fixture_matches_backend_output(path):
    """If the API shape changes, the React tests would silently keep testing the old shape.
    This test fails instead, so the fixtures must be regenerated."""
    fixture = json.loads(path.read_text())
    endpoint = "compile" if len(fixture["stages"]) == len(STAGE_IDS) else "analyze"
    live = client.post(f"/api/{endpoint}", json={"source": fixture["source"]}).json()
    assert live == fixture


def test_fixtures_cover_the_failure_modes_the_ui_has_to_handle():
    stages = {json.loads(p.read_text())["failed_stage"] for p in FIXTURES}
    assert {None, "tokens", "ast", "semantic", "execution"} <= stages


# ======================================================================
# Safety limits through the whole stack
# ======================================================================
class TestResourceLimits:
    def post(self, src):
        return client.post("/api/compile", json={"source": src}).json()

    def test_infinite_loop_stops(self):
        body = self.post("while (true) { }")
        assert body["failed_stage"] == "execution" and "step" in body["errors"][0]["message"].lower()

    def test_runaway_recursion_stops(self):
        body = self.post("function f(n) { return f(n + 1); }\nprint(f(0));")
        assert body["failed_stage"] == "execution"

    # Each shape: (builder, a size that must run through all ten stages, a size that must be refused).
    SHAPES = {
        "parentheses": (lambda n: "print(" + "(" * n + "1" + ")" * n + ");", 35, 60),
        "blocks": (lambda n: "{" * n + "}" * n, 35, 60),
        "nested if": (lambda n: "if (true) {" * n + "print(1);" + "}" * n, 35, 60),
        "nested while": (lambda n: "while (false) {" * n + "}" * n, 35, 60),
        "array literals": (lambda n: "let a = " + "[" * n + "1" + "]" * n + ";", 35, 60),
        "nested calls": (lambda n: "function f(x){return x;}\nprint(" + "f(" * n + "1" + ")" * n + ");", 35, 60),
        "addition chain": (lambda n: "print(" + "+".join(["1"] * n) + ");", 90, 200),
        "and chain": (lambda n: "print(" + " && ".join(["true"] * n) + ");", 90, 200),
        "minus signs": (lambda n: "print(" + "-" * n + "1);", 90, 200),
        "not signs": (lambda n: "print(" + "!" * n + "true);", 90, 200),
        "index chain": (lambda n: "function g(a) { return a" + "[0]" * n + "; }\nprint(1);", 90, 200),
        "else-if ladder": (lambda n: "let x = 1;\nif (x == 0) { print(0); }" + "".join(
            f" else if (x == {i}) {{ print({i}); }}" for i in range(1, n)), 90, 200),
    }

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_deep_but_allowed_input_runs_all_ten_stages(self, shape):
        make, fine, _ = self.SHAPES[shape]
        body = self.post(make(fine))
        assert body["ok"], body["errors"]
        assert body["stages"][-1]["id"] == "execution" and body["stages"][-1]["status"] == "ok"

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_too_deep_input_is_a_syntax_error_never_a_crash(self, shape):
        make, _, too_deep = self.SHAPES[shape]
        for n in (too_deep, 1200):                 # just over the limit, and far past Python's recursion limit
            r = client.post("/api/compile", json={"source": make(n)})
            assert r.status_code == 200, (shape, n)
            body = r.json()
            assert body["failed_stage"] == "ast"
            assert "nested too deeply" in body["errors"][0]["message"]

    def test_long_program_compiles(self):
        src = "\n".join(f"let v{i} = {i} + 1;" for i in range(400)) + "\nprint(v399);"
        body = self.post(src)
        assert body["ok"] and body["stages"][-1]["data"]["output"] == "400\n"

    def test_garbage_input_is_an_error_not_a_crash(self):
        for src in ("\x00\x01\x02", "}}}}", "let", "(((", '"unterminated', "/* never closed", "1 +"):
            body = self.post(src)
            assert body["ok"] is False and body["errors"], repr(src)
