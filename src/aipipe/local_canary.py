from __future__ import annotations

import hashlib
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .agents.base import AgentAdapter, AgentResult
from .agents.qwen import QwenAdapter
from .quality import QualityEngine
from .util import run


_CANARY_FILE = "canary_output.txt"
_CANARY_VALUE = "LOCAL_QWEN_CANARY_OK"


@dataclass(frozen=True)
class LocalQwenCanaryResult:
    ok: bool
    read_only_ok: bool
    implementation_ok: bool
    verification_ok: bool
    planner_output: str
    implementation_output: str
    input_tokens: int
    output_tokens: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _workspace_digest(workspace: Path) -> str:
    """Hash workspace-visible files while ignoring Git's internal metadata."""
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(workspace)
        if ".git" in relative.parts or not path.is_file():
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _verification_engine() -> QualityEngine:
    command = (
        'python -c "from pathlib import Path; '
        f"assert Path('{_CANARY_FILE}').read_text(encoding='utf-8').strip() == '{_CANARY_VALUE}'"
        '"'
    )
    return QualityEngine({"local-qwen-canary": command}, timeout=30)


def _run_in_workspace(
    workspace: Path,
    *,
    adapter_factory: Callable[[], AgentAdapter] = QwenAdapter,  # type: ignore[assignment]
    quality_engine: QualityEngine | None = None,
) -> LocalQwenCanaryResult:
    """Exercise read-only and write-capable roles in one disposable Git repo."""
    init = run(["git", "init", "-q"], workspace, timeout=30)
    if not init.ok:
        return LocalQwenCanaryResult(
            False, False, False, False, "", "", 0, 0,
            f"Could not initialize canary Git repository: {init.stderr.strip()}",
        )

    (workspace / "README.md").write_text(
        "# Local Qwen canary\n\nThis disposable repository verifies AIpipe local-agent integration.\n",
        encoding="utf-8",
    )

    adapter = adapter_factory()
    before = _workspace_digest(workspace)
    planner = adapter.run(
        "PLANNER",
        "Inspect this disposable repository and briefly state its purpose. Do not modify any files.",
        workspace,
    )
    after = _workspace_digest(workspace)
    read_only_ok = planner.ok and before == after
    if not read_only_ok:
        detail = (
            "Read-only canary modified the workspace."
            if before != after
            else "Read-only Qwen invocation failed."
        )
        return LocalQwenCanaryResult(
            False,
            read_only_ok,
            False,
            False,
            planner.output,
            "",
            planner.input_tokens,
            planner.output_tokens,
            detail,
        )

    implementation = adapter.run(
        "IMPLEMENTER",
        (
            f"Create or replace {_CANARY_FILE} with exactly this single line followed by a newline: "
            f"{_CANARY_VALUE}. Do not create or modify any other workspace file. Do not commit."
        ),
        workspace,
    )
    implementation_ok = implementation.ok and (workspace / _CANARY_FILE).is_file()

    engine = quality_engine or _verification_engine()
    quality_results = engine.execute(workspace) if implementation_ok else []
    verification_ok = bool(quality_results) and all(result.ok for _, result in quality_results)

    ok = read_only_ok and implementation_ok and verification_ok
    if ok:
        detail = "Local Qwen completed read-only, implementation, and deterministic AIpipe verification stages."
    elif not implementation_ok:
        detail = "Implementation canary did not create the required workspace artifact successfully."
    else:
        evidence = next(
            (
                result.stderr.strip() or result.stdout.strip()
                for _, result in quality_results
                if not result.ok
            ),
            "required canary content was not verified",
        )
        detail = f"AIpipe deterministic verification failed: {evidence}"

    return LocalQwenCanaryResult(
        ok,
        read_only_ok,
        implementation_ok,
        verification_ok,
        planner.output,
        implementation.output,
        planner.input_tokens + implementation.input_tokens,
        planner.output_tokens + implementation.output_tokens,
        detail,
    )


def run_local_qwen_canary(
    *,
    adapter_factory: Callable[[], AgentAdapter] | None = None,
    quality_engine: QualityEngine | None = None,
) -> LocalQwenCanaryResult:
    """Run the real local-Qwen canary in an automatically cleaned workspace."""
    factory = adapter_factory or (lambda: QwenAdapter({}))
    with tempfile.TemporaryDirectory(prefix="aipipe-local-qwen-canary-") as tmp:
        return _run_in_workspace(
            Path(tmp),
            adapter_factory=factory,
            quality_engine=quality_engine,
        )
