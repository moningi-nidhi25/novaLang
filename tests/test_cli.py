"""Phase 11: the command-line runner (python -m compiler FILE)."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from compiler.cli import main, render
from compiler.pipeline import STAGE_IDS, STAGES, run_pipeline

ROOT = Path(__file__).resolve().parents[1]
FACTORIAL = ROOT / "examples" / "demo_factorial.nova"
EXAMPLES = sorted((ROOT / "examples").glob("*.nova"))
ERROR_DEMOS = sorted((ROOT / "examples" / "errors").glob("*.nova"))


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_factorial_demo_prints_all_ten_stages_and_120(capsys):
    code, out, _ = run(capsys, FACTORIAL)
    assert code == 0
    for number, (_, name) in enumerate(STAGES, start=1):
        assert f"[{number}/10] {name}  -  ok" in out
    assert "  120\n" in out
    assert "optimized TAC output is identical" in out


def test_each_stage_shows_its_own_content(capsys):
    _, out, _ = run(capsys, FACTORIAL)
    assert "FUNCTION     'function'" in out                    # tokens
    assert "FunctionDeclaration factorial(n)" in out           # AST
    assert "BinaryExpression <=   : bool" in out               # AST with inferred type
    assert "factorial(n): function" in out                     # symbol table
    assert "t3 = call factorial, 1" in out                     # TAC
    assert "-> B2 (true), B3 (false)" in out                   # CFG
    assert "What changed:" in out                              # optimizer log


def test_only_one_stage(capsys):
    code, out, _ = run(capsys, FACTORIAL, "--stage", "tac")
    assert code == 0 and "Three Address Code" in out and "Tokens" not in out


def test_unknown_stage_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main([str(FACTORIAL), "--stage", "bogus"])
    assert exc.value.code == 2


def test_json_output_equals_the_api_shape(capsys):
    code, out, _ = run(capsys, FACTORIAL, "--json")
    assert code == 0
    assert json.loads(out) == run_pipeline(FACTORIAL.read_text()).to_dict()


def test_reads_standard_input(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(6 * 7);"))
    code, out, _ = run(capsys, "-")
    assert code == 0 and "  42\n" in out


def test_missing_file_is_exit_code_2_with_a_message(capsys):
    code, out, err = run(capsys, ROOT / "nope.nova")
    assert code == 2 and out == "" and "cannot read" in err


@pytest.mark.parametrize("path", ERROR_DEMOS, ids=lambda p: p.stem)
def test_errors_exit_1_and_show_a_caret_under_the_source(capsys, path):
    code, out, _ = run(capsys, path)
    assert code == 1
    assert "FAILED" in out and "^" in out


def test_stages_after_a_failure_are_marked_skipped(capsys):
    _, out, _ = run(capsys, ROOT / "examples" / "errors" / "syntax_error.nova")
    assert "Abstract Syntax Tree  -  FAILED" in out
    assert "Three Address Code  -  skipped" in out


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_renders_without_error(capsys, path):
    code, out, _ = run(capsys, path)
    assert code == 0
    assert out.count("[") >= 10 and "DIFFERS" not in out


def test_render_never_leaks_python_objects():
    text = render(run_pipeline(FACTORIAL.read_text()))
    for bad in ("<compiler", "object at 0x", "'type':", "None"):
        assert bad not in text


def test_python_dash_m_works_as_a_real_command():
    done = subprocess.run([sys.executable, "-m", "compiler", str(FACTORIAL), "--stage", "execution"],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "120" in done.stdout
