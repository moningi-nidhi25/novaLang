"""Hand-written lexer (scanner) for NovaLang.

Compiler concept: *lexical analysis* is the first phase. It reads the raw
characters of the source and groups them into tokens, discarding whitespace
and comments. Each token remembers where it came from (line and column) so
that every later phase can point at the exact place of an error.

Design notes for students
-------------------------
* The lexer is a simple hand-coded finite automaton: look at the current
  character, decide which kind of token starts here, then consume characters
  until that token is complete ("maximal munch" -- always take the longest
  possible match, so `<=` is one token, not `<` followed by `=`).
* The lexer does NOT stop at the first problem. It records a LexicalError,
  skips the bad character(s), and keeps going so that one run reports every
  lexical mistake (this is called *error recovery*).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from compiler.errors.errors import LexicalError
from compiler.lexer.tokens import (
    KEYWORDS,
    SINGLE_CHAR_TOKENS,
    TWO_CHAR_OPERATORS,
    Token,
    TokenType,
)

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "0": "\0"}


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_alpha(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


def _is_alnum(ch: str) -> bool:
    return _is_alpha(ch) or _is_digit(ch)


class Lexer:
    """Converts NovaLang source text into a list of tokens."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._reset()

    def _reset(self) -> None:
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []
        self.errors: List[LexicalError] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def tokenize(self) -> List[Token]:
        """Scan the whole source. Tokens are returned (always ending with EOF);
        any lexical errors are collected in ``self.errors``."""
        self._reset()
        while not self._at_end():
            self._scan_token()
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return self.tokens

    # ------------------------------------------------------------------
    # Character helpers
    # ------------------------------------------------------------------
    def _at_end(self) -> bool:
        return self.pos >= len(self.source)

    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.source[i] if i < len(self.source) else "\0"

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _error(self, message: str, line: int, column: int, hint: str | None = None) -> None:
        self.errors.append(LexicalError(message, line, column, hint))

    def _emit(self, type_: TokenType, start: int, line: int, column: int, value=None) -> None:
        self.tokens.append(Token(type_, self.source[start:self.pos], line, column, value))

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------
    def _scan_token(self) -> None:
        ch = self._peek()

        if ch in " \t\r\n":
            self._advance()
            return

        if ch == "/" and self._peek(1) == "/":
            self._line_comment()
            return
        if ch == "/" and self._peek(1) == "*":
            self._block_comment()
            return

        if _is_digit(ch):
            self._number()
            return
        if _is_alpha(ch):
            self._identifier()
            return
        if ch == '"':
            self._string()
            return

        start, line, column = self.pos, self.line, self.column

        # Two-character operators first (maximal munch).
        two = ch + self._peek(1)
        if two in TWO_CHAR_OPERATORS:
            self._advance()
            self._advance()
            self._emit(TWO_CHAR_OPERATORS[two], start, line, column)
            return

        if ch in SINGLE_CHAR_TOKENS:
            self._advance()
            self._emit(SINGLE_CHAR_TOKENS[ch], start, line, column)
            return

        # Anything else is an error. Give a targeted hint for common slips.
        self._advance()
        if ch == "&":
            self._error(
                "Unexpected character '&' (NovaLang has no bitwise operators).",
                line, column,
                "Logical AND is written '&&' with two ampersands.",
            )
        elif ch == "|":
            self._error(
                "Unexpected character '|' (NovaLang has no bitwise operators).",
                line, column,
                "Logical OR is written '||' with two vertical bars.",
            )
        elif ch == "'":
            self._error(
                "Unexpected character ''' (single quote).",
                line, column,
                "Strings in NovaLang use double quotes, like \"hello\".",
            )
        else:
            self._error(
                f"Unexpected character '{ch}' at line {line}, column {column}.",
                line, column,
                f"'{ch}' does not belong to the NovaLang alphabet, so no token can "
                "start with it. Remove it or replace it with a valid symbol.",
            )

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    def _line_comment(self) -> None:
        while not self._at_end() and self._peek() != "\n":
            self._advance()

    def _block_comment(self) -> None:
        line, column = self.line, self.column
        self._advance()  # '/'
        self._advance()  # '*'
        while not self._at_end():
            if self._peek() == "*" and self._peek(1) == "/":
                self._advance()
                self._advance()
                return
            self._advance()
        self._error(
            "Unterminated block comment.",
            line, column,
            "A comment opened with '/*' must be closed with '*/'.",
        )

    # ------------------------------------------------------------------
    # Numbers, identifiers, strings
    # ------------------------------------------------------------------
    def _number(self) -> None:
        start, line, column = self.pos, self.line, self.column
        while _is_digit(self._peek()):
            self._advance()

        is_float = False
        # A '.' only belongs to the number if a digit follows ("3.14", not "3.").
        if self._peek() == "." and _is_digit(self._peek(1)):
            is_float = True
            self._advance()
            while _is_digit(self._peek()):
                self._advance()

        # Something like "12abc": a number glued to letters.
        if _is_alpha(self._peek()):
            while _is_alnum(self._peek()):
                self._advance()
            bad = self.source[start:self.pos]
            self._error(
                f"Invalid number literal '{bad}'.",
                line, column,
                "A number cannot be immediately followed by letters, and "
                "identifiers cannot start with a digit.",
            )
            return

        text = self.source[start:self.pos]
        if is_float:
            self._emit(TokenType.FLOAT, start, line, column, float(text))
        else:
            self._emit(TokenType.INTEGER, start, line, column, int(text))

    def _identifier(self) -> None:
        start, line, column = self.pos, self.line, self.column
        while _is_alnum(self._peek()):
            self._advance()
        text = self.source[start:self.pos]
        type_ = KEYWORDS.get(text, TokenType.IDENTIFIER)
        value = {TokenType.TRUE: True, TokenType.FALSE: False}.get(type_)
        self._emit(type_, start, line, column, value)

    def _string(self) -> None:
        start, line, column = self.pos, self.line, self.column
        self._advance()  # opening quote
        chars: List[str] = []
        ok = True

        while True:
            if self._at_end() or self._peek() == "\n":
                self._error(
                    "Unterminated string literal.",
                    line, column,
                    "A string must be closed with a matching '\"' on the same line.",
                )
                return
            ch = self._peek()
            if ch == '"':
                self._advance()
                break
            if ch == "\\":
                esc_line, esc_col = self.line, self.column
                self._advance()
                if self._at_end() or self._peek() == "\n":
                    continue  # reported as unterminated on the next loop turn
                code = self._advance()
                if code in ESCAPES:
                    chars.append(ESCAPES[code])
                else:
                    ok = False
                    self._error(
                        f"Invalid escape sequence '\\{code}'.",
                        esc_line, esc_col,
                        "Supported escapes are \\n, \\t, \\r, \\\\, \\\" and \\0.",
                    )
                continue
            chars.append(self._advance())

        if ok:
            self._emit(TokenType.STRING, start, line, column, "".join(chars))


# ----------------------------------------------------------------------
# Convenience wrapper used by the API and other phases
# ----------------------------------------------------------------------
@dataclass
class LexResult:
    tokens: List[Token] = field(default_factory=list)
    errors: List[LexicalError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "tokens": [t.to_dict() for t in self.tokens],
            "errors": [e.to_dict() for e in self.errors],
        }


def lex(source: str) -> LexResult:
    """Tokenize *source* and return tokens plus any lexical errors."""
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    return LexResult(tokens, lexer.errors)
