from scout_email.writing.similarity import max_recent_similarity, structure_similarity


def test_identical_structure_scores_one():
    text = "Noticed the booking button is hard to spot on mobile. Want me to send over one idea?"
    assert structure_similarity(text, text) == 1.0


def test_same_structure_with_changed_business_details_scores_high():
    first = "Noticed Acme Dental's booking button is hard to spot on mobile. Want me to send over one idea?"
    second = "Noticed Nova Dental's booking button is hard to spot on mobile. Want me to send over one idea?"
    assert structure_similarity(first, second) >= 0.8


def test_unrelated_copy_scores_lower():
    first = "Noticed the booking button is hard to spot on mobile. Want me to send over one idea?"
    second = "Your Instagram work is polished, but the website tells a very different brand story."
    assert structure_similarity(first, second) < 0.6


def test_max_recent_similarity_uses_highest_match():
    candidate = "Noticed the booking button is hard to spot on mobile. Want me to send over one idea?"
    recent = [
        "Completely unrelated structure about brand consistency.",
        "Noticed Nova Dental's booking button is hard to spot on mobile. Want me to send over one idea?",
    ]
    assert max_recent_similarity(candidate, recent) >= 0.8
