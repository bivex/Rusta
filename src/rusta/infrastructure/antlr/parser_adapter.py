"""ANTLR-backed Rust parser adapter."""

from __future__ import annotations

from time import perf_counter

from rusta.domain.model import (
    GrammarVersion,
    ParseOutcome,
    ParseStatistics,
    SourceUnit,
    StructuralElement,
    StructuralElementKind,
)
from rusta.domain.ports import RustSyntaxParser
from rusta.infrastructure.antlr.runtime import (
    ANTLR_GRAMMAR_VERSION,
    load_generated_types,
    parse_source_text,
)


class AntlrRustSyntaxParser(RustSyntaxParser):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    @property
    def grammar_version(self) -> GrammarVersion:
        return ANTLR_GRAMMAR_VERSION

    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        started_at = perf_counter()
        try:
            parse_result = parse_source_text(source_unit.content, self._generated)
            structure_visitor = _build_structure_visitor(self._generated.visitor_type)()
            structure_visitor.visit(parse_result.tree)

            elements = tuple(structure_visitor.elements)
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

            return ParseOutcome.success(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                diagnostics=parse_result.diagnostics,
                structural_elements=elements,
                statistics=ParseStatistics(
                    token_count=len(parse_result.token_stream.tokens),
                    structural_element_count=len(elements),
                    diagnostic_count=len(parse_result.diagnostics),
                    elapsed_ms=elapsed_ms,
                ),
            )
        except Exception as error:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
            return ParseOutcome.technical_failure(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                message=str(error),
                elapsed_ms=elapsed_ms,
            )


def _build_structure_visitor(visitor_base: type) -> type:
    class RustStructureVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.elements: list[StructuralElement] = []
            self._containers: list[str] = []

        def visitUseDeclaration(self, ctx):
            import_path = ctx.useTree().getText()
            self._append(
                StructuralElementKind.USE,
                import_path,
                ctx,
                signature=f"use {import_path};",
            )
            return None

        def visitModule(self, ctx):
            name = ctx.identifier().getText()
            self._append(
                StructuralElementKind.MODULE,
                name,
                ctx,
                signature=ctx.getText(),
            )
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitTypeAlias(self, ctx):
            name = ctx.identifier().getText()
            self._append(
                StructuralElementKind.TYPE_ALIAS,
                name,
                ctx,
                signature=ctx.getText(),
            )
            return None

        def visitConstantItem(self, ctx):
            name = ctx.identifier().getText() if ctx.identifier() is not None else "_"
            self._append(
                StructuralElementKind.CONSTANT,
                name,
                ctx,
                signature=ctx.getText(),
            )
            return None

        def visitStaticItem(self, ctx):
            name = ctx.identifier().getText()
            self._append(
                StructuralElementKind.STATIC,
                name,
                ctx,
                signature=ctx.getText(),
            )
            return None

        def visitFunction_(self, ctx):
            name = ctx.identifier().getText()
            self._append(
                StructuralElementKind.FUNCTION,
                name,
                ctx,
                signature=ctx.getText(),
            )
            return None

        def visitStruct_(self, ctx):
            if ctx.structStruct() is not None:
                name = ctx.structStruct().identifier().getText()
            else:
                name = ctx.tupleStruct().identifier().getText()
            self._append(StructuralElementKind.STRUCT, name, ctx, signature=ctx.getText())
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitEnumeration(self, ctx):
            name = ctx.identifier().getText()
            self._append(StructuralElementKind.ENUM, name, ctx, signature=ctx.getText())
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitUnion_(self, ctx):
            name = ctx.identifier().getText()
            self._append(StructuralElementKind.UNION, name, ctx, signature=ctx.getText())
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitTrait_(self, ctx):
            name = ctx.identifier().getText()
            self._append(StructuralElementKind.TRAIT, name, ctx, signature=ctx.getText())
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitImplementation(self, ctx):
            name = self._extract_impl_name(ctx)
            self._append(
                StructuralElementKind.IMPLEMENTATION,
                name,
                ctx,
                signature=ctx.getText(),
            )
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def _append(self, kind, name: str, ctx, signature: str | None = None) -> None:
            container = ".".join(self._containers) if self._containers else None
            self.elements.append(
                StructuralElement(
                    kind=kind,
                    name=name,
                    line=ctx.start.line,
                    column=ctx.start.column,
                    container=container,
                    signature=signature,
                )
            )

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _extract_impl_name(self, ctx) -> str:
            if ctx.inherentImpl() is not None:
                return ctx.inherentImpl().type_().getText()
            if ctx.traitImpl() is not None:
                trait_path = ctx.traitImpl().typePath().getText()
                target_type = ctx.traitImpl().type_().getText()
                return f"{trait_path} for {target_type}"
            return "impl"

    return RustStructureVisitor
