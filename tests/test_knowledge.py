from aipipe.knowledge import parse_knowledge_entries, select_relevant_entries


def test_structured_tag_scope_retrieval_single_match():
    text = (
        "## D-1 Auth decision\nTags: auth\nStatus: active\nKeep auth server-side.\n\n"
        "## D-2 UI decision\nTags: ui\nStatus: active\nUse grid.\n"
    )
    result = select_relevant_entries(text, ["auth"])
    assert "Keep auth server-side" in result
    assert "Use grid" not in result


def test_multiple_matching_entries_returned_together():
    text = (
        "## D-1 First\nTags: auth\nStatus: active\nFirst body.\n\n"
        "## D-2 Second\nTags: auth,backend\nStatus: active\nSecond body.\n\n"
        "## D-3 Unrelated\nTags: ui\nStatus: active\nThird body.\n"
    )
    result = select_relevant_entries(text, ["auth"])
    assert "First body" in result
    assert "Second body" in result
    assert "Third body" not in result


def test_unrelated_entries_omitted_even_when_active():
    text = "## D-1 Only\nTags: billing\nStatus: active\nBilling body.\n"
    result = select_relevant_entries(text, ["frontend"])
    assert "Billing body" not in result


def test_general_fallback_returns_bounded_set_when_nothing_matches():
    text = "\n\n".join(
        f"## D-{i} Title {i}\nTags: scope{i}\nStatus: active\nBody {i}.\n" for i in range(10)
    )
    result = select_relevant_entries(text, ["general"])
    # Bounded fallback (3), not all 10 unrelated entries.
    assert result.count("Body ") == 3
    assert "Body 0" in result


def test_general_fallback_returns_nothing_extra_when_something_matches():
    text = (
        "## D-1 Matched\nTags: auth\nStatus: active\nMatched body.\n\n"
        "## D-2 Other\nTags: billing\nStatus: active\nOther body.\n\n"
        "## D-3 AnotherOther\nTags: shipping\nStatus: active\nAnother body.\n"
    )
    result = select_relevant_entries(text, ["auth", "general"])
    assert "Matched body" in result
    assert "Other body" not in result
    assert "Another body" not in result


def test_obsolete_and_superseded_excluded_regardless_of_tag_match():
    text = (
        "## D-1 Old\nTags: auth\nStatus: obsolete\nOld body.\n\n"
        "## D-2 Replaced\nTags: auth\nStatus: superseded\nReplaced body.\n\n"
        "## D-3 Current\nTags: auth\nStatus: active\nCurrent body.\n"
    )
    result = select_relevant_entries(text, ["auth"])
    assert "Old body" not in result
    assert "Replaced body" not in result
    assert "Current body" in result


def test_malformed_metadata_degrades_safely():
    text = (
        "## D-1 No status line\nTags: auth\nBody one.\n\n"
        "## D-2 Garbled tags\nTags: \nStatus: active\nBody two.\n\n"
        "## No id or tags at all\nJust a plain body.\n\n"
        "## D-4 auth\nTags: auth\nStatus: not-a-real-status\nBody four.\n"
    )
    # Must never raise regardless of scopes.
    entries = parse_knowledge_entries(text)
    assert len(entries) == 4
    result = select_relevant_entries(text, ["auth"])
    # D-1 has no Status: line -> defaults to active, tag auth -> included.
    assert "Body one" in result
    # D-4 has a garbled (non-obsolete/superseded) status -> defaults active-ish
    # and still tag-matches, so it's safe to include.
    assert "Body four" in result
    # Entries with no matching tag/id are simply omitted, not erroring.
    general_result = select_relevant_entries(text, ["general"])
    assert isinstance(general_result, str)


def test_legacy_flat_bullet_list_retrieves_matching_bullets():
    text = (
        "# Learnings\n\n"
        "- Auth tokens must be stored server-side, never in local storage.\n"
        "- The billing system uses Stripe webhooks for reconciliation.\n"
    )
    entries = parse_knowledge_entries(text)
    assert len(entries) == 2
    assert all(not e.structured for e in entries)
    result = select_relevant_entries(text, ["auth"])
    assert "Auth tokens" in result
    assert "billing system" not in result


def test_bounded_output_for_large_knowledge_file():
    text = "\n\n".join(
        f"## D-{i} Title {i}\nTags: auth\nStatus: active\nBody number {i} " + ("x" * 500) + "\n"
        for i in range(50)
    )
    result = select_relevant_entries(text, ["auth"], limit=3000)
    # Entry-count cap keeps this well under 50 entries worth of content...
    assert result.count("Body number") <= 8
    # ...and the char-limit truncation still applies on top of the cap.
    assert len(result) <= 3000 + len("\n...<truncated>...\n") + 10


def test_duplicate_entries_collapse_to_one_occurrence():
    text = (
        "## D-1 First\nTags: auth\nStatus: active\nShared body text.\n\n"
        "## D-1 First\nTags: auth\nStatus: active\nShared body text.\n\n"
        "## D-2 Different id, same body\nTags: auth\nStatus: active\nShared body text.\n"
    )
    result = select_relevant_entries(text, ["auth"])
    assert result.count("Shared body text") == 1


def test_html_comment_wrapped_template_example_never_surfaces():
    text = (
        "# Cross-project Learnings\n\n"
        "Only store knowledge here when it is genuinely reusable across unrelated projects.\n"
        "Do not store task history.\n\n"
        "<!--\n"
        "## L-001 Example\n"
        "Tags: testing, reliability\n"
        "Status: active\n"
        "Severity: medium\n\n"
        "Rule:\n"
        "Do not fix a flaky test by increasing sleeps before understanding the synchronization boundary.\n"
        "-->\n"
    )
    entries = parse_knowledge_entries(text)
    assert entries == []
    result = select_relevant_entries(text, ["testing", "general"])
    assert "flaky test" not in result
