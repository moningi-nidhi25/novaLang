"""Phase 8 tests: the pipeline function and the FastAPI endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import MAX_SOURCE_CHARS
from compiler.pipeline import (
    ERROR, OK, SKIPPED, STAGE_IDS, UPTO, WARNING, run_pipeline,
)

client = TestClient(app)
EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples").glob("*.nova"))
FACTORIAL = (Path(__file__).resolve().parents[1] / "examples" / "demo_factorial.nova").read_text()


def post(endpoint: str, source: str):
    return client.post(f"/api/{endpoint}", json={"source": source})


def statuses(result):
    return {s.id: s.status for s in result.stages}


# ======================================================================
# The pipeline function
# ======================================================================
class TestPipeline:
    def test_ten_stages_in_order(self):
        assert STAGE_IDS == ["source", "tokens", "ast", "semantic", "symbol_table", "tac",
                             "cfg", "optimized_tac", "optimized_cfg", "execution"]
        assert [s.id for s in run_pipeline("print(1);").stages] == STAGE_IDS

    def test_factorial_demo_all_stages_ok(self):
        r = run_pipeline(FACTORIAL)
        assert r.ok and r.failed_stage is None
        assert set(statuses(r).values()) == {OK}
        ex = r.stage("execution").data
        assert ex["output"] == "120\n"
        assert ex["verified"] is True

    def test_lexical_error_stops_everything_after_tokens(self):
        r = run_pipeline("let x = 5 @;")
        assert r.failed_stage == "tokens"
        st = statuses(r)
        assert st["source"] == OK and st["tokens"] == ERROR
        assert all(st[i] == SKIPPED for i in STAGE_IDS[2:])
        assert r.errors[0].phase == "Lexical Error"

    def test_syntax_error_attributed_to_ast_stage(self):
        r = run_pipeline("let x = ;")
        assert r.failed_stage == "ast"
        assert statuses(r)["tokens"] == OK
        assert r.stage("ast").data is None
        assert all(statuses(r)[i] == SKIPPED for i in STAGE_IDS[3:])

    def test_semantic_error_stops_before_tac(self):
        r = run_pipeline("print(undefined_var);")
        assert r.failed_stage == "semantic"
        st = statuses(r)
        assert st["ast"] == OK                      # it parsed fine
        assert st["symbol_table"] == OK             # table exists even for a bad program
        assert st["tac"] == SKIPPED and st["execution"] == SKIPPED

    def test_warning_does_not_block_later_stages(self):
        r = run_pipeline("let x = 1 / 0;")
        assert r.stage("semantic").status == WARNING
        assert r.stage("tac").status == OK
        # ...the division then fails at run time, in the execution stage
        assert r.failed_stage == "execution"
        assert "zero" in r.errors[0].message.lower()

    def test_runtime_error_is_execution_failure_but_engines_agree(self):
        r = run_pipeline("let a = [1, 2];\nprint(a[5]);")
        ex = r.stage("execution")
        assert ex.status == ERROR
        assert ex.data["verified"] is True          # optimized TAC fails the same way
        assert r.stage("tac").status == OK

    def test_partial_output_kept_when_runtime_error(self):
        r = run_pipeline("print(1);\nprint(1 / 0);\nprint(3);")
        assert r.stage("execution").data["output"] == "1\n"

    @pytest.mark.parametrize("upto", STAGE_IDS)
    def test_upto_skips_later_stages(self, upto):
        r = run_pipeline(FACTORIAL, upto=upto)
        idx = STAGE_IDS.index(upto)
        st = statuses(r)
        for i, sid in enumerate(STAGE_IDS):
            if i > idx:
                assert st[sid] == SKIPPED, sid
        assert r.ok

    def test_upto_symbol_table_includes_it_even_for_bad_programs(self):
        r = run_pipeline("print(zzz);", upto="symbol_table")
        assert r.stage("symbol_table").status == OK and r.failed_stage == "semantic"

    def test_unknown_stage_rejected(self):
        with pytest.raises(ValueError):
            run_pipeline("print(1);", upto="nope")

    def test_empty_program(self):
        r = run_pipeline("")
        assert r.ok
        assert r.stage("execution").data["output"] == ""

    def test_ast_is_decorated_with_inferred_types(self):
        r = run_pipeline("let x = 1 + 2;", upto="ast")
        assert "inferred_type" in str(r.stage("ast").data)

    def test_summaries_are_filled(self):
        r = run_pipeline(FACTORIAL)
        assert all(s.summary for s in r.stages)

    def test_optimization_visible_in_stage_data(self):
        r = run_pipeline("let x = 2 * 3 + 4;\nprint(x);")
        data = r.stage("optimized_tac").data
        assert data["changes"] and data["instruction_counts"]["after"] < data["instruction_counts"]["before"]

    def test_to_dict_only_filters_stages(self):
        d = run_pipeline("print(1);").to_dict(only=["tokens"])
        assert [s["id"] for s in d["stages"]] == ["tokens"]

    def test_json_serializable(self):
        import json
        for path in EXAMPLES:
            json.dumps(run_pipeline(path.read_text()).to_dict())

    @pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
    def test_every_example_runs_and_is_verified(self, path):
        r = run_pipeline(path.read_text())
        assert r.ok, [e.format() for e in r.errors]
        assert r.stage("execution").data["verified"] is True


# ======================================================================
# Endpoints
# ======================================================================
class TestEndpoints:
    def test_health_and_stages(self):
        assert client.get("/api/health").json() == {"status": "ok"}
        ids = [s["id"] for s in client.get("/api/stages").json()["stages"]]
        assert ids == STAGE_IDS

    def test_every_endpoint_is_mapped(self):
        for endpoint in UPTO:
            assert post(endpoint, "print(1);").status_code == 200

    @pytest.mark.parametrize("endpoint,last", [
        ("lex", "tokens"), ("parse", "ast"), ("analyze", "symbol_table"),
        ("tac", "tac"), ("cfg", "cfg"), ("optimize", "optimized_cfg"),
        ("compile", "execution"),
    ])
    def test_endpoint_returns_stages_up_to_its_own(self, endpoint, last):
        body = post(endpoint, FACTORIAL).json()
        ids = [s["id"] for s in body["stages"]]
        assert ids == STAGE_IDS[: STAGE_IDS.index(last) + 1]
        assert body["ok"] is True
        assert all(s["status"] == OK for s in body["stages"])

    def test_run_returns_only_execution(self):
        body = post("run", FACTORIAL).json()
        assert [s["id"] for s in body["stages"]] == ["execution"]
        assert body["stages"][0]["data"]["output"] == "120\n"

    def test_compile_factorial_demo(self):
        body = post("compile", FACTORIAL).json()
        assert len(body["stages"]) == 10
        by_id = {s["id"]: s for s in body["stages"]}
        assert by_id["execution"]["data"]["output"] == "120\n"
        assert by_id["execution"]["data"]["verified"] is True
        assert by_id["source"]["data"]["text"] == FACTORIAL

    def test_lex_endpoint_token_shape(self):
        tok = post("lex", "let x = 1;").json()["stages"][1]["data"][0]
        assert tok["type"] == "LET" and tok["line"] == 1 and tok["column"] == 1

    def test_compile_error_is_200_with_structured_error(self):
        r = post("compile", "let x = ;")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False and body["failed_stage"] == "ast"
        err = body["errors"][0]
        assert err["phase"] == "Syntax Error" and err["line"] == 1
        assert err["message"]

    def test_semantic_error_has_hint_and_position(self):
        err = post("analyze", "print(zzz);").json()["errors"][0]
        assert err["phase"] == "Semantic Error" and err["line"] == 1 and err["column"] >= 1

    def test_warnings_are_reported(self):
        body = post("analyze", "let x = 1 / 0;").json()
        assert body["ok"] is True
        assert body["warnings"]

    def test_run_endpoint_reports_runtime_error(self):
        body = post("run", "print(1 / 0);").json()
        assert body["ok"] is False
        assert body["errors"][0]["phase"] == "Runtime Error"

    def test_infinite_loop_is_stopped_not_hung(self):
        body = post("run", "while (true) { }").json()
        assert body["ok"] is False
        assert "step" in body["errors"][0]["message"].lower()

    def test_runaway_recursion_is_stopped(self):
        body = post("run", "function f(n) { return f(n + 1); }\nprint(f(0));").json()
        assert body["ok"] is False

    def test_endpoint_matches_pipeline_function(self):
        direct = run_pipeline(FACTORIAL).to_dict()
        via_api = post("compile", FACTORIAL).json()
        assert direct == via_api

    def test_missing_source_defaults_to_empty_program(self):
        r = client.post("/api/compile", json={})
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_wrong_type_is_422(self):
        assert client.post("/api/compile", json={"source": 123}).status_code == 422
        assert client.post("/api/compile", content="not json",
                           headers={"content-type": "application/json"}).status_code == 422

    def test_oversized_source_rejected(self):
        r = post("compile", "x" * (MAX_SOURCE_CHARS + 1))
        assert r.status_code == 422

    def test_max_size_source_accepted(self):
        assert post("lex", "1 " * (MAX_SOURCE_CHARS // 2)).status_code == 200

    def test_unicode_source(self):
        body = post("run", 'print("héllo ✓");').json()
        assert body["stages"][0]["data"]["output"] == "héllo ✓\n"

    def test_wrong_method_is_405(self):
        assert client.get("/api/compile").status_code == 405

    def test_cors_allows_vite_dev_server(self):
        r = client.options("/api/compile", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        })
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_cors_blocks_other_origins(self):
        r = client.options("/api/compile", headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        })
        assert "access-control-allow-origin" not in r.headers


class TestExamples:
    def test_list(self):
        names = client.get("/api/examples").json()["examples"]
        assert "demo_factorial" in names and names == sorted(names)

    def test_get_example_source_runs(self):
        body = client.get("/api/examples/demo_factorial").json()
        assert body["name"] == "demo_factorial"
        assert post("run", body["source"]).json()["stages"][0]["data"]["output"] == "120\n"

    def test_unknown_example_404(self):
        assert client.get("/api/examples/nope").status_code == 404

    @pytest.mark.parametrize("bad", ["..%2Fpytest", "%2e%2e%2fpytest.ini", "..", "hello.nova"])
    def test_no_path_traversal(self, bad):
        assert client.get(f"/api/examples/{bad}").status_code == 404


# ======================================================================
# Regression: deep (but legal) programs used to make the API answer HTTP 500 on some platforms
# ======================================================================
def json_depth(value) -> int:
    best, stack = 0, [(value, 1)]
    while stack:
        item, depth = stack.pop()
        best = max(best, depth)
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values() if isinstance(v, (dict, list)))
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item if isinstance(v, (dict, list)))
    return best


DEEPEST_LEGAL = {
    "nested if": "if (true) {" * 39 + "print(1);" + "}" * 39,   # the 40th level would be refused
    "nested while": "while (false) {" * 40 + "}" * 40,
    "index chain": "function g(a) { return a" + "[0]" * 95 + "; }\nprint(1);",
    "else-if ladder": "let x = 1;\nif (x == 0) { print(0); }" + "".join(
        f" else if (x == {i}) {{ print({i}); }}" for i in range(1, 95)),
}


class TestDeepResponses:
    """pydantic's JSON serializer gives up on nesting deeper than about 100 levels on some platforms
    (Windows + recent Python, in the report that found this) with "Circular reference detected (depth
    exceeded)". The compile endpoints therefore must not go through it."""

    def test_compile_endpoints_do_not_use_pydantics_serializer(self, monkeypatch):
        from pydantic import TypeAdapter

        def refuse(self, *args, **kwargs):
            raise ValueError("Circular reference detected (depth exceeded)")

        monkeypatch.setattr(TypeAdapter, "dump_json", refuse)   # simulate the platform that fails
        for endpoint in UPTO:
            response = post(endpoint, FACTORIAL)
            assert response.status_code == 200, endpoint
            assert response.json()["ok"] is True

    @pytest.mark.parametrize("shape", sorted(DEEPEST_LEGAL))
    def test_deepest_legal_programs_get_a_complete_answer(self, shape):
        body = post("compile", DEEPEST_LEGAL[shape]).json()
        assert body["ok"], body["errors"]
        assert body["stages"][-1]["id"] == "execution" and body["stages"][-1]["status"] == "ok"
        assert json_depth(body) > 100, "this program should be deeper than the serializer limit it guards against"

    @pytest.mark.parametrize("shape", sorted(DEEPEST_LEGAL))
    def test_deep_answers_still_work_when_pydantic_refuses(self, shape, monkeypatch):
        from pydantic import TypeAdapter
        monkeypatch.setattr(TypeAdapter, "dump_json", lambda *a, **k: (_ for _ in ()).throw(ValueError("depth exceeded")))
        assert post("compile", DEEPEST_LEGAL[shape]).status_code == 200
