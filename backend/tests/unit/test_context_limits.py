from scout_email.llm.context import build_writer_context, sanitize_context


def test_writer_context_contains_only_approved_bounded_sections():
    source = {
        "dossier_summary": {"business":"Acme Dental","target_customer":"patients"},
        "persuasion_brief": {"primary_angle":"booking friction"},
        "allowed_evidence": [{"id":12,"claim":"Book CTA is below first mobile viewport"}],
        "weberaise_context": "WEBERAISE designs and develops websites.",
        "writing_rules": ["short", "specific"],
        "approved_examples": [{"subject":"quick thought","body":"..."}],
        "recent_corrections": [{"from":"discuss","to":"send over"}],
        "raw_html": "<html>huge noisy page</html>",
        "crawl_pages": [{"html":"<body>raw</body>","important_text":"useful but not writer input"}],
        "browser_dump": {"dom":"noise"},
        "secret_internal_note": "must not leak",
    }

    context = build_writer_context(source)

    assert set(context) == {
        "dossier_summary",
        "persuasion_brief",
        "allowed_evidence",
        "weberaise_context",
        "writing_rules",
        "approved_examples",
        "recent_corrections",
    }
    rendered = str(context)
    assert "<html>" not in rendered
    assert "browser_dump" not in rendered
    assert "secret_internal_note" not in rendered


def test_sanitize_context_removes_raw_html_recursively_and_applies_text_budget():
    source = {
        "summary": "A" * 500,
        "nested": {
            "raw_html": "<html>forbidden</html>",
            "html": "<body>also forbidden</body>",
            "safe": "B" * 500,
        },
        "items": [{"raw_html":"bad","claim":"C" * 500}],
    }

    cleaned = sanitize_context(source, max_text_chars=120)
    rendered = str(cleaned)

    assert "raw_html" not in rendered
    assert "<html>" not in rendered
    assert "<body>" not in rendered
    assert len(cleaned["summary"]) <= 120
    assert len(cleaned["nested"]["safe"]) <= 120
    assert len(cleaned["items"][0]["claim"]) <= 120
