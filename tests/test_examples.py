"""Every program in examples/ must work through the whole pipeline built so far."""

import glob
import os

import pytest

from compiler.interpreter.interpreter import interpret
from compiler.lexer.lexer import lex
from compiler.parser.parser import parse
from compiler.semantic.analyzer import analyze_source

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")
FILES = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.nova")))

EXPECTED_OUTPUT = {
    "hello.nova": "Hello, NovaLang!\n",
    "demo_factorial.nova": "120\n",
    "calculator.nova": "15\n5\n50\n2\nCannot divide by zero\nnil\n14\n20\n3\n3.5\n2\n",
    "conditions.nova": "x is smaller\nA\nB\nC\nF\nEntry allowed\nNot a senior\n",
    "loops.nova": "0\n1\n2\n3\n4\n55\n1\n3\n5\n7\n",
    "functions.nova": "30\n120\n55\n2\n",
    "arrays.nova": "10\n[10, 99, 30, 40]\n4\n99\n[[1, 2], [9, 4]]\n",
    "optimizer_showcase.nova": "100\n86400\n",   # area = 10 * 10 + 0 = 100 > 50, then 60 * 60 * 24
}


def test_all_required_examples_exist():
    names = {os.path.basename(f) for f in FILES}
    assert {"hello.nova", "calculator.nova", "conditions.nova", "loops.nova",
            "functions.nova", "arrays.nova", "demo_factorial.nova"} <= names


@pytest.mark.parametrize("path", FILES, ids=[os.path.basename(p) for p in FILES])
def test_example_passes_every_phase(path):
    source = open(path).read()
    assert lex(source).ok
    assert parse(source).ok
    sem = analyze_source(source)
    assert sem.ok and not sem.warnings
    result = interpret(sem.program)
    assert result.ok
    assert result.output == EXPECTED_OUTPUT[os.path.basename(path)]
