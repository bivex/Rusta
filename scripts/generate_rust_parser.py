"""Generate Python parser artifacts from the vendored Rust grammar."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "build" / "tools"
BUILD_DIR = ROOT / "build" / "antlr-rust"
WORK_DIR = BUILD_DIR / "grammar"
GENERATED_DIR = BUILD_DIR / "generated"
GRAMMAR_DIR = ROOT / "resources" / "grammars" / "rust"
OUTPUT_DIR = ROOT / "src" / "swifta" / "infrastructure" / "antlr" / "generated" / "rust"
ANTLR_VERSION = "4.13.2"
ANTLR_JAR = TOOLS_DIR / f"antlr-{ANTLR_VERSION}-complete.jar"
ANTLR_JAR_URL = f"https://www.antlr.org/download/antlr-{ANTLR_VERSION}-complete.jar"


def main() -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _ensure_grammar_exists()
    _ensure_antlr_jar_exists()
    _stage_grammar()
    _transform_staged_grammar()
    _generate_parser()
    _copy_support_modules()
    _copy_generated_files()
    _ensure_package_files()


def _ensure_grammar_exists() -> None:
    required = (
        GRAMMAR_DIR / "RustLexer.g4",
        GRAMMAR_DIR / "RustParser.g4",
        GRAMMAR_DIR / "Python3" / "RustLexerBase.py",
        GRAMMAR_DIR / "Python3" / "RustParserBase.py",
        GRAMMAR_DIR / "Python3" / "transformGrammar.py",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing grammar files: {', '.join(missing)}")


def _ensure_antlr_jar_exists() -> None:
    if ANTLR_JAR.exists():
        return
    print(f"Downloading ANTLR {ANTLR_VERSION}...")
    urlretrieve(ANTLR_JAR_URL, ANTLR_JAR)


def _stage_grammar() -> None:
    shutil.copy2(GRAMMAR_DIR / "RustLexer.g4", WORK_DIR / "RustLexer.g4")
    shutil.copy2(GRAMMAR_DIR / "RustParser.g4", WORK_DIR / "RustParser.g4")
    shutil.copy2(GRAMMAR_DIR / "Python3" / "transformGrammar.py", WORK_DIR / "transformGrammar.py")


def _transform_staged_grammar() -> None:
    subprocess.run(["python3", "transformGrammar.py"], check=True, cwd=WORK_DIR)


def _generate_parser() -> None:
    lexer_command = [
        "java",
        "-jar",
        str(ANTLR_JAR),
        "-Dlanguage=Python3",
        "-visitor",
        "-no-listener",
        "-o",
        "../generated",
        "RustLexer.g4",
    ]
    parser_command = [
        "java",
        "-jar",
        str(ANTLR_JAR),
        "-Dlanguage=Python3",
        "-visitor",
        "-no-listener",
        "-lib",
        "../generated",
        "-o",
        "../generated",
        "RustParser.g4",
    ]
    subprocess.run(lexer_command, check=True, cwd=WORK_DIR)
    subprocess.run(parser_command, check=True, cwd=WORK_DIR)


def _copy_support_modules() -> None:
    shutil.copy2(GRAMMAR_DIR / "Python3" / "RustLexerBase.py", GENERATED_DIR / "RustLexerBase.py")
    shutil.copy2(GRAMMAR_DIR / "Python3" / "RustParserBase.py", GENERATED_DIR / "RustParserBase.py")


def _copy_generated_files() -> None:
    for source in GENERATED_DIR.glob("*.py"):
        shutil.copy2(source, OUTPUT_DIR / source.name)


def _ensure_package_files() -> None:
    init_file = OUTPUT_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated Rust ANTLR parser."""\n', encoding="utf-8")


if __name__ == "__main__":
    main()
