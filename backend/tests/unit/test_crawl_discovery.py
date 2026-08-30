from scout_email.crawl.discovery import select_candidate_urls


def test_candidate_selection_is_same_site_deduplicated_and_priority_bounded():
    urls = [
        "https://example.com/services",
        "https://example.com/about",
        "https://example.com/contact#form",
        "https://example.com/blog/post-one",
        "https://example.com/privacy-policy",
        "https://other.example/contact",
        "https://example.com/services?utm_source=maps",
        "https://www.example.com/pricing",
        "mailto:hello@example.com",
    ]

    selected = select_candidate_urls(
        "https://example.com/",
        urls,
        max_pages=5,
    )

    assert selected[0] == "https://example.com/"
    assert len(selected) == 5
    assert "https://example.com/services" in selected
    assert "https://example.com/contact" in selected
    assert "https://example.com/about" in selected
    assert "https://www.example.com/pricing" in selected
    assert all("privacy" not in url for url in selected)
    assert all("other.example" not in url for url in selected)
    assert len(set(selected)) == len(selected)


def test_candidate_selection_prefers_business_pages_over_blog_archives():
    selected = select_candidate_urls(
        "https://example.com/",
        [
            "https://example.com/blog/how-we-work",
            "https://example.com/tag/news",
            "https://example.com/services/web-design",
            "https://example.com/case-studies/acme",
            "https://example.com/faq",
        ],
        max_pages=4,
    )

    assert selected == [
        "https://example.com/",
        "https://example.com/services/web-design",
        "https://example.com/case-studies/acme",
        "https://example.com/faq",
    ]
