# NovaLang Architecture and Roadmap

## 1. Pipeline

```
Source ─► Lexer ─► Tokens ─► Parser ─► AST ─► Semantic Analyzer ─► Annotated AST + Symbol Table
                                                       │
                                  ┌────────────────────┤
                                  ▼                    ▼
                          TAC Generator          Interpreter ─► Output
                                  │
                                  ▼
                       Basic Blocks / CFG
                                  │
                                  ▼
                            Optimizer ─► Optimized TAC
```

Design rules:

1. Each phase is a pure Python module: input data in, result data (plus a list of errors) out.
2. Phases never import from `backend/`. FastAPI is a thin layer that calls a single
   `run_pipeline()` orchestrator (`compiler/pipeline.py`, added in Phase 8) so no logic is duplicated across endpoints.
3. Every phase exposes `to_dict()` / JSON output for the "Explain mode" UI.
4. Every error is a `NovaLangError` with `phase`, `message`, `line`, `column`, `hint`.
5. The interpreter runs the **AST** (not the TAC). TAC/optimizer exist to *show* the IR
   concepts; keeping them separate keeps each part simple and independently testable.

## 2. Components

| Package | Responsibility | Key concepts |
|---------|----------------|--------------|
| `compiler/lexer` | characters → tokens | regular languages, DFA, maximal munch, error recovery |
| `compiler/parser` | tokens → AST | CFG, recursive descent, precedence climbing, syntax errors |
| `compiler/semantic` | scopes, types, checks | symbol table, static scoping, type checking |
| `compiler/ir` | AST → TAC, TAC → basic blocks/CFG | three-address code, leaders, flow graphs |
| `compiler/optimizer` | TAC → TAC | constant folding/propagation, algebraic simplification, dead code |
| `compiler/interpreter` | run the AST | environments, call stack, runtime errors |
| `compiler/errors` | shared error classes | uniform diagnostics |
| `backend` | FastAPI endpoints | `/api/lex /parse /analyze /tac /optimize /run /compile` |
| `frontend` | React + Vite playground | editor, token table, AST graph, TAC, CFG, explain mode |

## 3. Folder structure

```
novalang/
├── compiler/
│   ├── errors/errors.py
│   ├── lexer/{tokens.py,lexer.py}
│   ├── parser/{ast.py,parser.py}
│   ├── semantic/{symbol_table.py,analyzer.py}
│   ├── ir/{tac.py,generator.py,tac_runner.py,basic_blocks.py}
│   ├── optimizer/{optimizer.py,dataflow.py,type_inference.py}
│   ├── interpreter/{environment.py,interpreter.py}
│   ├── pipeline.py                 # run_pipeline(): all ten stages in one function
│   └── cli.py, __main__.py         # python -m compiler FILE
├── backend/{main.py,schemas.py,routes/}
├── frontend/src/{components,lib,test}
├── examples/*.nova, examples/errors/*.nova
├── tests/                          # one file per phase, plus test_integration.py and test_cli.py
├── docs/{01_language_spec.md,02_architecture_and_roadmap.md,03_demo_script.md,screenshots/}
├── pytest.ini
├── requirements.txt
└── README.md
```

## 4. Team split (two students)

* **Student 1 (front half):** language syntax, lexer, parser, AST, syntax errors.
* **Student 2 (back half):** symbol table, semantic analyzer, interpreter, TAC, optimizer.
* **Both:** API integration, frontend, tests, documentation, presentation.

The interface between the halves is the AST (`compiler/parser/ast.py`): agree on its node
classes early (Phase 2) and both can work independently. Suggested Git flow: `main` stays green;
feature branches `feat/lexer`, `feat/parser`, `feat/semantic`, ...; one phase per pull request;
run `pytest` before every merge.

## 5. Roadmap

| Phase | Deliverable | Done when |
|-------|-------------|-----------|
| 1  | Spec, tokens, lexer, lexer tests | all lexer tests pass (**done**, 76 tests) |
| 2  | AST nodes, recursive descent parser, JSON AST, syntax errors with caret display | parser tests pass (**done**, 68 tests) |
| 3  | Symbol table, semantic analyzer | undefined/duplicate vars, type, arity, return, break/continue checks (**done**, 75 tests) |
| 4  | Interpreter + environment | factorial(5) prints 120, runtime errors reported (**done**, 77 tests) |
| 5  | TAC generation | arithmetic, assignment, if/while/for, calls, returns, arrays (**done**, 135 tests + 8 example tests) |
| 6  | Basic blocks + CFG | leaders computed per standard rules; JSON graph (**done**, 60 tests) |
| 7  | Optimizer | constant folding/propagation, algebraic simplification, dead code; results verified safe (**done**, 144 tests) |
| 8  | FastAPI backend | all endpoints delegate to one orchestrator, `compiler/pipeline.py` (**done**, 67 tests) |
| 9  | React frontend | editor, run/analyze, output panel, tabs (**done**; found already present, see note below) |
| 10 | Visualization | AST diagram, CFG diagram (zoom/pan/highlight/click-to-source), TAC jump highlighting (**done**, 69 new frontend tests) |
| 11 | Integration tests, README, examples, demo | factorial demo shows all 10 pipeline stages, output 120 (**done**: 107 integration tests, CLI, README, demo script) |

Rule: do not start phase N+1 until phase N's tests pass, and re-run the whole suite after
every phase.

## API (Phase 8)

Run: `uvicorn backend.main:app --reload` (interactive docs at `/docs`).

| Method & path | Returns |
|---|---|
| `POST /api/lex` `parse` `analyze` `tac` `cfg` `optimize` | pipeline stages up to that point |
| `POST /api/run` | the execution stage only |
| `POST /api/compile` | all 10 stages in one response |
| `GET /api/examples`, `/api/examples/{name}` | bundled demo programs |
| `GET /api/stages`, `/api/health` | stage list, liveness |

Body: `{"source": "..."}`. Compile errors are HTTP 200 with `ok: false` and a
`failed_stage`; HTTP 422 is only for malformed requests (wrong type, source over 100,000 characters).
Each stage is `{id, name, status (ok|warning|error|skipped), summary, data, errors, warnings}`.
`execution.data.verified` is true when the optimized TAC prints exactly what the interpreter prints.

## Frontend (Phases 9 and 10)

Run (two terminals):

    uvicorn backend.main:app --port 8000
    cd frontend && npm install && npm run dev        # http://localhost:5173

Tests and build: `cd frontend && npm test && npm run build` (124 tests).

* **Layout code is separate from drawing code.** `src/lib/graphLayout.js` (tree and layered CFG layout)
  and `src/lib/viewport.js` (pan / zoom math) are pure functions with their own unit tests; the
  components only draw what they return.
* **AST diagram:** each node is centered over its first and last child. Click selects a node,
  highlights its path to the root, and jumps the editor to its source. The round buttons collapse subtrees.
* **CFG diagram (layered layout):** loops are found as back edges and drawn dashed down the right side, leaving
  the bottom of a block and re-entering the top of the loop header. An edge that skips rows gets a
  thin lane in each row it crosses, so no edge is ever drawn through a block.
* **TAC:** selecting a jump highlights the label it targets; selecting a label highlights every jump to it.
* **Known limitation:** the two outcomes of a condition can cross each other when their target blocks
  land in the opposite order (no crossing-minimization beyond one sweep per direction).
* **Phase 9 note:** the Phase 9 app (editor, stage rail, tabs, 55 tests) was already in `frontend/` when
  Phase 10 started. Three of its config files were accidentally overwritten and rebuilt from the
  built `dist/` and the app's imports; see the project notes.

## Safety limits (found by the Phase 11 stress tests)

Python's recursion limit used to turn a pathological program (about 150 nested parentheses) into a crash,
which the API would have reported as an HTTP 500. The parser now refuses such input with an ordinary syntax
error: at most 40 levels of nesting (parentheses, blocks, array literals, call arguments) and a finished syntax
tree at most 100 levels deep, which also bounds long chains like `1 + 1 + 1 + ...`. `tests/test_integration.py`
pushes twelve different deep shapes through the whole stack, just under and well over the limit.
