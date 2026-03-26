"""Domain model for structured control flow diagrams."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControlFlowStep:
    """Base type for a structured control flow step."""


@dataclass(frozen=True, slots=True)
class ActionFlowStep(ControlFlowStep):
    label: str


@dataclass(frozen=True, slots=True)
class IfFlowStep(ControlFlowStep):
    condition: str
    then_steps: tuple[ControlFlowStep, ...]
    else_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class GuardFlowStep(ControlFlowStep):
    condition: str
    else_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class WhileFlowStep(ControlFlowStep):
    condition: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class LoopFlowStep(ControlFlowStep):
    label: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class ForInFlowStep(ControlFlowStep):
    header: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class RepeatWhileFlowStep(ControlFlowStep):
    condition: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class SwitchCaseFlow:
    label: str
    steps: tuple[ControlFlowStep, ...]
    guard: str | None = None  # Match guard condition (if any)
    is_range: bool = False  # Whether this is a range pattern


@dataclass(frozen=True, slots=True)
class SwitchFlowStep(ControlFlowStep):
    expression: str
    cases: tuple[SwitchCaseFlow, ...]


@dataclass(frozen=True, slots=True)
class CatchClauseFlow:
    pattern: str
    steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class DoCatchFlowStep(ControlFlowStep):
    body_steps: tuple[ControlFlowStep, ...]
    catches: tuple[CatchClauseFlow, ...]


@dataclass(frozen=True, slots=True)
class DeferFlowStep(ControlFlowStep):
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class TryPropagateFlowStep(ControlFlowStep):
    """Represents the ? operator for error propagation."""
    label: str


@dataclass(frozen=True, slots=True)
class AwaitFlowStep(ControlFlowStep):
    """Represents an .await point in async code."""
    label: str


@dataclass(frozen=True, slots=True)
class UnsafeFlowStep(ControlFlowStep):
    """Represents an unsafe block."""
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class LabeledBlockFlowStep(ControlFlowStep):
    """Represents a labeled block ('label: { ... })."""
    label: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class ClosureFlowStep(ControlFlowStep):
    """Represents a closure/lambda expression."""
    signature: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class BreakWithValueFlowStep(ControlFlowStep):
    """Represents a break with a value expression."""
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class LetElseFlowStep(ControlFlowStep):
    """Represents a let-else statement (Rust 1.65+)."""
    pattern: str
    else_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class ElseIfChainFlowStep(ControlFlowStep):
    """Represents an if-else-if chain for better visualization."""
    conditions: tuple[tuple[str, tuple[ControlFlowStep, ...]], ...]
    # Each tuple is (condition, then_steps), with optional else_steps at the end


@dataclass(frozen=True, slots=True)
class FunctionControlFlow:
    name: str
    signature: str
    container: str | None
    steps: tuple[ControlFlowStep, ...]

    @property
    def qualified_name(self) -> str:
        if self.container:
            return f"{self.container}.{self.name}"
        return self.name


@dataclass(frozen=True, slots=True)
class ControlFlowDiagram:
    source_location: str
    functions: tuple[FunctionControlFlow, ...]
