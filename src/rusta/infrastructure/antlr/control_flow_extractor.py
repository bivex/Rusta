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
    LoopFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    TryPropagateFlowStep,
    UnsafeFlowStep,
    WhileFlowStep,
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

            self.functions.append(
                FunctionControlFlow(
                    name=function_ctx.identifier().getText(),
                    signature=signature,
                    container=".".join(self._containers) or None,
                    steps=self._extract_block(block_ctx) if block_ctx is not None else (),
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
                # Check if the let statement contains special expressions
                expr_getter = getattr(let_ctx, "expression", None)
                expr_ctx = expr_getter() if callable(expr_getter) else expr_getter

                if expr_ctx is not None:
                    steps = self._extract_expression(expr_ctx)
                    # If we found special types (? or await), return them
                    if len(steps) == 1 and not isinstance(steps[0], ActionFlowStep):
                        # Wrap in a let action for context
                        return [ActionFlowStep(label=ctx.compact(let_ctx, limit=140)), steps[0]]
                    elif len(steps) > 1 and any(not isinstance(s, ActionFlowStep) for s in steps):
                        # Multiple special steps found
                        return [ActionFlowStep(label=ctx.compact(let_ctx, limit=140))] + steps
                return [ActionFlowStep(label=ctx.compact(let_ctx, limit=140))]
            if statement_ctx.expressionStatement() is not None:
                return self._extract_expression_statement(statement_ctx.expressionStatement())
            if statement_ctx.macroInvocationSemi() is not None:
                return [ActionFlowStep(ctx.compact(statement_ctx.macroInvocationSemi(), limit=140))]
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
                value = ctx.compact(value_ctx, limit=60) if value_ctx and not callable(value_ctx) else ""
                return [BreakWithValueFlowStep(label=label, value=value)]

            # continue (ContinueExpressionContext) - render as action
            if ctx_type == "ContinueExpressionContext":
                return [ActionFlowStep(label=ctx.compact(expression_ctx, limit=140))]

            # closure (ClosureExpression_Context)
            if ctx_type == "ClosureExpression_Context":
                sig = ctx.compact(expression_ctx, limit=80)
                block = getattr(expression_ctx, "blockExpression", None)
                # blockExpression might be a getter method
                if callable(block):
                    block = block()
                if block is not None:
                    return [ClosureFlowStep(signature=sig, body_steps=self._extract_block(block))]
                return [ClosureFlowStep(signature=sig, body_steps=())]

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

        def _extract_match(self, match_ctx) -> SwitchFlowStep:
            cases: list[SwitchCaseFlow] = []
            arms_ctx = match_ctx.matchArms()
            if arms_ctx is not None:
                arms = arms_ctx.matchArm()
                arm_expressions = arms_ctx.matchArmExpression()

                for arm_ctx, arm_expression_ctx in zip(arms[:-1], arm_expressions, strict=False):
                    cases.append(
                        SwitchCaseFlow(
                            label=ctx.compact(arm_ctx, limit=120),
                            steps=tuple(self._extract_match_arm_expression(arm_expression_ctx)),
                        )
                    )

                if arms:
                    last_arm_ctx = arms[-1]
                    cases.append(
                        SwitchCaseFlow(
                            label=ctx.compact(last_arm_ctx, limit=120),
                            steps=tuple(self._extract_expression(arms_ctx.expression())),
                        )
                    )

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
