import json

from aipipe.task_map import (
    _MAX_ITEM_CHARS,
    _MAX_ITEMS_PER_FIELD,
    _RENDER_LIMIT,
    TaskMap,
    parse_task_map,
    render_task_map,
)


def test_parse_task_map_extracts_all_fields_from_valid_json():
    output = (
        "Goal\nDo the thing.\n\n"
        "```json\n"
        + json.dumps(
            {
                "relevant_files": ["src/aipipe/orchestrator.py", "src/aipipe/context.py"],
                "relevant_symbols": ["Orchestrator.run", "ContextBuilder.build"],
                "likely_tests": ["tests/test_orchestrator_hardening.py"],
                "constraints": ["Planner stays read-only"],
                "risks": ["Must not block DEEP tasks without a map"],
                "out_of_scope": ["#50 constraint persistence"],
            }
        )
        + "\n```\n"
    )
    task_map = parse_task_map(output)
    assert task_map is not None
    assert task_map.relevant_files == ("src/aipipe/orchestrator.py", "src/aipipe/context.py")
    assert task_map.relevant_symbols == ("Orchestrator.run", "ContextBuilder.build")
    assert task_map.likely_tests == ("tests/test_orchestrator_hardening.py",)
    assert task_map.constraints == ("Planner stays read-only",)
    assert task_map.risks == ("Must not block DEEP tasks without a map",)
    assert task_map.out_of_scope == ("#50 constraint persistence",)


def test_parse_task_map_returns_none_for_empty_output():
    assert parse_task_map("") is None


def test_parse_task_map_returns_none_when_no_json_present():
    assert parse_task_map("Goal\nJust prose, no JSON at all.\n") is None


def test_parse_task_map_returns_none_for_malformed_json():
    output = "```json\n{relevant_files: [oops this is not valid json]}\n```\n"
    assert parse_task_map(output) is None


def test_parse_task_map_ignores_unrelated_json_objects():
    output = 'Here is an example config: {"foo": "bar", "baz": 1}\nNo task map here.'
    assert parse_task_map(output) is None


def test_parse_task_map_returns_none_when_all_fields_end_up_empty():
    output = '```json\n{"relevant_files": [], "constraints": ""}\n```\n'
    assert parse_task_map(output) is None


def test_parse_task_map_finds_the_task_map_after_an_unrelated_json_block():
    output = (
        'Example: {"foo": "bar"}\n\n'
        '```json\n{"relevant_files": ["a.py"]}\n```\n'
    )
    task_map = parse_task_map(output)
    assert task_map is not None
    assert task_map.relevant_files == ("a.py",)


# -- Size bounds --------------------------------------------------------


def test_parse_task_map_caps_item_count_per_field():
    output = "```json\n" + json.dumps({"relevant_files": [f"file_{i}.py" for i in range(50)]}) + "\n```\n"
    task_map = parse_task_map(output)
    assert task_map is not None
    assert len(task_map.relevant_files) == _MAX_ITEMS_PER_FIELD


def test_parse_task_map_caps_characters_per_item_and_collapses_whitespace():
    huge_item = "x" * 5000
    output = "```json\n" + json.dumps({"constraints": [huge_item]}) + "\n```\n"
    task_map = parse_task_map(output)
    assert task_map is not None
    assert len(task_map.constraints[0]) <= _MAX_ITEM_CHARS


def test_parse_task_map_collapses_multiline_code_block_style_content_in_an_item():
    code_like = "def handler():\n    return {\n        'a': 1,\n    }\n" * 20
    output = "```json\n" + json.dumps({"risks": [code_like]}) + "\n```\n"
    task_map = parse_task_map(output)
    assert task_map is not None
    item = task_map.risks[0]
    assert "\n" not in item
    assert len(item) <= _MAX_ITEM_CHARS


def test_parse_task_map_coerces_a_string_field_into_a_single_item_list():
    output = "```json\n" + json.dumps({"relevant_files": "single_file.py"}) + "\n```\n"
    task_map = parse_task_map(output)
    assert task_map is not None
    assert task_map.relevant_files == ("single_file.py",)


def test_render_task_map_stays_within_documented_size_limit():
    task_map = TaskMap(
        relevant_files=tuple(f"file_{i}.py" * 3 for i in range(_MAX_ITEMS_PER_FIELD)),
        relevant_symbols=tuple(f"Symbol{i}" * 3 for i in range(_MAX_ITEMS_PER_FIELD)),
        likely_tests=tuple(f"tests/test_{i}.py" * 3 for i in range(_MAX_ITEMS_PER_FIELD)),
        constraints=tuple(f"constraint {i}" * 3 for i in range(_MAX_ITEMS_PER_FIELD)),
        risks=tuple(f"risk {i}" * 3 for i in range(_MAX_ITEMS_PER_FIELD)),
        out_of_scope=tuple(f"out of scope {i}" * 3 for i in range(_MAX_ITEMS_PER_FIELD)),
    )
    rendered = render_task_map(task_map)
    # `truncate`'s head+tail marker can add a small, fixed overhead beyond
    # the limit; the bound that matters is "stays the same order of
    # magnitude as the limit", not byte-exact equality.
    assert len(rendered) <= _RENDER_LIMIT + 50


def test_render_task_map_never_contains_multiline_items_ie_no_full_source_duplication():
    huge_source_like = "\n".join(f"line {i} of a fake source file" for i in range(200))
    task_map = TaskMap(relevant_files=(), constraints=(huge_source_like,))
    # Even a pathologically large single field, parsed through parse_task_map,
    # must already be collapsed/capped before render_task_map ever sees it.
    output = "```json\n" + json.dumps({"constraints": [huge_source_like]}) + "\n```\n"
    parsed = parse_task_map(output)
    assert parsed is not None
    rendered = render_task_map(parsed)
    assert "line 199 of a fake source file" not in rendered
    assert len(rendered) <= _RENDER_LIMIT


# -- Guidance/precedence framing in the rendered text --------------------


def test_render_task_map_states_it_is_guidance_not_a_contract():
    task_map = TaskMap(relevant_files=("a.py",))
    rendered = render_task_map(task_map)
    assert "not a contract" in rendered
    assert "take precedence" in rendered
    assert "Verify" in rendered
