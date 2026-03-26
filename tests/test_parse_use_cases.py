import json
import subprocess
import sys
from pathlib import Path

from swifta.application.dto import ParseDirectoryCommand, ParseFileCommand
from swifta.application.use_cases import ParsingJobService
from swifta.infrastructure.antlr.parser_adapter import AntlrRustSyntaxParser
from swifta.infrastructure.filesystem.source_repository import FileSystemSourceRepository
from swifta.infrastructure.system import (
    InMemoryParsingJobRepository,
    StructuredLoggingEventPublisher,
    SystemClock,
)


ROOT = Path(__file__).resolve().parent.parent


def _ensure_generated_parser() -> None:
    generated_parser = (
        ROOT / "src" / "swifta" / "infrastructure" / "antlr" / "generated" / "rust" / "RustParser.py"
    )
    if generated_parser.exists():
        return
    subprocess.run(
        [sys.executable, "scripts/generate_rust_parser.py"],
        cwd=ROOT,
        check=True,
    )


def _build_service() -> ParsingJobService:
    _ensure_generated_parser()
    return ParsingJobService(
        source_repository=FileSystemSourceRepository(),
        parser=AntlrRustSyntaxParser(),
        event_publisher=StructuredLoggingEventPublisher(),
        clock=SystemClock(),
        job_repository=InMemoryParsingJobRepository(),
    )


def test_parse_file_extracts_structure() -> None:
    service = _build_service()
    report = service.parse_file(ParseFileCommand(path=str(ROOT / "tests" / "fixtures" / "valid.rs")))

    assert report.summary.source_count == 1
    assert report.summary.technical_failure_count == 0
    assert report.sources[0].status in {"succeeded", "succeeded_with_diagnostics"}
    assert {element.kind for element in report.sources[0].structural_elements} >= {
        "use",
        "module",
        "struct",
        "function",
        "trait",
        "impl",
        "enum",
        "constant",
        "static",
        "type_alias",
    }


def test_parse_directory_returns_report_for_all_files() -> None:
    service = _build_service()
    report = service.parse_directory(ParseDirectoryCommand(root_path=str(ROOT / "tests" / "fixtures")))

    assert report.summary.source_count == 3
    assert len(report.sources) == 3


def test_parse_file_handles_trait_and_impl(tmp_path: Path) -> None:
    service = _build_service()
    source_path = tmp_path / "trait_parse.rs"
    source_path.write_text(
        """
trait Renderable {
    fn render(&self) -> String;
}

struct Screen;

impl Renderable for Screen {
    fn render(&self) -> String {
        "ok".to_string()
    }
}
""".strip(),
        encoding="utf-8",
    )

    report = service.parse_file(ParseFileCommand(path=str(source_path)))

    assert report.summary.source_count == 1
    assert report.summary.technical_failure_count == 0
    assert {element.kind for element in report.sources[0].structural_elements} >= {
        "trait",
        "impl",
        "function",
        "struct",
    }


def test_parse_file_reports_syntax_diagnostics() -> None:
    service = _build_service()
    report = service.parse_file(ParseFileCommand(path=str(ROOT / "tests" / "fixtures" / "invalid.rs")))

    assert report.summary.source_count == 1
    assert report.sources[0].status == "succeeded_with_diagnostics"
    assert report.sources[0].diagnostics


def test_cli_outputs_json() -> None:
    _ensure_generated_parser()
    env = dict(__import__("os").environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = "src" if not existing_pythonpath else f"src:{existing_pythonpath}"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "swifta.presentation.cli.main",
            "parse-file",
            str(ROOT / "tests" / "fixtures" / "valid.rs"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["source_count"] == 1
