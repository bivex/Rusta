# Rusta

Rusta is a small layered parser service for Rust source code built on top of ANTLR4 and Python bindings.

The repo keeps the same general architecture as the earlier Swift-focused version:

* domain-first, layered monolith
* ANTLR grammar kept behind infrastructure ports
* CLI contract that parses one file or a whole directory and returns versioned JSON
* generated Python parser artifacts committed locally from vendored upstream grammar inputs

The import path and console script are still named `swifta` for compatibility, but the parser target is now Rust.

## What It Parses

Today the parser recognizes Rust source files (`.rs`) and extracts a lightweight structural dictionary with:

* `use`
* `module`
* `type_alias`
* `constant`
* `static`
* `function`
* `struct`
* `enum`
* `union`
* `trait`
* `impl`

Syntax diagnostics from the ANTLR lexer/parser are included in the JSON report.

## Grammar Source

The Rust grammar is vendored from [`antlr/grammars-v4`](https://github.com/antlr/grammars-v4/tree/master/rust).

Included locally:

* [resources/grammars/rust/RustLexer.g4](/Volumes/External/Code/Rusta/resources/grammars/rust/RustLexer.g4)
* [resources/grammars/rust/RustParser.g4](/Volumes/External/Code/Rusta/resources/grammars/rust/RustParser.g4)
* [resources/grammars/rust/Python3/RustLexerBase.py](/Volumes/External/Code/Rusta/resources/grammars/rust/Python3/RustLexerBase.py)
* [resources/grammars/rust/Python3/RustParserBase.py](/Volumes/External/Code/Rusta/resources/grammars/rust/Python3/RustParserBase.py)
* [resources/grammars/rust/Python3/transformGrammar.py](/Volumes/External/Code/Rusta/resources/grammars/rust/Python3/transformGrammar.py)

The upstream Rust grammar README says it was last updated for Rust `v1.60.0` and targets stable `2018+` syntax.

## Quick Start

1. Install dependencies:

```bash
uv sync --extra dev
```

2. Generate Python parser artifacts from the vendored Rust grammar:

```bash
uv run python scripts/generate_rust_parser.py
```

3. Parse one Rust file:

```bash
uv run swifta parse-file path/to/lib.rs
```

4. Parse a directory of Rust files:

```bash
uv run swifta parse-dir path/to/project
```

If you run the module directly instead of `uv run`, make sure `src` is on `PYTHONPATH`.

## Output Contract

The CLI returns JSON with:

* job metadata
* summary counters
* one report per source file
* syntax diagnostics
* structural elements with `kind`, `name`, `line`, `column`, `container`, and `signature`
* token/statistics metadata

## Current Scope

This rewrite replaces the Swift parser path with Rust parsing. The old Swift-specific control-flow and Nassi-Shneiderman diagram features are not part of the active CLI anymore.
