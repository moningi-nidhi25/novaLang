"""Recursive descent parser for NovaLang.

Compiler concept: *syntax analysis*. The parser checks that the token stream
follows the grammar (docs/01_language_spec.md) and builds the AST.

Recursive descent means: one method per grammar rule, and the methods call
each other the same way the rules refer to each other. Operator precedence is
encoded by the call chain

    expression -> logic_or -> logic_and -> equality -> comparison
               -> term -> factor -> unary -> postfix -> primary

Rules lower in the chain bind tighter. That is why `2 + 3 * 4` parses as
`2 + (3 * 4)`: `term` asks `factor` for its operands, so `3 * 4` is grouped
before `term` sees the `+`.

Error handling: when the parser finds a syntax error it records it, then
*synchronizes* ("panic mode"): it skips tokens until a likely statement
boundary and continues, so one run can report several independent errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from compiler.errors.errors import NovaLangError, SyntaxError_
from compiler.lexer.lexer import Lexer
from compiler.lexer.tokens import Token, TokenType as T
from compiler.parser import ast as A


class _NestingTooDeep(Exception):
    """Stops the whole parse at once (carries the SyntaxError_ to report)."""

    def __init__(self, error: SyntaxError_) -> None:
        super().__init__(error.message)
        self.error = error

# Limits that keep the later, recursive stages (semantic analysis, interpreter, TAC generation, JSON
# output) safely inside Python's recursion limit. Real programs never come close: they exist so
# a pathological input becomes a clear error instead of a crash (and an HTTP 500 in the API).
MAX_NESTING = 40      # levels of parentheses / brackets / call arguments / blocks inside each other
MAX_AST_DEPTH = 100   # depth of the finished tree; also catches long chains like 1 + 1 + 1 + ...

# Tokens at which a new statement can begin; used to resynchronize after errors.
STATEMENT_START = {
    T.LET, T.FUNCTION, T.IF, T.WHILE, T.FOR,
    T.RETURN, T.PRINT, T.BREAK, T.CONTINUE,
}


class Parser:
    def __init__(self, tokens: List[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.errors: List[SyntaxError_] = []
        self._depth = 0

    # ==================================================================
    # Public API
    # ==================================================================
    def parse(self) -> A.Program:
        first = self.tokens[0]
        program = A.Program(line=first.line, column=first.column)
        try:
            while not self._at_end():
                node = self._declaration(top_level=True)
                if node is not None:
                    program.body.append(node)
        except _NestingTooDeep as stop:
            self.errors.append(stop.error)       # give up: parsing deeper would only repeat the problem
        except RecursionError:
            # Safety net for recursion that does not pass through _enter (a very long `- - - ... 1`
            # or `else if` ladder): the same clear error instead of a crash.
            self.errors.append(self._error_at(
                self._peek(),
                f"This code is nested too deeply (more than {MAX_AST_DEPTH} levels).",
                "Break the expression into smaller statements, or move inner blocks into functions.",
                found=False,
            ))
        return program

    def _enter(self) -> None:
        """Count one more level of nesting; refuse to go past MAX_NESTING."""
        self._depth += 1
        if self._depth > MAX_NESTING:
            raise _NestingTooDeep(self._error_at(
                self._peek(),
                f"This code is nested too deeply (more than {MAX_NESTING} levels).",
                "Break the expression into smaller statements, or move inner blocks into functions.",
                found=False,
            ))

    # ==================================================================
    # Token helpers
    # ==================================================================
    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _previous(self) -> Token:
        return self.tokens[self.pos - 1]

    def _at_end(self) -> bool:
        return self._peek().type is T.EOF

    def _check(self, *types: T) -> bool:
        return self._peek().type in types

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type is not T.EOF:
            self.pos += 1
        return tok

    def _match(self, *types: T) -> bool:
        if self._check(*types):
            self._advance()
            return True
        return False

    @staticmethod
    def _describe(tok: Token) -> str:
        return "end of file" if tok.type is T.EOF else f"'{tok.lexeme}'"

    def _error_at(self, tok: Token, message: str, hint: str, *, found: bool = True) -> SyntaxError_:
        if found:
            hint = f"{hint} Found {self._describe(tok)} instead."
        return SyntaxError_(message, tok.line, tok.column, hint)

    def _consume(self, type_: T, message: str, hint: str, *, after_previous: bool = False) -> Token:
        """Require the next token to be *type_*, or raise a SyntaxError_.

        With ``after_previous`` the error points just past the previous token,
        which is where a missing ';' or ')' should have been written (this
        gives a much better caret than pointing at the *next* line).
        """
        if self._check(type_):
            return self._advance()
        tok = self._peek()
        if after_previous and self.pos > 0:
            prev = self._previous()
            err = SyntaxError_(
                message, prev.line, prev.column + len(prev.lexeme),
                f"{hint} Found {self._describe(tok)} instead.",
            )
            raise err
        raise self._error_at(tok, message, hint)

    # ==================================================================
    # Error recovery
    # ==================================================================
    def _synchronize(self) -> None:
        """Skip tokens until a probable statement boundary (panic mode)."""
        while not self._at_end():
            if self.pos > 0 and self._previous().type is T.SEMICOLON:
                return
            if self._peek().type is T.LBRACE:
                # Skip a whole `{ ... }` body as one unit. Stopping inside it
                # would leave its closing '}' looking like a stray token and
                # produce a misleading follow-up error.
                depth = 0
                while not self._at_end():
                    kind = self._advance().type
                    if kind is T.LBRACE:
                        depth += 1
                    elif kind is T.RBRACE:
                        depth -= 1
                        if depth == 0:
                            break
                return
            if self._peek().type in STATEMENT_START or self._peek().type is T.RBRACE:
                return
            self._advance()

    # ==================================================================
    # Declarations and statements
    # ==================================================================
    def _declaration(self, top_level: bool = False) -> Optional[A.Node]:
        start = self.pos
        try:
            if self._check(T.FUNCTION):
                if not top_level:
                    # Record the problem, then still parse the function so its
                    # tokens are consumed and we don't report a cascade of errors.
                    self.errors.append(self._error_at(
                        self._peek(),
                        "Functions can only be declared at the top level.",
                        "NovaLang has no nested functions; move this function outside "
                        "of any block.",
                        found=False,
                    ))
                    self._function_declaration()
                    return None
                return self._function_declaration()
            return self._statement()
        except SyntaxError_ as err:
            self.errors.append(err)
            self._synchronize()
            if self.pos == start:      # guarantee progress, never loop forever
                self._advance()
            return None

    def _function_declaration(self) -> A.FunctionDeclaration:
        kw = self._advance()  # 'function'
        name = self._consume(
            T.IDENTIFIER, "Expected function name after 'function'.",
            "A function declaration looks like: function name(a, b) { ... }.",
        )
        self._consume(
            T.LPAREN, "Expected '(' after function name.",
            "The parameter list must be enclosed in parentheses.",
        )
        params: List[str] = []
        if not self._check(T.RPAREN):
            while True:
                p = self._consume(
                    T.IDENTIFIER, "Expected parameter name.",
                    "Parameters are plain names separated by commas.",
                )
                params.append(p.lexeme)
                if not self._match(T.COMMA):
                    break
        self._consume(
            T.RPAREN, "Expected ')' after parameters.",
            "Close the parameter list with ')'.", after_previous=True,
        )
        body = self._block("function body")
        return A.FunctionDeclaration(
            name=name.lexeme, params=params, body=body, line=kw.line, column=kw.column
        )

    def _block(self, what: str) -> A.Block:
        lbrace = self._consume(
            T.LBRACE, f"Expected '{{' before {what}.",
            "NovaLang requires braces around every body, even a single statement.",
        )
        block = A.Block(line=lbrace.line, column=lbrace.column)
        self._enter()
        try:
            while not self._check(T.RBRACE) and not self._at_end():
                node = self._declaration(top_level=False)
                if node is not None:
                    block.statements.append(node)
        finally:
            self._depth -= 1
        if not self._check(T.RBRACE):
            raise self._error_at(
                self._peek(),
                "Expected '}' to close the block.",
                f"The block opened at line {lbrace.line}, column {lbrace.column} "
                "is never closed.",
            )
        self._advance()
        return block

    def _statement(self) -> A.Node:
        tok = self._peek()
        if tok.type is T.LET:
            return self._let_declaration()
        if tok.type is T.IF:
            return self._if_statement()
        if tok.type is T.WHILE:
            return self._while_statement()
        if tok.type is T.FOR:
            return self._for_statement()
        if tok.type is T.RETURN:
            return self._return_statement()
        if tok.type is T.BREAK:
            self._advance()
            self._consume(T.SEMICOLON, "Expected ';' after 'break'.",
                          "Every statement ends with ';'.", after_previous=True)
            return A.BreakStatement(line=tok.line, column=tok.column)
        if tok.type is T.CONTINUE:
            self._advance()
            self._consume(T.SEMICOLON, "Expected ';' after 'continue'.",
                          "Every statement ends with ';'.", after_previous=True)
            return A.ContinueStatement(line=tok.line, column=tok.column)
        if tok.type is T.PRINT:
            return self._print_statement()
        if tok.type is T.LBRACE:
            return self._block("block")
        return self._assignment_or_expression_statement()

    def _let_declaration(self, *, expect_semicolon: bool = True) -> A.VariableDeclaration:
        kw = self._advance()  # 'let'
        name = self._consume(
            T.IDENTIFIER, "Expected variable name after 'let'.",
            "A declaration looks like: let name = value;",
        )
        self._consume(
            T.ASSIGN, "Expected '=' after variable name.",
            "Every variable needs an initial value: let name = value;",
            after_previous=True,
        )
        init = self._expression()
        if expect_semicolon:
            self._consume(
                T.SEMICOLON, "Expected ';' after variable declaration.",
                "Every statement ends with ';'.", after_previous=True,
            )
        return A.VariableDeclaration(
            name=name.lexeme, initializer=init, line=kw.line, column=kw.column
        )

    def _if_statement(self) -> A.IfStatement:
        kw = self._advance()  # 'if'
        self._consume(T.LPAREN, "Expected '(' after 'if'.",
                      "The condition must be enclosed in parentheses: if (condition) { ... }")
        cond = self._expression()
        self._consume(T.RPAREN, "Expected ')' after condition.",
                      "The condition of an if-statement must be closed with ')'.",
                      after_previous=True)
        then_branch = self._block("if body")
        else_branch: Optional[A.Node] = None
        if self._match(T.ELSE):
            if self._check(T.IF):
                else_branch = self._if_statement()
            else:
                else_branch = self._block("else body")
        return A.IfStatement(
            condition=cond, then_branch=then_branch, else_branch=else_branch,
            line=kw.line, column=kw.column,
        )

    def _while_statement(self) -> A.WhileStatement:
        kw = self._advance()  # 'while'
        self._consume(T.LPAREN, "Expected '(' after 'while'.",
                      "The condition must be enclosed in parentheses: while (condition) { ... }")
        cond = self._expression()
        self._consume(T.RPAREN, "Expected ')' after condition.",
                      "The condition of a while-loop must be closed with ')'.",
                      after_previous=True)
        body = self._block("while body")
        return A.WhileStatement(condition=cond, body=body, line=kw.line, column=kw.column)

    def _for_statement(self) -> A.ForStatement:
        kw = self._advance()  # 'for'
        self._consume(T.LPAREN, "Expected '(' after 'for'.",
                      "A for-loop looks like: for (let i = 0; i < n; i = i + 1) { ... }")
        if self._check(T.LET):
            init: A.Node = self._let_declaration(expect_semicolon=False)
        else:
            init = self._assignment_core()
        self._consume(T.SEMICOLON, "Expected ';' after for-loop initializer.",
                      "The three parts of a for-loop are separated by ';'.",
                      after_previous=True)
        cond = self._expression()
        self._consume(T.SEMICOLON, "Expected ';' after for-loop condition.",
                      "The three parts of a for-loop are separated by ';'.",
                      after_previous=True)
        update = self._assignment_core()
        self._consume(T.RPAREN, "Expected ')' after for-loop clauses.",
                      "Close the for-loop header with ')'.", after_previous=True)
        body = self._block("for body")
        return A.ForStatement(
            init=init, condition=cond, update=update, body=body,
            line=kw.line, column=kw.column,
        )

    def _return_statement(self) -> A.ReturnStatement:
        kw = self._advance()  # 'return'
        value = None
        if not self._check(T.SEMICOLON):
            value = self._expression()
        self._consume(T.SEMICOLON, "Expected ';' after return value.",
                      "Every statement ends with ';'.", after_previous=True)
        return A.ReturnStatement(value=value, line=kw.line, column=kw.column)

    def _print_statement(self) -> A.PrintStatement:
        kw = self._advance()  # 'print'
        self._consume(T.LPAREN, "Expected '(' after 'print'.",
                      "print takes its argument in parentheses: print(value);")
        value = self._expression()
        self._consume(T.RPAREN, "Expected ')' after print argument.",
                      "Close the argument list with ')'.", after_previous=True)
        self._consume(T.SEMICOLON, "Expected ';' after print statement.",
                      "Every statement ends with ';'.", after_previous=True)
        return A.PrintStatement(expression=value, line=kw.line, column=kw.column)

    def _assignment_core(self) -> A.Assignment:
        """target '=' expression   (no semicolon; used by statements and `for`)."""
        target = self._expression()
        eq = self._consume(
            T.ASSIGN, "Expected '=' in assignment.",
            "An assignment looks like: name = value;", after_previous=True,
        )
        if not isinstance(target, (A.Identifier, A.IndexExpression)):
            raise SyntaxError_(
                "Invalid assignment target.", target.line, target.column,
                "You can only assign to a variable (x = 1) or an array element (a[0] = 1).",
            )
        value = self._expression()
        return A.Assignment(target=target, value=value, line=eq.line, column=eq.column)

    def _assignment_or_expression_statement(self) -> A.Node:
        start_tok = self._peek()
        expr = self._expression()
        if self._check(T.ASSIGN):
            eq = self._advance()
            if not isinstance(expr, (A.Identifier, A.IndexExpression)):
                raise SyntaxError_(
                    "Invalid assignment target.", expr.line, expr.column,
                    "You can only assign to a variable (x = 1) or an array element (a[0] = 1).",
                )
            value = self._expression()
            self._consume(T.SEMICOLON, "Expected ';' after assignment.",
                          "Every statement ends with ';'.", after_previous=True)
            return A.Assignment(target=expr, value=value, line=eq.line, column=eq.column)
        self._consume(T.SEMICOLON, "Expected ';' after expression.",
                      "Every statement ends with ';'.", after_previous=True)
        return A.ExpressionStatement(
            expression=expr, line=start_tok.line, column=start_tok.column
        )

    # ==================================================================
    # Expressions (one method per precedence level, lowest first)
    # ==================================================================
    def _expression(self) -> A.Node:
        self._enter()
        try:
            return self._ternary()
        finally:
            self._depth -= 1

    def _ternary(self) -> A.Node:
        condition = self._logic_or()

        if self._match(T.QUESTION):
            question = self._previous()
            true_expr = self._expression()

            self._consume(
                T.COLON,
                "Expected ':' between the two ternary alternatives.",
                "Write condition ? value_if_true : value_if_false.",
                after_previous=True,
            )

            false_expr = self._ternary()

            return A.TernaryExpression(
                condition=condition,
                true_expr=true_expr,
                false_expr=false_expr,
                line=question.line,
                column=question.column,
            )

        return condition
        
    def _binary_level(self, next_level, *op_types: T) -> A.Node:
        """Shared loop for the left-associative binary levels."""
        left = next_level()
        while self._check(*op_types):
            op = self._advance()
            right = next_level()
            left = A.BinaryExpression(
                operator=op.lexeme, left=left, right=right,
                line=op.line, column=op.column,
            )
        return left

    def _logic_or(self) -> A.Node:
        return self._binary_level(self._logic_and, T.OR)

    def _logic_and(self) -> A.Node:
        return self._binary_level(self._equality, T.AND)

    def _equality(self) -> A.Node:
        return self._binary_level(self._comparison, T.EQ, T.NEQ)

    def _comparison(self) -> A.Node:
        return self._binary_level(self._term, T.LT, T.GT, T.LTE, T.GTE)

    def _term(self) -> A.Node:
        return self._binary_level(self._factor, T.PLUS, T.MINUS)

    def _factor(self) -> A.Node:
        return self._binary_level(self._unary, T.STAR, T.SLASH, T.PERCENT)

    def _unary(self) -> A.Node:
        if self._check(T.NOT, T.MINUS):
            op = self._advance()
            operand = self._unary()          # right-associative: --x, !!x
            return A.UnaryExpression(
                operator=op.lexeme, operand=operand, line=op.line, column=op.column
            )
        return self._postfix()

    def _postfix(self) -> A.Node:
        expr = self._primary()
        while True:
            if self._check(T.LPAREN):
                self._advance()
                args: List[A.Node] = []
                if not self._check(T.RPAREN):
                    args.append(self._expression())
                    while self._match(T.COMMA):
                        args.append(self._expression())
                self._consume(T.RPAREN, "Expected ')' after arguments.",
                              "Close the argument list with ')'.", after_previous=True)
                expr = A.FunctionCall(
                    callee=expr, arguments=args, line=expr.line, column=expr.column
                )
            elif self._check(T.LBRACKET):
                self._advance()
                index = self._expression()
                self._consume(T.RBRACKET, "Expected ']' after index.",
                              "Close the index with ']'.", after_previous=True)
                expr = A.IndexExpression(
                    object=expr, index=index, line=expr.line, column=expr.column
                )
            else:
                return expr

    def _primary(self) -> A.Node:
        tok = self._peek()
        t = tok.type
        if t is T.INTEGER:
            self._advance()
            return A.Literal(value=tok.value, literal_type="int", line=tok.line, column=tok.column)
        if t is T.FLOAT:
            self._advance()
            return A.Literal(value=tok.value, literal_type="float", line=tok.line, column=tok.column)
        if t is T.STRING:
            self._advance()
            return A.Literal(value=tok.value, literal_type="string", line=tok.line, column=tok.column)
        if t in (T.TRUE, T.FALSE):
            self._advance()
            return A.Literal(value=(t is T.TRUE), literal_type="bool", line=tok.line, column=tok.column)
        if t is T.NIL:
            self._advance()
            return A.Literal(value=None, literal_type="nil", line=tok.line, column=tok.column)
        if t is T.IDENTIFIER:
            self._advance()
            return A.Identifier(name=tok.lexeme, line=tok.line, column=tok.column)
        if t is T.LPAREN:
            self._advance()
            inner = self._expression()
            self._consume(T.RPAREN, "Expected ')' after expression.",
                          "Every '(' needs a matching ')'.", after_previous=True)
            return inner                       # grouping leaves no node: the tree shape says it all
        if t is T.LBRACKET:
            self._advance()
            elements: List[A.Node] = []
            if not self._check(T.RBRACKET):
                elements.append(self._expression())
                while self._match(T.COMMA):
                    elements.append(self._expression())
            self._consume(T.RBRACKET, "Expected ']' after array elements.",
                          "Close the array literal with ']'.", after_previous=True)
            return A.ArrayLiteral(elements=elements, line=tok.line, column=tok.column)

        raise self._error_at(
            tok, "Expected expression.",
            "An expression is a number, string, true/false/nil, a variable, a call, "
            "'(' ... ')' or an array like [1, 2].",
        )


# ======================================================================
# Convenience wrapper used by the API and other phases
# ======================================================================
@dataclass
class ParseResult:
    tokens: List[Token] = field(default_factory=list)
    program: Optional[A.Program] = None
    errors: List[NovaLangError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "tokens": [t.to_dict() for t in self.tokens],
            "ast": self.program.to_dict() if self.program is not None else None,
            "errors": [e.to_dict() for e in self.errors],
        }


def parse(source: str) -> ParseResult:
    """Lex and parse *source*.

    If the lexer reported errors, parsing is skipped: a token stream with
    holes would only produce confusing follow-up syntax errors.
    """
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    if lexer.errors:
        return ParseResult(tokens, None, list(lexer.errors))
    parser = Parser(tokens)
    program = parser.parse()
    if not parser.errors:
        depth, deepest = A.tree_depth(program)
        if depth > MAX_AST_DEPTH:
            # No tree is returned: the stages after the parser recurse over it and would crash.
            return ParseResult(tokens, None, [SyntaxError_(
                f"This code is nested too deeply (the syntax tree is {depth} levels deep; "
                f"the limit is {MAX_AST_DEPTH}).",
                deepest.line, deepest.column,
                "A very long chain such as 1 + 1 + 1 + ... counts too. "
                "Split it into smaller statements.",
            )])
    return ParseResult(tokens, program, list(parser.errors))
