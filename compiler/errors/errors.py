"""Error types shared by every compiler phase.

Every error carries a *phase* name, a message, and a source position, so the
frontend can show educational messages such as:

    Lexical Error: Unexpected character '$' at line 2, column 5.

      2 | let $x = 5;
        |     ^
"""

from __future__ import annotations

from typing import Optional


class NovaLangError(Exception):
    """Base class for all NovaLang compile-time and run-time errors."""

    phase = "Error"

    def __init__(
        self,
        message: str,
        line: int = 0,
        column: int = 0,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.hint = hint

    # -- presentation -------------------------------------------------------
    def format(self, source: Optional[str] = None) -> str:
        """Return a multi-line, human-friendly description of the error.

        If *source* is given, the offending line is printed with a caret
        pointing at the exact column.
        """
        out = [f"{self.phase}: {self.message}"]
        if source is not None and self.line >= 1:
            lines = source.splitlines()
            if self.line <= len(lines):
                text = lines[self.line - 1]
                gutter = f"{self.line} | "
                pad = " " * (len(str(self.line)) + 3)
                caret_pos = max(self.column - 1, 0)
                out.append("")
                out.append(f"  {gutter}{text}")
                out.append(f"  {pad}{' ' * caret_pos}^")
        if self.hint:
            out.append("")
            out.append(f"Why: {self.hint}")
        return "\n".join(out)

    def to_dict(self) -> dict:
        """JSON-friendly form used by the API."""
        return {
            "phase": self.phase,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "hint": self.hint,
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.phase}: {self.message} (line {self.line}, column {self.column})"


class LexicalError(NovaLangError):
    phase = "Lexical Error"


class SyntaxError_(NovaLangError):
    """Parser error (named with a trailing underscore to avoid shadowing the builtin)."""

    phase = "Syntax Error"


class SemanticError(NovaLangError):
    phase = "Semantic Error"


class SemanticWarning(NovaLangError):
    """Not an error: the program is still valid, but something looks suspicious."""

    phase = "Semantic Warning"


class NovaRuntimeError(NovaLangError):
    phase = "Runtime Error"
