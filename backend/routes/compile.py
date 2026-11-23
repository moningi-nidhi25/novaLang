"""Compiler endpoints.

Every endpoint is a thin wrapper: it calls ``run_pipeline`` with the stage it
wants to stop at, and returns the stages up to there. There is deliberately no
compiler logic in this file -- see compiler/pipeline.py.

A program with compile errors is NOT an HTTP error: the request was valid and
the answer is "your program has a problem", returned as ``ok: false`` with
structured errors (200). HTTP 4xx is reserved for malformed requests.

Why the responses are built as JSONResponse and not returned as plain dicts: FastAPI would
push a returned dict through pydantic, whose serializer refuses structures nested more than a
fixed number of levels (about 100 on some platforms, e.g. Windows) with "Circular reference
detected (depth exceeded)". The syntax tree of a perfectly legal program (30+ nested ifs, a long
chain like a[0][0][0]...) is nested deeper than that, so the API would answer HTTP 500. Python's own
JSON encoder has no such limit (the parser caps nesting far below Python's recursion limit).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.schemas import SourceRequest
from compiler.pipeline import STAGE_IDS, UPTO, run_pipeline

router = APIRouter(prefix="/api", tags=["compiler"])


def _respond(source: str, endpoint: str, only=None) -> JSONResponse:
    upto = UPTO[endpoint]
    result = run_pipeline(source, upto=upto)
    shown = only or STAGE_IDS[: STAGE_IDS.index(upto) + 1]
    return JSONResponse(result.to_dict(only=shown))


@router.post("/lex")
def lex_endpoint(req: SourceRequest) -> JSONResponse:
    """Source -> tokens."""
    return _respond(req.source, "lex")


@router.post("/parse")
def parse_endpoint(req: SourceRequest) -> JSONResponse:
    """Source -> tokens -> AST."""
    return _respond(req.source, "parse")


@router.post("/analyze")
def analyze_endpoint(req: SourceRequest) -> JSONResponse:
    """... -> semantic analysis and the symbol table."""
    return _respond(req.source, "analyze")


@router.post("/tac")
def tac_endpoint(req: SourceRequest) -> JSONResponse:
    """... -> Three Address Code."""
    return _respond(req.source, "tac")


@router.post("/cfg")
def cfg_endpoint(req: SourceRequest) -> JSONResponse:
    """... -> basic blocks and control-flow graphs."""
    return _respond(req.source, "cfg")


@router.post("/optimize")
def optimize_endpoint(req: SourceRequest) -> JSONResponse:
    """... -> optimized TAC and optimized CFG, with the change log."""
    return _respond(req.source, "optimize")


@router.post("/run")
def run_endpoint(req: SourceRequest) -> JSONResponse:
    """Run the program. Returns only the execution stage (plus diagnostics)."""
    return _respond(req.source, "run", only=["execution"])


@router.post("/compile")
def compile_endpoint(req: SourceRequest) -> JSONResponse:
    """Everything: all ten stages in one response (powers the frontend)."""
    return _respond(req.source, "compile")
