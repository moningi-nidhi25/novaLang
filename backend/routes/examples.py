"""Serve the bundled example programs so the frontend can offer a dropdown."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

router = APIRouter(prefix="/api/examples", tags=["examples"])


def _names() -> list:
    return sorted(p.stem for p in EXAMPLES_DIR.glob("*.nova"))


@router.get("")
def list_examples() -> dict:
    return {"examples": _names()}


@router.get("/{name}")
def get_example(name: str) -> dict:
    # Only names from our own directory listing are accepted: no path tricks.
    if name not in _names():
        raise HTTPException(status_code=404, detail=f"no example named {name!r}")
    return {"name": name, "source": (EXAMPLES_DIR / f"{name}.nova").read_text(encoding="utf-8")}
