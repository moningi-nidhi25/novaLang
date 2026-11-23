"""NovaLang web API.   Run:  uvicorn backend.main:app --reload   (docs at /docs)"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import compile as compile_routes
from backend.routes import examples as example_routes
from compiler.pipeline import STAGES

app = FastAPI(
    title="NovaLang Compiler API",
    description="Makes every compiler stage visible: tokens, AST, semantic analysis, "
                "TAC, CFG, optimization and execution.",
    version="1.0.0",
)

# The Vite dev server (React frontend) runs on another port, so allow it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(compile_routes.router)
app.include_router(example_routes.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stages", tags=["meta"])
def stages() -> dict:
    """The ordered pipeline stages (id + display name)."""
    return {"stages": [{"id": i, "name": n} for i, n in STAGES]}
