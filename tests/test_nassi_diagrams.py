import json
import os
import subprocess
import sys
from pathlib import Path

from rusta.application.control_flow import (
    BuildNassiDiagramCommand,
    BuildNassiDirectoryCommand,
    NassiDiagramService,
)
from rusta.infrastructure.antlr.control_flow_extractor import AntlrRustControlFlowExtractor
from rusta.infrastructure.filesystem.source_repository import FileSystemSourceRepository
from rusta.infrastructure.rendering.nassi_html_renderer import HtmlNassiDiagramRenderer


ROOT = Path(__file__).resolve().parent.parent


def _ensure_generated_parser() -> None:
    generated_parser = (
        ROOT / "src" / "rusta" / "infrastructure" / "antlr" / "generated" / "rust" / "RustParser.py"
    )
    if generated_parser.exists():
        return
    subprocess.run(
        [sys.executable, "scripts/generate_rust_parser.py"],
        cwd=ROOT,
        check=True,
    )


def _build_service() -> NassiDiagramService:
    _ensure_generated_parser()
    return NassiDiagramService(
        source_repository=FileSystemSourceRepository(),
        extractor=AntlrRustControlFlowExtractor(),
        renderer=HtmlNassiDiagramRenderer(),
    )


def test_nassi_service_builds_html_document() -> None:
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "control_flow.rs"))
    )

    assert document.function_count == 2
    assert "score" in document.function_names
    assert "MathBox.normalize" in document.function_names
    assert "While total &gt; 100" in document.html
    assert "match total" in document.html
    assert "Loop" in document.html


def test_nassi_service_builds_directory_bundle() -> None:
    service = _build_service()
    bundle = service.build_directory_diagrams(
        BuildNassiDirectoryCommand(root_path=str(ROOT / "tests" / "fixtures"))
    )

    # Should include .rs files only (control_flow.rs, valid.rs, p0_features.rs, p0_let_else_limitation.rs)
    # Note: invalid.rs is excluded due to parsing errors
    assert bundle.document_count == 5
    assert bundle.root_path == str((ROOT / "tests" / "fixtures").resolve())
    assert any(document.source_location.endswith("control_flow.rs") for document in bundle.documents)
    assert any(document.function_count == 2 for document in bundle.documents)


def test_nassi_cli_writes_html_file(tmp_path: Path) -> None:
    _ensure_generated_parser()
    output_path = tmp_path / "control_flow.html"
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = "src" if not existing_pythonpath else f"src:{existing_pythonpath}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rusta.presentation.cli.main",
            "nassi-file",
            str(ROOT / "tests" / "fixtures" / "control_flow.rs"),
            "--out",
            str(output_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["function_count"] == 2
    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "match total" in html


def test_nassi_cli_writes_directory_bundle(tmp_path: Path) -> None:
    _ensure_generated_parser()
    output_dir = tmp_path / "bundle"
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = "src" if not existing_pythonpath else f"src:{existing_pythonpath}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rusta.presentation.cli.main",
            "nassi-dir",
            str(ROOT / "tests" / "fixtures"),
            "--out",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    # Should process .rs files (control_flow.rs, valid.rs, p0_features.rs, p0_let_else_limitation.rs)
    # Note: invalid.rs is excluded due to parsing errors
    assert payload["document_count"] == 5
    assert (output_dir / "index.html").exists()
    assert any(item["relative_output_path"].endswith("control_flow.nassi.html") for item in payload["documents"])


# P0 Feature Tests

def test_match_guards_are_detected() -> None:
    """Test that match guards (x if condition) are properly detected and visualized."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_match_guards" in document.function_names

    # Check that the HTML contains guard badges
    assert "guard-badge" in document.html
    assert "if x &gt; 10" in document.html or "if x > 10" in document.html


def test_or_patterns_are_detected() -> None:
    """Test that OR patterns (A | B) are properly detected in match arms."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_or_patterns" in document.function_names

    # Check that OR patterns are shown in the HTML
    html = document.html
    assert "Ok(x)" in html
    assert "Err(&quot;special&quot;)" in html or 'Err("special")' in html


def test_error_propagation_detected() -> None:
    """Test that ? operator is detected as TryPropagateFlowStep."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_error_propagation" in document.function_names

    # Check that ? operator is visualized
    assert "ns-try-propagate" in document.html


def test_async_await_detected() -> None:
    """Test that .await is detected as AwaitFlowStep."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_async_await" in document.function_names

    # Check that .await is visualized
    assert "ns-await" in document.html


def test_unsafe_blocks_detected() -> None:
    """Test that unsafe blocks are detected as UnsafeFlowStep."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_unsafe" in document.function_names

    # Check that unsafe blocks are visualized
    assert "ns-unsafe" in document.html


def test_closures_detected() -> None:
    """Test that closures are detected as ClosureFlowStep."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_closure" in document.function_names

    # Check that closures are visualized
    assert "ns-closure" in document.html


def test_break_with_value_detected() -> None:
    """Test that break with value is detected as BreakWithValueFlowStep."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_break_with_value" in document.function_names

    # Check that break with value is visualized
    assert "ns-break-value" in document.html


def test_range_patterns_fully_supported() -> None:
    """Test that range patterns (..=, ..) are detected via parse tree, not text heuristics."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_range_patterns_limited" in document.function_names
    assert "test_range_or_pattern" in document.function_names

    # range-indicator ↔ should appear for ..= and .. arms
    assert "range-indicator" in document.html
    # both inclusive and half-open ranges should be marked
    assert "1..=10" in document.html or "1..=" in document.html
    assert "101.." in document.html

    # range+OR combined: 1..=5 | 8..=10 must also be marked as range
    assert "is-range" in document.html


def test_async_fn_badge_rendered() -> None:
    """Test that async fn shows an async badge in the HTML header."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_async_await" in document.function_names
    assert 'fn-badge-async' in document.html


def test_unsafe_fn_badge_rendered() -> None:
    """Test that unsafe fn shows an unsafe badge in the HTML header."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_unsafe_fn" in document.function_names
    assert 'fn-badge-unsafe' in document.html


def test_labeled_continue_detected() -> None:
    """Test that labeled continue extracts the label into the action text."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_labeled_continue" in document.function_names
    assert "continue 'outer" in document.html or "continue &#x27;outer" in document.html or "&#39;outer" in document.html


def test_const_fn_badge_rendered() -> None:
    """Test that const fn shows a const badge in the HTML header."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_const_fn" in document.function_names
    assert "fn-badge-const" in document.html


def test_where_clause_rendered() -> None:
    """Test that where clauses are extracted and rendered in the function header."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_where_clause" in document.function_names
    assert "fn-where" in document.html
    assert "Clone" in document.html


def test_outer_attributes_rendered() -> None:
    """Test that outer attributes (#[...]) are collected and rendered as chips."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_with_attribute" in document.function_names
    assert "fn-attr" in document.html
    assert "must_use" in document.html


def test_coroutine_yield_and_gen_block() -> None:
    """Test that yield expressions and gen {} blocks are detected."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_coroutine_yield" in document.function_names
    assert "ns-yield" in document.html
    assert "ns-gen" in document.html


def test_let_else_supported() -> None:
    """Test that let-else (Rust 1.65+) is now supported after grammar extension."""
    fixture_path = ROOT / "tests" / "fixtures" / "p0_let_else_limitation.rs"
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(fixture_path))
    )

    assert "test_let_else" in document.function_names
    assert "test_if_let_alternative" in document.function_names
    assert "test_match_alternative" in document.function_names
    assert "ns-let-else" in document.html


def test_macro_calls_rendered() -> None:
    """Test that macro invocations are rendered as distinct MacroCallFlowStep nodes."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_macros" in document.function_names
    assert "ns-macro" in document.html


def test_const_param_rendered() -> None:
    """Test that generic const params are extracted and shown in the function header."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_const_param" in document.function_names
    # const param chip should appear in header
    assert "const N" in document.html or "const N:" in document.html


def test_if_let_chain_detected() -> None:
    """Test that if-let chains (Rust 1.64+) are rendered with && conditions."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert document.function_count == 21
    assert "test_if_let_chain_simple" in document.function_names
    assert "test_if_let_chain_double" in document.function_names

    html = document.html
    # Single let + bool condition chain
    assert "Some(x)" in html
    assert "&amp;&amp;" in html or "&&" in html
    # Double let chain
    assert "Some(y)" in html


def test_labeled_block_detected() -> None:
    """Test that labeled blocks ('label: { }) are detected as LabeledBlockFlowStep."""
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "p0_features.rs"))
    )

    assert "test_labeled_block" in document.function_names
    assert "ns-labeled-block" in document.html
    assert "block" in document.html
