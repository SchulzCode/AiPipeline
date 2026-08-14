import json
from pathlib import Path

from aipipe.quality import autodetect_quality


def test_node_only_uses_existing_scripts(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}), encoding="utf-8")
    commands = autodetect_quality(tmp_path)
    assert commands == {"test": "npm run test", "lint": "npm run lint"}


def test_python_detects_pytest(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    assert autodetect_quality(tmp_path)["test"] == "python -m pytest"
