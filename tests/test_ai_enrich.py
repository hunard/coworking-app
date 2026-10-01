from leadgen import ai_enrich, scoring

TEXT = "We offer hot desks and private offices for freelancers in Andheri. Visit our Mumbai centre today."


def test_validate_keeps_real_quotes_and_drops_fake_ones():
    raw = {
        "is_flexible_workspace_operator": {"value": True, "quote": "We offer hot desks and private offices"},
        "operator_type": {"value": "independent", "quote": "We run a global franchise of 500 centres"},
        "space_types": [{"value": "hot_desk", "quote": "hot desks and private offices"}],
        "target_customers": [{"value": "startups", "quote": "perfect for unicorn startups"}],
    }
    profile, stats = ai_enrich.validate(raw, TEXT)
    assert profile["is_operator"] is True
    assert profile["operator_type"] is None          # quote is not on the page
    assert profile["space_types"] == ["hot_desk"]
    assert profile["target_customers"] == []         # quote is not on the page
    assert stats["claims"] == 4 and stats["dropped"] == 2


def test_validate_rejects_unknown_values_and_bad_input():
    raw = {"operator_type": {"value": "alien_base", "quote": "We offer hot desks"}}
    profile, _ = ai_enrich.validate(raw, TEXT)
    assert profile["operator_type"] is None
    profile, _ = ai_enrich.validate(None, TEXT)
    assert profile["space_types"] == []


def test_not_operator_gets_zero_marketplace_fit():
    lead = {"ai_profile": {"is_operator": False, "space_types": ["hot_desk"]}, "services": ["Hot desks"]}
    parts, _ = scoring.marketplace_fit(lead)
    assert sum(p for p, _ in parts) == 0


def test_marketplace_fit_max_is_30_and_falls_back_to_keywords():
    full = {"ai_profile": {
        "is_operator": True,
        "operator_type": "independent",
        "space_types": ["hot_desk", "day_pass", "meeting_room", "private_office", "virtual_office"],
        "target_customers": ["freelancers", "startups", "enterprises"],
    }}
    parts, source = scoring.marketplace_fit(full)
    assert sum(p for p, _ in parts) == 30
    assert source == "ai_inferred_quote_verified"

    parts, source = scoring.marketplace_fit({"services": ["Hot desks", "Meeting rooms"]})
    assert source == "keyword_fallback"
    assert sum(p for p, _ in parts) == 6