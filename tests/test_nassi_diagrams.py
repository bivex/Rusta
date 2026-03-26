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

    assert bundle.document_count == 3
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
    assert payload["document_count"] == 3
    assert (output_dir / "index.html").exists()
    assert any(item["relative_output_path"].endswith("control_flow.nassi.html") for item in payload["documents"])
