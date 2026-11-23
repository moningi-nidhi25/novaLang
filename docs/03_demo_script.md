# Demo script: factorial(5) through all ten stages

About five minutes. Start both servers (see the README), open http://localhost:5173, press **Run**.

The program is already in the editor. Say what it does: a recursive function, then `print(result)`.

1. **Output.** The page opens on the Output tab: `120`, and "Verified: the optimized TAC behaves exactly like the original program." Every stage in the bar at the top is green.
2. **Tokens.** 42 tokens, each with line and column. Point at `<=`: one token, not `<` then `=` (maximal munch).
3. **Syntax tree.** The diagram shows the shape of the program. Click `BinaryExpression <=`: the path up to the root lights up and the editor jumps to line 2. The chip says `bool`, a type found by semantic analysis.
4. **Semantic and Symbols.** `factorial` is a function with one parameter `n`; `n` lives in the function's own scope.
5. **TAC.** Show `factorial`: `t1 = n <= 1`, `ifFalse t1 goto L1`. Click the `ifFalse` line: label `L1:` lights up.
6. **CFG.** Pick `factorial`. Four blocks, a green and a red arrow out of the first, two exits (the two returns).
7. **Optimization.** `factorial` improves only a little (13 instructions become 12). Then load `optimizer_showcase` and press Run: 17 instructions become 6. Open Before and after.
8. **Errors.** Delete a `;` in the editor and press Run (`examples/errors/` has one failing program per stage, which `python -m compiler` can run): the failing stage turns red, later stages say skipped, and the message points at the exact column.

No browser? `python -m compiler examples/demo_factorial.nova` prints the same ten stages as text.
