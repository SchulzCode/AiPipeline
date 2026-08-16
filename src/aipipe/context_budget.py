"""Deterministic, provider-agnostic context-size budgets.

No LLM call, tokenizer, or network access is involved: token counts are a
conservative character-based estimate, and budgets are a static lookup table
keyed by role and :class:`~aipipe.models.ContextClass`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from .models import ContextClass

# Conservative chars-per-token estimate. Real tokenizers average ~4 chars per
# token for English text; using 3 deliberately over-estimates token usage so
# the derived character budget stays on the safe (smaller) side.
CHARS_PER_TOKEN = 3

ROLE_PLANNER = "PLANNER"
ROLE_IMPLEMENTER = "IMPLEMENTER"
ROLE_IMPLEMENTER_REMEDIATION = "IMPLEMENTER_REMEDIATION"
ROLE_REVIEWER = "REVIEWER"
ROLE_SECURITY_REVIEWER = "SECURITY_REVIEWER"

# One total assembled-context token budget per role x ContextClass. Values
# are monotonically increasing SMALL < NORMAL < DEEP for every role, and
# remediation runs get a smaller budget than the initial implementer run
# (they carry a diff + feedback instead of exploring from scratch).
ROLE_TOTAL_BUDGET_TOKENS: dict[str, dict[ContextClass, int]] = {
    ROLE_PLANNER: {
        ContextClass.SMALL: 12_000,
        ContextClass.NORMAL: 20_000,
        ContextClass.DEEP: 32_000,
    },
    ROLE_IMPLEMENTER: {
        ContextClass.SMALL: 14_000,
        ContextClass.NORMAL: 24_000,
        ContextClass.DEEP: 40_000,
    },
    ROLE_IMPLEMENTER_REMEDIATION: {
        ContextClass.SMALL: 10_000,
        ContextClass.NORMAL: 16_000,
        ContextClass.DEEP: 26_000,
    },
    ROLE_REVIEWER: {
        ContextClass.SMALL: 12_000,
        ContextClass.NORMAL: 20_000,
        ContextClass.DEEP: 32_000,
    },
    ROLE_SECURITY_REVIEWER: {
        ContextClass.SMALL: 12_000,
        ContextClass.NORMAL: 20_000,
        ContextClass.DEEP: 32_000,
    },
}

# Fallback for any role without a dedicated entry above (e.g. DISCOVERY_AGENT,
# ROUTER).
DEFAULT_TOTAL_BUDGET_TOKENS: dict[ContextClass, int] = {
    ContextClass.SMALL: 10_000,
    ContextClass.NORMAL: 16_000,
    ContextClass.DEEP: 26_000,
}


def estimate_tokens(text: str) -> int:
    """Deterministic, conservative token-count estimate for arbitrary text."""
    if not text:
        return 0
    return ceil(len(text) / CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ContextBudget:
    role: str
    context_class: ContextClass
    total_tokens: int

    @property
    def total_chars(self) -> int:
        return self.total_tokens * CHARS_PER_TOKEN


def budget_for(role: str | None, context_class: ContextClass | None) -> ContextBudget:
    cls = context_class if context_class is not None else ContextClass.NORMAL
    table = ROLE_TOTAL_BUDGET_TOKENS.get(role or "")
    if table is None:
        table = DEFAULT_TOTAL_BUDGET_TOKENS
    tokens = table.get(cls, DEFAULT_TOTAL_BUDGET_TOKENS[cls])
    return ContextBudget(role=role or "", context_class=cls, total_tokens=tokens)
