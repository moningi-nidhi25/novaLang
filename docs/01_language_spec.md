# NovaLang Language Specification (v0.1)

NovaLang is a small, educational language with inferred static types where they can be known and run-time checks where they cannot. Its purpose is to make
compiler internals visible, so every design choice below favours simplicity and
unambiguous rules over convenience.

## 1. Program structure

A program is a sequence of declarations and statements executed top to bottom.
Every simple statement ends with `;`. Blocks use `{ }`. Whitespace is insignificant.

```
function add(a, b) { return a + b; }
let result = add(10, 20);
print(result);
```

## 2. Data types

| Type    | Literal examples        | Notes                                           |
|---------|-------------------------|-------------------------------------------------|
| int     | `0`, `42`               | arbitrary-size Python int                       |
| float   | `9.65`, `0.5`           | digits required on both sides of `.`            |
| string  | `"Nidhi"`, `"a\n"`      | double quotes only; escapes `\n \t \r \\ \" \0` |
| bool    | `true`, `false`         |                                                 |
| array   | `[1, 2, 3]`             | may mix types; zero-based; index must be int    |
| nil     | `nil`                   | "no value"                                      |

Negative numbers are the unary `-` operator applied to a literal (`-5` is `-` then `5`).

## 3. Variables and scope

* `let x = expr;` declares a variable. An initializer is required.
* Redeclaring a name in the *same* scope is a semantic error; shadowing in an inner scope is allowed. Parameters and the top-level statements of a function body share one scope.
* Variables must be declared textually **before** use (a variable is not visible in its own initializer). Functions are the exception: they are visible everywhere in the file.
* `x = expr;` and `a[i] = expr;` assign to an existing variable / array element. Assigning to an undeclared name is an error.
* Assignment is a **statement**, not an expression (keeps TAC generation simple).
* Scopes are lexical: the global scope, each function body, and each `{ }` block.
* Functions are declared at top level only and are visible throughout the file (so mutual recursion works). No closures.

## 4. Operators and precedence (high to low)

| Level | Operators            | Associativity |
|-------|----------------------|---------------|
| 1     | `()` call, `[]` index | left          |
| 2     | unary `-` `!`        | right         |
| 3     | `*` `/` `%`          | left          |
| 4     | `+` `-`              | left          |
| 5     | `<` `>` `<=` `>=`    | left          |
| 6     | `==` `!=`            | left          |
| 7     | `&&`                 | left (short-circuit) |
| 8     | `||`                 | left (short-circuit) |

So `2 + 3 * 4` is `2 + (3 * 4)` = 14.

### Typing rules

The semantic analyzer infers a static type for every expression: `int`, `float`, `string`, `bool`, `array`, `nil` or `any` (unknown until run time: function parameters and call results). A variable's type is fixed by its initializer (`let x = nil;` gives type `any`). Assigning a different known type is an error; `int` may widen to `float`, never the reverse. Checks involving `any` are deferred to the interpreter. Constant division/modulo by zero and unreachable code are *warnings*, not errors.

* `+ - * / %` : numeric operands. `int op int -> int`, any float involved `-> float`.
  `/` on two ints truncates toward zero (documented choice); division/modulo by zero is a runtime error.
* `+` also concatenates two strings (string + string only; no implicit conversion).
* `< > <= >=` : both numeric, or both strings. Result bool.
* `== !=` : any two values; different types are simply unequal (int and float compare numerically).
* `&& || !` : bool operands only (no truthiness). `&&`/`||` short-circuit.
* `if`/`while`/`for` conditions must be bool.

## 5. Control flow

```
if (cond) { ... } else { ... }          // else optional; "else if" allowed
while (cond) { ... }
for (let i = 0; i < 5; i = i + 1) { ... }   // init: let or assignment; update: assignment
break;      // only inside a loop
continue;   // only inside a loop
```
Braces are mandatory (no dangling-else ambiguity).

## 6. Functions

```
function factorial(n) {
    if (n <= 1) { return 1; }
    return n * factorial(n - 1);
}
```
* Parameters are local variables. Arguments count must match the parameter count.
* `return expr;` returns a value; `return;` or falling off the end returns `nil`.
* `return` outside a function is a semantic error. Recursion is supported.
* Built-in: `len(x)` returns the length of an array or string.

## 7. Output

`print(expr);` writes the value followed by a newline. Floats print in Python style, `true/false/nil` lowercase, arrays as `[1, 2, 3]`.

### Runtime semantics

* `/` on two ints truncates toward zero; `%` takes the sign of the dividend, so `a == (a / b) * b + a % b`. Division or modulo by zero is a runtime error (`Division by zero at line N.`).
* `==` on numbers compares by value (`1 == 1.0`); other types must match (`true == 1` is false); arrays compare element by element.
* Arrays are reference values: `let b = a;` shares one array. Strings are immutable. Array and string indexes are bounds-checked.
* Calls get a fresh scope whose parent is the *global* scope (no access to the caller's locals). Arguments are evaluated left to right.
* Safety limits: 1,000,000 executed steps (catches infinite loops), 500 nested calls (catches missing base cases), strings up to 1,000,000 characters.
* Source limits: at most 40 levels of nesting (parentheses, blocks, array literals, call arguments) and a syntax tree at most 100 levels deep; deeper programs are rejected with a syntax error. Source text is limited to 100,000 characters by the API.
* `print` shows strings raw at top level and quoted inside arrays: `[1, "a", true, nil]`.

## 8. Comments

```
// single line
/* multi
   line (not nestable) */
```

## 9. Error categories

| Phase    | Example |
|----------|---------|
| Lexical  | `Unexpected character '$' at line 2, column 5.` |
| Syntax   | `Expected ')' after condition.` |
| Semantic | `Variable 'y' is not defined.` |
| Runtime  | `Division by zero at line 8.` |

Every error carries line, column, and an educational "Why" hint.

---

# Formal grammar (EBNF)

Terminals are in UPPERCASE or quotes. `*` zero or more, `?` optional, `|` choice.

```
program        -> declaration* EOF
declaration    -> functionDecl | statement
functionDecl   -> "function" IDENTIFIER "(" parameters? ")" block
parameters     -> IDENTIFIER ( "," IDENTIFIER )*

statement      -> letDecl | assignStmt | ifStmt | whileStmt | forStmt
                | returnStmt | breakStmt | continueStmt | printStmt
                | exprStmt | block
block          -> "{" declaration* "}"
letDecl        -> "let" IDENTIFIER "=" expression ";"
assignStmt     -> assignTarget "=" expression ";"
assignTarget   -> IDENTIFIER ( "[" expression "]" )*
ifStmt         -> "if" "(" expression ")" block ( "else" ( ifStmt | block ) )?
whileStmt      -> "while" "(" expression ")" block
forStmt        -> "for" "(" forInit ";" expression ";" forUpdate ")" block
forInit        -> "let" IDENTIFIER "=" expression | assignTarget "=" expression
forUpdate      -> assignTarget "=" expression
returnStmt     -> "return" expression? ";"
breakStmt      -> "break" ";"
continueStmt   -> "continue" ";"
printStmt      -> "print" "(" expression ")" ";"
exprStmt       -> expression ";"

expression     -> logicOr
logicOr        -> logicAnd ( "||" logicAnd )*
logicAnd       -> equality ( "&&" equality )*
equality       -> comparison ( ( "==" | "!=" ) comparison )*
comparison     -> term ( ( "<" | ">" | "<=" | ">=" ) term )*
term           -> factor ( ( "+" | "-" ) factor )*
factor         -> unary ( ( "*" | "/" | "%" ) unary )*
unary          -> ( "!" | "-" ) unary | postfix
postfix        -> primary ( "(" arguments? ")" | "[" expression "]" )*
arguments      -> expression ( "," expression )*
primary        -> INTEGER | FLOAT | STRING | "true" | "false" | "nil"
                | IDENTIFIER | "(" expression ")" | "[" arguments? "]"
```

The grammar is LL(1) apart from `assignStmt` vs `exprStmt`, which the parser resolves by
parsing an expression and checking whether `=` follows (the expression must then be an
assignable target). Each non-terminal becomes one method in the recursive descent parser,
and the precedence table above is encoded by the nesting `logicOr -> ... -> unary`.

---

# Token specification

| Category    | Token type(s) | Lexeme / pattern |
|-------------|---------------|------------------|
| Literals    | `INTEGER` `FLOAT` `STRING` | `[0-9]+`, `[0-9]+\.[0-9]+`, `"..."` |
| Identifier  | `IDENTIFIER`  | `[A-Za-z_][A-Za-z0-9_]*` (if not a keyword) |
| Keywords    | `LET FUNCTION RETURN IF ELSE WHILE FOR BREAK CONTINUE PRINT TRUE FALSE NIL` | `let function return if else while for break continue print true false nil` |
| Arithmetic  | `PLUS MINUS STAR SLASH PERCENT` | `+ - * / %` |
| Comparison  | `EQ NEQ LT GT LTE GTE` | `== != < > <= >=` |
| Logical     | `AND OR NOT`  | `&& \|\| !` |
| Assignment  | `ASSIGN`      | `=` |
| Punctuation | `LPAREN RPAREN LBRACE RBRACE LBRACKET RBRACKET COMMA SEMICOLON` | `( ) { } [ ] , ;` |
| Special     | `EOF`         | end of input |
| Skipped     | (none)        | whitespace, `// ...`, `/* ... */` |

Each token records `type`, `lexeme`, `value` (parsed int/float/string/bool), `line`, `column` (both 1-based).

Note: the original brief sketches a single `NUMBER` token; we split it into `INTEGER` and `FLOAT`
because the language has both types and the lexer can tell them apart for free.


---

# Intermediate representation: Three Address Code

Every instruction has the form `op, arg1, arg2, result` (JSON keys of the same names, plus a ready-made `text`, the source `line`/`column` and an `index`). An operand is a variable or temporary name, or a constant written like its NovaLang literal (`10`, `2.5`, `"hi"`, `true`, `false`, `nil`).

| op | text form | meaning |
|----|-----------|---------|
| `+ - * / %` `== != < > <= >=` | `t1 = a + b` | binary operation |
| `neg`, `not` | `t1 = -a`, `t1 = !a` | unary operation |
| `copy` | `x = t1` | assignment |
| `label` / `goto` | `L1:` / `goto L1` | jump target / unconditional jump |
| `if_false` / `if_true` | `ifFalse t1 goto L1` / `if t1 goto L1` | conditional jump |
| `param` / `call` | `param x` / `t1 = call f, 2` | push an argument / call with n arguments |
| `return` | `return t1` | return a value (`return nil` when there is none) |
| `print` | `print t1` | output |
| `array_new` / `index` / `index_set` | `t1 = newarray 3` / `t2 = a[i]` / `a[i] = t2` | arrays |

Code generation rules:

* `let result = (a + b) * c;` becomes `t1 = a + b`, `t2 = t1 * c`, `result = t2` (every expression result goes through a temporary; the optimizer cleans this up in Phase 7).
* `if`/`while`/`for` become labels and jumps. `break` jumps to the loop's end label, `continue` to its start (in a `for` loop, to the update step).
* `&&` and `||` short-circuit, so they compile to jumps rather than to an operator.
* A call evaluates all its arguments first, then emits one `param` per argument, then `call`.
* Temporaries are `t1, t2, ...` and restart in every function. Labels are `L1, L2, ...` and are unique in the whole program.
* TAC has one flat namespace per function, so a variable that shadows another gets a fresh name (`x` becomes `x_1`), and a function's own variables never share a name with a global.
* `TACProgram.globals` lists the top-level variables. A call may change any of them.
* Operands are evaluated in the same order as in the interpreter, so a program means the same thing before and after translation (checked by running both and comparing output).


# Basic blocks and the control-flow graph

A **leader** is the first instruction of a basic block. An instruction is a leader if it is (1) the first instruction of the function, (2) the target of a jump, or (3) immediately after a jump or a return. Each block runs from one leader up to, but not including, the next.

Edges connect blocks. The last instruction of a block decides them:

| last instruction | edges |
|------------------|-------|
| `goto L` | `jump` to the block starting at `L` |
| `ifFalse c goto L` | `true` to the next block, `false` to `L` |
| `if c goto L` | `true` to `L`, `false` to the next block |
| `return` | none (an exit block) |
| anything else | `next` to the following block |

If both outcomes of a conditional reach the same block, one `branch` edge is used. A CFG is built per function; blocks are named `B1, B2, ...` within each function. A block that cannot be reached from the entry has `reachable: false` (dead code). The generator is deliberately simple and emits some dead code, for example a `goto` after a `return` inside an if/else; the Phase 7 optimizer removes it.

API shape (`compile_to_cfg(source).to_dict()["cfg"]`): `{"functions": [{"function", "entry", "exits", "blocks": [{"name", "id", "start", "end", "label", "leader_reasons", "instructions", "successors", "predecessors", "reachable", "is_entry", "is_exit"}], "edges": [{"source", "target", "kind"}]}]}`.


# Optimizer

The optimizer rewrites TAC into TAC that does the same thing with less work. **The optimized program must behave exactly like the original:** same output, same run-time errors, same final values of the global variables. The test-suite enforces this by running the interpreter, the original TAC and the optimized TAC side by side on every example, hundreds of generated programs and random expressions, and by deliberately breaking the optimizer to check that the tests notice.

Passes (repeated, with types re-inferred each round, until nothing changes):

| pass | example | safety condition |
|------|---------|------------------|
| constant propagation | `x = 10; y = x + 5` becomes `y = 10 + 5` | forward data-flow analysis over the CFG; every global is unknown after a call and at the start of a function; arrays are never constants |
| constant folding | `t1 = 10 + 20` becomes `t1 = 30` | never folds an operation that would fail (`1 / 0`, `"a" + 1`), or one whose result is infinite or enormous |
| algebraic simplification | `x + 0`, `x - 0`, `x * 1`, `x / 1`, `x * 0` | only when `x` is *proven* numeric (see below) |
| branch folding | `ifFalse true goto L` is deleted; `ifFalse false goto L` becomes `goto L` | the condition must be a constant bool |
| unreachable code | blocks no path reaches are deleted | CFG reachability |
| temporary coalescing | `t1 = a + b; x = t1` becomes `x = a + b` | `t1` is read only by that copy and is not global |
| dead store removal | an assignment nobody reads is deleted | liveness analysis; global variables are always kept; only instructions that cannot fail are deleted (a dead call keeps the call but loses its result) |
| jump cleanup | `goto L` right before `L:`, and labels nobody jumps to, are deleted | none needed |

**Why types matter.** `x + 0 -> x` is only correct if `x` is an int: if `x` is a string the original program raises an error and the "simplified" one would not. `x * 0 -> 0` and `x + 0 -> x` are restricted to ints because floats have `-0.0`: `-0.0 + 0` is `0.0`, and `-2.5 * 0` is `-0.0`, so the identities change the printed result. `x * 1`, `x - 0` and `x / 1` are exact for ints and floats. Types are inferred from the TAC itself: a variable has a known type only if *every* assignment to it anywhere in the program produces that type; parameters and call results are unknown (`any`).

**What is deliberately not optimized.** Anything that can raise a run-time error is never deleted even if its result is unused: `t = a / b` stays. A global variable is never removed (other functions may read it, and its final value is part of the program's result).

API shape (`compile_and_optimize(source).to_dict()`): `{"ok", "errors", "warnings", "original": <tac>, "optimized": <tac>, "changes": [{"pass", "function", "line", "before", "after", "description"}], "stats": {pass: count}, "instruction_counts": {"before", "after"}}`. `after` is `null` when an instruction was deleted.
