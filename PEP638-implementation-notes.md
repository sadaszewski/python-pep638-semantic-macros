# PEP 638 in CPython 3.14.2: implementation notes

Base: CPython `v3.14.2` (the version Pyodide 314.0.7 pins). One commit, exported as
`pep638-cpython-3.14.2.patch` (about 2,300 hand-written lines in 37 files; the rest of the
750 KB is regenerated parser and AST code).

## What is implemented

| PEP section | Where | Notes |
|---|---|---|
| `MACRO_NAME` token | `Parser/lexer/lexer.c`, `Grammar/Tokens` | `name!` with no space. `name!=` stays `NAME` `!=`. Inside an f-string field `name!` is a macro only when followed by `(`, so `f"{x!r}"` is unchanged. |
| Statement form | `Grammar/python.gram` (`macro_block_stmt`, `macro_simple_stmt`) | `name! [args] [import NAME] [as NAME] [: body]`. Takes precedence over the expression form. |
| Expression form | `macro_expr` in `atom` | `name!(args)`; also `name!(x for x in y)`. |
| AST nodes | `Parser/Python.asdl` | `MacroStmt(name, args, importname, asname, body)`, `MacroExpr(name, args)`, `StmtExpr(stmt, value)`. Aliases `macro_stmt`, `macro_expr`, `stmt_expr` in `_ast`/`ast`. |
| Expansion | `Python/compile.c` (`_PyCompile_ExpandMacros`) calling `Lib/macros.py` | Runs before the symbol table. Outer macros first; results are re-expanded; inner macros need no processor. |
| `import!` / `from!` | `Lib/macros.py` | Compile-time import; registration is per scope (module, class, function, nested scopes see outer ones), from the import onwards. |
| Processor tuple, kinds, `macro_processor` | `Lib/macros.py`, constants also in `_ast` | `STMT_MACRO`, `SIBLING_MACRO`, `EXPR_MACRO`; syntax is checked against the kind. |
| Multi-part macros | `Lib/macros.py` | Following sibling statements named in `additional_names` are passed as extra arguments, in order; absent parts are `None`. |
| `stmt_expr` | symtable, codegen, optimizer, validator | Statement then value. `return`/`break`/`continue` out of the statement are a `SyntaxError` (unknown stack depth). |
| Version tracking | `Lib/importlib/_bootstrap_external.py` | The compiler adds `__macros__ = ("$macros", (module, name, version), ...)`; a cached `.pyc` is discarded when a version differs. |
| Hygiene helper | `macros.new_name(node, variable=None)` | `$$name_line_col` / `$var_line_col`. |

Extras not in the PEP: `compile(..., macros=dict)` (used by `codeop`, the REPL and Pyodide's
console so `from!` persists between inputs), `macros.expand(tree)`, a statement processor may
return a list of statements or `None`, a `SyntaxError` raised by a processor without location
gets the macro's location.

## Decisions where the PEP is silent or impractical

1. **AST immutability / compiler on Python objects.** The PEP's implementation sketch
   rewrites the compiler to work on immutable `_ast` objects. Not done: the tree is converted to
   `ast` objects only when it contains macros (a flag on the parser arena makes the check free),
   expanded in Python, converted back and validated. Code without macros takes the old path.
2. **`"red" = 1` in macro bodies.** Valid in the 2020 LL(1) grammar, a parse error under PEG.
   Direct children of a macro body may therefore assign to arbitrary expressions
   (`macro_assignment`). Nested blocks inside the body follow normal rules.
3. **Expression macro at the start of a statement.** `dbg!(x)` alone on a line is a macro
   *statement*, so with an `EXPR_MACRO` processor it is an error, as the PEP specifies
   ("the compiler will check that the syntax used matches the declared kind"). Write `(dbg!(x))`.
   Relaxing this is a three-line change in `_Expander.expand_stmt`.
4. **`from! m import a, b`** is rejected with a dedicated message: the PEP grammar imports one name.
5. **Relative imports** in `from!` are not supported (`testlist` cannot express `.mod`).
6. **Sibling macros** applied to sibling macros nest (`a!` / `b!` / `def f` gives `a!` the
   `b!` node whose body is `def f`).
7. A macro cannot be used in the module that defines it (it is needed to compile that module).
8. The basic (non-readline) C REPL does not persist `from!` between lines; the default REPL does.

## Verification

- `Lib/test/test_macros.py`: 71 tests (tokenizer, parser, unparse round trips, three kinds,
  multi-part, scoping, errors, `stmt_expr`, symtable, `compile(macros=)`, codeop, pyc invalidation).
- Full CPython suite, native build: 484 test files run, 2 failures, both caused by this sandbox
  (`test_socket` VSOCK device, `test_urllib` outbound proxy). Two upstream tests that used
  `return x!` as their example of invalid syntax were changed to `return x?`.
- In the WebAssembly build (Node): `test_macros`, `test_grammar`, `test_syntax`, `test_unparse`,
  `test_codeop`, `test_tokenize`: 409 tests pass.
- Playground page driven in headless Chromium through all seven examples and one error case.

## Pyodide build

Pyodide tag `314.0.7`, Emscripten 5.0.3 with Pyodide's patches. Because of download
restrictions in the build sandbox the toolchain was assembled by hand rather than through emsdk:
Emscripten from git, LLVM 23.1.3 and Binaryen 127 from their GitHub releases (emsdk normally
ships an LLVM snapshot of the same major version). `-Werror` had to be dropped for Emscripten's
own system libraries with this newer clang. SQLite is 3.52.0 (from the `sqlite3` npm package)
instead of 3.39.0. Pyodide itself needs only `pep638-pyodide-314.0.7.patch` (console macro
persistence). To reproduce on a normal machine: apply the CPython patch as an extra file in
`pyodide/cpython/patches/`, apply the Pyodide patch, `make`.
