"""CLI application."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

from rusta.application.control_flow import (
    BuildNassiDiagramCommand,
    BuildNassiDirectoryCommand,
    NassiDiagramBundleDTO,
    NassiDiagramService,
)
from rusta.application.dto import ParseDirectoryCommand, ParseFileCommand, ParsingJobReportDTO
from rusta.application.use_cases import ParsingJobService
from rusta.domain.errors import RustaError
from rusta.infrastructure.antlr.control_flow_extractor import AntlrRustControlFlowExtractor
from rusta.infrastructure.antlr.parser_adapter import AntlrRustSyntaxParser
from rusta.infrastructure.filesystem.source_repository import FileSystemSourceRepository
from rusta.infrastructure.rendering.nassi_html_renderer import HtmlNassiDiagramRenderer
from rusta.infrastructure.system import (
    InMemoryParsingJobRepository,
    StructuredLoggingEventPublisher,
    SystemClock,
    configure_logging,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    configure_logging(verbose=getattr(args, "verbose", False))

    try:
        if args.command == "parse-file":
            report = _build_parse_service().parse_file(ParseFileCommand(path=args.path))
        elif args.command == "parse-dir":
            report = _build_parse_service().parse_directory(ParseDirectoryCommand(root_path=args.path))
        elif args.command == "nassi-file":
            document = _build_nassi_service().build_file_diagram(
                BuildNassiDiagramCommand(path=args.path)
            )
            output_path = _resolve_output_path(args.path, args.out)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(document.html, encoding="utf-8")

            payload = document.to_dict()
            payload["output_path"] = str(output_path)
            print(json.dumps(payload, indent=2))
            return 0
        elif args.command == "nassi-dir":
            bundle = _build_nassi_service().build_directory_diagrams(
                BuildNassiDirectoryCommand(root_path=args.path)
            )
            output_dir = _resolve_output_directory(args.path, args.out)
            written_diagrams = _write_directory_diagrams(bundle, output_dir)
            index_path = output_dir / "index.html"
            index_path.write_text(
                _render_directory_index(bundle.root_path, written_diagrams),
                encoding="utf-8",
            )

            payload = bundle.to_dict()
            payload["output_dir"] = str(output_dir)
            payload["index_path"] = str(index_path)
            payload["documents"] = [
                {
                    "source_location": diagram.source_location,
                    "function_count": diagram.function_count,
                    "function_names": list(diagram.function_names),
                    "output_path": str(diagram.output_path),
                    "relative_output_path": diagram.relative_output_path,
                }
                for diagram in written_diagrams
            ]
            print(json.dumps(payload, indent=2))
            return 0
        else:
            parser.error(f"unsupported command: {args.command}")
    except RustaError as error:
        print(json.dumps({"error": str(error)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(report.to_dict(), indent=2))
    return _exit_code_for(report)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse Rust source code with ANTLR.")
    parser.add_argument("--verbose", action="store_true", help="Enable lifecycle logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_file = subparsers.add_parser("parse-file", help="Parse one Rust file.")
    parse_file.add_argument("path", help="Path to a .rs file.")

    parse_dir = subparsers.add_parser("parse-dir", help="Parse all Rust files in a directory.")
    parse_dir.add_argument("path", help="Path to a directory.")

    nassi_file = subparsers.add_parser(
        "nassi-file",
        help="Build a Nassi-Shneiderman HTML diagram for one Rust file.",
    )
    nassi_file.add_argument("path", help="Path to a .rs file.")
    nassi_file.add_argument(
        "--out",
        help="Output HTML path. Defaults to <input>.nassi.html.",
    )

    nassi_dir = subparsers.add_parser(
        "nassi-dir",
        help="Build Nassi-Shneiderman HTML diagrams for all Rust files in a directory.",
    )
    nassi_dir.add_argument("path", help="Path to a directory.")
    nassi_dir.add_argument(
        "--out",
        help="Output directory. Defaults to <input>.nassi/.",
    )
    return parser


def _build_parse_service() -> ParsingJobService:
    return ParsingJobService(
        source_repository=FileSystemSourceRepository(),
        parser=AntlrRustSyntaxParser(),
        event_publisher=StructuredLoggingEventPublisher(),
        clock=SystemClock(),
        job_repository=InMemoryParsingJobRepository(),
    )


def _build_nassi_service() -> NassiDiagramService:
    return NassiDiagramService(
        source_repository=FileSystemSourceRepository(),
        extractor=AntlrRustControlFlowExtractor(),
        renderer=HtmlNassiDiagramRenderer(),
    )


def _exit_code_for(report: ParsingJobReportDTO) -> int:
    if report.summary.technical_failure_count > 0:
        return 1
    return 0


def _resolve_output_path(input_path: str, explicit_output_path: str | None) -> Path:
    if explicit_output_path:
        return Path(explicit_output_path).expanduser().resolve()

    resolved_input = Path(input_path).expanduser().resolve()
    return resolved_input.with_suffix(".nassi.html")


def _resolve_output_directory(input_path: str, explicit_output_path: str | None) -> Path:
    if explicit_output_path:
        return Path(explicit_output_path).expanduser().resolve()

    resolved_input = Path(input_path).expanduser().resolve()
    return resolved_input.with_name(f"{resolved_input.name}.nassi")


@dataclass(frozen=True, slots=True)
class _WrittenNassiDiagram:
    source_location: str
    function_count: int
    function_names: tuple[str, ...]
    output_path: Path
    relative_output_path: str
    relative_source_path: str


def _write_directory_diagrams(
    bundle: NassiDiagramBundleDTO,
    output_dir: Path,
) -> tuple[_WrittenNassiDiagram, ...]:
    root_path = Path(bundle.root_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    written_diagrams: list[_WrittenNassiDiagram] = []
    for document in bundle.documents:
        source_path = Path(document.source_location)
        relative_source_path = source_path.relative_to(root_path)
        output_path = (output_dir / relative_source_path).with_suffix(".nassi.html")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(document.html, encoding="utf-8")
        written_diagrams.append(
            _WrittenNassiDiagram(
                source_location=document.source_location,
                function_count=document.function_count,
                function_names=document.function_names,
                output_path=output_path,
                relative_output_path=output_path.relative_to(output_dir).as_posix(),
                relative_source_path=relative_source_path.as_posix(),
            )
        )
    return tuple(written_diagrams)


def _render_directory_index(
    root_path: str,
    written_diagrams: tuple[_WrittenNassiDiagram, ...],
) -> str:
    rows = "".join(
        (
            "<tr>"
            f'<td><a href="{escape(diagram.relative_output_path)}">{escape(diagram.relative_source_path)}</a></td>'
            f"<td>{diagram.function_count}</td>"
            f"<td>{escape(', '.join(diagram.function_names) if diagram.function_names else 'No functions found')}</td>"
            "</tr>"
        )
        for diagram in written_diagrams
    )
    if not rows:
        rows = '<tr><td colspan="3">No diagrams were generated.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Rusta NSD Index</title>
    <style>
      body {{
        font-family: system-ui, sans-serif;
        margin: 0;
        padding: 24px;
        background: #0c121d;
        color: #d8e1f7;
      }}
      .panel {{
        max-width: 1120px;
        margin: 0 auto;
        background: #131c2b;
        border: 1px solid #31415f;
        border-radius: 14px;
        overflow: hidden;
      }}
      .head {{
        padding: 16px 20px;
        background: #1b2740;
        border-bottom: 1px solid #31415f;
      }}
      .title {{
        margin: 0 0 6px;
        font-size: 18px;
      }}
      .path {{
        margin: 0;
        font-family: ui-monospace, monospace;
        font-size: 12px;
        color: #9cb1dc;
        overflow-wrap: anywhere;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th, td {{
        padding: 12px 16px;
        border-top: 1px solid #24324d;
        text-align: left;
        vertical-align: top;
      }}
      th {{
        background: #172131;
      }}
      a {{
        color: #9cc2ff;
        text-decoration: none;
      }}
      a:hover {{
        text-decoration: underline;
      }}
    </style>
  </head>
  <body>
    <div class="panel">
      <div class="head">
        <h1 class="title">Rusta Nassi Bundle</h1>
        <p class="path">{escape(root_path)}</p>
      </div>
      <table>
        <thead>
          <tr>
            <th>Source</th>
            <th>Functions</th>
            <th>Names</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
  </body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
