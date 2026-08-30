import json

from scout_email.writing.playbook import load_playbook


def _seed(root):
    root.mkdir(parents=True)
    (root / "company_context.md").write_text("WEBERAISE builds websites.\n")
    (root / "writing_rules.md").write_text("Keep outreach short and specific.\n")
    (root / "banned_phrases.md").write_text("I hope this email finds you well\n")
    (root / "cta_rules.md").write_text("Use a low-friction CTA.\n")
    (root / "approved_examples.json").write_text(json.dumps([]))
    (root / "rejected_patterns.json").write_text(
        json.dumps([{"pattern": "take your business to the next level", "reason": "generic"}])
    )


def test_load_playbook_returns_required_content_and_stable_hash(tmp_path):
    root = tmp_path / "weberaise"
    _seed(root)

    first = load_playbook(root)
    second = load_playbook(root)

    assert first.version_hash == second.version_hash
    assert len(first.version_hash) == 64
    assert "WEBERAISE" in first.company_context
    assert "short and specific" in first.writing_rules
    assert "I hope this email finds you well" in first.banned_phrases
    assert first.approved_examples == ()
    assert first.rejected_patterns[0]["pattern"] == "take your business to the next level"


def test_playbook_hash_changes_when_source_content_changes(tmp_path):
    root = tmp_path / "weberaise"
    _seed(root)
    before = load_playbook(root).version_hash

    (root / "writing_rules.md").write_text("Keep outreach short, specific, and natural.\n")

    after = load_playbook(root).version_hash
    assert before != after


def test_playbook_fails_if_a_required_source_file_is_missing(tmp_path):
    root = tmp_path / "weberaise"
    _seed(root)
    (root / "cta_rules.md").unlink()

    try:
        load_playbook(root)
    except FileNotFoundError as exc:
        assert "cta_rules.md" in str(exc)
    else:
        raise AssertionError("missing required playbook file must fail closed")


def test_markdown_banned_phrase_bullets_are_normalized_for_exact_scanning(tmp_path):
    root = tmp_path / "weberaise"
    _seed(root)
    (root / "banned_phrases.md").write_text(
        "# Banned\n\n- I hope this email finds you well\n- elevate your online presence\n"
    )

    playbook = load_playbook(root)

    assert playbook.banned_phrases == (
        "I hope this email finds you well",
        "elevate your online presence",
    )
