"""Extract structured control flow from Rust source through ANTLR."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rusta.domain.control_flow import (
    ActionFlowStep,
    AwaitFlowStep,
    BreakWithValueFlowStep,
    ClosureFlowStep,
    ControlFlowDiagram,
    ControlFlowStep,
    ForInFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    LabeledBlockFlowStep,
    LetElseFlowStep,
    LoopFlowStep,
    MacroCallFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    TryPropagateFlowStep,
    UnsafeFlowStep,
    WhileFlowStep,
    YieldFlowStep,
    GenBlockFlowStep,
)
from rusta.domain.model import SourceUnit
from rusta.domain.ports import RustControlFlowExtractor
from rusta.infrastructure.antlr.runtime import load_generated_types, parse_source_text


@dataclass(frozen=True, slots=True)
class _ExtractorContext:
    source_text: str
    token_stream: object

    def text(self, ctx) -> str:
        if ctx is None:
            return ""
        start = getattr(ctx.start, "start", None)
        stop = getattr(ctx.stop, "stop", None)
        if isinstance(start, int) and isinstance(stop, int) and 0 <= start <= stop:
            return self.source_text[start : stop + 1]
        return self.token_stream.getText(
            start=ctx.start.tokenIndex,
            stop=ctx.stop.tokenIndex,
        )

    def text_between(self, start_token, end_token) -> str:
        if start_token is None or end_token is None:
            return ""
        start = getattr(start_token, "start", None)
        stop = getattr(end_token, "stop", None)
        if isinstance(start, int) and isinstance(stop, int) and 0 <= start <= stop:
            return self.source_text[start : stop + 1]
        return self.token_stream.getText(
            start=start_token.tokenIndex,
            stop=end_token.tokenIndex,
        )

    def compact(self, ctx, *, limit: int = 96) -> str:
        text = re.sub(r"\s+", " ", self.text(ctx)).strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}..."

    def compact_text(self, text: str, *, limit: int = 96) -> str:
        compacted = re.sub(r"\s+", " ", text).strip()
        if len(compacted) <= limit:
            return compacted
        return f"{compacted[: limit - 1]}..."


class AntlrRustControlFlowExtractor(RustControlFlowExtractor):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        parse_result = parse_source_text(source_unit.content, self._generated)
        visitor = _build_control_flow_visitor(
            self._generated.visitor_type,
            _ExtractorContext(
                source_text=source_unit.content,
                token_stream=parse_result.token_stream,
            ),
        )()
        visitor.visit(parse_result.tree)
        return ControlFlowDiagram(
            source_location=source_unit.location,
            functions=tuple(visitor.functions),
        )


def _build_control_flow_visitor(visitor_base: type, ctx: _ExtractorContext) -> type:
    class RustControlFlowVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.functions: list[FunctionControlFlow] = []
            self._containers: list[str] = []

        def visitModule(self, module_ctx):
            return self._with_container(
                module_ctx.identifier().getText(),
                lambda: self.visitChildren(module_ctx),
            )

        def visitTrait_(self, trait_ctx):
            return self._with_container(
                trait_ctx.identifier().getText(),
                lambda: self.visitChildren(trait_ctx),
            )

        def visitImplementation(self, impl_ctx):
            return self._with_container(
                self._extract_impl_name(impl_ctx),
                lambda: self.visitChildren(impl_ctx),
            )

        def visitFunction_(self, function_ctx):
            block_ctx = function_ctx.blockExpression()
            signature_end = (
                block_ctx.start.tokenIndex - 1
                if block_ctx is not None
                else function_ctx.stop.tokenIndex
            )
            end_token = ctx.token_stream.tokens[signature_end]
            signature = ctx.compact_text(ctx.text_between(function_ctx.start, end_token), limit=180)

            qualifiers_getter = getattr(function_ctx, "functionQualifiers", None)
            qualifiers = qualifiers_getter() if callable(qualifiers_getter) else None
            is_async = qualifiers is not None and qualifiers.KW_ASYNC() is not None
            is_unsafe = qualifiers is not None and qualifiers.KW_UNSAFE() is not None
            is_const = qualifiers is not None and qualifiers.KW_CONST() is not None

            where_clause_getter = getattr(function_ctx, "whereClause", None)
            where_ctx = where_clause_getter() if callable(where_clause_getter) else None
            where_clause = ctx.compact(where_ctx, limit=240) if where_ctx is not None else None

            # Generic const params: fn foo<const N: usize>
            const_params: tuple[str, ...] = ()
            try:
                gp_getter = getattr(function_ctx, "genericParams", None)
                gp_ctx = gp_getter() if callable(gp_getter) else None
                if gp_ctx is not None:
                    gp_getter2 = getattr(gp_ctx, "genericParam", None)
                    gp_list = gp_getter2() if callable(gp_getter2) else []
                    collected = []
                    for gp in (gp_list or []):
                        cp_getter = getattr(gp, "constParam", None)
                        cp = cp_getter() if callable(cp_getter) else None
                        if cp is not None:
                            collected.append(ctx.compact(cp, limit=80))
                    const_params = tuple(collected)
            except Exception:
                pass

            # Outer attributes are on the grandparent ItemContext (outerAttribute* visItem)
            attributes: tuple[str, ...] = ()
            try:
                item_ctx = function_ctx.parentCtx.parentCtx
                outer_attr_getter = getattr(item_ctx, "outerAttribute", None)
                if callable(outer_attr_getter):
                    attrs = outer_attr_getter()
                    if attrs:
                        attributes = tuple(ctx.compact(a, limit=120) for a in attrs)
            except Exception:
                pass

            self.functions.append(
                FunctionControlFlow(
                    name=function_ctx.identifier().getText(),
                    signature=signature,
                    container=".".join(self._containers) or None,
                    steps=self._extract_block(block_ctx) if block_ctx is not None else (),
                    is_async=is_async,
                    is_unsafe=is_unsafe,
                    is_const=is_const,
                    where_clause=where_clause,
                    attributes=attributes,
                    const_params=const_params,
                )
            )
            return None

        def _extract_block(self, block_ctx) -> tuple[ControlFlowStep, ...]:
            if block_ctx is None or block_ctx.statements() is None:
                return ()

            statements_ctx = block_ctx.statements()
            steps: list[ControlFlowStep] = []
            for statement_ctx in statements_ctx.statement():
                steps.extend(self._extract_statement(statement_ctx))

            tail_expression = statements_ctx.expression()
            if tail_expression is not None:
                steps.extend(self._extract_expression(tail_expression))

            return tuple(steps)

        def _extract_statement(self, statement_ctx) -> list[ControlFlowStep]:
            if statement_ctx.letStatement() is not None:
                let_ctx = statement_ctx.letStatement()

                # let-else: let <pattern> = <expr> else { <block> }
                else_block_getter = getattr(let_ctx, "blockExpression", None)
                else_block = else_block_getter() if callable(else_block_getter) else None
                kw_else_getter = getattr(let_ctx, "KW_ELSE", None)
                has_else = kw_else_getter is not None and (
                    kw_else_getter() if callable(kw_else_getter) else kw_else_getter
                ) is not None
                if has_else and else_block is not None:
                    pattern_getter = getattr(let_ctx, "patternNoTopAlt", None)
                    pattern_ctx = pattern_getter() if callable(pattern_getter) else None
                    expr_getter = getattr(let_ctx, "expression", None)
                    expr_ctx = expr_getter() if callable(expr_getter) else None
                    pattern_text = (
                        f"let {ctx.compact(pattern_ctx, limit=60)} = "
                        f"{ctx.compact(expr_ctx, limit=60)}"
                        if pattern_ctx and expr_ctx
                        else ctx.compact(let_ctx, limit=120)
                    )
                    return [LetElseFlowStep(
                        pattern=pattern_text,
                        else_steps=self._extract_block(else_block),
                    )]

                # Regular let — check for special RHS expressions (? or await)
                expr_getter = getattr(let_ctx, "expression", None)
                expr_ctx = expr_getter() if callable(expr_getter) else expr_getter
                if expr_ctx is not None:
                    steps = self._extract_expression(expr_ctx)
                    if len(steps) == 1 and not isinstance(steps[0], ActionFlowStep):
                        return [ActionFlowStep(label=ctx.compact(let_ctx, limit=140)), steps[0]]
                    elif len(steps) > 1 and any(not isinstance(s, ActionFlowStep) for s in steps):
                        return [ActionFlowStep(label=ctx.compact(let_ctx, limit=140))] + steps
                return [ActionFlowStep(label=ctx.compact(let_ctx, limit=140))]

            if statement_ctx.expressionStatement() is not None:
                return self._extract_expression_statement(statement_ctx.expressionStatement())
            if statement_ctx.macroInvocationSemi() is not None:
                return [MacroCallFlowStep(label=ctx.compact(statement_ctx.macroInvocationSemi(), limit=140))]
            # println!/assert!/vec! etc. parsed as statement → item → macroItem → macroInvocationSemi
            item_getter = getattr(statement_ctx, "item", None)
            if callable(item_getter):
                item_ctx = item_getter()
                if item_ctx is not None:
                    macro_item_getter = getattr(item_ctx, "macroItem", None)
                    if callable(macro_item_getter):
                        macro_item = macro_item_getter()
                        if macro_item is not None:
                            macro_invoc_getter = getattr(macro_item, "macroInvocationSemi", None)
                            if callable(macro_invoc_getter):
                                macro_invoc = macro_invoc_getter()
                                if macro_invoc is not None:
                                    return [MacroCallFlowStep(label=ctx.compact(macro_invoc, limit=140))]
            return []

        def _extract_expression_statement(self, expression_statement_ctx) -> list[ControlFlowStep]:
            if expression_statement_ctx.expressionWithBlock() is not None:
                return self._extract_expression_with_block(expression_statement_ctx.expressionWithBlock())
            if expression_statement_ctx.expression() is not None:
                return self._extract_expression(expression_statement_ctx.expression())
            return []

        def _extract_expression(self, expression_ctx) -> list[ControlFlowStep]:
            nested_with_block = getattr(expression_ctx, "expressionWithBlock", None)
            if callable(nested_with_block):
                with_block_ctx = nested_with_block()
                if with_block_ctx is not None:
                    return self._extract_expression_with_block(with_block_ctx)

            # Check for specific expression types using context type names
            ctx_type = type(expression_ctx).__name__

            # ? operator (ErrorPropagationExpressionContext)
            if ctx_type == "ErrorPropagationExpressionContext":
                return [TryPropagateFlowStep(label=ctx.compact(expression_ctx, limit=140))]

            # .await (AwaitExpressionContext)
            if ctx_type == "AwaitExpressionContext":
                return [AwaitFlowStep(label=ctx.compact(expression_ctx, limit=140))]

            # break with optional label and value (BreakExpressionContext)
            if ctx_type == "BreakExpressionContext":
                label_token = getattr(expression_ctx, "LIFETIME_OR_LABEL", None)
                # Check if it's a terminal node (has getText) not a getter method
                if label_token and not callable(label_token):
                    label = label_token.getText().removesuffix(":")
                else:
                    label = ""
                value_ctx = getattr(expression_ctx, "expression", None)
                # Call the getter if it's callable
                if value_ctx is not None:
                    if callable(value_ctx):
                        value_ctx = value_ctx()
                    value = ctx.compact(value_ctx, limit=60) if value_ctx else ""
                else:
                    value = ""
                return [BreakWithValueFlowStep(label=label, value=value)]

            # continue (ContinueExpressionContext) - render as action (with optional label)
            if ctx_type == "ContinueExpressionContext":
                label_token = getattr(expression_ctx, "LIFETIME_OR_LABEL", None)
                if label_token is not None and not callable(label_token):
                    return [ActionFlowStep(label=f"continue {label_token.getText()}")]
                return [ActionFlowStep(label=ctx.compact(expression_ctx, limit=140))]

            # closure (ClosureExpression_Context)
            if ctx_type == "ClosureExpression_Context":
                # The ANTLR grammar has a nested structure for closures:
                # ClosureExpression_Context -> closureExpression() -> ClosureExpressionContext -> closureParameters()
                inner_closure = getattr(expression_ctx, "closureExpression", None)
                if callable(inner_closure):
                    inner_closure = inner_closure()
                if inner_closure is not None:
                    params_ctx = getattr(inner_closure, "closureParameters", None)
                    if callable(params_ctx):
                        params_ctx = params_ctx()
                    sig = ctx.compact(params_ctx, limit=80) if params_ctx else "|...|"
                else:
                    sig = "|...|"

                # Body is on inner_closure (ClosureExpressionContext), not on the outer wrapper
                body_source = inner_closure if inner_closure is not None else expression_ctx
                block = getattr(body_source, "blockExpression", None)
                if callable(block):
                    block = block()
                if block is not None:
                    return [ClosureFlowStep(signature=sig, body_steps=self._extract_block(block))]
                # Closures can also have an expression body (including ExpressionWithBlock_)
                expr_body = getattr(body_source, "expression", None)
                if callable(expr_body):
                    expr_body = expr_body()
                if expr_body is not None:
                    return [ClosureFlowStep(signature=sig, body_steps=tuple(self._extract_expression(expr_body)))]
                return [ClosureFlowStep(signature=sig, body_steps=())]

            # yield (YieldExpressionContext) — coroutine/generator
            if ctx_type == "YieldExpressionContext":
                expr_getter = getattr(expression_ctx, "expression", None)
                expr_ctx = expr_getter() if callable(expr_getter) else None
                value = ctx.compact(expr_ctx, limit=80) if expr_ctx else ""
                return [YieldFlowStep(value=value)]

            # return (ReturnExpressionContext)
            if ctx_type == "ReturnExpressionContext":
                return [ActionFlowStep(label=ctx.compact(expression_ctx, limit=140))]

            return [ActionFlowStep(label=ctx.compact(expression_ctx, limit=140))]

        def _extract_expression_with_block(self, expression_with_block_ctx) -> list[ControlFlowStep]:
            nested = expression_with_block_ctx.expressionWithBlock()
            if nested is not None:
                return self._extract_expression_with_block(nested)
            if expression_with_block_ctx.blockExpression() is not None:
                return list(self._extract_block(expression_with_block_ctx.blockExpression()))
            if expression_with_block_ctx.asyncBlockExpression() is not None:
                async_block = expression_with_block_ctx.asyncBlockExpression()
                if async_block.blockExpression() is not None:
                    # For async blocks, we show as a special node since .await points happen inside
                    return list(self._extract_block(async_block.blockExpression()))
                return [ActionFlowStep(ctx.compact(expression_with_block_ctx.asyncBlockExpression(), limit=140))]
            if expression_with_block_ctx.unsafeBlockExpression() is not None:
                unsafe_block = expression_with_block_ctx.unsafeBlockExpression()
                if unsafe_block.blockExpression() is not None:
                    return [UnsafeFlowStep(body_steps=self._extract_block(unsafe_block.blockExpression()))]
                return [ActionFlowStep(ctx.compact(expression_with_block_ctx.unsafeBlockExpression(), limit=140))]
            if expression_with_block_ctx.genBlockExpression() is not None:
                gen_block = expression_with_block_ctx.genBlockExpression()
                if gen_block.blockExpression() is not None:
                    return [GenBlockFlowStep(body_steps=self._extract_block(gen_block.blockExpression()))]
                return [ActionFlowStep(ctx.compact(expression_with_block_ctx.genBlockExpression(), limit=140))]
            if expression_with_block_ctx.asyncGenBlockExpression() is not None:
                async_gen = expression_with_block_ctx.asyncGenBlockExpression()
                if async_gen.blockExpression() is not None:
                    return [GenBlockFlowStep(body_steps=self._extract_block(async_gen.blockExpression()), is_async=True)]
                return [ActionFlowStep(ctx.compact(expression_with_block_ctx.asyncGenBlockExpression(), limit=140))]
            if expression_with_block_ctx.loopExpression() is not None:
                return [self._extract_loop(expression_with_block_ctx.loopExpression())]
            if expression_with_block_ctx.ifExpression() is not None:
                return [self._extract_if(expression_with_block_ctx.ifExpression())]
            if expression_with_block_ctx.ifLetExpression() is not None:
                return [self._extract_if_let(expression_with_block_ctx.ifLetExpression())]
            if expression_with_block_ctx.matchExpression() is not None:
                return [self._extract_match(expression_with_block_ctx.matchExpression())]
            return [ActionFlowStep(ctx.compact(expression_with_block_ctx, limit=140))]

        def _extract_if(self, if_ctx) -> IfFlowStep:
            then_steps = self._extract_block(if_ctx.blockExpression(0))
            else_steps: tuple[ControlFlowStep, ...] = ()

            block_count = len(if_ctx.blockExpression())
            if block_count > 1:
                else_steps = self._extract_block(if_ctx.blockExpression(1))
            elif if_ctx.ifExpression() is not None:
                else_steps = (self._extract_if(if_ctx.ifExpression()),)
            elif if_ctx.ifLetExpression() is not None:
                else_steps = (self._extract_if_let(if_ctx.ifLetExpression()),)

            return IfFlowStep(
                condition=ctx.compact(if_ctx.expression(), limit=120),
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _extract_if_let(self, if_let_ctx) -> IfFlowStep:
            then_steps = self._extract_block(if_let_ctx.blockExpression(0))
            else_steps: tuple[ControlFlowStep, ...] = ()

            block_count = len(if_let_ctx.blockExpression())
            if block_count > 1:
                else_steps = self._extract_block(if_let_ctx.blockExpression(1))
            elif if_let_ctx.ifExpression() is not None:
                else_steps = (self._extract_if(if_let_ctx.ifExpression()),)
            elif if_let_ctx.ifLetExpression() is not None:
                else_steps = (self._extract_if_let(if_let_ctx.ifLetExpression()),)

            condition = (
                f"let {ctx.compact(if_let_ctx.pattern(), limit=60)} = "
                f"{ctx.compact(if_let_ctx.expression(), limit=60)}"
            )
            return IfFlowStep(
                condition=condition,
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _extract_loop(self, loop_ctx) -> ControlFlowStep:
            if loop_ctx.infiniteLoopExpression() is not None:
                block_ctx = loop_ctx.infiniteLoopExpression().blockExpression()
                label = (
                    ctx.compact(loop_ctx.loopLabel(), limit=32).removesuffix(":")
                    if loop_ctx.loopLabel() is not None
                    else "loop"
                )
                return LoopFlowStep(label=label, body_steps=self._extract_block(block_ctx))

            predicate_getter = loop_ctx.predicateLoopExpression
            predicate_ctx = predicate_getter() if callable(predicate_getter) else predicate_getter
            if predicate_ctx is not None:
                expr_getter = getattr(predicate_ctx, "expression", None)
                expr = expr_getter() if callable(expr_getter) else expr_getter
                block_getter = getattr(predicate_ctx, "blockExpression", None)
                block = block_getter() if callable(block_getter) else block_getter
                return WhileFlowStep(
                    condition=ctx.compact(expr, limit=120) if expr else "",
                    body_steps=self._extract_block(block) if block else (),
                )

            pred_pattern_getter = loop_ctx.predicatePatternLoopExpression
            pred_pattern_ctx = pred_pattern_getter() if callable(pred_pattern_getter) else pred_pattern_getter
            if pred_pattern_ctx is not None:
                pattern_getter = getattr(pred_pattern_ctx, "pattern", None)
                pattern = pattern_getter() if callable(pattern_getter) else pattern_getter
                expr_getter = getattr(pred_pattern_ctx, "expression", None)
                expr = expr_getter() if callable(expr_getter) else expr_getter
                block_getter = getattr(pred_pattern_ctx, "blockExpression", None)
                block = block_getter() if callable(block_getter) else block_getter
                return WhileFlowStep(
                    condition=(
                        f"let {ctx.compact(pattern, limit=60)} = "
                        f"{ctx.compact(expr, limit=60)}"
                    ) if pattern and expr else "",
                    body_steps=self._extract_block(block) if block else (),
                )

            iterator_getter = loop_ctx.iteratorLoopExpression
            iterator_ctx = iterator_getter() if callable(iterator_getter) else iterator_getter
            if iterator_ctx is not None:
                pattern_getter = getattr(iterator_ctx, "pattern", None)
                pattern = pattern_getter() if callable(pattern_getter) else pattern_getter
                expr_getter = getattr(iterator_ctx, "expression", None)
                expr = expr_getter() if callable(expr_getter) else expr_getter
                block_getter = getattr(iterator_ctx, "blockExpression", None)
                block = block_getter() if callable(block_getter) else block_getter
                return ForInFlowStep(
                    header=(
                        f"{ctx.compact(pattern, limit=60)} in "
                        f"{ctx.compact(expr, limit=60)}"
                    ) if pattern and expr else "",
                    body_steps=self._extract_block(block) if block else (),
                )

            # Fallback - shouldn't happen but handle gracefully
            return ActionFlowStep(label=ctx.compact(loop_ctx, limit=140))

        def _pattern_has_range(self, pattern_ctx) -> bool:
            """Return True if any alternative in the pattern is a range pattern."""
            if pattern_ctx is None:
                return False
            alts_getter = getattr(pattern_ctx, "patternNoTopAlt", None)
            if not callable(alts_getter):
                return False
            for alt in (alts_getter() or []):
                rp_getter = getattr(alt, "rangePattern", None)
                if callable(rp_getter) and rp_getter() is not None:
                    return True
            return False

        def _extract_arm(self, arm_ctx) -> tuple[str, str | None, bool]:
            """Return (label, guard, is_range) for a single match arm."""
            guard_getter = getattr(arm_ctx, "matchArmGuard", None)
            guard_ctx = guard_getter() if callable(guard_getter) else None
            guard = None
            if guard_ctx is not None:
                expr_getter = getattr(guard_ctx, "expression", None)
                expr = expr_getter() if callable(expr_getter) else None
                guard = ctx.compact(expr, limit=80) if expr else None

            pattern_getter = getattr(arm_ctx, "pattern", None)
            pattern_ctx = pattern_getter() if callable(pattern_getter) else None
            label = ctx.compact(pattern_ctx, limit=120) if pattern_ctx else "_"
            is_range = self._pattern_has_range(pattern_ctx)
            return label, guard, is_range

        def _extract_match(self, match_ctx) -> SwitchFlowStep:
            cases: list[SwitchCaseFlow] = []
            arms_ctx = match_ctx.matchArms()
            if arms_ctx is not None:
                arms = arms_ctx.matchArm()
                arm_expressions = arms_ctx.matchArmExpression()

                for arm_ctx, arm_expression_ctx in zip(arms[:-1], arm_expressions, strict=False):
                    label, guard, is_range = self._extract_arm(arm_ctx)
                    cases.append(SwitchCaseFlow(
                        label=label,
                        steps=tuple(self._extract_match_arm_expression(arm_expression_ctx)),
                        guard=guard,
                        is_range=is_range,
                    ))

                if arms:
                    label, guard, is_range = self._extract_arm(arms[-1])
                    cases.append(SwitchCaseFlow(
                        label=label,
                        steps=tuple(self._extract_expression(arms_ctx.expression())),
                        guard=guard,
                        is_range=is_range,
                    ))

            return SwitchFlowStep(
                expression=ctx.compact(match_ctx.expression(), limit=120),
                cases=tuple(cases),
            )

        def _extract_match_arm_expression(self, match_arm_expression_ctx) -> list[ControlFlowStep]:
            if match_arm_expression_ctx.expressionWithBlock() is not None:
                return self._extract_expression_with_block(match_arm_expression_ctx.expressionWithBlock())
            if match_arm_expression_ctx.expression() is not None:
                return self._extract_expression(match_arm_expression_ctx.expression())
            return [ActionFlowStep(ctx.compact(match_arm_expression_ctx, limit=140))]

        def _extract_impl_name(self, impl_ctx) -> str:
            if impl_ctx.inherentImpl() is not None:
                return ctx.compact(impl_ctx.inherentImpl().type_(), limit=120)
            if impl_ctx.traitImpl() is not None:
                return (
                    f"{ctx.compact(impl_ctx.traitImpl().typePath(), limit=60)} for "
                    f"{ctx.compact(impl_ctx.traitImpl().type_(), limit=60)}"
                )
            return "impl"

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

    return RustControlFlowVisitor
