from leadgen import enrichment, scoring


# ---------- enrichment: email policy ----------

def test_package_versions_are_not_emails():
    html = '<script src="x">leaflet@1.7.1 slick-carousel@1.8.1</script> <a href="mailto:info@site.com">mail</a>'
    assert enrichment.extract_emails(html) == ["info@site.com"]


def test_emails_inside_script_code_are_ignored():
    html = "<script>// font by impallari@gmail.com</script><p>Welcome</p>"
    assert enrichment.extract_emails(html) == []


def test_classify_own_related_free_other():
    emails = ["info@ikigaiconnect.com", "support@wework.co.in", "me@gmail.com", "hello@rfuenzalida.com"]
    own, related, free, other = enrichment.classify_emails(emails, {"www.ikigaiconnect.com"})
    assert own == ["info@ikigaiconnect.com"]
    assert free == ["me@gmail.com"]
    assert other == ["support@wework.co.in", "hello@rfuenzalida.com"]
    assert related == []


def test_related_brand_domain_is_accepted():
    own, related, free, other = enrichment.classify_emails(["support@wework.co.in"], {"wework.com"})
    assert related == ["support@wework.co.in"]


def test_unrelated_domain_is_rejected():
    own, related, free, other = enrichment.classify_emails(["info@alfaesol.com"], {"weworkoffice.in"})
    assert other == ["info@alfaesol.com"]


# ---------- enrichment: socials, services, full lead ----------

def test_social_links_skip_share_buttons():
    html = ('<a href="https://www.linkedin.com/company/foo/">in</a>'
            '<a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a>')
    assert enrichment.extract_socials(html) == {"linkedin": "https://www.linkedin.com/company/foo"}


def test_services_found_in_fixed_html():
    html = "<p>We offer hot desks, private cabins and a day pass. Open 24/7.</p>"
    assert enrichment.extract_services(html) == ["day_pass", "hot_desk", "open_24x7", "private_cabin"]


def test_enrich_lead_uses_own_email_and_drops_stale_one():
    page = '<a href="mailto:info@example-cowork.com">Email us</a>'
    fake = lambda url: {"url": url, "status": "ok", "html": page}
    lead = {"company_name": "X", "website": "https://example-cowork.com", "email": "stale@old.com"}
    out = enrichment.enrich_lead(lead, fetch=fake)
    assert out["email"] == "info@example-cowork.com"
    assert out["data_provenance"]["email"] == "website_scraped"


def test_blocked_site_is_skipped_not_bypassed():
    fake = lambda url: {"url": url, "status": "blocked", "html": ""}
    out = enrichment.enrich_lead({"company_name": "X", "website": "https://blocked-site.com"}, fetch=fake)
    assert out["fetch_status"] == "blocked"
    assert out["email"] is None


# ---------- scoring ----------

FULL = {"company_name": "A", "phone": "+919999999999", "phone_type": "mobile",
        "email": "a@a.com", "website": "https://a.com",
        "social_links": {"linkedin": "x", "facebook": "y"},
        "rating": 4.8, "review_count": 150,
        "services": ["hot_desk", "day_pass", "parking", "open_24x7", "meeting_room", "private_cabin"]}


def test_perfect_lead_scores_100_and_hot():
    score, label, reason, _ = scoring.score_lead(FULL)
    assert score == 100 and label == "Hot"


def test_score_always_within_bounds():
    for lead in ({}, FULL, {"company_name": "A", "phone": "+911"}, {"rating": 5, "review_count": 10**6}):
        score, *_ = scoring.score_lead(lead)
        assert 0 <= score <= 100


def test_incomplete_lead_is_capped_at_39():
    lead = dict(FULL, phone=None, email=None)
    score, label, reason, _ = scoring.score_lead(lead)
    assert label == "Incomplete" and score <= 39
    assert "capped" in reason


def test_toll_free_phone_scores_below_direct_phone():
    direct, *_ = scoring.score_lead(dict(FULL, email=None))
    toll, *_ = scoring.score_lead(dict(FULL, email=None, phone_type="toll_free"))
    assert toll < direct


def test_lead_without_name_is_incomplete():
    assert not scoring.is_complete({"phone": "+919999999999"})