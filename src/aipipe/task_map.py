"""Bounded, deterministic Planner -> Implementer task-map handoff.

The Planner is asked (see ``PLANNER_SUFFIX`` in ``prompts.py``) to emit one
trailing JSON object summarizing what it already discovered while exploring
the repository, so the initial Implementer does not have to broadly
rediscover the same structure. Parsing here is pure/local (no LLM call,
no I/O): a malformed or missing task map must never block a task, only
degrade to the current behavior of an Implementer prompt with no map.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .util import truncate

_JSON_DECODER = json.JSONDecoder()
_WHITESPACE_RE = re.compile(r"\s+")

# The exact TaskMap field names a Planner's trailing JSON block may use. A
# candidate JSON object is only treated as a task map if it contains at
# least one of these keys, the same way `reliability._parse_review_payload`
# requires a `verdict` key before treating JSON as a review envelope. This
# keeps an unrelated example JSON snippet elsewhere in the plan from being
# mistaken for the task map.
_FIELDS = (
    "relevant_files",
    "relevant_symbols",
    "likely_tests",
    "constraints",
    "risks",
    "out_of_scope",
)

# Hard bounds applied regardless of what the Planner returns. These keep the
# task map small and deterministic to parse/render, and make it structurally
# impossible to smuggle a full source file or large code block in as a
# single "item".
_MAX_ITEMS_PER_FIELD = 10
_MAX_ITEM_CHARS = 160
_RENDER_LIMIT = 2500


@dataclass(frozen=True)
class TaskMap:
    relevant_files: tuple[str, ...] = field(default_factory=tuple)
    relevant_symbols: tuple[str, ...] = field(default_factory=tuple)
    likely_tests: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    out_of_scope: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return not any(
            (
                self.relevant_files,
                self.relevant_symbols,
                self.likely_tests,
                self.constraints,
                self.risks,
                self.out_of_scope,
            )
        )


def _coerce_items(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    items: list[str] = []
    for entry in raw:
        if len(items) >= _MAX_ITEMS_PER_FIELD:
            break
        text = _WHITESPACE_RE.sub(" ", str(entry)).strip()
        if not text:
            continue
        # A plain prefix cut (not `truncate`'s head+tail marker, which would
        # keep a smuggled tail-of-file and can itself contain newlines) is
        # what makes it structurally impossible for one "item" to carry a
        # full source file or large code block through to the Implementer.
        items.append(text[:_MAX_ITEM_CHARS])
    return tuple(items)


def _task_map_from_payload(payload: dict) -> TaskMap | None:
    if not any(key in payload for key in _FIELDS):
        return None
    task_map = TaskMap(
        relevant_files=_coerce_items(payload.get("relevant_files")),
        relevant_symbols=_coerce_items(payload.get("relevant_symbols")),
        likely_tests=_coerce_items(payload.get("likely_tests")),
        constraints=_coerce_items(payload.get("constraints")),
        risks=_coerce_items(payload.get("risks")),
        out_of_scope=_coerce_items(payload.get("out_of_scope")),
    )
    return None if task_map.is_empty() else task_map


def parse_task_map(output: str) -> TaskMap | None:
    """Extract a bounded :class:`TaskMap` from raw Planner output.

    Uses ``json.JSONDecoder.raw_decode`` the same way
    ``reliability._embedded_review_payloads`` extracts review JSON from
    free-form prose, so a fenced or inline JSON object is found regardless
    of surrounding markdown. Returns ``None`` whenever no recognized,
    non-empty task map is present -- the only failure path, so callers can
    degrade safely to the current no-task-map behavior instead of raising.
    """
    if not output:
        return None

    index = 0
    while True:
        start = output.find("{", index)
        if start < 0:
            return None
        try:
            payload, consumed = _JSON_DECODER.raw_decode(output[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = start + max(consumed, 1)
        if not isinstance(payload, dict):
            continue
        task_map = _task_map_from_payload(payload)
        if task_map is not None:
            return task_map


def render_task_map(task_map: TaskMap) -> str:
    """Render a bounded task map as compact guidance text for the Implementer."""
    lines = [
        "# Task Map",
        "This is Planner-derived guidance about the repository, not a contract: "
        "the task goal, acceptance criteria, and out-of-scope constraints above "
        "always take precedence. Verify these files/symbols first instead of "
        "broadly re-exploring the repository, but still read and understand any "
        "code you modify, and expand beyond this map if it is incomplete or incorrect.",
    ]

    def _section(title: str, items: tuple[str, ...]) -> None:
        if not items:
            return
        lines.append(f"## {title}")
        lines.extend(f"- {item}" for item in items)

    _section("Relevant files", task_map.relevant_files)
    _section("Relevant symbols", task_map.relevant_symbols)
    _section("Likely tests", task_map.likely_tests)
    _section("Constraints", task_map.constraints)
    _section("Risks / compatibility concerns", task_map.risks)
    _section("Out of scope", task_map.out_of_scope)

    return truncate("\n".join(lines), _RENDER_LIMIT)
