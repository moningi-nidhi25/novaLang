"""Token definitions for NovaLang.

A *token* is the smallest meaningful unit of source code. The lexer's job is
to turn a stream of characters into a stream of tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TokenType(Enum):
    # Literals
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    IDENTIFIER = "IDENTIFIER"

    # Keywords
    LET = "LET"
    FUNCTION = "FUNCTION"
    RETURN = "RETURN"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    FOR = "FOR"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    PRINT = "PRINT"
    TRUE = "TRUE"
    FALSE = "FALSE"
    NIL = "NIL"

    # Arithmetic operators
    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    PERCENT = "PERCENT"

    # Comparison operators
    EQ = "EQ"        # ==
    NEQ = "NEQ"      # !=
    LT = "LT"        # <
    GT = "GT"        # >
    LTE = "LTE"      # <=
    GTE = "GTE"      # >=

    # Logical operators
    AND = "AND"      # &&
    OR = "OR"        # ||
    NOT = "NOT"      # !

    # Assignment
    ASSIGN = "ASSIGN"  # =

    # Punctuation
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    COMMA = "COMMA"
    SEMICOLON = "SEMICOLON"
    QUESTION = "QUESTION"  # ? (ternary conditional operator)
    COLON = "COLON"        # : (ternary conditional separator)

    # End of input
    EOF = "EOF"


# Reserved words. An identifier whose text is in this table becomes a keyword token.
KEYWORDS = {
    "let": TokenType.LET,
    "function": TokenType.FUNCTION,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "print": TokenType.PRINT,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "nil": TokenType.NIL,
}

# Operators made of two characters (checked before single-character ones).
TWO_CHAR_OPERATORS = {
    "==": TokenType.EQ,
    "!=": TokenType.NEQ,
    "<=": TokenType.LTE,
    ">=": TokenType.GTE,
    "&&": TokenType.AND,
    "||": TokenType.OR,
}

SINGLE_CHAR_TOKENS = {
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.STAR,
    "/": TokenType.SLASH,
    "%": TokenType.PERCENT,
    "<": TokenType.LT,
    ">": TokenType.GT,
    "!": TokenType.NOT,
    "=": TokenType.ASSIGN,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
    "[": TokenType.LBRACKET,
    "]": TokenType.RBRACKET,
    ",": TokenType.COMMA,
    ";": TokenType.SEMICOLON,
    "?": TokenType.QUESTION,
    ":": TokenType.COLON,
}


@dataclass(frozen=True)
class Token:
    """One lexical unit.

    type    -- the category (TokenType)
    lexeme  -- the exact source text that produced the token
    value   -- the interpreted value (int for INTEGER, str without quotes or
               with escapes processed for STRING, True/False/None for
               TRUE/FALSE/NIL); None for everything else
    line    -- 1-based line number where the token starts
    column  -- 1-based column number where the token starts
    """

    type: TokenType
    lexeme: str
    line: int
    column: int
    value: Any = None

    def __str__(self) -> str:
        if self.type in (TokenType.IDENTIFIER, TokenType.INTEGER, TokenType.FLOAT):
            return f"{self.type.value}({self.lexeme})"
        if self.type is TokenType.STRING:
            return f"STRING({self.value!r})"
        return self.type.value

    def to_dict(self) -> dict:
        """JSON-friendly form used by the API / token table in the UI."""
        return {
            "type": self.type.value,
            "lexeme": self.lexeme,
            "value": self.value,
            "line": self.line,
            "column": self.column,
        }
